"""Tests for app.server -- the local HTTP/JSON API. Fully offline.

``build_state`` is exercised as a pure function. The endpoints are driven through
FastAPI's TestClient with ``fetch_arrivals`` monkeypatched, so no network or live
feeds are touched.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import server
from app.arrivals import Arrival, ArrivalGroup
from app.feeds import FeedError
from app.stops import StationResolutionError

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
    assert payload == {"updated_at": NOW.isoformat(), "stations": [], "alerts": []}


# --- endpoints ---------------------------------------------------------------


def test_health(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_state_returns_current_arrivals(client: TestClient, monkeypatch):
    groups = [_group("DeKalb Av", "Q", "N", [_arrival(3)])]
    monkeypatch.setattr(server, "fetch_arrivals", lambda *a, **k: groups)

    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stations"][0]["name"] == "DeKalb Av"
    assert body["stations"][0]["arrivals"][0]["arrivals"][0]["minutes"] == 3
    assert body["alerts"] == []
    assert "updated_at" in body


@pytest.mark.parametrize(
    "exc",
    [
        FeedError("feed down"),
        StationResolutionError("Unknown station 'Nowhere'"),
        ValueError("Unknown subway route 'X'"),
    ],
)
def test_state_returns_503_on_upstream_error(client: TestClient, monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(server, "fetch_arrivals", boom)

    resp = client.get("/api/state")
    assert resp.status_code == 503
    # A stable, generic message -- the raw exception text is not leaked to clients.
    assert resp.json()["detail"] == "Arrivals are temporarily unavailable."


def test_frontend_served_from_same_origin(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "MTA Train Board" in resp.text
