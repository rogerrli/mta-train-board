"""Scheduled station-to-station ride durations from the GTFS static timetable.

The arrivals model (#4) answers "when does the next train reach *this* stop?" It
has no notion of a destination. Trip planning (arrive-by, #27) also needs "how
long is the *ride* from A to B?" -- e.g. "the N from 36 St to Union Sq takes
~14 min." This module supplies that scheduled duration.

Data source (#26 decision): the **GTFS static** schedule, not realtime. The MTA
publishes a static ``stop_times.txt`` giving each trip's timetabled stop times;
differencing two stops on the same trip yields a scheduled ride duration that
varies by time of day and service day. ``stop_times.txt`` is ~36 MB, so we don't
vendor it raw: ``scripts/refresh-travel-times`` downloads the feed, trims it to
the watched routes, and writes a compact vendored artifact
(``app/data/travel_times.json.gz``) recording the feed version + date. Realtime
refinement (using the live trip updates we already poll) is a deliberate
follow-up, not done here.

Model
-----
For each ``route`` x ``direction`` (N/S) x ``service_type`` (weekday / saturday /
sunday) we keep the list of scheduled trips; each trip is ``{stop_id: seconds}``
mapping a direction-suffixed GTFS stop ID (e.g. ``"R20N"``) to its scheduled time
in seconds since midnight. (In the MTA subway feed a stop's arrival and departure
times are always equal, so one number per stop suffices.)

:meth:`TravelTimeModel.travel_time` takes **parent** stop IDs plus a direction --
matching :class:`app.stops.ResolvedStation` (whose ``line_stops`` are parent IDs
and whose directions are ``N``/``S``) -- suffixes them, picks the scheduled trip
whose departure from the boarding stop is nearest ``at_time``, and returns
``arrival_at_destination - departure_at_boarding`` as a :class:`timedelta`. When
no scheduled trip serves the pair (unknown route/stop, wrong order, or no service
that day) it returns ``None`` -- an explicit "no estimate" rather than a guess.

Service day is weekday / Saturday / Sunday (per #26 scope); holiday exceptions
(``calendar_dates.txt``) are intentionally ignored.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import httpx

from app.feeds import EASTERN

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
VENDORED_TRAVEL_TIMES = _DATA_DIR / "travel_times.json.gz"

# MTA GTFS static "subway" feed (trips.txt, stop_times.txt, calendar.txt, ...).
# The classic web.mta.info URL 301-redirects here. Confirmed working 2026-08-30;
# used by scripts/refresh-travel-times.
STATIC_GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"

DOWNLOAD_TIMEOUT = 120.0

VALID_DIRECTIONS = ("N", "S")


def _service_type(at_time: datetime) -> str:
    """Service day for ``at_time``: weekday / saturday / sunday (holidays ignored)."""
    weekday = at_time.weekday()  # Mon=0 .. Sun=6
    if weekday == 5:
        return "saturday"
    if weekday == 6:
        return "sunday"
    return "weekday"


def _seconds_since_midnight(at_time: datetime) -> int:
    return at_time.hour * 3600 + at_time.minute * 60 + at_time.second


# One trip's scheduled stops: direction-suffixed stop_id -> seconds since midnight.
_Trip = dict[str, int]
# route -> direction -> service_type -> [trip, ...]
_Schedule = dict[str, dict[str, dict[str, list[_Trip]]]]


@dataclass(frozen=True)
class TravelTimeModel:
    """Scheduled ride durations, loaded from the vendored trimmed timetable.

    ``feed_version`` / ``generated`` record the provenance of the vendored data
    (the GTFS ``feed_version`` and the date the artifact was built). ``routes`` is
    the set of routes the artifact was trimmed to; a query for any other route
    returns ``None``.
    """

    feed_version: str
    generated: str
    routes: tuple[str, ...]
    _schedule: _Schedule

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TravelTimeModel:
        return cls(
            feed_version=data.get("feed_version", ""),
            generated=data.get("generated", ""),
            routes=tuple(data.get("routes", [])),
            _schedule=data.get("schedule", {}),
        )

    @classmethod
    def load(cls, path: Path = VENDORED_TRAVEL_TIMES) -> TravelTimeModel:
        """Load the model from a gzipped-JSON artifact (vendored one by default)."""
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def travel_time(
        self,
        from_stop: str,
        to_stop: str,
        line: str,
        direction: str,
        at_time: datetime,
    ) -> timedelta | None:
        """Scheduled ride duration from ``from_stop`` to ``to_stop``, or ``None``.

        ``from_stop`` / ``to_stop`` are **parent** GTFS stop IDs (no direction
        suffix, e.g. ``"R20"``), as carried by :class:`app.stops.ResolvedStation`.
        ``line`` is the GTFS route/line (e.g. ``"N"``); ``direction`` is ``"N"`` or
        ``"S"``. ``at_time`` selects both the service day (weekday/saturday/sunday)
        and the specific trip -- the scheduled train whose departure from
        ``from_stop`` is closest to it.

        Returns the ``timedelta`` for that trip, or ``None`` when no scheduled
        trip serves the pair in the given order on that day (unknown route/stop,
        same or reversed stops, or no service).
        """
        if direction not in VALID_DIRECTIONS:
            return None
        # Service day + nearest-trip selection are defined in Eastern wall-clock
        # (the timetable's own zone). Normalize a tz-aware time from any zone;
        # a naive datetime is assumed to already be Eastern.
        if at_time.tzinfo is not None:
            at_time = at_time.astimezone(EASTERN)
        trips = (
            self._schedule.get(line, {})
            .get(direction, {})
            .get(_service_type(at_time), [])
        )
        if not trips:
            return None

        from_id = from_stop + direction
        to_id = to_stop + direction
        at_seconds = _seconds_since_midnight(at_time)

        best_ride: int | None = None
        best_gap = float("inf")
        for trip in trips:
            depart = trip.get(from_id)
            arrive = trip.get(to_id)
            # Times increase monotonically along a trip, so arrive > depart also
            # enforces that to_stop is genuinely after from_stop on this run
            # (and rules out from == to).
            if depart is None or arrive is None or arrive <= depart:
                continue
            # GTFS encodes after-midnight stops on the prior service day as
            # 24:00+ (e.g. 00:30 -> 88200s). Compare at_seconds against both the
            # same-day and next-day framing so an early-morning query still
            # matches those trips instead of picking a far one.
            gap = min(abs(depart - at_seconds), abs(depart - at_seconds - 86400))
            if gap < best_gap:
                best_gap = gap
                best_ride = arrive - depart

        return timedelta(seconds=best_ride) if best_ride is not None else None


@cache
def _default_model() -> TravelTimeModel:
    return TravelTimeModel.load()


def travel_time(
    from_stop: str,
    to_stop: str,
    line: str,
    direction: str,
    at_time: datetime,
) -> timedelta | None:
    """Scheduled ride duration using the vendored model (lazily loaded once).

    Thin convenience over :meth:`TravelTimeModel.travel_time`; see it for the
    argument contract and the ``None`` ("no estimate") result.
    """
    return _default_model().travel_time(from_stop, to_stop, line, direction, at_time)


# --- Building the vendored artifact (scripts/refresh-travel-times) -------------


def _time_to_seconds(hms: str) -> int:
    """Parse a GTFS ``HH:MM:SS`` time to seconds since midnight (hours may be >=24)."""
    h, m, s = (int(part) for part in hms.split(":"))
    return h * 3600 + m * 60 + s


def _service_type_by_day_flags(row: dict[str, str]) -> str:
    """Classify a ``calendar.txt`` row as weekday / saturday / sunday by its flags."""
    if row.get("saturday") == "1":
        return "saturday"
    if row.get("sunday") == "1":
        return "sunday"
    return "weekday"


def _read_gtfs_csv(zf: zipfile.ZipFile, name: str) -> csv.DictReader[str]:
    """Stream a member of the GTFS zip as CSV rows (avoids buffering the ~36 MB
    stop_times.txt in full)."""
    return csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig"))


def build_schedule(zf: zipfile.ZipFile, routes: set[str]) -> dict[str, Any]:
    """Build the trimmed travel-times artifact dict from an open GTFS static zip.

    Keeps only trips on ``routes``, and for each service_type (weekday / saturday
    / sunday) only the single ``service_id`` with the most trips -- the base daily
    schedule -- dropping small holiday-supplement variants. Pure parsing (stdlib
    only), so it is unit-testable against a tiny in-memory zip.
    """
    service_type_of = {
        row["service_id"]: _service_type_by_day_flags(row)
        for row in _read_gtfs_csv(zf, "calendar.txt")
    }

    # trip_id -> (route, service_id) for watched routes; plus per-service_id counts
    # so we can pick the busiest service_id per service_type as the representative.
    trip_service: dict[str, tuple[str, str]] = {}
    counts: dict[str, int] = {}
    for row in _read_gtfs_csv(zf, "trips.txt"):
        route = row["route_id"]
        if route not in routes:
            continue
        sid = row["service_id"]
        trip_service[row["trip_id"]] = (route, sid)
        counts[sid] = counts.get(sid, 0) + 1

    chosen: dict[str, str] = {}
    for sid, count in counts.items():
        stype = service_type_of.get(sid, "weekday")
        if count > counts.get(chosen.get(stype, ""), -1):
            chosen[stype] = sid
    chosen_sids = set(chosen.values())

    # Stream stop_times.txt (the ~36 MB file), collecting stops per kept trip.
    trip_stops: dict[str, list[tuple[int, str, int]]] = {}
    for row in _read_gtfs_csv(zf, "stop_times.txt"):
        trip_id = row["trip_id"]
        service = trip_service.get(trip_id)
        if service is None or service[1] not in chosen_sids:
            continue
        trip_stops.setdefault(trip_id, []).append(
            (
                int(row["stop_sequence"]),
                row["stop_id"],
                _time_to_seconds(row["arrival_time"]),
            )
        )

    schedule: _Schedule = {}
    for trip_id, stops in trip_stops.items():
        route, sid = trip_service[trip_id]
        stype = service_type_of.get(sid, "weekday")
        stops.sort()  # by stop_sequence
        direction = stops[0][1][-1]  # N/S suffix; consistent within a trip
        if direction not in VALID_DIRECTIONS:
            # Unexpected stop_id (no N/S suffix): skip rather than bucket it under
            # a direction key travel_time can never query.
            continue
        trip: _Trip = {stop_id: seconds for _, stop_id, seconds in stops}
        schedule.setdefault(route, {}).setdefault(direction, {}).setdefault(
            stype, []
        ).append(trip)

    feed_info = next(_read_gtfs_csv(zf, "feed_info.txt"), {})
    return {
        "feed_version": feed_info.get("feed_version", ""),
        "generated": date.today().isoformat(),
        "routes": sorted(routes),
        "schedule": schedule,
    }


def download_static_gtfs(
    url: str = STATIC_GTFS_URL, timeout: float = DOWNLOAD_TIMEOUT
) -> bytes:
    """Download the MTA GTFS static subway zip. Raises :class:`httpx.HTTPError`."""
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def refresh_vendored_travel_times(
    routes: set[str],
    *,
    url: str = STATIC_GTFS_URL,
    dest: Path = VENDORED_TRAVEL_TIMES,
) -> Path:
    """Download the GTFS static feed, trim to ``routes``, and write the vendored gzip.

    Returns the written path. Used by ``scripts/refresh-travel-times``.
    """
    zip_bytes = download_static_gtfs(url)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        artifact = build_schedule(zf, routes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wt", encoding="utf-8") as f:
        json.dump(artifact, f, separators=(",", ":"))
    return dest


def _main() -> int:
    """Print one scheduled ride duration. For a quick spot-check against the MTA.

    ``uv run python -m app.travel <from_parent> <to_parent> <line> <N|S> [HH:MM]``
    e.g. ``uv run python -m app.travel R20 R16 Q N 08:30`` (Union Sq -> Times Sq).
    """
    import sys

    if len(sys.argv) < 5:
        print(_main.__doc__)
        return 2
    from_stop, to_stop, line, direction = sys.argv[1:5]
    now = datetime.now(EASTERN)
    if len(sys.argv) > 5:
        hh, mm = (int(x) for x in sys.argv[5].split(":"))
        now = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    model = TravelTimeModel.load()
    print(f"feed {model.feed_version} (built {model.generated})")
    ride = model.travel_time(from_stop, to_stop, line, direction, now)
    if ride is None:
        print(f"no scheduled estimate for {from_stop}->{to_stop} {line} {direction}")
        return 1
    print(
        f"{line} {direction} {from_stop}->{to_stop} at {now:%a %H:%M}: "
        f"{ride} ({ride.total_seconds() / 60:.0f} min)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
