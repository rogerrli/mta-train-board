"""FastAPI app serving arrivals as JSON.

The arrivals endpoints are implemented in issue #5. For now this exposes a
health check so a fresh clone can run the dev server:

    uv run uvicorn app.server:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="MTA Train Board")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


# TODO(#5): add arrivals endpoints (e.g. GET /arrivals) backed by app.arrivals.
