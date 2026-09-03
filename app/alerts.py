"""Fetch MTA subway service alerts and match them to the watched lines (#13).

The MTA publishes service alerts as a GTFS-Realtime *alerts* feed with the
Camsys/"Mercury" extensions, served as JSON at :data:`ALERTS_URL` (no protobuf,
no API key). Each alert names the affected route(s), an active period, an
``alert_type`` (``Delays`` / ``Planned - Stops Skipped`` / ...), and
human-readable header + description text. This module fetches that feed and
normalizes the alerts that touch a watched line into a small :class:`Alert`.

Scope (#13, owner's calls):

* **Match by line.** An alert is kept when any of its ``informed_entity`` routes
  is a line the board watches (the union of the ``[[stations]]`` line-sets --
  ``[[trips]]`` lines are a subset). Which specific stops it names is ignored --
  line-level, matching the "the A line is experiencing delays" framing.
* **What's worth surfacing.** Low-value types (:data:`EXCLUDED_ALERT_TYPES` --
  boarding changes, station notices, extra service, weekend-schedule notes) are
  dropped; current disruptions and planned service changes are kept.
* **When.** An alert shows if it is active right now, or if a planned change
  starts later *today* (Eastern). Anything wholly in the past, or starting on a
  future day, is dropped -- so a "no evening A trains" heads-up appears the same
  day, not before.

The board (#7) renders a per-line badge on affected station groups and shows the
alert text in the tap-through detail overlay (#9). This module is the backend
half: fetch + normalize + match. :func:`parse_alerts` is a pure function of
(feed JSON, watched lines, now) so it is fully unit-testable offline.

CLI: ``uv run python -m app.alerts A C 1`` fetches live alerts for the given
lines and prints the matched ones -- a quick spot-check against the MTA app.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.feeds import DEFAULT_TIMEOUT, EASTERN, FeedError

# MTA subway service-alerts feed, GTFS-Realtime + Mercury extensions as JSON.
# No API key. Confirmed working against the live service on 2026-09-03.
ALERTS_URL = (
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json"
)

# The Mercury extension key carrying the alert's ``alert_type`` (and timestamps).
_MERCURY_ALERT = "transit_realtime.mercury_alert"

# Alert types not worth a spot on a glance board (owner's #13 call): routine
# boarding-position notes, station notices, added service, and weekend-schedule
# reminders. Everything else that touches a watched line -- current disruptions
# (Delays, Reduced Service, Suspended, reroutes) and planned service changes
# (Planned - *) -- is surfaced.
EXCLUDED_ALERT_TYPES = frozenset(
    {"Boarding Change", "Station Notice", "Extra Service", "Sunday Schedule"}
)


@dataclass(frozen=True)
class Alert:
    """One normalized service alert matched to the watched lines.

    ``lines`` are the watched lines this alert affects (sorted). ``header`` is the
    short human summary; ``description`` the longer follow-up (either may be
    empty). ``alert_type`` is the Mercury category (``Delays`` / ``Planned -
    ...``). ``active`` is whether the alert's active period covers ``now`` -- a
    disruption in effect, versus an upcoming/planned heads-up (the board weights
    the badge and label off it). ``start`` / ``end`` bound the relevant active
    period (the one covering now, else the soonest upcoming-today one); either may
    be ``None`` (an open-ended ongoing disruption has no start/end).
    """

    id: str
    lines: tuple[str, ...]
    header: str
    description: str
    alert_type: str
    active: bool
    start: datetime | None
    end: datetime | None


def _translation(block: Any, language: str = "en") -> str:
    """Pull ``language`` text from a GTFS-RT ``{translation: [...]}`` block.

    Prefers the exact language, falls back to the first translation, then to "".
    Returns the plain-text variant, not the ``en-html`` one (the board renders
    text, not markup).
    """
    if not isinstance(block, dict):
        return ""
    translations = block.get("translation") or []
    chosen = ""
    for t in translations:
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        if t.get("language") == language:
            return text
        if not chosen:
            chosen = text
    return chosen


def _epoch_to_eastern(value: Any) -> datetime | None:
    """Convert a Unix-epoch active-period bound to an Eastern datetime, or None."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), EASTERN)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _periods(alert: dict[str, Any]) -> list[tuple[datetime | None, datetime | None]]:
    """Parse an alert's ``active_period`` list into (start, end) Eastern pairs.

    A missing ``active_period`` means the alert is ongoing with no bounds, which
    we represent as a single ``(None, None)`` period (active right now).
    """
    raw = alert.get("active_period") or []
    if not raw:
        return [(None, None)]
    return [
        (_epoch_to_eastern(p.get("start")), _epoch_to_eastern(p.get("end")))
        for p in raw
    ]


