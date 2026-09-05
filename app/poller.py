"""Background feed poller + in-memory cache (issue #6).

The API used to fetch and compute arrivals live on every request (issue #5).
This module moves that work off the request path: a single background task
refreshes the board on an interval and stores the result, so ``/api/state``
answers instantly from the last successful poll and we stay friendly to the MTA
endpoints (one fetch per interval, not one per client request).

Design (owner's calls on this issue):

* **Concurrency** -- one asyncio task started in the server's lifespan. Each
  cycle runs the *synchronous* :func:`app.trips.fetch_board` in a worker
  thread (:func:`asyncio.to_thread`) so the event loop never blocks on network.
* **Staleness** -- the cache keeps the last successful :class:`Snapshot` and its
  poll time. The API exposes ``stale``/``age_seconds`` computed against
  ``stale_after_seconds`` so the UI can show "data is old".
* **Errors** -- a failed poll keeps the last good snapshot (served flagged
  stale) and backs off exponentially, capped, resetting to the normal interval
  on the next success. No thundering on the MTA during an outage.

Before the first successful poll the cache is empty (``snapshot is None``); the
API returns 503 until then.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.alerts import Alert, fetch_alerts
from app.arrivals import ArrivalGroup
from app.config import load_config
from app.feeds import EASTERN, FeedError
from app.focus import FocusConfigError, FocusRule, resolve_focus_rules
from app.trips import TripRecommendation, fetch_board

logger = logging.getLogger(__name__)

# Fallbacks when config omits them.
DEFAULT_REFRESH_SECONDS = 30.0
DEFAULT_STALE_AFTER_SECONDS = 90.0  # ~3x refresh; board reads "old" past this.
DEFAULT_MAX_BACKOFF_SECONDS = 300.0  # cap the retry interval during an outage.
MIN_REFRESH_SECONDS = 5.0  # floor so a misconfigured interval can't hammer the MTA.
DEFAULT_ALERT_LEAD_MINUTES = 10  # focus-mode leave-by heads-up lead time (#54).

# How many trains per line/direction to keep in the cached board. The glance view
# (issue #7) only renders the first few, but tapping a train opens a detail
# breakdown (issue #9) that shows this deeper list -- so the one cached payload
# already carries enough for both, no extra fetch. Deeper than arrivals'
# DEFAULT_LIMIT (which the CLI spot-check still uses).
BOARD_LIMIT = 10


@dataclass(frozen=True)
class Snapshot:
    """The last successfully computed board and the time it was polled.

    ``recommendations`` are the arrive-by trip picks (#27), computed from the same
    poll; empty when no ``[[trips]]`` are configured. ``focus_rules`` are the
    resolved scheduled-focus rules (#39); the API decides which (if any) is active
    at request time, so they ride along with the snapshot rather than being frozen
    at poll time. Empty when no ``[[focus]]`` blocks are configured. ``alerts`` are
    the service alerts (#13) matched to the watched lines this poll; empty when
    none apply or the alerts feed was unreachable (it's a secondary enhancement --
    a failed alerts fetch never blanks the board).
    """

    groups: list[ArrivalGroup]
    updated_at: datetime
    recommendations: list[TripRecommendation] = field(default_factory=list)
    focus_rules: list[FocusRule] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)


class Poller:
    """Refreshes arrivals on a background interval into an in-memory cache.

    :attr:`snapshot` holds the last successful poll (``None`` until the first one
    succeeds). :meth:`start`/:meth:`stop` manage the background task; the server
    drives them from its lifespan.
    """

    def __init__(
        self,
        *,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        alert_lead_minutes: int = DEFAULT_ALERT_LEAD_MINUTES,
    ) -> None:
        # Clamp so a bad config value (0, negative, non-numeric) can't busy-loop
        # the feeds or crash asyncio.sleep(); float() fails fast on a non-number.
        self.refresh_seconds = max(float(refresh_seconds), MIN_REFRESH_SECONDS)
        self.stale_after_seconds = max(float(stale_after_seconds), 0.0)
        self.max_backoff_seconds = max(float(max_backoff_seconds), self.refresh_seconds)
        # Frontend behavior value forwarded in /api/state (#54): the focus-mode
        # board beeps this many minutes before leave-by. Clamp to a non-negative
        # int; int() fails fast on a non-number.
        self.alert_lead_minutes = max(int(alert_lead_minutes), 0)
        self._snapshot: Snapshot | None = None
        self._task: asyncio.Task[None] | None = None

    @classmethod
    def from_config(cls) -> Poller:
        """Build a poller from the active config (interval + staleness threshold)."""
        cfg = load_config()
        return cls(
            refresh_seconds=cfg.get(
                "refresh_interval_seconds", DEFAULT_REFRESH_SECONDS
            ),
            stale_after_seconds=cfg.get(
                "stale_after_seconds", DEFAULT_STALE_AFTER_SECONDS
            ),
            alert_lead_minutes=cfg.get(
                "alert_lead_minutes", DEFAULT_ALERT_LEAD_MINUTES
            ),
        )

    @property
    def snapshot(self) -> Snapshot | None:
        """The last successful poll, or ``None`` before the first one succeeds."""
        return self._snapshot

    def age_seconds(self, snapshot: Snapshot, *, now: datetime | None = None) -> float:
        """Seconds since ``snapshot`` was polled."""
        now = now or datetime.now(EASTERN)
        return (now - snapshot.updated_at).total_seconds()

    def is_stale(self, snapshot: Snapshot, *, now: datetime | None = None) -> bool:
        """Whether ``snapshot`` is older than ``stale_after_seconds``."""
        return self.age_seconds(snapshot, now=now) > self.stale_after_seconds

    def poll_once(self) -> Snapshot:
        """Fetch the feeds and compute one board. Synchronous; may raise.

        Runs in a worker thread from the loop. Propagates whatever
        :func:`app.trips.fetch_board` raises (feed, config, or unforeseen errors);
        the loop catches broadly and backs off so a failure never ends polling.
        """
        now = datetime.now(EASTERN)
        # TODO(#6): fetch_board -> parse_feed rebuilds the NYCTFeed GTFS-static
        # tables from disk every poll (see the note in app/feeds.py:parse_feed).
        # A perf win for the Pi is to build one NYCTFeed and reuse it via
        # load_gtfs_bytes() across polls; deferred to keep this issue in its lane.
        config = load_config()
        groups, recommendations = fetch_board(config, now=now, board_limit=BOARD_LIMIT)
        # Resolve focus rules against the same config, validating each references a
        # real trip (#39). Focus is an optional enhancement layered on the board, so
        # a malformed [[focus]] block must not blank the whole board: log it and
        # serve the board with focus disabled rather than failing the poll (which
        # would strand /api/state at 503). Broader feed/trip errors still propagate.
        try:
            focus_rules = resolve_focus_rules(config, {r.name for r in recommendations})
        except FocusConfigError as exc:
            logger.warning("Ignoring invalid [[focus]] config; focus disabled: %s", exc)
            focus_rules = []
        # Fetch service alerts for the watched lines (#13). The board's groups
        # already name every watched line, so derive the set from them rather than
        # re-parsing config. Alerts are a secondary enhancement: a feed failure
        # must not blank the board, so drop them and serve arrivals on any error
        # (the outer loop still succeeds and the cache stays fresh).
        watched_lines = {g.line for g in groups}
        try:
            alerts = fetch_alerts(watched_lines, now=now)
        except FeedError as exc:
            logger.warning(
                "Alerts feed unavailable; serving board without them: %s", exc
            )
            alerts = []
        return Snapshot(
            groups=groups,
            updated_at=now,
            recommendations=recommendations,
            focus_rules=focus_rules,
            alerts=alerts,
        )

    async def _run(self) -> None:
        """Poll loop: refresh on success, back off exponentially on failure."""
        backoff = self.refresh_seconds
        while True:
            try:
                self._snapshot = await asyncio.to_thread(self.poll_once)
            except Exception as exc:
                # Catch broadly: this loop must never die. A feed/config error or
                # an unforeseen one (a feed-format change surfacing deep in a dep)
                # would otherwise end polling for the process lifetime. CancelledError
                # is a BaseException, so a real shutdown still propagates past this.
                # Keep the last good snapshot (served flagged stale) and back off.
                backoff = min(backoff * 2, self.max_backoff_seconds)
                logger.warning(
                    "Feed poll failed; serving last-known data, retrying in %.0fs: %s",
                    backoff,
                    exc,
                )
                await asyncio.sleep(backoff)
            else:
                backoff = self.refresh_seconds
                await asyncio.sleep(self.refresh_seconds)

    def start(self) -> None:
        """Start the background poll task (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background poll task and wait for it to unwind."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
