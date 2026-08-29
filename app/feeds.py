"""Fetch and parse MTA GTFS-Realtime subway feeds.

The MTA publishes real-time subway data as GTFS-Realtime protobuf feeds, split
across line groups (numbered lines, ACE, BDFM, G, JZ, NQRW, L, SIR). As of 2021
these subway feeds no longer require an API key.

This module:

1. Maps each subway route (line) to its feed group and URL
   (:data:`ROUTE_TO_FEED`, :data:`FEED_URLS`).
2. Fetches the raw protobuf bytes over HTTP with :mod:`httpx` (explicit timeout
   and error handling), so a later async polling loop can reuse the fetch.
3. Hands those bytes to ``nyct-gtfs`` for parsing (it understands the NYCT
   protobuf extensions: N/S direction, track, friendly Trip/stop objects).
4. Normalizes the parsed trips into a small :class:`StopUpdate` dataclass.

Scope note: this module only fetches and parses into a normalized shape. It does
not compute per-station countdowns (issue #4), poll/cache (issue #6), or serve
JSON (issue #5).

Errors (HTTP failures, timeouts, malformed protobuf) are raised as a typed
:class:`FeedError` rather than swallowed, so the caller (e.g. the polling loop)
can decide whether to log-and-continue or surface the failure.

CLI: ``uv run python -m app.feeds <route> [stop_id]`` fetches the live feed for a
route and prints upcoming stop-time updates (optionally filtered to one stop),
e.g. ``uv run python -m app.feeds 6 631N``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from google.protobuf.message import DecodeError
from nyct_gtfs import NYCTFeed

# The MTA subway system runs on Eastern time; feed timestamps are Unix epochs
# that nyct-gtfs decodes into naive host-local datetimes (see _to_eastern).
_EASTERN = ZoneInfo("America/New_York")

# Base URL for the MTA GTFS-Realtime subway feeds. No API key required.
_FEED_BASE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds"

# Feed group -> feed URL. One feed serves each line group. Confirmed working
# against the live MTA service on 2026-08-29.
FEED_URLS: dict[str, str] = {
    "numbered": f"{_FEED_BASE}/nyct%2Fgtfs",
    "ace": f"{_FEED_BASE}/nyct%2Fgtfs-ace",
    "bdfm": f"{_FEED_BASE}/nyct%2Fgtfs-bdfm",
    "g": f"{_FEED_BASE}/nyct%2Fgtfs-g",
    "jz": f"{_FEED_BASE}/nyct%2Fgtfs-jz",
    "nqrw": f"{_FEED_BASE}/nyct%2Fgtfs-nqrw",
    "l": f"{_FEED_BASE}/nyct%2Fgtfs-l",
    "sir": f"{_FEED_BASE}/nyct%2Fgtfs-si",
}

# Route (GTFS route_id) -> feed group. Covers every subway route plus the three
# shuttles: "GS" (42 St / Times Sq-Grand Central), "FS" (Franklin Av), "H"
# (Rockaway Park). Keyed by the route_id that appears in the realtime feed.
ROUTE_TO_FEED: dict[str, str] = {
    "1": "numbered",
    "2": "numbered",
    "3": "numbered",
    "4": "numbered",
    "5": "numbered",
    "6": "numbered",
    "7": "numbered",
    "GS": "numbered",
    "A": "ace",
    "C": "ace",
    "E": "ace",
    "H": "ace",
    "B": "bdfm",
    "D": "bdfm",
    "F": "bdfm",
    "M": "bdfm",
    "FS": "bdfm",
    "G": "g",
    "J": "jz",
    "Z": "jz",
    "N": "nqrw",
    "Q": "nqrw",
    "R": "nqrw",
    "W": "nqrw",
    "L": "l",
    "SI": "sir",
    "SIR": "sir",
}

# Default HTTP timeout (seconds) for a single feed fetch.
DEFAULT_TIMEOUT = 10.0


class FeedError(Exception):
    """A feed could not be fetched or parsed (HTTP error, timeout, or bad data)."""


@dataclass(frozen=True)
class StopUpdate:
    """A single predicted stop for one trip, normalized from the feed.

    ``stop_id`` includes the direction suffix (e.g. ``"631N"``); ``direction`` is
    that same "N"/"S" suffix pulled out for convenience. ``arrival``/``departure``
    are timezone-aware America/New_York datetimes and may be ``None`` (the feed
    omits arrival at an origin terminal and departure at a destination terminal).
    """

    route_id: str
    trip_id: str
    stop_id: str
    direction: str
    arrival: datetime | None
    departure: datetime | None


def _to_eastern(dt: datetime | None) -> datetime | None:
    """Make a nyct-gtfs datetime timezone-aware in America/New_York.

    nyct-gtfs builds arrival/departure via ``datetime.fromtimestamp(ts)`` with no
    tzinfo, yielding a naive datetime in the *host's* local zone. Calling
    ``astimezone`` on a naive datetime interprets it as host-local and converts to
    Eastern, so the result is correct regardless of the server's timezone.
    """
    if dt is None:
        return None
    return dt.astimezone(_EASTERN)


def feed_urls_for_routes(routes: Iterable[str]) -> set[str]:
    """Return the set of feed URLs needed to cover ``routes``.

    Raises :class:`ValueError` (with a clear message) if a route is unknown, so a
    typo in config surfaces loudly rather than silently fetching nothing.
    """
    urls: set[str] = set()
    for route in routes:
        try:
            group = ROUTE_TO_FEED[route]
        except KeyError:
            raise ValueError(
                f"Unknown subway route {route!r}; known routes: {sorted(ROUTE_TO_FEED)}"
            ) from None
        urls.add(FEED_URLS[group])
    return urls


def fetch_feed_bytes(url: str, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """Fetch the raw protobuf bytes for one feed URL.

    Raises :class:`FeedError` on any HTTP error or timeout.
    """
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FeedError(f"Failed to fetch feed {url}: {exc}") from exc
    return response.content


def parse_feed(raw: bytes) -> NYCTFeed:
    """Parse raw protobuf bytes into an ``NYCTFeed``.

    Raises :class:`FeedError` if the bytes are not a valid GTFS-Realtime message.
    """
    # fetch_immediately=False so nyct-gtfs does not hit the network; the URL is a
    # placeholder that is never fetched because we supply the bytes ourselves.
    # Note (#6): constructing NYCTFeed reloads the bundled GTFS-static tables
    # (trips.txt/stops.txt) from disk each call. A polling loop should build one
    # NYCTFeed and reuse it via load_gtfs_bytes() rather than rebuilding per poll.
    feed = NYCTFeed("https://placeholder.invalid/gtfs", fetch_immediately=False)
    try:
        feed.load_gtfs_bytes(raw)
    except DecodeError as exc:
        raise FeedError(f"Malformed GTFS-Realtime feed: {exc}") from exc
    return feed


def extract_stop_updates(
    feed: NYCTFeed,
    routes: Iterable[str] | None = None,
    stop_id: str | None = None,
) -> list[StopUpdate]:
    """Flatten a parsed feed into :class:`StopUpdate` records.

    ``routes``, if given, keeps only trips on those routes (a feed group carries
    several routes, e.g. the NQRW feed includes N/Q/R/W). ``stop_id``, if given,
    keeps only updates at that exact stop, e.g. ``"631N"``.
    """
    route_filter = set(routes) if routes is not None else None
    updates: list[StopUpdate] = []
    for trip in feed.trips:
        if route_filter is not None and trip.route_id not in route_filter:
            continue
        for stu in trip.stop_time_updates:
            if stop_id is not None and stu.stop_id != stop_id:
                continue
            updates.append(
                StopUpdate(
                    route_id=trip.route_id,
                    trip_id=trip.trip_id,
                    stop_id=stu.stop_id,
                    direction=stu.stop_id[-1],
                    arrival=_to_eastern(stu.arrival),
                    departure=_to_eastern(stu.departure),
                )
            )
    return updates


def fetch_stop_updates(
    routes: Iterable[str],
    stop_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[StopUpdate]:
    """Fetch the feed(s) serving ``routes`` and return normalized stop updates.

    Only the feed group(s) needed by ``routes`` are fetched. Results are filtered
    to ``routes`` (and to ``stop_id`` if given). Raises :class:`FeedError` if any
    needed feed cannot be fetched or parsed.
    """
    routes = list(routes)
    updates: list[StopUpdate] = []
    for url in feed_urls_for_routes(routes):
        feed = parse_feed(fetch_feed_bytes(url, timeout=timeout))
        updates.extend(extract_stop_updates(feed, routes=routes, stop_id=stop_id))
    return updates


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.feeds <route> [stop_id]")
        print("example: python -m app.feeds 6 631N")
        return 2

    route = argv[0]
    stop_id = argv[1] if len(argv) > 1 else None
    try:
        updates = fetch_stop_updates([route], stop_id=stop_id)
    except (FeedError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    where = f"stop {stop_id}" if stop_id else f"route {route}"
    print(f"{len(updates)} upcoming stop-time update(s) for {where}:")
    for u in sorted(updates, key=lambda u: (u.arrival is None, u.arrival)):
        when = u.arrival.strftime("%H:%M:%S") if u.arrival else "--:--:--"
        print(f"  {u.route_id:>2} {u.direction or '?'}  {u.stop_id:<6} arr {when}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
