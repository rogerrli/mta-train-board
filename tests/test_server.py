"""Tests for app.server -- the local HTTP/JSON API. Fully offline.

``build_state`` is exercised as a pure function. The endpoints are driven through
FastAPI's TestClient with the poller's cache set directly. The client fixture
does *not* enter the app's lifespan (no ``with`` block), so the background poll
task never starts and no network or live feeds are touched.
"""

from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import server
from app.arrivals import Arrival, ArrivalGroup
from app.focus import FocusRule
from app.poller import Snapshot
from app.trips import TrainOption, TripRecommendation

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=EASTERN)


def _arrival(
    minutes: int, trip: str = "t1", headsign: str = "Uptown", catchability=None
) -> Arrival:
    return Arrival(
        minutes=minutes,
        arrival=NOW.replace(minute=minutes),
        trip_id=trip,
        headsign=headsign,
        catchability=catchability,
    )


def _group(
    station,
    line,
    direction,
    arrivals,
    color="#FCCC0A",
    walk_minutes=None,
    terminal=None,
    borough=None,
):
    label = {"N": "Northbound", "S": "Southbound"}[direction]
    return ArrivalGroup(
        station=station,
        line=line,
        direction=direction,
        direction_label=label,
        color=color,
        arrivals=arrivals,
        walk_minutes=walk_minutes,
        terminal=terminal,
        borough=borough,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def reset_cache():
    """Isolate each test: clear the shared poller cache before and after."""
    server.poller._snapshot = None
    yield
    server.poller._snapshot = None


# --- build_state (pure) ------------------------------------------------------


def test_build_state_nests_groups_under_their_station():
    groups = [
        _group("14 St-Union Sq", "Q", "N", [_arrival(2), _arrival(9)]),
        _group("14 St-Union Sq", "R", "S", [_arrival(5)]),
        _group("Fulton St", "2", "N", []),
    ]

    payload = server.build_state(groups, NOW)

    assert payload["updated_at"] == NOW.isoformat()
    assert payload["alerts"] == []
    # Two source stations -> two station entries, config order preserved.
    assert [s["name"] for s in payload["stations"]] == ["14 St-Union Sq", "Fulton St"]

    dekalb = payload["stations"][0]
    assert [(g["line"], g["direction"]) for g in dekalb["arrivals"]] == [
        ("Q", "N"),
        ("R", "S"),
    ]
    q = dekalb["arrivals"][0]
    assert q["direction_label"] == "Northbound"
    assert q["color"] == "#FCCC0A"
    assert q["walk_minutes"] is None
    assert [a["minutes"] for a in q["arrivals"]] == [2, 9]
    # Arrival serialization carries the details the UI may use.
    assert q["arrivals"][0] == {
        "minutes": 2,
        "arrival": NOW.replace(minute=2).isoformat(),
        "trip_id": "t1",
        "headsign": "Uptown",
        "catchability": None,
    }


def test_build_state_empty_when_no_groups():
    payload = server.build_state([], NOW)
    assert payload == {
        "updated_at": NOW.isoformat(),
        "stale": False,
        "age_seconds": 0,
        "refresh_interval_seconds": 30.0,
        "stations": [],
        "trips": [],
        "focus": None,
        "alerts": [],
    }


def test_build_state_serializes_trip_recommendation():
    target = NOW.replace(hour=9, minute=0)
    departure = NOW.replace(hour=8, minute=41)
    rec = TripRecommendation(
        name="morning-uptown",
        boarding="Fulton St",
        line="A",
        direction="N",
        destination="59 St-Columbus Circle",
        target=target,
        status="on_time",
        recommended=TrainOption(
            departure=departure,
            minutes=4,
            leave_by=departure - timedelta(minutes=6),
            leave_in_minutes=2,
            arrival=NOW.replace(hour=8, minute=59),
            on_time=True,
            lateness_minutes=0,
        ),
        fallback=None,
    )
    payload = server.build_state([], NOW, recommendations=[rec])
    (trip,) = payload["trips"]
    assert trip["name"] == "morning-uptown"
    assert trip["status"] == "on_time"
    assert trip["line"] == "A"
    assert trip["color"] == "#0039A6"  # A = 8 Av blue
    assert trip["target"] == target.isoformat()
    assert trip["recommended"]["leave_in_minutes"] == 2
    assert trip["recommended"]["on_time"] is True
    assert trip["recommended"]["departure"] == departure.isoformat()
    assert trip["fallback"] is None


def test_build_state_passes_through_staleness():
    payload = server.build_state([], NOW, stale=True, age_seconds=125)
    assert payload["stale"] is True
    assert payload["age_seconds"] == 125


def test_build_state_exposes_catchability_walk_and_refresh():
    # The board (issue #7) styles urgency off catchability and reclassifies between
    # polls using walk_minutes; it re-polls on refresh_interval_seconds. Issue #8
    # added catchability/walk_minutes to the model; this asserts the API exposes
    # them (they were not serialized before).
    groups = [
        _group(
            "Times Sq-42 St",
            "A",
            "N",
            [_arrival(2, catchability="HURRY"), _arrival(9, catchability="CATCHABLE")],
            walk_minutes=3.0,
        )
    ]
    payload = server.build_state(groups, NOW, refresh_interval_seconds=45.0)

    assert payload["refresh_interval_seconds"] == 45.0
    group = payload["stations"][0]["arrivals"][0]
    assert group["walk_minutes"] == 3.0
    assert [a["catchability"] for a in group["arrivals"]] == ["HURRY", "CATCHABLE"]


def test_build_state_exposes_terminal_and_borough():
    # Terminal-station direction labels (#41): the board renders terminal as the
    # primary direction text and borough as secondary, falling back to
    # direction_label when unconfigured (null here).
    groups = [
        _group(
            "14 St-Union Sq",
            "Q",
            "N",
            [_arrival(3)],
            terminal="96 St-2 Av",
            borough="Man",
        ),
        _group("14 St-Union Sq", "R", "S", [_arrival(5)]),
    ]
    payload = server.build_state(groups, NOW)

    labeled, fallback = payload["stations"][0]["arrivals"]
    assert (labeled["terminal"], labeled["borough"]) == ("96 St-2 Av", "Man")
    assert labeled["direction_label"] == "Northbound"
    assert (fallback["terminal"], fallback["borough"]) == (None, None)


def _rec(name="morning-uptown", line="A", direction="N", terminal=None, borough=None):
    return TripRecommendation(
        name=name,
        boarding="Fulton St",
        line=line,
        direction=direction,
        destination="59 St-Columbus Circle",
        target=NOW.replace(hour=9),
        status="on_time",
        terminal=terminal,
        borough=borough,
    )


def test_build_state_focus_null_by_default():
    # No active focus rule -> focus directive is null (normal glance board #39).
    payload = server.build_state([], NOW, recommendations=[_rec()])
    assert payload["focus"] is None


def test_build_state_focus_names_the_active_trip():
    # An active focus trip -> the directive just names which trip the board is
    # dedicated to; its recommendation (terminal label and all) rides in trips[].
    payload = server.build_state(
        [], NOW, recommendations=[_rec()], focus_trip="morning-uptown"
    )
    assert payload["focus"] == {"trip": "morning-uptown"}


def test_build_state_focus_stays_on_a_no_target_trip():
    # Owner's decision (#39): a focus rule firing on a day its trip has no target
    # stays in focus and shows that state, rather than silently reverting to the
    # glance board. So the directive is still emitted even when the focused trip's
    # recommendation is no_target (the board renders FocusView's no_target branch).
    no_target = replace(_rec(), status="no_target", target=None)
    payload = server.build_state(
        [], NOW, recommendations=[no_target], focus_trip="morning-uptown"
    )
    assert payload["focus"] == {"trip": "morning-uptown"}
    assert payload["trips"][0]["status"] == "no_target"


def test_build_state_serializes_recommendation_terminal_label():
    # The #41 terminal-station label rides on the recommendation (resolved from its
    # boarding group in app.trips), so focus mode reads it without re-joining groups.
    rec = _rec(terminal="Inwood-207 St", borough="Man")
    (trip,) = server.build_state([], NOW, recommendations=[rec])["trips"]
    assert (trip["terminal"], trip["borough"]) == ("Inwood-207 St", "Man")

    # Unlabeled (line, direction) -> null, and the board falls back to destination.
    (bare,) = server.build_state([], NOW, recommendations=[_rec()])["trips"]
    assert (bare["terminal"], bare["borough"]) == (None, None)


# --- endpoints ---------------------------------------------------------------


def test_health(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_state_serves_fresh_cache(client: TestClient):
    groups = [_group("14 St-Union Sq", "Q", "N", [_arrival(3)])]
    # A snapshot polled just now -> not stale.
    server.poller._snapshot = Snapshot(groups=groups, updated_at=datetime.now(EASTERN))

    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stations"][0]["name"] == "14 St-Union Sq"
    assert body["stations"][0]["arrivals"][0]["arrivals"][0]["minutes"] == 3
    assert body["alerts"] == []
    assert body["stale"] is False
    assert body["age_seconds"] < server.poller.stale_after_seconds
    assert "updated_at" in body


def test_state_flags_stale_when_cache_is_old(client: TestClient):
    old = datetime.now(EASTERN) - timedelta(
        seconds=server.poller.stale_after_seconds + 60
    )
    server.poller._snapshot = Snapshot(groups=[], updated_at=old)

    body = client.get("/api/state").json()
    assert body["stale"] is True
    assert body["age_seconds"] >= server.poller.stale_after_seconds


def test_state_returns_503_before_first_poll(client: TestClient):
    # Cold start: the cache is empty (reset_cache fixture leaves it None).
    resp = client.get("/api/state")
    assert resp.status_code == 503
    # A stable, generic message -- no internal detail leaked to clients.
    assert resp.json()["detail"] == "Arrivals are temporarily unavailable."


class _FixedClock:
    """Stand-in for the ``datetime`` the endpoint uses, with a pinned ``now``."""

    def __init__(self, value):
        self._value = value

    def now(self, tz=None):
        return self._value


def _focus_snapshot(when):
    """A fresh snapshot with a morning-uptown rec + an 08:00-09:00 weekday rule."""
    rule = FocusRule(
        trip="morning-uptown",
        days=frozenset({0, 1, 2, 3, 4}),
        start=time(8, 0),
        end=time(9, 0),
    )
    return Snapshot(
        groups=[],
        updated_at=when,
        recommendations=[_rec(terminal="Inwood-207 St")],
        focus_rules=[rule],
    )


def test_state_activates_focus_inside_the_window(client: TestClient, monkeypatch):
    # A weekday inside 08:00-09:00 -> the endpoint re-checks the window against the
    # request clock (#39) and names the focused trip; its terminal label rides in
    # trips[] on the recommendation.
    when = datetime(2026, 9, 2, 8, 30, tzinfo=EASTERN)  # Wednesday
    server.poller._snapshot = _focus_snapshot(when)
    monkeypatch.setattr(server, "datetime", _FixedClock(when))

    body = client.get("/api/state").json()
    assert body["focus"] == {"trip": "morning-uptown"}
    assert body["trips"][0]["terminal"] == "Inwood-207 St"


def test_state_no_focus_outside_the_window(client: TestClient, monkeypatch):
    # Same snapshot, but the request clock is before the window -> normal board.
    when = datetime(2026, 9, 2, 7, 30, tzinfo=EASTERN)
    server.poller._snapshot = _focus_snapshot(when)
    monkeypatch.setattr(server, "datetime", _FixedClock(when))

    assert client.get("/api/state").json()["focus"] is None


def test_frontend_served_from_same_origin(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "MTA Train Board" in resp.text
