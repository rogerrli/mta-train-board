"""Tests for app.arrivals -- fully offline.

The pure core (:func:`compute_arrivals`) is exercised with synthetic
:class:`StopUpdate` records and a fixed ``now`` so countdown math is
deterministic. One end-to-end test drives the committed numbered-lines feed
fixture through station resolution to assert the wiring holds together.
"""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import arrivals, feeds
from app.arrivals import Arrival, ArrivalGroup, compute_arrivals
from app.feeds import StopUpdate
from app.stops import ResolvedStation, StopIndex

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=EASTERN)

FIXTURE = Path(__file__).parent / "fixtures" / "gtfs_numbered.pb"


def _update(
    route: str, stop: str, minutes: float | None, trip: str = "t"
) -> StopUpdate:
    """A StopUpdate arriving ``minutes`` from NOW (None -> no arrival time)."""
    arrival = None if minutes is None else NOW + timedelta(minutes=minutes)
    return StopUpdate(
        route_id=route,
        trip_id=trip,
        stop_id=stop,
        direction=stop[-1],
        arrival=arrival,
        departure=arrival,
        headsign="Uptown Terminal",
    )


def _station(
    name="DeKalb Av",
    lines=("Q",),
    directions=("N",),
    parent="R30",
    walk_minutes=None,
):
    return ResolvedStation(
        name=name,
        directions=tuple(directions),
        line_stops={line: parent for line in lines},
        walk_minutes=walk_minutes,
    )


# --- core countdown math -----------------------------------------------------


def test_computes_floored_minutes_sorted_soonest_first():
    station = _station()
    updates = [
        _update("Q", "R30N", 5.9, trip="b"),  # floors to 5
        _update("Q", "R30N", 2.1, trip="a"),  # floors to 2
    ]
    (group,) = compute_arrivals([station], updates, now=NOW)
    assert [a.minutes for a in group.arrivals] == [2, 5]
    assert [a.trip_id for a in group.arrivals] == ["a", "b"]


def test_drops_past_and_missing_arrivals():
    station = _station()
    updates = [
        _update("Q", "R30N", -3, trip="past"),  # already departed
        _update("Q", "R30N", None, trip="notime"),  # no arrival timestamp
        _update("Q", "R30N", 4, trip="good"),
    ]
    (group,) = compute_arrivals([station], updates, now=NOW)
    assert [a.trip_id for a in group.arrivals] == ["good"]


def test_falls_back_to_departure_at_origin_terminal():
    # The feed omits arrival at a trip's origin terminal, giving only departure.
    # Such a train should still show, counted down from its departure time.
    station = _station()
    depart = NOW + timedelta(minutes=5)
    terminal = StopUpdate(
        route_id="Q",
        trip_id="origin",
        stop_id="R30N",
        direction="N",
        arrival=None,
        departure=depart,
        headsign="Uptown Terminal",
    )
    (group,) = compute_arrivals([station], [terminal], now=NOW)
    assert [a.trip_id for a in group.arrivals] == ["origin"]
    assert group.arrivals[0].minutes == 5
    assert group.arrivals[0].arrival == depart


def test_arriving_now_is_zero_and_kept():
    station = _station()
    (group,) = compute_arrivals([station], [_update("Q", "R30N", 0.5)], now=NOW)
    assert group.arrivals[0].minutes == 0


def test_limit_keeps_next_n():
    station = _station()
    updates = [_update("Q", "R30N", m, trip=f"t{m}") for m in (1, 2, 3, 4, 5)]
    (group,) = compute_arrivals([station], updates, now=NOW, limit=3)
    assert [a.minutes for a in group.arrivals] == [1, 2, 3]


# --- catchability against walk time (#8) -------------------------------------


def test_classifies_catchable_hurry_missed_against_walk_time():
    # W=5, delta=1 -> HURRY band is [4, 5]; >5 catchable, <4 missed.
    station = _station(walk_minutes=5)
    updates = [_update("Q", "R30N", m, trip=f"t{m}") for m in (7, 6, 5, 4, 3, 2)]
    (group,) = compute_arrivals([station], updates, now=NOW, limit=10)
    got = {a.minutes: a.catchability for a in group.arrivals}
    assert got == {
        7: "CATCHABLE",
        6: "CATCHABLE",
        5: "HURRY",  # m == W
        4: "HURRY",  # m == W - delta (lower edge)
        3: "MISSED",
        2: "MISSED",
    }


def test_no_walk_time_leaves_catchability_unknown():
    station = _station(walk_minutes=None)
    updates = [_update("Q", "R30N", m) for m in (1, 10)]
    (group,) = compute_arrivals([station], updates, now=NOW)
    assert all(a.catchability is None for a in group.arrivals)
    assert group.walk_minutes is None


def test_walk_best_case_delta_widens_hurry_band():
    # delta=3, W=5 -> HURRY band [2, 5]; a 2-min train is HURRY, not MISSED.
    station = _station(walk_minutes=5)
    updates = [_update("Q", "R30N", m, trip=f"t{m}") for m in (2, 1)]
    (group,) = compute_arrivals([station], updates, now=NOW, walk_best_case_delta=3)
    got = {a.minutes: a.catchability for a in group.arrivals}
    assert got == {2: "HURRY", 1: "MISSED"}


def test_zero_delta_collapses_hurry_to_single_minute():
    # delta=0 -> HURRY only at exactly m == W.
    station = _station(walk_minutes=4)
    updates = [_update("Q", "R30N", m, trip=f"t{m}") for m in (5, 4, 3)]
    (group,) = compute_arrivals([station], updates, now=NOW, walk_best_case_delta=0)
    got = {a.minutes: a.catchability for a in group.arrivals}
    assert got == {5: "CATCHABLE", 4: "HURRY", 3: "MISSED"}


