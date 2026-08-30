"""FastAPI app: serves the arrivals board as JSON and hosts the static frontend.

A single combined endpoint ``GET /api/state`` returns the whole board (stations
-> arrivals) plus alerts and an ``updated_at`` timestamp in one atomic payload --
the owner's API decision on issue #5 (one poll from the UI, simplest to reason
about, no split arrivals/alerts endpoints). ``GET /api/health`` is a liveness
check. The built frontend (issue #7) is served from the same origin so the Pi
runs a single process.

Run the dev server (bind to localhost only for a local device):

    uv run uvicorn app.server:app --reload --host 127.0.0.1

Scope note (#5): this only shapes and serves the computed arrivals. It fetches
the live feeds per request for now; the background poll + cache is issue #6.
Service alerts are issue #13 (the ``alerts`` slot is an empty placeholder here),
and richer stale/offline error states are issue #14.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.arrivals import Arrival, ArrivalGroup, fetch_arrivals
from app.config import load_config
from app.feeds import EASTERN, FeedError
from app.stops import StationResolutionError

# The built frontend lives here (issue #7 fills it in). A placeholder index.html
# ships so same-origin serving works from a fresh clone today.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

logger = logging.getLogger(__name__)

app = FastAPI(title="MTA Train Board")

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


def build_state(groups: list[ArrivalGroup], updated_at: datetime) -> dict[str, Any]:
    """Shape computed arrival groups into the ``/api/state`` payload.

    Arrival groups are nested under their station (config order preserved) so the
    board UI can render station by station. ``alerts`` is an empty placeholder
    until service alerts land in issue #13. Pure and offline -- unit-testable.
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
        "stations": list(stations.values()),
        "alerts": [],  # TODO(#13): service alerts for the watched lines.
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@app.get("/api/state")
def state() -> dict[str, Any]:
    """Return the whole board as one JSON payload (stations -> arrivals)."""
    # TODO(#6): serve from the background poll cache instead of resolving stations
    # and fetching the live feeds on every request (fine for a wall board, not at
    # scale). updated_at is the compute time; #6 makes it the last successful poll.
    now = datetime.now(EASTERN)
    try:
        groups = fetch_arrivals(load_config(), now=now)
    except (FeedError, StationResolutionError, ValueError) as exc:
        # Log the real cause server-side; return a stable, generic message rather
        # than leaking internal detail across the API boundary.
        # TODO(#14): richer stale/offline UX (serve last-known board when stale).
        logger.warning("Could not build /api/state: %s", exc)
        raise HTTPException(
            status_code=503, detail="Arrivals are temporarily unavailable."
        ) from exc
    return build_state(groups, now)


# The built frontend (issue #7) is served from the same origin so the device runs
# one process. Mounted last so the /api/* routes above take precedence; html=True
# serves index.html at "/".
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
