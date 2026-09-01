"""FastAPI app: serves the arrivals board as JSON and hosts the static frontend.

A single combined endpoint ``GET /api/state`` returns the whole board (stations
-> arrivals) plus alerts and an ``updated_at`` timestamp in one atomic payload --
the owner's API decision on issue #5 (one poll from the UI, simplest to reason
about, no split arrivals/alerts endpoints). ``GET /api/health`` is a liveness
check. The built frontend (issue #7) is served from the same origin so the Pi
runs a single process.

Run the dev server (bind to localhost only for a local device):

    uv run uvicorn app.server:app --reload --host 127.0.0.1

Scope note: this only shapes and serves the computed arrivals. A background
:class:`~app.poller.Poller` (issue #6) refreshes the board on an interval and
``/api/state`` answers from that cache -- ``updated_at`` is the last successful
poll and the payload carries ``stale``/``age_seconds`` so the UI can show "data
is old". Service alerts are issue #13 (the ``alerts`` slot is an empty
placeholder here), and richer stale/offline error states are issue #14.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.arrivals import Arrival, ArrivalGroup, route_color
from app.feeds import EASTERN
from app.poller import Poller
from app.trips import TrainOption, TripRecommendation

# The board (issue #7) is a Vite + Svelte app whose built output lands in
# frontend/dist. dist/ is gitignored and built at deploy time
# (``npm ci && npm run build`` in frontend/), so the Pi runs no Node at runtime.
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

logger = logging.getLogger(__name__)

# The background poller (issue #6) owns the arrivals cache the API serves. One
# instance for the process; its task is started/stopped by the lifespan below.
poller = Poller.from_config()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the background poll task for the life of the server process."""
    poller.start()
    try:
        yield
    finally:
        await poller.stop()


app = FastAPI(title="MTA Train Board", lifespan=lifespan)

# This runs on a single local device. The frontend is served same-origin (no CORS
# needed for it), but allow any localhost dev server (e.g. a Vite port) to call the
# API during development. GET only, no credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _serialize_arrival(a: Arrival) -> dict[str, Any]:
    """One upcoming train as JSON: countdown minutes + the details the UI may use."""
    return {
        "minutes": a.minutes,
        "arrival": a.arrival.isoformat(),
        "trip_id": a.trip_id,
        "headsign": a.headsign,
        # Walk-time class from issue #8 (CATCHABLE/HURRY/MISSED, or null when the
        # station has no walk_minutes). The board styles urgency off this and
        # recomputes it every second from ``arrival`` between polls (issue #8).
        "catchability": a.catchability,
    }


def _serialize_train_option(option: TrainOption | None) -> dict[str, Any] | None:
    """One candidate train (leave/board/arrive times) as JSON, or null."""
    if option is None:
        return None
    return {
        "departure": option.departure.isoformat(),
        "minutes": option.minutes,
        "leave_by": option.leave_by.isoformat(),
        "leave_in_minutes": option.leave_in_minutes,
        "arrival": option.arrival.isoformat() if option.arrival else None,
        "on_time": option.on_time,
        "lateness_minutes": option.lateness_minutes,
    }


def _serialize_recommendation(rec: TripRecommendation) -> dict[str, Any]:
    """One arrive-by trip recommendation (#27) as JSON.

    Absolute times (``leave_by``, ``departure``, ``arrival``, ``target``) are sent
    so the board can recompute "leave in N min" every second between polls, the
    same way it reclassifies catchability (#8).
    """
    return {
        "name": rec.name,
        "boarding": rec.boarding,
        "line": rec.line,
        "color": route_color(rec.line),
        "direction": rec.direction,
        "destination": rec.destination,
        "target": rec.target.isoformat() if rec.target else None,
        "status": rec.status,
        "recommended": _serialize_train_option(rec.recommended),
        "fallback": _serialize_train_option(rec.fallback),
    }


