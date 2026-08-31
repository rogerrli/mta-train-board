"""Background feed poller + in-memory cache (issue #6).

The API used to fetch and compute arrivals live on every request (issue #5).
This module moves that work off the request path: a single background task
refreshes the board on an interval and stores the result, so ``/api/state``
answers instantly from the last successful poll and we stay friendly to the MTA
endpoints (one fetch per interval, not one per client request).

Design (owner's calls on this issue):

* **Concurrency** -- one asyncio task started in the server's lifespan. Each
  cycle runs the *synchronous* :func:`app.arrivals.fetch_arrivals` in a worker
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
from dataclasses import dataclass
from datetime import datetime

from app.arrivals import ArrivalGroup, fetch_arrivals
from app.config import load_config
from app.feeds import EASTERN

logger = logging.getLogger(__name__)

# Fallbacks when config omits them.
DEFAULT_REFRESH_SECONDS = 30.0
DEFAULT_STALE_AFTER_SECONDS = 90.0  # ~3x refresh; board reads "old" past this.
DEFAULT_MAX_BACKOFF_SECONDS = 300.0  # cap the retry interval during an outage.
MIN_REFRESH_SECONDS = 5.0  # floor so a misconfigured interval can't hammer the MTA.

# How many trains per line/direction to keep in the cached board. The glance view
# (issue #7) only renders the first few, but tapping a train opens a detail
# breakdown (issue #9) that shows this deeper list -- so the one cached payload
# already carries enough for both, no extra fetch. Deeper than arrivals'
# DEFAULT_LIMIT (which the CLI spot-check still uses).
BOARD_LIMIT = 10


@dataclass(frozen=True)
class Snapshot:
    """The last successfully computed board and the time it was polled."""

    groups: list[ArrivalGroup]
    updated_at: datetime


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
    ) -> None:
        # Clamp so a bad config value (0, negative, non-numeric) can't busy-loop
        # the feeds or crash asyncio.sleep(); float() fails fast on a non-number.
        self.refresh_seconds = max(float(refresh_seconds), MIN_REFRESH_SECONDS)
        self.stale_after_seconds = max(float(stale_after_seconds), 0.0)
        self.max_backoff_seconds = max(float(max_backoff_seconds), self.refresh_seconds)
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
        :func:`fetch_arrivals` raises (feed, config, or unforeseen errors); the
        loop catches broadly and backs off so a failure never ends polling.
        """
        now = datetime.now(EASTERN)
        # TODO(#6): fetch_arrivals -> parse_feed rebuilds the NYCTFeed GTFS-static
        # tables from disk every poll (see the note in app/feeds.py:parse_feed).
        # A perf win for the Pi is to build one NYCTFeed and reuse it via
        # load_gtfs_bytes() across polls; deferred to keep this issue in its lane.
        return Snapshot(
            groups=fetch_arrivals(load_config(), now=now, limit=BOARD_LIMIT),
            updated_at=now,
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
