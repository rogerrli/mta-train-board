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
from fastapi.staticfiles import StaticFiles

from app.arrivals import Arrival, ArrivalGroup
from app.feeds import EASTERN
from app.poller import Poller

# The built frontend lives here (issue #7 fills it in). A placeholder index.html
# ships so same-origin serving works from a fresh clone today.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

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
    }


def build_state(
    groups: list[ArrivalGroup],
    updated_at: datetime,
    *,
    stale: bool = False,
    age_seconds: int = 0,
) -> dict[str, Any]:
    """Shape computed arrival groups into the ``/api/state`` payload.

    Arrival groups are nested under their station (config order preserved) so the
    board UI can render station by station. ``updated_at`` is the last successful
    poll time; ``stale``/``age_seconds`` (issue #6) let the UI flag old data.
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
                "color": g.color,
                "arrivals": [_serialize_arrival(a) for a in g.arrivals],
            }
        )
    return {
        "updated_at": updated_at.isoformat(),
        "stale": stale,
        "age_seconds": age_seconds,
        "stations": list(stations.values()),
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
        stale=poller.is_stale(snapshot, now=now),
        age_seconds=int(poller.age_seconds(snapshot, now=now)),
    )


# The built frontend (issue #7) is served from the same origin so the device runs
# one process. Mounted last so the /api/* routes above take precedence; html=True
# serves index.html at "/".
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
