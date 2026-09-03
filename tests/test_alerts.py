"""Tests for app.alerts -- fetch + normalize + match service alerts (#13).

``parse_alerts`` is a pure function of (feed JSON, watched lines, now), so these
build small feed dicts that mirror the live MTA JSON shape (Mercury extensions,
``header_text``/``description_text`` translations, epoch ``active_period``) and
assert the matching, time-window, and severity rules. Fully offline.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.alerts import EXCLUDED_ALERT_TYPES, parse_alerts

EASTERN = ZoneInfo("America/New_York")
# A Thursday afternoon -- planned "later today" windows are in the evening.
NOW = datetime(2026, 9, 3, 14, 0, 0, tzinfo=EASTERN)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _entity(
    entity_id,
    routes,
    alert_type,
    *,
    periods=None,
    header="Header text.",
    description="Description text.",
):
    """Build one feed entity mirroring the live JSON shape."""
    informed = [
        {
            "agency_id": "MTASBWY",
            "route_id": r,
            "transit_realtime.mercury_entity_selector": {},
        }
        for r in routes
    ]
    alert = {
        "informed_entity": informed,
        "header_text": {
            "translation": [
                {"text": header, "language": "en"},
                {"text": f"<p>{header}</p>", "language": "en-html"},
            ]
        },
        "description_text": {"translation": [{"text": description, "language": "en"}]},
        "transit_realtime.mercury_alert": {"alert_type": alert_type},
    }
    if periods is not None:
        alert["active_period"] = [{k: _epoch(v) for k, v in p.items()} for p in periods]
    return {"id": entity_id, "alert": alert}


def _feed(*entities):
    return {"header": {"gtfs_realtime_version": "2.0"}, "entity": list(entities)}


def test_matches_watched_line_active_now():
    feed = _feed(
        _entity("a1", ["2", "3"], "Delays", periods=[{"start": NOW.replace(hour=13)}])
    )
    alerts = parse_alerts(feed, {"2"}, now=NOW)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.lines == ("2",)  # only the watched line is reported
    assert a.active is True  # a live disruption
    assert a.header == "Header text."  # plain en, not the en-html variant
    assert a.description == "Description text."


def test_unwatched_line_dropped():
    feed = _feed(
        _entity("a1", ["A"], "Delays", periods=[{"start": NOW.replace(hour=13)}])
    )
    assert parse_alerts(feed, {"2", "3"}, now=NOW) == []


def test_excluded_alert_types_dropped():
    # Every excluded type on a watched, active line is still dropped.
    entities = [
        _entity(f"e{i}", ["1"], t, periods=[{"start": NOW.replace(hour=13)}])
        for i, t in enumerate(sorted(EXCLUDED_ALERT_TYPES))
    ]
    assert parse_alerts(_feed(*entities), {"1"}, now=NOW) == []


def test_planned_starting_later_today_included_and_flagged():
    feed = _feed(
        _entity(
            "p1",
            ["A"],
            "Planned - Part Suspended",
            periods=[{"start": NOW.replace(hour=22), "end": NOW.replace(hour=23)}],
        )
    )
    alerts = parse_alerts(feed, {"A"}, now=NOW)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.active is False  # a heads-up for later today, not in effect yet
    assert a.start == NOW.replace(hour=22)
    assert a.end == NOW.replace(hour=23)


def test_planned_starting_tomorrow_dropped():
    tomorrow = NOW.replace(day=4, hour=6)
    feed = _feed(
        _entity("p1", ["A"], "Planned - Reroute", periods=[{"start": tomorrow}])
    )
    assert parse_alerts(feed, {"A"}, now=NOW) == []


def test_wholly_past_alert_dropped():
    feed = _feed(
        _entity(
            "old",
            ["A"],
            "Delays",
            periods=[{"start": NOW.replace(hour=8), "end": NOW.replace(hour=9)}],
        )
    )
    assert parse_alerts(feed, {"A"}, now=NOW) == []


def test_missing_active_period_treated_as_ongoing():
    feed = _feed(_entity("ongoing", ["A"], "Delays", periods=None))
    alerts = parse_alerts(feed, {"A"}, now=NOW)
    assert len(alerts) == 1
    assert alerts[0].active is True
    assert alerts[0].start is None and alerts[0].end is None


def test_sorted_current_first_then_by_start():
    later = _entity(
        "later",
        ["A"],
        "Planned - Reroute",
        periods=[{"start": NOW.replace(hour=21)}],
    )
    sooner = _entity(
        "sooner",
        ["A"],
        "Planned - Reroute",
        periods=[{"start": NOW.replace(hour=18)}],
    )
    active = _entity(
        "active", ["A"], "Delays", periods=[{"start": NOW.replace(hour=13)}]
    )
    alerts = parse_alerts(_feed(later, sooner, active), {"A"}, now=NOW)
    assert [a.id for a in alerts] == ["active", "sooner", "later"]


def test_entity_without_alert_ignored():
    feed = {"entity": [{"id": "vehicle-only"}, _entity("a", ["A"], "Delays")]}
    alerts = parse_alerts(feed, {"A"}, now=NOW)
    assert [a.id for a in alerts] == ["a"]
