"""Arrive-by trip recommendations: pick the ideal train for a target arrival (#27).

The board (#4/#7) answers "what's coming?"; this module answers the real commute
question: "I need to be at X by 9:00 -- which train do I catch?" Given a *trip*
(a boarding station + line/direction + destination) and a *target arrival time*,
it recommends the **latest** train that still gets you there on time -- so you
don't leave earlier than you must -- plus a safer earlier fallback, and it says
so plainly when even the best train arrives late.

It composes three things computed elsewhere:

* **Walk time** to the platform (#8) -- the boarding station's ``walk_minutes``:
  a train is only boardable when ``now + walk <= departure``.
* **Live countdowns** (#4) -- the :class:`~app.arrivals.ArrivalGroup` for the
  boarding station x line x direction gives each train's real departure time.
* **Scheduled ride duration** (#26) -- :func:`app.travel.travel_time` gives how
  long the ride from the boarding stop to the destination takes, so we know when
  each train *arrives* at X.

Target schedule
---------------
The target arrival is the user's *own* recurring schedule, distinct from the GTFS
timetable (#26 supplies ride durations, not desired arrival times). It's a small
TOML table keyed by weekday abbreviation (``mon``..``sun``) plus an optional
``default``:

    [trips.target]
    default = "09:00"   # applies to any *weekday* (Mon-Fri) not listed below
    tue = "08:45"       # Tuesdays specifically

Resolution for "today" (Eastern): an explicit weekday key wins; otherwise a
weekday falls back to ``default``; a weekend with no explicit key (and no
weekday-only ``default`` reaching it) has **no target** -- the board simply shows
no recommendation. So the example above means Tue 8:45, other weekdays 9:00, no
target on weekends. (Real stations/times live only in gitignored
``config.local.toml``; committed examples stay generic.)

Scope (#27): a single line/direction per trip. Cross-line alternatives and
transfers are out of scope -- TODO(#27-followup). Ad hoc touchscreen entry of a
one-off target is a deliberate follow-up too; config is the source of truth here.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from app.arrivals import (
    DEFAULT_LIMIT,
    ArrivalGroup,
    CrowdingHint,
    compute_arrivals,
    minutes_until,
    resolve_and_fetch,
)
from app.crowding import (
    CrowdingConfigError,
    annotate_crowding,
    resolve_crowding_rules,
    validated_crowd_window,
)
from app.feeds import EASTERN
from app.stops import ResolvedStation, StopIndex
from app.travel import travel_time as default_travel_time

logger = logging.getLogger(__name__)

# Weekday abbreviations indexed by ``datetime.weekday()`` (Mon=0 .. Sun=6). These
# are the valid per-day keys in a trip's ``target`` table, alongside ``default``.
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_KEY_SET = frozenset(WEEKDAY_KEYS) | {"default"}

# How many upcoming trains per trip to weigh when picking the ideal one. Larger
# than the board's DEFAULT_LIMIT so the ideal train can be further out than the
# few trains the board displays (a target up to ~an hour away at long headways).
RECOMMENDATION_LIMIT = 16

# A trip recommendation's overall state:
#   on_time     -- recommending the latest train that still arrives by target.
#   late        -- no boardable train makes it; recommending the least-late one.
#   no_service  -- no boardable train at all (nothing coming, or all un-catchable).
#   no_estimate -- boardable trains exist but no ride duration is known for them.
#   no_target   -- today has no target arrival time (e.g. a weekend).
RecommendationStatus = Literal[
    "on_time", "late", "no_service", "no_estimate", "no_target"
]

# travel_time(from_stop, to_stop, line, direction, at_time) -> timedelta | None.
TravelTimeFn = Callable[[str, str, str, str, datetime], timedelta | None]


class TripConfigError(Exception):
    """A ``[[trips]]`` block is malformed or references an unusable station."""


@dataclass(frozen=True)
class ResolvedTrip:
    """A configured trip resolved to concrete stops and a validated target table.

    ``origin_stop`` / ``dest_stop`` are **parent** GTFS stop IDs (as
    :func:`app.travel.travel_time` expects). ``boarding`` must match a configured
    ``[[stations]]`` block on the same ``line``/``direction`` -- that's where the
    live countdowns and ``walk_minutes`` come from. ``target`` is the raw
    weekday->``HH:MM`` table (validated); ``arrive_buffer_minutes`` shifts the
    effective target earlier so you arrive with a cushion.
    """

    name: str
    boarding: str
    line: str
    direction: str
    destination: str
    origin_stop: str
    dest_stop: str
    target: dict[str, str]
    arrive_buffer_minutes: float = 0.0
    # Optional lead-in window (#50): show this trip's recommendation strip only in
    # the last ``show_before_minutes`` before the target, then hide it. ``None``
    # keeps the original behavior -- the strip shows all day on a target day.
    show_before_minutes: float | None = None

    def effective_target(self, now: datetime) -> datetime | None:
        """Today's target arrival as a tz-aware datetime, or ``None`` if none.

        Picks the weekday's ``HH:MM`` from :attr:`target` (explicit day, else
        ``default`` on weekdays), anchors it to ``now``'s date in Eastern, and
        subtracts :attr:`arrive_buffer_minutes`. ``None`` means "no target today"
        (a weekend with no rule) -- the board shows no recommendation.
        """
        now = now.astimezone(EASTERN) if now.tzinfo else now.replace(tzinfo=EASTERN)
        key = WEEKDAY_KEYS[now.weekday()]
        if key in self.target:
            hhmm = self.target[key]
        elif now.weekday() < 5 and "default" in self.target:
            hhmm = self.target["default"]
        else:
            return None
        hour, minute = (int(part) for part in hhmm.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target - timedelta(minutes=self.arrive_buffer_minutes)


@dataclass(frozen=True)
class TrainOption:
    """One candidate train for a trip: when to leave, board, and arrive.

    ``departure`` is when the train leaves the boarding stop (from the live feed);
    ``minutes`` its whole-minute countdown. ``leave_by`` is the latest you can
    step out the door (``departure - walk``) and ``leave_in_minutes`` how long
    that is from now (never negative). ``arrival`` is the scheduled arrival at the
    destination, or ``None`` when no ride estimate exists. ``on_time`` is whether
    it arrives by the (buffered) target; ``lateness_minutes`` is how late it is
    otherwise (0 when on time or unknown).
    """

    departure: datetime
    minutes: int
    leave_by: datetime
    leave_in_minutes: int
    arrival: datetime | None
    on_time: bool
    lateness_minutes: int
    # Transfer-crowding hint (#28), carried from the boarding train's Arrival so a
    # consumer can flag a packed pick and prefer a fallback that beats the crowd.
    crowding: CrowdingHint | None = None


@dataclass(frozen=True)
class TripRecommendation:
    """The recommended train (and fallback) for one trip, plus its status.

    ``target`` is today's effective target arrival (``None`` on a no-target day).
    ``recommended`` is the train to catch -- the latest on-time one, or the
    least-late one when nothing makes it; ``fallback`` is a safer earlier on-time
    train when one exists. Both are ``None`` for the no-target / no-service /
    no-estimate states, which :attr:`status` names. ``terminal`` / ``borough`` are
    the boarding group's #41 terminal-station label for this (line, direction) --
    the same label the board shows -- so a consumer (e.g. focus mode #39) can name
    the direction without re-joining the board's groups; ``None`` when unlabeled.
    """

    name: str
    boarding: str
    line: str
    direction: str
    destination: str
    target: datetime | None
    status: RecommendationStatus
    recommended: TrainOption | None = None
    fallback: TrainOption | None = None
    terminal: str | None = None
    borough: str | None = None
    # The trip's optional lead-in window (#50), carried through so a consumer can
    # decide visibility against the request clock (see :meth:`visible_at`).
    show_before_minutes: float | None = None

    def visible_at(self, now: datetime) -> bool:
        """Whether this trip's recommendation strip should show at ``now`` (#50).

        No target today -> never (a weekend has nothing to recommend). No window
        configured -> always, the original behavior. Otherwise visible only in the
        lead-in window ``[target - show_before_minutes, target]`` -- so the strip
        appears as the train approaches and disappears once its moment has passed,
        rather than sitting on the board all day and wasting vertical space.
        """
        if self.target is None:
            return False
        if self.show_before_minutes is None:
            return True
        now = now.astimezone(EASTERN) if now.tzinfo else now.replace(tzinfo=EASTERN)
        start = self.target - timedelta(minutes=self.show_before_minutes)
        return start <= now <= self.target


def _resolve_stop(
    index: StopIndex, name: str, line: str, direction: str
) -> tuple[str, str]:
    """Canonical name + parent GTFS stop ID for ``name`` on ``line`` (via #3)."""
    resolved = index.resolve(name, [line], [direction])
    return resolved.name, resolved.line_stops[line]


def _validate_target(name: str, target: Any) -> dict[str, str]:
    """Validate a trip's ``target`` table: weekday/``default`` keys -> ``HH:MM``."""
    if not isinstance(target, dict) or not target:
        raise TripConfigError(
            f"Trip {name!r}: 'target' must be a non-empty table of "
            f'weekday -> "HH:MM" (e.g. {{ default = "09:00", tue = "08:45" }}).'
        )
    validated: dict[str, str] = {}
    for key, value in target.items():
        if key not in _WEEKDAY_KEY_SET:
            raise TripConfigError(
                f"Trip {name!r}: unknown target key {key!r}; use one of "
                f"{list(WEEKDAY_KEYS)} or 'default'."
            )
        try:
            hour, minute = (int(part) for part in str(value).split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError:
            raise TripConfigError(
                f'Trip {name!r}: target {key!r} must be "HH:MM" (24h), got {value!r}.'
            ) from None
        validated[key] = f"{hour:02d}:{minute:02d}"
    return validated


def resolve_trips(
    config: dict[str, Any], *, index: StopIndex | None = None
) -> list[ResolvedTrip]:
    """Resolve every ``[[trips]]`` block to a :class:`ResolvedTrip`.

    Validates the target table, the direction, and a non-negative arrive buffer,
    and resolves the boarding + destination names to parent stop IDs on the trip's
    line (via :mod:`app.stops`). Raises :class:`TripConfigError` on any problem.
    Returns ``[]`` when no trips are configured. Pass a prebuilt ``index`` to keep
    resolution offline (tests); otherwise the vendored station data is used.
    """
    trip_cfgs = config.get("trips", [])
    if not trip_cfgs:
        return []
    if index is None:
        index = StopIndex.from_csv()

    resolved: list[ResolvedTrip] = []
    seen: set[str] = set()
    for cfg in trip_cfgs:
        name = str(cfg.get("name", "")).strip()
        if not name:
            raise TripConfigError("A [[trips]] block is missing a 'name'.")
        if name in seen:
            raise TripConfigError(f"Duplicate trip name {name!r}.")
        seen.add(name)

        boarding = str(cfg.get("boarding", "")).strip()
        destination = str(cfg.get("destination", "")).strip()
        line = str(cfg.get("line", "")).strip()
        direction = str(cfg.get("direction", "")).strip()
        if not boarding or not destination or not line or not direction:
            raise TripConfigError(
                f"Trip {name!r}: 'boarding', 'destination', 'line', and "
                f"'direction' are all required."
            )

        buffer = cfg.get("arrive_buffer_minutes", 0)
        if (
            isinstance(buffer, bool)
            or not isinstance(buffer, (int, float))
            or buffer < 0
        ):
            raise TripConfigError(
                f"Trip {name!r}: arrive_buffer_minutes must be a non-negative "
                f"number, got {buffer!r}."
            )

        show_before = cfg.get("show_before_minutes")
        if show_before is not None and (
            isinstance(show_before, bool)
            or not isinstance(show_before, (int, float))
            or show_before <= 0
        ):
            raise TripConfigError(
                f"Trip {name!r}: show_before_minutes must be a positive number "
                f"(minutes before the target to start showing the strip), got "
                f"{show_before!r}."
            )

        target = _validate_target(name, cfg.get("target"))
        try:
            boarding_name, origin_stop = _resolve_stop(index, boarding, line, direction)
            dest_name, dest_stop = _resolve_stop(index, destination, line, direction)
        except Exception as exc:  # StationResolutionError et al.
            raise TripConfigError(f"Trip {name!r}: {exc}") from exc

        resolved.append(
            ResolvedTrip(
                name=name,
                # Canonical dataset spelling so this matches ArrivalGroup.station.
                boarding=boarding_name,
                line=line,
                direction=direction,
                destination=dest_name,
                origin_stop=origin_stop,
                dest_stop=dest_stop,
                target=target,
                arrive_buffer_minutes=float(buffer),
                show_before_minutes=(
                    float(show_before) if show_before is not None else None
                ),
            )
        )
    return resolved


def _comfort_fallback(
    recommended: TrainOption, earlier: list[TrainOption]
) -> TrainOption | None:
    """Pick the fallback among the earlier on-time trains (#28 comfort tiebreaker).

    Normally the on-time train right before the recommended one (an earlier
    cushion). But when the recommended pick is likely ``crowded``, prefer the
    latest earlier on-time train that ``beats_crowd`` -- a comfier cushion, if one
    exists. Never touches the recommended pick, so a needed train is never demoted.
    """
    if not earlier:
        return None
    if recommended.crowding == "crowded":
        beats = [c for c in earlier if c.crowding == "beats_crowd"]
        if beats:
            return beats[-1]
    return earlier[-1]


def recommend_trip(
    trip: ResolvedTrip,
    group: ArrivalGroup | None,
    now: datetime,
    *,
    travel_time: TravelTimeFn = default_travel_time,
) -> TripRecommendation:
    """Recommend the ideal train for one trip against its live arrivals.

    ``group`` is the boarding station's :class:`ArrivalGroup` for this trip's
    line/direction (``None`` if the trip's boarding station isn't a configured
    ``[[stations]]`` block -- then there are no live countdowns to reason about).
    Walks each not-yet-un-catchable train, dates its arrival at the destination
    via ``travel_time``, and picks the latest on-time boardable train; see the
    module and :data:`RecommendationStatus` docstrings for the states.
    """
    target = trip.effective_target(now)
    base = TripRecommendation(
        name=trip.name,
        boarding=trip.boarding,
        line=trip.line,
        direction=trip.direction,
        destination=trip.destination,
        target=target,
        status="no_target",
        # Carry the boarding group's #41 label so consumers (focus mode #39) name
        # the direction without re-deriving it; None when the group is absent.
        terminal=group.terminal if group else None,
        borough=group.borough if group else None,
        # Carry the lead-in window (#50) so visibility is decided per request clock.
        show_before_minutes=trip.show_before_minutes,
    )
    if target is None:
        return base

    walk = timedelta(minutes=group.walk_minutes if group and group.walk_minutes else 0)
    candidates: list[TrainOption] = []
    any_estimate = False
    for arrival in group.arrivals if group else []:
        departure = arrival.arrival
        # Boardable: you can still be on the platform in time (#27's now+walk<=dep).
        if departure - now < walk:
            continue
        ride = travel_time(
            trip.origin_stop, trip.dest_stop, trip.line, trip.direction, departure
        )
        dest_arrival = departure + ride if ride is not None else None
        on_time = dest_arrival is not None and dest_arrival <= target
        any_estimate = any_estimate or dest_arrival is not None
        leave_by = departure - walk
        candidates.append(
            TrainOption(
                departure=departure,
                minutes=arrival.minutes,
                leave_by=leave_by,
                leave_in_minutes=max(0, minutes_until(leave_by, now)),
                arrival=dest_arrival,
                on_time=on_time,
                lateness_minutes=(
                    0
                    if dest_arrival is None or on_time
                    else max(0, math.ceil((dest_arrival - target).total_seconds() / 60))
                ),
                # Carry the boarding train's crowding hint (#28) so the UI can flag
                # a packed recommendation and the fallback can beat the crowd.
                crowding=arrival.crowding,
            )
        )

    # candidates are appended in group.arrivals order (compute_arrivals already
    # sorts soonest-first); sort defensively so this holds for any caller.
    candidates.sort(key=lambda c: c.departure)
    on_time_options = [c for c in candidates if c.on_time]
    if on_time_options:
        # Ideal = latest train that still arrives on time (leave as late as you
        # can) -- never demoted by crowding, so a train you need to catch is never
        # de-prioritized (#28's rule). Fallback = an earlier on-time cushion: the
        # one right before it, but as a comfort tiebreaker, when the pick is likely
        # crowded, prefer the latest earlier on-time train that beats the crowd.
        recommended = on_time_options[-1]
        earlier = on_time_options[:-1]
        fallback = _comfort_fallback(recommended, earlier)
        return replace(
            base, status="on_time", recommended=recommended, fallback=fallback
        )
    if any_estimate:
        # Nothing arrives on time; recommend the boardable train that arrives
        # earliest -- the least-late option -- and say clearly it'll be late. Every
        # candidate with an estimate is late here (on_time_options is empty), so its
        # lateness_minutes is a faithful, monotonic-in-arrival key.
        least_late = min(
            (c for c in candidates if c.arrival is not None),
            key=lambda c: c.lateness_minutes,
        )
        return replace(base, status="late", recommended=least_late)
    if candidates:
        return replace(base, status="no_estimate")
    return replace(base, status="no_service")


def recommend_trips(
    trips: list[ResolvedTrip],
    groups: list[ArrivalGroup],
    now: datetime,
    *,
    travel_time: TravelTimeFn = default_travel_time,
) -> list[TripRecommendation]:
    """Recommend a train for each trip, matching it to its boarding ArrivalGroup."""
    by_key = {(g.station, g.line, g.direction): g for g in groups}
    return [
        recommend_trip(
            trip,
            by_key.get((trip.boarding, trip.line, trip.direction)),
            now,
            travel_time=travel_time,
        )
        for trip in trips
    ]


def fetch_board(
    config: dict[str, Any],
    *,
    now: datetime | None = None,
    board_limit: int = DEFAULT_LIMIT,
    travel_time: TravelTimeFn = default_travel_time,
    index: StopIndex | None = None,
) -> tuple[list[ArrivalGroup], list[TripRecommendation]]:
    """Resolve config, fetch live feeds once, and compute the board + trip recs.

    Computes arrivals a single time at :data:`RECOMMENDATION_LIMIT` (deep enough
    that a trip's ideal train can be further out than the board shows), hands those
    groups to the trip recommendations, and derives the board's short groups by
    truncating each to ``board_limit``. Returns ``(groups, recommendations)``;
    ``recommendations`` is empty when no trips are configured. The polling loop
    (#6) calls this each cycle.
    """
    if now is None:
        now = datetime.now(EASTERN)
    stations, updates, delta, direction_labels = resolve_and_fetch(config, index=index)
    # Resolve trips against current on-disk data (index=None in production) so they
    # pick up any station-data auto-heal resolve_and_fetch just performed; an
    # injected index (offline tests) still flows through to keep them offline.
    trips = resolve_trips(config, index=index)
    _check_trip_boarding(trips, stations)
    # Compute deep enough for both consumers: the recommendations need
    # RECOMMENDATION_LIMIT trains, the board needs board_limit; take the larger so
    # the board slice below is never short-changed.
    groups = compute_arrivals(
        stations,
        updates,
        now=now,
        limit=max(RECOMMENDATION_LIMIT, board_limit),
        walk_best_case_delta=delta,
        direction_labels=direction_labels,
    )
    # Tag transfer-crowding hints (#28) on the deep groups before the board slice
    # and the recommendations, so both see them. Crowding is an advisory comfort
    # layer: a malformed [[transfer_crowding]] block must never blank the board, so
    # log it and serve arrivals without hints rather than failing the poll (which
    # would strand /api/state at 503 -- unlike a trip config error, this degrades).
    try:
        rules = resolve_crowding_rules(config, index=index)
        groups = annotate_crowding(
            groups, rules, window_minutes=validated_crowd_window(config)
        )
    except CrowdingConfigError as exc:
        logger.warning(
            "Ignoring invalid [[transfer_crowding]] config; crowding disabled: %s", exc
        )
    recommendations = (
        recommend_trips(trips, groups, now, travel_time=travel_time) if trips else []
    )
    # The board shows only the soonest few; the deeper list above already has them
    # as its prefix, so slice rather than recompute.
    board_groups = [replace(g, arrivals=g.arrivals[:board_limit]) for g in groups]
    return board_groups, recommendations


def _check_trip_boarding(
    trips: list[ResolvedTrip], stations: list[ResolvedStation]
) -> None:
    """Fail loudly if a trip's boarding stop isn't a watched ``[[stations]]`` block.

    A trip draws its live countdowns and walk time from a matching station block
    (same name + line + direction). Without one it would silently resolve to a
    misleading "no service"; catch that config mistake here instead. The matching
    block must also set ``walk_minutes`` -- an arrive-by recommendation needs it to
    know when you can be on the platform, so a walk-blind trip is rejected too.
    """
    walk_by_watch = {
        (s.name, line, direction): s.walk_minutes
        for s in stations
        for line, direction, _ in s.watches()
    }
    for trip in trips:
        key = (trip.boarding, trip.line, trip.direction)
        if key not in walk_by_watch:
            raise TripConfigError(
                f"Trip {trip.name!r}: boarding {trip.boarding!r} "
                f"({trip.line} {trip.direction}) is not a configured [[stations]] "
                f"block. Add that station with this line and direction so the trip "
                f"has live countdowns and a walk time."
            )
        if walk_by_watch[key] is None:
            raise TripConfigError(
                f"Trip {trip.name!r}: boarding station {trip.boarding!r} needs "
                f"walk_minutes set -- the arrive-by recommendation uses it to know "
                f"when you can be on the platform."
            )
