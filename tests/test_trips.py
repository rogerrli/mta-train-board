"""Tests for app.trips (arrive-by recommendations) -- fully offline.

Config resolution uses the vendored ``stations.csv`` via a prebuilt
:class:`StopIndex` (no network). Recommendation logic is driven with synthetic
:class:`ArrivalGroup`s, a fixed ``now``, and an injected ``travel_time`` so the
"which train?" math is deterministic and needs no live feeds or GTFS data.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.arrivals import Arrival, ArrivalGroup
from app.stops import ResolvedStation, StopIndex
from app.trips import (
    ResolvedTrip,
    TripConfigError,
    _check_trip_boarding,
    recommend_trip,
    recommend_trips,
    resolve_trips,
)

EASTERN = ZoneInfo("America/New_York")
# 2026-09-01 is a Tuesday; 09-02 Wednesday; 09-05 Saturday. Fixed so weekday and
# countdown math are stable.
TUESDAY_7_40 = datetime(2026, 9, 1, 7, 40, tzinfo=EASTERN)
WEDNESDAY_7_40 = datetime(2026, 9, 2, 7, 40, tzinfo=EASTERN)
SATURDAY_7_40 = datetime(2026, 9, 5, 7, 40, tzinfo=EASTERN)

TARGET = {"default": "08:30", "tue": "08:15"}  # placeholder, not a real schedule


@pytest.fixture(scope="module")
def index() -> StopIndex:
    return StopIndex.from_csv()


def _trip(
    *,
    boarding="Fulton St",
    origin="A38",
    dest="A24",
    target=None,
    buffer=0.0,
) -> ResolvedTrip:
    return ResolvedTrip(
        name="morning-uptown",
        boarding=boarding,
        line="A",
        direction="N",
        destination="59 St-Columbus Circle",
        origin_stop=origin,
        dest_stop=dest,
        target=dict(TARGET if target is None else target),
        arrive_buffer_minutes=buffer,
    )


def _group(
    trip: ResolvedTrip, depart_minutes: list[int], now: datetime, walk_minutes=6
) -> ArrivalGroup:
    """An ArrivalGroup whose trains depart the given whole-minutes from ``now``."""
    arrivals = [
        Arrival(
            minutes=m,
            arrival=now + timedelta(minutes=m),
            trip_id=f"t{m}",
            headsign="59 St-Columbus Circle",
        )
        for m in depart_minutes
    ]
    return ArrivalGroup(
        station=trip.boarding,
        line=trip.line,
        direction=trip.direction,
        direction_label="Northbound",
        color="#0039A6",
        arrivals=arrivals,
        walk_minutes=walk_minutes,
    )


def _fixed_ride(minutes: float):
    """A travel_time fn that always returns a fixed ride duration."""
    return lambda *_args: timedelta(minutes=minutes)


def _no_estimate(*_args) -> None:
    return None


# --- target schedule resolution ----------------------------------------------


def test_weekday_target_picks_explicit_day_over_default():
    trip = _trip()
    assert trip.effective_target(TUESDAY_7_40).timetz().isoformat().startswith("08:15")


def test_weekday_target_falls_back_to_default():
    trip = _trip()
    assert trip.effective_target(WEDNESDAY_7_40).hour == 8
    assert trip.effective_target(WEDNESDAY_7_40).minute == 30


def test_weekend_has_no_target_when_only_default_configured():
    # `default` reaches weekdays only; Saturday with no explicit key -> no target.
    assert _trip().effective_target(SATURDAY_7_40) is None


def test_explicit_weekend_key_is_honored():
    trip = _trip(target={"default": "08:30", "sat": "11:00"})
    assert trip.effective_target(SATURDAY_7_40).hour == 11


def test_arrive_buffer_shifts_target_earlier():
    trip = _trip(target={"tue": "08:15"}, buffer=5)
    target = trip.effective_target(TUESDAY_7_40)
    assert (target.hour, target.minute) == (8, 10)


# --- recommendation logic ----------------------------------------------------


def test_on_time_picks_latest_on_time_train_with_earlier_fallback():
    # Wednesday target 08:30, ride 40 min, walk 6. Depart 07:47->08:27, 07:49->08:29
    # (both boardable + on time), 07:56->08:36 (late). Ideal = 07:49 (latest on
    # time); fallback = 07:47 (the earlier on-time train).
    trip = _trip()
    now = WEDNESDAY_7_40
    group = _group(trip, [7, 9, 16], now)  # 07:47, 07:49, 07:56
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    assert rec.status == "on_time"
    assert rec.recommended.departure == now + timedelta(minutes=9)
    assert rec.recommended.on_time is True
    assert rec.fallback.departure == now + timedelta(minutes=7)


def test_no_earlier_on_time_train_leaves_fallback_none():
    trip = _trip()
    now = WEDNESDAY_7_40
    group = _group(trip, [9], now)  # only 07:49 -> 08:29, on time
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    assert rec.status == "on_time"
    assert rec.fallback is None


def test_late_when_no_train_makes_target_recommends_least_late():
    # Tuesday target 08:15, ride 40 min: earliest boardable 07:47 -> 08:27 (late).
    trip = _trip()
    now = TUESDAY_7_40
    group = _group(trip, [7, 12, 20], now)  # 07:47, 07:52, 08:00
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    assert rec.status == "late"
    # Soonest boardable = least late.
    assert rec.recommended.departure == now + timedelta(minutes=7)
    assert rec.recommended.on_time is False
    assert rec.recommended.lateness_minutes == 12  # 08:27 vs 08:15
    assert rec.fallback is None


def test_unboardable_trains_are_ignored():
    # walk 6 min: a train 3 min out can't be boarded; the 10-min one can.
    trip = _trip()
    now = WEDNESDAY_7_40
    group = _group(trip, [3, 10], now, walk_minutes=6)
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    assert rec.recommended.departure == now + timedelta(minutes=10)


def test_no_service_when_no_boardable_train():
    trip = _trip()
    now = WEDNESDAY_7_40
    group = _group(trip, [1, 2], now, walk_minutes=6)  # both within walk time
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    assert rec.status == "no_service"
    assert rec.recommended is None


def test_no_estimate_when_travel_time_unknown():
    trip = _trip()
    now = WEDNESDAY_7_40
    group = _group(trip, [10, 20], now)
    rec = recommend_trip(trip, group, now, travel_time=_no_estimate)
    assert rec.status == "no_estimate"
    assert rec.recommended is None


def test_no_target_day_returns_no_target_status():
    trip = _trip()
    group = _group(trip, [10], SATURDAY_7_40)
    rec = recommend_trip(trip, group, SATURDAY_7_40, travel_time=_fixed_ride(40))
    assert rec.status == "no_target"
    assert rec.target is None
    assert rec.recommended is None


def test_missing_group_is_no_service():
    # Boarding station isn't a configured [[stations]] block -> no live countdowns.
    trip = _trip()
    rec = recommend_trip(trip, None, WEDNESDAY_7_40, travel_time=_fixed_ride(40))
    assert rec.status == "no_service"


def test_leave_by_and_leave_in_are_correct():
    trip = _trip()
    now = WEDNESDAY_7_40
    group = _group(trip, [10], now, walk_minutes=6)  # departs 08:50, walk 6
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    opt = rec.recommended
    assert opt.leave_by == now + timedelta(minutes=4)  # 08:50 - 6 min walk
    assert opt.leave_in_minutes == 4


def test_recommend_trips_matches_group_by_station_line_direction():
    trip = _trip()
    now = WEDNESDAY_7_40
    matching = _group(trip, [10], now)
    other = ArrivalGroup(
        station="Somewhere Else",
        line="A",
        direction="N",
        direction_label="Northbound",
        color="#000",
        arrivals=[],
        walk_minutes=6,
    )
    recs = recommend_trips([trip], [other, matching], now, travel_time=_fixed_ride(40))
    assert recs[0].status == "on_time"


# --- boarding-station cross-check --------------------------------------------


def _resolved_station(name, line, direction, parent="A38", walk=6):
    return ResolvedStation(
        name=name,
        directions=(direction,),
        line_stops={line: parent},
        walk_minutes=walk,
    )


def test_check_trip_boarding_passes_when_station_is_watched():
    trip = _trip()
    stations = [_resolved_station("Fulton St", "A", "N")]
    _check_trip_boarding([trip], stations)  # no raise


def test_check_trip_boarding_raises_when_boarding_not_configured():
    trip = _trip()
    # Right station name but the A/N platform isn't watched (only C here).
    stations = [_resolved_station("Fulton St", "C", "N")]
    with pytest.raises(TripConfigError, match="not a configured"):
        _check_trip_boarding([trip], stations)


def test_check_trip_boarding_requires_walk_minutes():
    trip = _trip()
    stations = [_resolved_station("Fulton St", "A", "N", walk=None)]
    with pytest.raises(TripConfigError, match="walk_minutes"):
        _check_trip_boarding([trip], stations)


def test_recommend_reads_full_arrival_list_beyond_board_limit():
    # The board only shows the soonest few trains, but the ideal on-time train can
    # be further out. recommend_trip must reason over the whole group, not a
    # board-truncated prefix. Wednesday target 08:30, ride 40 min, walk 6: trains
    # every 2 min from 07:47; the latest on-time departure is 07:49, which sits at
    # index 1.
    trip = _trip()
    now = WEDNESDAY_7_40
    # Departures 07:47..08:05 (indices 0..9). On-time (dep <= 07:50) are 07:47, 07:49.
    group = _group(trip, list(range(7, 27, 2)), now)  # 7,9,11,...,25
    assert len(group.arrivals) == 10
    rec = recommend_trip(trip, group, now, travel_time=_fixed_ride(40))
    assert rec.status == "on_time"
    assert rec.recommended.departure == now + timedelta(minutes=9)  # 07:49

    # If recommendations were fed the board-truncated list (first 4), a later ideal
    # would be missed. Prove the deep list matters: with a target reachable only by
    # a train beyond index 4, truncating drops it.
    late_target = _trip(target={"default": "09:10"})  # 40-min ride -> dep <= 08:30
    full = recommend_trip(late_target, group, now, travel_time=_fixed_ride(40))
    truncated = recommend_trip(
        late_target,
        _group(late_target, list(range(7, 15, 2)), now),  # only 07:47..07:53
        now,
        travel_time=_fixed_ride(40),
    )
    # Full list picks the latest on-time train (08:05, index 9); the truncated
    # 4-train list can only reach 07:53 -- a strictly earlier recommendation.
    assert full.recommended.departure == now + timedelta(minutes=25)  # 08:05
    assert truncated.recommended.departure == now + timedelta(minutes=13)  # 07:53


# --- config resolution -------------------------------------------------------


def test_resolve_trips_resolves_parent_stops(index: StopIndex):
    cfg = {
        "trips": [
            {
                "name": "morning-uptown",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "59 St-Columbus Circle",
                "target": {"default": "08:30", "tue": "08:15"},
            }
        ]
    }
    (trip,) = resolve_trips(cfg, index=index)
    assert trip.origin_stop == "A38"
    assert trip.dest_stop == "A24"
    assert trip.boarding == "Fulton St"
    assert trip.target == {"default": "08:30", "tue": "08:15"}


def test_resolve_trips_empty_without_trips_config(index: StopIndex):
    assert resolve_trips({}, index=index) == []


@pytest.mark.parametrize(
    "trip_cfg, message",
    [
        ({"name": "t"}, "required"),
        ({"boarding": "x", "line": "A", "direction": "N", "destination": "y"}, "name"),
        (
            {
                "name": "t",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "59 St-Columbus Circle",
            },
            "target",
        ),
        (
            {
                "name": "t",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "59 St-Columbus Circle",
                "target": {"funday": "09:00"},
            },
            "unknown target key",
        ),
        (
            {
                "name": "t",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "59 St-Columbus Circle",
                "target": {"tue": "25:00"},
            },
            "HH:MM",
        ),
        (
            {
                "name": "t",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "59 St-Columbus Circle",
                "target": {"tue": "09:00"},
                "arrive_buffer_minutes": -1,
            },
            "arrive_buffer_minutes",
        ),
    ],
)
def test_resolve_trips_rejects_bad_config(index, trip_cfg, message):
    with pytest.raises(TripConfigError, match=message):
        resolve_trips({"trips": [trip_cfg]}, index=index)


def test_resolve_trips_rejects_duplicate_names(index: StopIndex):
    one = {
        "name": "dup",
        "boarding": "Fulton St",
        "line": "A",
        "direction": "N",
        "destination": "59 St-Columbus Circle",
        "target": {"tue": "09:00"},
    }
    with pytest.raises(TripConfigError, match="Duplicate"):
        resolve_trips({"trips": [one, dict(one)]}, index=index)


def test_resolve_trips_rejects_destination_not_on_line(index: StopIndex):
    cfg = {
        "trips": [
            {
                "name": "t",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "Grand Central-42 St",  # 4/5/6, not served by the A
                "target": {"tue": "09:00"},
            }
        ]
    }
    with pytest.raises(TripConfigError):
        resolve_trips(cfg, index=index)


# --- acceptance: recurring per-weekday target honored automatically ----------


def test_acceptance_recurring_weekday_targets(index: StopIndex):
    """A weekday-varying target is honored automatically (issue #27): Tuesday
    aims for one time and other weekdays another, with no target on weekends.
    Uses generic placeholder stations/times per AGENTS.md."""
    cfg = {
        "trips": [
            {
                "name": "morning-uptown",
                "boarding": "Fulton St",
                "line": "A",
                "direction": "N",
                "destination": "59 St-Columbus Circle",
                "target": {"default": "08:30", "tue": "08:15"},
            }
        ]
    }
    (trip,) = resolve_trips(cfg, index=index)
    tue = trip.effective_target(TUESDAY_7_40)
    wed = trip.effective_target(WEDNESDAY_7_40)
    assert (tue.hour, tue.minute) == (8, 15)
    assert (wed.hour, wed.minute) == (8, 30)
    assert trip.effective_target(SATURDAY_7_40) is None
