"""Tests for app.server -- the local HTTP/JSON API. Fully offline.

``build_state`` is exercised as a pure function. The endpoints are driven through
FastAPI's TestClient with the poller's cache set directly. The client fixture
does *not* enter the app's lifespan (no ``with`` block), so the background poll
task never starts and no network or live feeds are touched.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import server
from app.arrivals import Arrival, ArrivalGroup
from app.poller import Snapshot

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=EASTERN)


def _arrival(minutes: int, trip: str = "t1", headsign: str = "Uptown") -> Arrival:
    return Arrival(
        minutes=minutes,
        arrival=NOW.replace(minute=minutes),
        trip_id=trip,
        headsign=headsign,
    )


def _group(station, line, direction, arrivals, color="#FCCC0A"):
    label = {"N": "Northbound", "S": "Southbound"}[direction]
    return ArrivalGroup(
        station=station,
        line=line,
        direction=direction,
        direction_label=label,
        color=color,
        arrivals=arrivals,
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
        _group("DeKalb Av", "Q", "N", [_arrival(2), _arrival(9)]),
        _group("DeKalb Av", "R", "S", [_arrival(5)]),
        _group("Hoyt St", "2", "N", []),
    ]

    payload = server.build_state(groups, NOW)

    assert payload["updated_at"] == NOW.isoformat()
    assert payload["alerts"] == []
    # Two source stations -> two station entries, config order preserved.
    assert [s["name"] for s in payload["stations"]] == ["DeKalb Av", "Hoyt St"]

    dekalb = payload["stations"][0]
    assert [(g["line"], g["direction"]) for g in dekalb["arrivals"]] == [
        ("Q", "N"),
        ("R", "S"),
    ]
    q = dekalb["arrivals"][0]
    assert q["direction_label"] == "Northbound"
    assert q["color"] == "#FCCC0A"
    assert [a["minutes"] for a in q["arrivals"]] == [2, 9]
    # Arrival serialization carries the details the UI may use.
    assert q["arrivals"][0] == {
        "minutes": 2,
        "arrival": NOW.replace(minute=2).isoformat(),
        "trip_id": "t1",
        "headsign": "Uptown",
    }


def test_build_state_empty_when_no_groups():
    payload = server.build_state([], NOW)
    assert payload == {
        "updated_at": NOW.isoformat(),
        "stale": False,
        "age_seconds": 0,
        "stations": [],
        "alerts": [],
    }


def test_build_state_passes_through_staleness():
    payload = server.build_state([], NOW, stale=True, age_seconds=125)
    assert payload["stale"] is True
    assert payload["age_seconds"] == 125


# --- endpoints ---------------------------------------------------------------


def test_health(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_state_serves_fresh_cache(client: TestClient):
    groups = [_group("DeKalb Av", "Q", "N", [_arrival(3)])]
    # A snapshot polled just now -> not stale.
    server.poller._snapshot = Snapshot(groups=groups, updated_at=datetime.now(EASTERN))

    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stations"][0]["name"] == "DeKalb Av"
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


def test_frontend_served_from_same_origin(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "MTA Train Board" in resp.text
