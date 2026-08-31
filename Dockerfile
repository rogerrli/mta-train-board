# Multi-stage build for the public demo (issue #46).
#
# Stage 1 builds the Vite/Svelte frontend into frontend/dist. Stage 2 is the
# Python runtime that serves that dist plus the JSON API. frontend/dist is
# gitignored and built here, so a fresh clone needs no committed build output.
#
# The container runs the *default* config: with no config.local.toml the app
# falls back to config.example.toml (real Brooklyn stations) and pulls live,
# keyless MTA data -- no secrets to provision.

# --- Stage 1: build the frontend -------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /app/frontend
# Install deps first for layer caching, then build.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime -----------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies (cached) without the project or dev tools.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# App source + the files pyproject references when building the project wheel.
COPY app/ ./app/
COPY config.example.toml README.md LICENSE ./
RUN uv sync --locked --no-dev

# Built frontend from stage 1.
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Render injects $PORT; bind 0.0.0.0 so the service is reachable (unlike the
# Pi's localhost-only bind). Shell form so ${PORT} expands.
EXPOSE 8000
CMD uv run uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}