def _covers_now(start: datetime | None, end: datetime | None, now: datetime) -> bool:
    """Whether a (start, end) period covers ``now`` (open bounds mean unbounded)."""
    return (start is None or start <= now) and (end is None or now < end)


def _representative_period(
    periods: list[tuple[datetime | None, datetime | None]],
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    """Pick the period to report: the one covering now, else the soonest upcoming."""
    for start, end in periods:
        if _covers_now(start, end, now):
            return start, end
    upcoming = [(s, e) for s, e in periods if s is not None and s > now]
    return min(upcoming, key=lambda p: p[0] or now) if upcoming else (None, None)


def parse_alerts(
    feed: dict[str, Any],
    watched_lines: Iterable[str],
    now: datetime | None = None,
) -> list[Alert]:
    """Normalize a decoded alerts feed into the matched, surfaceable alerts.

    Pure and offline: keeps alerts that (a) aren't an excluded type, (b) touch a
    watched line, and (c) are active now or start later today (Eastern). Returns
    them sorted current-first, then by start time. See the module docstring for
    the owner's scope decisions.
    """
    if now is None:
        now = datetime.now(EASTERN)
    watched = set(watched_lines)
    today = now.date()

    out: list[Alert] = []
    for entity in feed.get("entity", []):
        alert = entity.get("alert")
        if not isinstance(alert, dict):
            continue
        mercury = alert.get(_MERCURY_ALERT) or {}
        alert_type = str(mercury.get("alert_type", "")).strip()
        if alert_type in EXCLUDED_ALERT_TYPES:
            continue

        # Match by line only. informed_entity also carries a direction_id (0/1),
        # but it's unusable for scoping to a platform: ~half of alerts omit it,
        # a single alert mixes 0 and 1 across its entities (a clearly one-way
        # "Manhattan-bound [F]" alert lists both), stop_ids are parent IDs with no
        # N/S suffix, and 0/1->N/S isn't an official mapping. Filtering on it would
        # badge the wrong platform, so we badge the whole line (owner's call, #13).
        routes = {
            str(ie["route_id"])
            for ie in alert.get("informed_entity", [])
            if ie.get("route_id")
        }
        lines = tuple(sorted(routes & watched))
        if not lines:
            continue

        periods = _periods(alert)
        active = any(_covers_now(s, e, now) for s, e in periods)
        starts_today = any(
            s is not None and s > now and s.date() == today for s, e in periods
        )
        if not (active or starts_today):
            continue

        start, end = _representative_period(periods, now)
        out.append(
            Alert(
                id=str(entity.get("id", "")),
                lines=lines,
                header=_translation(alert.get("header_text")),
                description=_translation(alert.get("description_text")),
                alert_type=alert_type,
                active=active,
                start=start,
                end=end,
            )
        )

    # Current disruptions first, then upcoming by start time. A None start means
    # an open-ended ongoing alert -- sort it as "now".
    out.sort(key=lambda a: (not a.active, a.start or now))
    return out


def fetch_alerts_json(timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Fetch and decode the alerts feed JSON. Raises :class:`FeedError` on failure."""
    try:
        response = httpx.get(ALERTS_URL, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise FeedError(f"Failed to fetch alerts feed {ALERTS_URL}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FeedError(f"Malformed alerts feed: {exc}") from exc


def fetch_alerts(
    watched_lines: Iterable[str],
    *,
    now: datetime | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Alert]:
    """Fetch the live alerts feed and return the alerts matched to ``watched_lines``.

    Raises :class:`FeedError` if the feed can't be fetched or decoded; the caller
    (the poller) treats alerts as a secondary enhancement and keeps serving the
    board without them on failure.
    """
    return parse_alerts(fetch_alerts_json(timeout=timeout), watched_lines, now=now)


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.alerts <line> [line ...]")
        print("example: python -m app.alerts A C 1")
        return 2
    try:
        alerts = fetch_alerts(argv)
    except FeedError as exc:
        print(f"error: {exc}")
        return 1

    print(f"{len(alerts)} matched alert(s) for {', '.join(argv)}:")
    for a in alerts:
        state = "NOW" if a.active else "planned"
        when = a.start.strftime("%a %H:%M") if a.start else "ongoing"
        print(f"  [{state}] {'/'.join(a.lines):<6} {a.alert_type:<24} {when}")
        print(f"        {a.header}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