def test_group_echoes_walk_minutes():
    station = _station(walk_minutes=6)
    (group,) = compute_arrivals([station], [_update("Q", "R30N", 3)], now=NOW)
    assert group.walk_minutes == 6


def test_fractional_walk_minutes_classifies_against_floored_countdowns():
    # W=4.5, delta=1 -> HURRY band [3.5, 4.5]. Countdowns are whole minutes.
    station = _station(walk_minutes=4.5)
    updates = [_update("Q", "R30N", m, trip=f"t{m}") for m in (5, 4, 3)]
    (group,) = compute_arrivals([station], updates, now=NOW)
    got = {a.minutes: a.catchability for a in group.arrivals}
    assert got == {5: "CATCHABLE", 4: "HURRY", 3: "MISSED"}


def test_delta_at_least_walk_time_makes_missed_unreachable():
    # W=3, delta=5 -> W-delta = -2, so every non-catchable train is HURRY;
    # you can always make it at best-case pace. Nothing is MISSED.
    station = _station(walk_minutes=3)
    updates = [_update("Q", "R30N", m, trip=f"t{m}") for m in (4, 3, 0)]
    (group,) = compute_arrivals([station], updates, now=NOW, walk_best_case_delta=5)
    got = {a.minutes: a.catchability for a in group.arrivals}
    assert got == {4: "CATCHABLE", 3: "HURRY", 0: "HURRY"}


@pytest.mark.parametrize("bad", [-1, "1", True])
def test_fetch_arrivals_rejects_bad_delta_before_any_network(bad):
    # Validation is the first thing fetch_arrivals does, so a bad config value
    # raises before station resolution or any feed fetch -- no network needed.
    with pytest.raises(ValueError, match="walk_best_case_delta_minutes"):
        arrivals.fetch_arrivals({"walk_best_case_delta_minutes": bad})


# --- grouping & metadata -----------------------------------------------------


def test_groups_per_line_and_direction():
    station = _station(lines=("Q", "R"), directions=("N", "S"))
    updates = [
        _update("Q", "R30N", 3),
        _update("R", "R30S", 6),
    ]
    groups = compute_arrivals([station], updates, now=NOW)
    # 2 lines x 2 directions = 4 groups, all present even when empty.
    keys = {(g.line, g.direction, len(g.arrivals)) for g in groups}
    assert keys == {("Q", "N", 1), ("Q", "S", 0), ("R", "N", 0), ("R", "S", 1)}


def test_only_matching_route_and_stop_counted():
    station = _station(lines=("Q",), directions=("N",))
    updates = [
        _update("R", "R30N", 3),  # wrong route at the watched stop
        _update("Q", "R30S", 3),  # right route, wrong (unwatched) direction
        _update("Q", "R30N", 3),  # the one that matches
    ]
    (group,) = compute_arrivals([station], updates, now=NOW)
    assert len(group.arrivals) == 1


def test_attaches_direction_label_color_and_headsign():
    station = _station(lines=("Q",), directions=("N",))
    (group,) = compute_arrivals([station], [_update("Q", "R30N", 3)], now=NOW)
    assert group.station == "DeKalb Av"
    assert group.direction_label == "Northbound"
    assert group.color == "#FCCC0A"  # N/Q/R/W yellow
    assert group.arrivals[0].headsign == "Uptown Terminal"


def test_empty_updates_still_emits_group():
    (group,) = compute_arrivals([_station()], [], now=NOW)
    assert group.arrivals == []


# --- end-to-end through the real fixture -------------------------------------


def test_end_to_end_with_numbered_fixture():
    # Grand Central-42 St 4/5/6 northbound resolves to 631N in the vendored data;
    # the committed numbered-lines fixture carries real updates for that stop.
    resolved = StopIndex.from_csv().resolve(
        "Grand Central-42 St", ["4", "5", "6"], ["N"]
    )
    updates = feeds.extract_stop_updates(feeds.parse_feed(FIXTURE.read_bytes()))

    # Pick a "now" just before the fixture's earliest 631N arrival so countdowns
    # are positive and deterministic without depending on wall-clock time.
    at_631n = [u.arrival for u in updates if u.stop_id == "631N" and u.arrival]
    now = min(at_631n) - timedelta(seconds=30)

    groups = compute_arrivals([resolved], updates, now=now)
    assert {g.line for g in groups} == {"4", "5", "6"}
    assert all(
        g.direction == "N" and g.station == "Grand Central-42 St" for g in groups
    )
    # At least one 4/5/6 train is coming, with a sane non-negative countdown.
    all_arrivals = [a for g in groups for a in g.arrivals]
    assert all_arrivals
    assert all(a.minutes >= 0 for a in all_arrivals)


def test_arrival_and_group_types_are_frozen():
    # Cheap guard that the model stays an immutable value type.
    a = Arrival(minutes=1, arrival=NOW, trip_id="t", headsign=None)
    g = ArrivalGroup("S", "Q", "N", "Northbound", "#FCCC0A", [a])
    for obj, field in ((a, "minutes"), (g, "line")):
        try:
            setattr(obj, field, "x")
        except AttributeError:
            continue
        raise AssertionError("dataclass should be frozen")


def test_unknown_route_falls_back_to_default_color():
    station = _station(lines=("XYZ",), directions=("N",), parent="R30")
    (group,) = compute_arrivals([station], [_update("XYZ", "R30N", 3)], now=NOW)
    assert group.color == arrivals._DEFAULT_COLOR
