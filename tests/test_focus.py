"""Tests for app.focus (scheduled focus mode #39) -- fully offline.

Rules are resolved from plain config dicts and evaluated against a fixed fake
``now`` (a chosen weekday + clock), so window/day logic is deterministic with no
wall-clock or network dependence.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.focus import (
    FocusConfigError,
    FocusRule,
    active_focus,
    resolve_focus_rules,
)

EASTERN = ZoneInfo("America/New_York")
# 2026-09-02 is a Wednesday; 09-05 a Saturday. Fixed so weekday math is stable.
WED = datetime(2026, 9, 2, 8, 30, tzinfo=EASTERN)  # inside a 08:00-09:00 window
SAT = datetime(2026, 9, 5, 8, 30, tzinfo=EASTERN)  # weekend, same clock

TRIP_NAMES = {"morning-uptown", "evening-home"}


def _cfg(**overrides):
    """A valid single-rule config, with field overrides."""
    rule = {
        "trip": "morning-uptown",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "start": "08:00",
        "end": "09:00",
    }
    rule.update(overrides)
    return {"focus": [rule]}


# --- resolution --------------------------------------------------------------


def test_no_focus_blocks_resolves_empty():
    assert resolve_focus_rules({}, TRIP_NAMES) == []
    assert resolve_focus_rules({"focus": []}, TRIP_NAMES) == []


def test_resolves_a_valid_rule():
    (rule,) = resolve_focus_rules(_cfg(), TRIP_NAMES)
    assert rule == FocusRule(
        trip="morning-uptown",
        days=frozenset({0, 1, 2, 3, 4}),
        start=time(8, 0),
        end=time(9, 0),
    )


def test_unknown_trip_reference_is_rejected():
    with pytest.raises(FocusConfigError, match="unknown trip 'nope'"):
        resolve_focus_rules(_cfg(trip="nope"), TRIP_NAMES)


def test_missing_trip_is_rejected():
    with pytest.raises(FocusConfigError, match="missing a 'trip'"):
        resolve_focus_rules(
            {"focus": [{"days": ["mon"], "start": "8:00", "end": "9:00"}]}, TRIP_NAMES
        )


@pytest.mark.parametrize("days", [[], "mon", ["funday"]])
def test_bad_days_are_rejected(days):
    with pytest.raises(FocusConfigError):
        resolve_focus_rules(_cfg(days=days), TRIP_NAMES)


@pytest.mark.parametrize("field", ["start", "end"])
def test_bad_time_is_rejected(field):
    with pytest.raises(FocusConfigError, match="HH:MM"):
        resolve_focus_rules(_cfg(**{field: "nope"}), TRIP_NAMES)


def test_missing_window_bound_is_rejected():
    with pytest.raises(FocusConfigError, match="'start' and 'end'"):
        resolve_focus_rules(
            {"focus": [{"trip": "morning-uptown", "days": ["mon"]}]}, TRIP_NAMES
        )


def test_start_must_be_before_end():
    with pytest.raises(FocusConfigError, match="crossing midnight"):
        resolve_focus_rules(_cfg(start="09:00", end="08:00"), TRIP_NAMES)


def test_equal_start_end_is_rejected():
    with pytest.raises(FocusConfigError):
        resolve_focus_rules(_cfg(start="08:00", end="08:00"), TRIP_NAMES)


# --- activation --------------------------------------------------------------


def test_active_inside_window_on_a_matching_weekday():
    rules = resolve_focus_rules(_cfg(), TRIP_NAMES)
    rule = active_focus(rules, WED)
    assert rule is not None and rule.trip == "morning-uptown"


def test_inactive_before_and_after_the_window():
    rules = resolve_focus_rules(_cfg(), TRIP_NAMES)
    assert active_focus(rules, WED.replace(hour=7, minute=59)) is None
    assert active_focus(rules, WED.replace(hour=9, minute=0)) is None  # end exclusive
    assert (
        active_focus(rules, WED.replace(hour=8, minute=0)) is not None
    )  # start inclusive


def test_inactive_on_a_non_matching_weekday():
    rules = resolve_focus_rules(_cfg(), TRIP_NAMES)
    assert active_focus(rules, SAT) is None


def test_naive_now_is_treated_as_eastern():
    rules = resolve_focus_rules(_cfg(), TRIP_NAMES)
    naive = datetime(2026, 9, 2, 8, 30)  # no tzinfo
    assert active_focus(rules, naive) is not None


def test_first_matching_rule_wins_on_overlap():
    cfg = {
        "focus": [
            {
                "trip": "morning-uptown",
                "days": ["wed"],
                "start": "08:00",
                "end": "10:00",
            },
            {"trip": "evening-home", "days": ["wed"], "start": "08:00", "end": "10:00"},
        ]
    }
    rules = resolve_focus_rules(cfg, TRIP_NAMES)
    rule = active_focus(rules, WED)
    assert rule is not None and rule.trip == "morning-uptown"


def test_a_second_rule_needs_no_code_changes():
    """Adding another rule (different trip/window/days) is pure config."""
    cfg = {
        "focus": [
            _cfg()["focus"][0],
            {"trip": "evening-home", "days": ["wed"], "start": "17:00", "end": "18:00"},
        ]
    }
    rules = resolve_focus_rules(cfg, TRIP_NAMES)
    assert len(rules) == 2
    evening = datetime(2026, 9, 2, 17, 30, tzinfo=EASTERN)
    assert active_focus(rules, WED).trip == "morning-uptown"
    assert active_focus(rules, evening).trip == "evening-home"
