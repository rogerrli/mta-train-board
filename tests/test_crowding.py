"""Tests for app.crowding (transfer-crowding hints, #28) -- fully offline.

The adjacency detection (:func:`annotate_crowding`) is driven with synthetic
:class:`ArrivalGroup`s and a fixed ``now`` so the "who's just before whom" math is
deterministic. Config resolution uses the vendored ``stations.csv`` via a prebuilt
:class:`StopIndex`, so nothing here touches the network.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.arrivals import Arrival, ArrivalGroup
from app.crowding import (
    DEFAULT_CROWD_WINDOW_MINUTES,
    CrowdingConfigError,
    CrowdingRule,
    annotate_crowding,
    resolve_crowding_rules,
    validated_crowd_window,
)
from app.stops import StopIndex

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=EASTERN)

STATION = "14 St-Union Sq"


@pytest.fixture(scope="module")
def index() -> StopIndex:
    return StopIndex.from_csv()


def _arrival(minutes: float, trip: str = "t") -> Arrival:
    """An Arrival ``minutes`` from NOW (fractional minutes allowed for windows)."""
    return Arrival(
        minutes=int(minutes),
        arrival=NOW + timedelta(minutes=minutes),
        trip_id=trip,
        headsign="Uptown",
    )


def _group(line: str, direction: str, minutes: list[float]) -> ArrivalGroup:
    return ArrivalGroup(
        station=STATION,
        line=line,
        direction=direction,
        direction_label="Northbound" if direction == "N" else "Southbound",
        color="#000000",
        arrivals=[_arrival(m, trip=f"{line}{direction}{m}") for m in minutes],
    )


def _hints(group: ArrivalGroup) -> dict[str, str | None]:
    return {a.trip_id: a.crowding for a in group.arrivals}


# --- adjacency detection -----------------------------------------------------


def test_train_following_a_feeder_is_crowded():
    # My Q at +5; an L feeder lands at +4 (1 min before) -> Q boards crowded.
    my = _group("Q", "N", [5])
    feeder = _group("L", "N", [4])
    (out_my, _) = annotate_crowding([my, feeder], [CrowdingRule(STATION, "Q", ("L",))])
    assert _hints(out_my) == {"QN5": "crowded"}


def test_train_ahead_of_a_feeder_beats_the_crowd():
    # My Q at +5; the next L feeder is at +6 (1 min after) -> Q beats the crowd.
    my = _group("Q", "N", [5])
    feeder = _group("L", "N", [6])
    (out_my, _) = annotate_crowding([my, feeder], [CrowdingRule(STATION, "Q", ("L",))])
    assert _hints(out_my) == {"QN5": "beats_crowd"}


def test_no_feeder_nearby_leaves_hint_none():
    # Feeders are far outside the 2-min window on either side -> no hint.
    my = _group("Q", "N", [10])
    feeder = _group("L", "N", [3, 20])
    (out_my, _) = annotate_crowding([my, feeder], [CrowdingRule(STATION, "Q", ("L",))])
    assert _hints(out_my) == {"QN10": None}


def test_simultaneous_feeder_counts_as_crowded():
    # A feeder arriving at the same moment already dumped its crowd -> crowded,
    # not beats_crowd (crowded wins the tie).
    my = _group("Q", "N", [5])
    feeder = _group("L", "N", [5])
    (out_my, _) = annotate_crowding([my, feeder], [CrowdingRule(STATION, "Q", ("L",))])
    assert _hints(out_my) == {"QN5": "crowded"}


def test_window_boundary_is_inclusive_and_tunable():
    # Default window 2 min: a feeder exactly 2 min before is still crowded; a
    # feeder 3 min before (with a 2-min window) is not.
    my = _group("Q", "N", [5, 10])
    feeder = _group("L", "N", [3, 7])  # 3 is 2m before the +5; 7 is 3m before +10
    (out_my, _) = annotate_crowding([my, feeder], [CrowdingRule(STATION, "Q", ("L",))])
    assert _hints(out_my) == {"QN5": "crowded", "QN10": None}

    # Widen the window to 3 min and the +10 train now follows the +7 feeder.
    (out_wide, _) = annotate_crowding(
        [my, feeder], [CrowdingRule(STATION, "Q", ("L",))], window_minutes=3
    )
    assert _hints(out_wide)["QN10"] == "crowded"


def test_feeder_counts_in_either_direction():
    # Owner's call (#28): a feeder in the OPPOSITE direction still crowds my train.
    my = _group("Q", "N", [5])
    feeder_south = _group("L", "S", [4])
    (out_my, _) = annotate_crowding(
        [my, feeder_south], [CrowdingRule(STATION, "Q", ("L",))]
    )
    assert _hints(out_my) == {"QN5": "crowded"}


def test_multiple_feeder_lines_pooled():
    my = _group("Q", "N", [5, 12])
    feeder_l = _group("L", "N", [4])  # crowds the +5
    feeder_6 = _group("6", "N", [13])  # the +12 beats it
    (out_my, _, _) = annotate_crowding(
        [my, feeder_l, feeder_6], [CrowdingRule(STATION, "Q", ("L", "6"))]
    )
    assert _hints(out_my) == {"QN5": "crowded", "QN12": "beats_crowd"}


def test_feeder_groups_and_unrelated_groups_pass_through_unchanged():
    my = _group("Q", "N", [5])
    feeder = _group("L", "N", [4])
    other = _group("N", "N", [4])  # not my line, not a feeder in the rule
    out = annotate_crowding([my, feeder, other], [CrowdingRule(STATION, "Q", ("L",))])
    # Only the Q group is annotated; the feeder and unrelated groups are untouched.
    assert _hints(out[0]) == {"QN5": "crowded"}
    assert all(a.crowding is None for a in out[1].arrivals)
    assert all(a.crowding is None for a in out[2].arrivals)


def test_no_rules_returns_groups_unchanged():
    groups = [_group("Q", "N", [5])]
    assert annotate_crowding(groups, []) is groups


def test_rule_only_applies_at_its_own_station():
    # A same-line group at a different complex must not pick up the hint.
    my_here = _group("Q", "N", [5])
    my_elsewhere = ArrivalGroup(
        station="Times Sq-42 St",
        line="Q",
        direction="N",
        direction_label="Northbound",
        color="#000000",
        arrivals=[_arrival(5, trip="elsewhere")],
    )
    feeder = _group("L", "N", [4])
    out = annotate_crowding(
        [my_here, my_elsewhere, feeder], [CrowdingRule(STATION, "Q", ("L",))]
    )
    assert out[0].arrivals[0].crowding == "crowded"
    assert out[1].arrivals[0].crowding is None  # different station, untouched


# --- config resolution -------------------------------------------------------


def test_resolve_valid_rule(index: StopIndex):
    config = {
        "transfer_crowding": [
            {"name": "14 St-Union Sq", "line": "Q", "feeders": ["L", "4", "5", "6"]}
        ]
    }
    (rule,) = resolve_crowding_rules(config, index=index)
    assert rule.station == "14 St-Union Sq"
    assert rule.line == "Q"
    assert rule.feeders == ("L", "4", "5", "6")


def test_resolve_uses_canonical_station_name(index: StopIndex):
    # A lower-cased / loosely-spelled name resolves to the dataset's spelling so it
    # matches ArrivalGroup.station.
    config = {
        "transfer_crowding": [{"name": "14 st-union sq", "line": "Q", "feeders": ["L"]}]
    }
    (rule,) = resolve_crowding_rules(config, index=index)
    assert rule.station == "14 St-Union Sq"


def test_resolve_dedupes_feeders_and_drops_the_annotated_line(index: StopIndex):
    config = {
        "transfer_crowding": [
            {"name": "14 St-Union Sq", "line": "Q", "feeders": ["L", "L", "4"]}
        ]
    }
    (rule,) = resolve_crowding_rules(config, index=index)
    assert rule.feeders == ("L", "4")


def test_resolve_empty_when_absent(index: StopIndex):
    assert resolve_crowding_rules({}, index=index) == []


def test_resolve_rejects_unknown_station(index: StopIndex):
    config = {"transfer_crowding": [{"name": "Nowhere", "line": "Q", "feeders": ["L"]}]}
    with pytest.raises(CrowdingConfigError, match="unknown station"):
        resolve_crowding_rules(config, index=index)


def test_resolve_rejects_line_not_served(index: StopIndex):
    # The A does not stop at 14 St-Union Sq.
    config = {
        "transfer_crowding": [{"name": "14 St-Union Sq", "line": "A", "feeders": ["L"]}]
    }
    with pytest.raises(CrowdingConfigError, match="not served"):
        resolve_crowding_rules(config, index=index)


def test_resolve_rejects_feeder_not_served(index: StopIndex):
    config = {
        "transfer_crowding": [{"name": "14 St-Union Sq", "line": "Q", "feeders": ["A"]}]
    }
    with pytest.raises(CrowdingConfigError, match="not served"):
        resolve_crowding_rules(config, index=index)


def test_resolve_rejects_line_as_its_own_feeder(index: StopIndex):
    config = {
        "transfer_crowding": [{"name": "14 St-Union Sq", "line": "Q", "feeders": ["Q"]}]
    }
    with pytest.raises(CrowdingConfigError, match="feeder of itself"):
        resolve_crowding_rules(config, index=index)


@pytest.mark.parametrize(
    "block",
    [
        {"line": "Q", "feeders": ["L"]},  # no name
        {"name": "14 St-Union Sq", "feeders": ["L"]},  # no line
        {"name": "14 St-Union Sq", "line": "Q"},  # no feeders
        {"name": "14 St-Union Sq", "line": "Q", "feeders": []},  # empty feeders
    ],
)
def test_resolve_rejects_malformed_block(index: StopIndex, block: dict):
    with pytest.raises(CrowdingConfigError):
        resolve_crowding_rules({"transfer_crowding": [block]}, index=index)


def test_resolve_rejects_duplicate_station_line(index: StopIndex):
    dup = {"name": "14 St-Union Sq", "line": "Q", "feeders": ["L"]}
    with pytest.raises(CrowdingConfigError, match="[Dd]uplicate"):
        resolve_crowding_rules({"transfer_crowding": [dup, dup]}, index=index)


# --- window validation -------------------------------------------------------


def test_window_defaults_when_absent():
    assert validated_crowd_window({}) == DEFAULT_CROWD_WINDOW_MINUTES


def test_window_reads_override():
    assert validated_crowd_window({"transfer_crowd_window_minutes": 1}) == 1.0


@pytest.mark.parametrize("bad", [-1, "2", True])
def test_window_rejects_bad_value(bad):
    with pytest.raises(CrowdingConfigError, match="transfer_crowd_window_minutes"):
        validated_crowd_window({"transfer_crowd_window_minutes": bad})