def build_state(
    groups: list[ArrivalGroup],
    updated_at: datetime,
    *,
    recommendations: list[TripRecommendation] | None = None,
    stale: bool = False,
    age_seconds: int = 0,
    refresh_interval_seconds: float = 30.0,
) -> dict[str, Any]:
    """Shape computed arrival groups into the ``/api/state`` payload.

    Arrival groups are nested under their station (config order preserved) so the
    board UI can render station by station. ``updated_at`` is the last successful
    poll time; ``stale``/``age_seconds`` (issue #6) let the UI flag old data.
    ``refresh_interval_seconds`` tells the board how often to re-poll this endpoint.
    ``alerts`` is an empty placeholder until service alerts land in issue #13.
    Pure and offline -- unit-testable.
    """
    # Insertion-ordered dict groups by station while preserving config order.
    stations: dict[str, dict[str, Any]] = {}
    for g in groups:
        station = stations.setdefault(g.station, {"name": g.station, "arrivals": []})
        station["arrivals"].append(
            {
                "line": g.line,
                "direction": g.direction,
                "direction_label": g.direction_label,
                # Configured terminal-station label for this (line, direction)
                # (#41): the board shows ``terminal`` as the primary direction
                # text with ``borough`` as smaller secondary text, falling back
                # to ``direction_label`` when these are null (unconfigured).
                "terminal": g.terminal,
                "borough": g.borough,
                "color": g.color,
                # Station walk time behind each arrival's catchability (issue #8),
                # so the board can reclassify between polls; null when unconfigured.
                "walk_minutes": g.walk_minutes,
                "arrivals": [_serialize_arrival(a) for a in g.arrivals],
            }
        )
    return {
        "updated_at": updated_at.isoformat(),
        "stale": stale,
        "age_seconds": age_seconds,
        "refresh_interval_seconds": refresh_interval_seconds,
        "stations": list(stations.values()),
        # Arrive-by trip recommendations (#27); empty when no [[trips]] configured.
        "trips": [_serialize_recommendation(r) for r in (recommendations or [])],
        "alerts": [],  # TODO(#13): service alerts for the watched lines.
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@app.get("/api/state")
def state() -> dict[str, Any]:
    """Return the whole board as one JSON payload (stations -> arrivals).

    Served from the background poller's cache, so it answers instantly and never
    fetches live per request. Until the first poll succeeds the cache is empty and
    we return 503; after that we always serve the last-known board, flagged
    ``stale`` once it ages past the configured threshold (issue #6).
    """
    snapshot = poller.snapshot
    if snapshot is None:
        # No successful poll yet (cold start or a sustained outage from boot).
        # TODO(#14): richer stale/offline UX at the frontend.
        raise HTTPException(
            status_code=503, detail="Arrivals are temporarily unavailable."
        )
    now = datetime.now(EASTERN)
    return build_state(
        snapshot.groups,
        snapshot.updated_at,
        recommendations=snapshot.recommendations,
        stale=poller.is_stale(snapshot, now=now),
        age_seconds=int(poller.age_seconds(snapshot, now=now)),
        refresh_interval_seconds=poller.refresh_seconds,
    )


# The built board is served from the same origin so the device runs one process.
# Mounted last so the /api/* routes above take precedence; html=True serves
# index.html at "/". If dist/ isn't built yet (fresh clone, no `npm run build`),
# serve a short hint at "/" instead of failing to boot -- StaticFiles raises on a
# missing directory, and the API must still come up.
if (FRONTEND_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    logger.warning(
        "Board not built (%s missing); serving a build hint at /. "
        "Run `npm ci && npm run build` in frontend/.",
        FRONTEND_DIST / "index.html",
    )

    @app.get("/", response_class=HTMLResponse)
    def _frontend_not_built() -> str:
        return (
            "<!doctype html><meta charset=utf-8><title>MTA Train Board</title>"
            "<h1>MTA Train Board</h1><p>The board isn't built yet. Run "
            "<code>npm ci &amp;&amp; npm run build</code> in <code>frontend/</code>, "
            "then reload.</p><p>API: <a href=/api/state>/api/state</a></p>"
        )
