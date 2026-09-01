"""Compute per-station arrival countdowns from feed data + configured stops.

This is the core domain logic (#4): it turns normalized feed records
(:class:`app.feeds.StopUpdate`) plus the resolved stations from config
(:class:`app.stops.ResolvedStation`) into the arrivals model the UI/API needs --
per station/line/direction, the next several trains as countdown minutes.

Shape produced (one :class:`ArrivalGroup` per station x line x direction):

    {station, line, direction, direction_label, color, arrivals: [minutes...]}

The heart is :func:`compute_arrivals`, a pure function of (resolved stations,
stop updates, now). It does no I/O, so it is fully unit-testable offline.
:func:`fetch_arrivals` is a thin convenience that resolves config, fetches the
needed feeds via :mod:`app.feeds`, and calls :func:`compute_arrivals`; the
polling/caching loop (#6) and the JSON API (#5) build on these.

Countdowns floor to whole minutes (a train 2m45s out reads "2 min"), matching the
MTA station countdown clocks. Trains that have already arrived (arrival in the
past) and updates with no arrival time are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.feeds import EASTERN, StopUpdate, fetch_stop_updates
from app.stops import VALID_DIRECTIONS, ResolvedStation, resolve_stations

# How many upcoming trains to keep per line/direction by default.
DEFAULT_LIMIT = 4

# Can I make this train, given the walk from home? (#8)
#   CATCHABLE  countdown > walk time -- makeable even at worst-case pace.
#   HURRY      walk_time - delta <= countdown <= walk_time -- only if you move.
#   MISSED     countdown < walk_time - delta -- not feasible; don't bother.
# ``None`` (not in this Literal) means the station has no configured walk time,
# so catchability is unknown and nothing is flagged.
Catchability = Literal["CATCHABLE", "HURRY", "MISSED"]

# Best-case walk is this many minutes faster than the configured worst-case walk;
# the HURRY band is that grace window. Overridable via config (#8).
DEFAULT_WALK_BEST_CASE_DELTA = 1

# Human labels for the feed's N/S direction suffix -- the fallback shown for any
# (line, direction) with no configured terminal label (#41).
_DIRECTION_LABELS = {"N": "Northbound", "S": "Southbound"}

# Official MTA line colors (hex), keyed by GTFS route_id. Grouped by trunk line;
# shuttles (GS/FS/H) and the Staten Island Railway use the MTA "grey"/SIR blue.
# Source: MTA subway line colors (developer resources), stable over many years.
_ROUTE_COLORS = {
    "1": "#EE352E",
    "2": "#EE352E",
    "3": "#EE352E",  # red (Broadway-7 Av)
    "4": "#00933C",
    "5": "#00933C",
    "6": "#00933C",  # green (Lexington Av)
    "7": "#B933AD",  # purple (Flushing)
    "A": "#0039A6",
    "C": "#0039A6",
    "E": "#0039A6",  # blue (8 Av)
    "B": "#FF6319",
    "D": "#FF6319",
    "F": "#FF6319",
    "M": "#FF6319",  # orange (6 Av)
    "G": "#6CBE45",  # light green (Crosstown)
    "J": "#996633",
    "Z": "#996633",  # brown (Nassau St)
    "L": "#A7A9AC",  # grey (14 St-Canarsie)
    "N": "#FCCC0A",
    "Q": "#FCCC0A",
    "R": "#FCCC0A",
    "W": "#FCCC0A",  # yellow (Broadway)
    "GS": "#808183",
    "FS": "#808183",
    "H": "#808183",  # shuttles (dark grey)
    "SI": "#0039A6",
    "SIR": "#0039A6",  # Staten Island Railway (blue)
}

# Fallback color for any route not in the map above.
_DEFAULT_COLOR = "#808183"


@dataclass(frozen=True)
class Arrival:
    """One upcoming train at a stop.

    ``minutes`` is whole minutes until arrival, floored and never negative (0
    means arriving now). ``arrival`` is the tz-aware America/New_York time it was
    computed from -- the feed's arrival time, or its departure time at a trip's
    origin terminal where the feed omits arrival. ``headsign`` is the
    destination/terminal label. ``catchability`` classifies the train against the
    station's walk time (#8), or is ``None`` when no walk time is configured.
    """

    minutes: int
    arrival: datetime
    trip_id: str
    headsign: str | None
    catchability: Catchability | None = None


@dataclass(frozen=True)
class DirectionLabel:
    """A configured terminal-station label for one (line, direction) (#41).

    ``terminal`` is the destination the board shows in place of the compass word
    (e.g. "Inwood-207 St"); ``borough`` is the smaller secondary text (e.g.
    "Man"). Both are author-written free text, so a branchy direction can carry a
    combined label ("Rockaway / Lefferts"). Both are required together.
    """

    terminal: str
    borough: str


@dataclass(frozen=True)
class ArrivalGroup:
    """The next several trains for one station x line x direction.

    ``direction`` is the raw "N"/"S" feed suffix; ``direction_label`` its human
    compass form ("Northbound"/"Southbound"). ``terminal`` / ``borough`` are the
    configured terminal-station label for this (line, direction) (#41), or
    ``None`` when unconfigured -- the board then falls back to ``direction_label``.
    ``color`` is the line's hex color. ``walk_minutes`` is the station's
    configured walk time (``None`` if unset), echoed here so the UI has the
    threshold behind each arrival's catchability.
    """

    station: str
    line: str
    direction: str
    direction_label: str
    color: str
    arrivals: list[Arrival]
    walk_minutes: float | None = None
    terminal: str | None = None
    borough: str | None = None


def _minutes_until(arrival: datetime, now: datetime) -> int:
    """Floored whole minutes from ``now`` to ``arrival`` (a 2m45s gap -> 2)."""
    return int((arrival - now).total_seconds() // 60)


def _classify(
    minutes: int, walk_minutes: float | None, delta: float
) -> Catchability | None:
    """Classify a train ``minutes`` out against a ``walk_minutes`` walk time.

    Returns ``None`` when no walk time is configured (unknown); otherwise
    CATCHABLE / HURRY / MISSED per the bands documented on :data:`Catchability`,
    with ``delta`` as the best-case grace window.
    """
    if walk_minutes is None:
        return None
    if minutes > walk_minutes:
        return "CATCHABLE"
    if minutes >= walk_minutes - delta:
        return "HURRY"
    return "MISSED"


def _clean_label_field(entry: dict[str, Any], key: str) -> str:
    """Return a required non-empty string field from a direction_labels entry."""
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"direction_labels entry {entry!r}: {key!r} must be a non-empty string."
        )
    return value.strip()


def parse_direction_labels(
    config: dict[str, Any],
) -> dict[tuple[str, str], DirectionLabel]:
    """Parse ``[[direction_labels]]`` config into a (line, direction) -> label map.

    Each entry must give a ``line``, an ``N``/``S`` ``direction``, and non-empty
    ``terminal`` and ``borough`` strings. Raises :class:`ValueError` on a
    malformed or duplicate entry. A (line, direction) with no entry simply isn't
    in the map, and :func:`compute_arrivals` falls back to the compass label for
    it -- so unconfigured lines keep working.
    """
    labels: dict[tuple[str, str], DirectionLabel] = {}
    for entry in config.get("direction_labels", []):
        line = _clean_label_field(entry, "line")
        direction = _clean_label_field(entry, "direction")
        if direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"direction_labels entry {entry!r}: direction must be one of "
                f"{list(VALID_DIRECTIONS)}."
            )
        key = (line, direction)
        if key in labels:
            raise ValueError(
                f"Duplicate direction_labels entry for line {line!r} "
                f"direction {direction!r}."
            )
        labels[key] = DirectionLabel(
            terminal=_clean_label_field(entry, "terminal"),
            borough=_clean_label_field(entry, "borough"),
        )
    return labels


def compute_arrivals(
    stations: list[ResolvedStation],
    updates: list[StopUpdate],
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    walk_best_case_delta: float = DEFAULT_WALK_BEST_CASE_DELTA,
    direction_labels: dict[tuple[str, str], DirectionLabel] | None = None,
) -> list[ArrivalGroup]:
    """Build the arrivals model from resolved stations + feed stop updates.

    For each station x line x direction, keep the ``limit`` soonest not-yet-passed
    trains as :class:`Arrival` countdowns. ``updates`` may span many stops/routes
    (e.g. a whole feed group); only those matching a watched (route, stop) count.
    Groups are emitted in config order and always present, even when empty (no
    trains coming), so the UI can render a stable board. ``now`` defaults to the
    current America/New_York time.

    Each arrival is classified against its station's walk time (#8) using
    ``walk_best_case_delta`` as the HURRY grace window; see :func:`_classify`.
    ``walk_best_case_delta`` is trusted here (a plain number); :func:`fetch_arrivals`
    validates it at the config boundary. TODO(#6): the polling loop must reuse
    :func:`fetch_arrivals` or run the same non-negative check before calling this,
    so a bad config value can't reach here unvalidated.
    """
    if now is None:
        now = datetime.now(EASTERN)
    labels = direction_labels or {}

    # Index updates by (route_id, stop_id) for O(1) lookup per watched combo.
    by_route_stop: dict[tuple[str, str], list[StopUpdate]] = {}
    for u in updates:
        by_route_stop.setdefault((u.route_id, u.stop_id), []).append(u)

    groups: list[ArrivalGroup] = []
    for station in stations:
        for line, direction, stop_id in station.watches():
            arrivals: list[Arrival] = []
            for u in by_route_stop.get((line, stop_id), []):
                # The feed omits arrival at a trip's origin terminal (a train
                # starting its run there has no arrival, only a departure); fall
                # back to departure so those trains still show. Mid-line stops
                # carry both, so this picks arrival there as before.
                when = u.arrival or u.departure
                if when is None:
                    continue  # no timestamp at all -> can't count down
                minutes = _minutes_until(when, now)
                if minutes < 0:
                    continue  # already departed / in the past
                arrivals.append(
                    Arrival(
                        minutes=minutes,
                        arrival=when,
                        trip_id=u.trip_id,
                        headsign=u.headsign,
                        catchability=_classify(
                            minutes, station.walk_minutes, walk_best_case_delta
                        ),
                    )
                )
            arrivals.sort(key=lambda a: (a.arrival, a.trip_id))
            label = labels.get((line, direction))
            terminal, borough = (
                (label.terminal, label.borough) if label else (None, None)
            )
            groups.append(
                ArrivalGroup(
                    station=station.name,
                    line=line,
                    direction=direction,
                    direction_label=_DIRECTION_LABELS.get(direction, direction),
                    color=_ROUTE_COLORS.get(line, _DEFAULT_COLOR),
                    arrivals=arrivals[:limit],
                    walk_minutes=station.walk_minutes,
                    terminal=terminal,
                    borough=borough,
                )
            )
    return groups


def fetch_arrivals(
    config: dict[str, Any],
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[ArrivalGroup]:
    """Resolve ``config``, fetch the needed live feeds, and compute arrivals.

    A convenience tying resolution + fetch + :func:`compute_arrivals` together for
    a CLI or a first-cut API. Only the feed group(s) covering the configured lines
    are fetched (deduped by :mod:`app.feeds`). The polling/caching loop (#6) will
    instead reuse a cached fetch rather than calling this each request.
    """
    delta = config.get("walk_best_case_delta_minutes", DEFAULT_WALK_BEST_CASE_DELTA)
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or delta < 0:
        raise ValueError(
            f"walk_best_case_delta_minutes must be a non-negative number, "
            f"got {delta!r}."
        )
    # Parse the label config before resolving stations so a malformed
    # direction_labels block fails fast, before resolve_stations can touch the
    # network on a stale-data refresh (mirrors the delta check above).
    direction_labels = parse_direction_labels(config)
    stations = resolve_stations(config)
    routes = {line for s in stations for line in s.lines}
    updates = fetch_stop_updates(routes)
    return compute_arrivals(
        stations,
        updates,
        now=now,
        limit=limit,
        walk_best_case_delta=delta,
        direction_labels=direction_labels,
    )


def _main() -> int:
    """Print the computed arrivals board for the active config (live feeds).

    Run with ``uv run python -m app.arrivals`` -- a quick spot-check against the
    MTA app / station countdown clocks (acceptance criteria).
    """
    import logging

    from app.config import load_config
    from app.feeds import FeedError
    from app.stops import StationResolutionError

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        groups = fetch_arrivals(load_config())
    except (StationResolutionError, FeedError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    # Compact catchability marker per train: + catchable, ! hurry, x missed.
    marks = {"CATCHABLE": "+", "HURRY": "!", "MISSED": "x"}
    for g in groups:
        trains = [
            f"{a.minutes}m{marks.get(a.catchability or '', '')}" for a in g.arrivals
        ]
        mins = ", ".join(trains) or "(none)"
        walk = f"walk {g.walk_minutes:g}m" if g.walk_minutes is not None else "walk ?"
        print(f"{g.station:<24} {g.line:>2} {g.direction_label:<10} {walk:<8} {mins}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
