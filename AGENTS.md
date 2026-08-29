# Agent workflow — mta-train-board

Instructions for any AI coding session working an issue in this repo. Read this
before starting. The model is **one session per issue**: you pick up a single
GitHub issue, drive it end-to-end, and coordinate merges with the repo owner.

## What this project is

A glanceable NYC subway arrivals board for a wall-mounted touchscreen. A Python
backend polls the MTA GTFS-Realtime feeds, computes arrivals for configured
stations/directions, and serves JSON to a fullscreen web UI. See `README.md`.

## Stack & conventions

- **Python 3.12**, managed with **uv** (`pyproject.toml` + `uv.lock`).
- **FastAPI + uvicorn** for the local HTTP/JSON API and serving the frontend.
- **Config in TOML**: `config.example.toml` (committed) + `config.local.toml`
  (gitignored local override). Load with stdlib `tomllib`.
- **ruff** for lint + format; **mypy** for type checking; **pytest** for tests.
- Datetimes that represent train times are **timezone-aware `America/New_York`**.
- Prefer the stdlib and existing deps. Add a dependency only when it clearly
  earns its place. Laziest-that-works over speculative abstraction (YAGNI).

## Dev commands

```bash
uv sync                                   # install (use --locked in CI)
uv run uvicorn app.server:app --reload    # run the dev server
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

## Per-issue workflow (definition of done)

1. **Branch** `issue-<N>-<slug>` off the latest `main`. One issue per branch.
2. **Implement** to the issue's acceptance criteria — nothing more (see Scope).
3. **Verify**: ruff clean, mypy clean, `pytest` green. Include real evidence
   (commands + output) — never claim done without running it.
4. Run **`/simplify`** on the diff; commit any cleanup.
5. Run **`/code-review`** in report mode (no `--fix`).
6. **Disposition** each review finding with the repo owner (a quick
   per-finding choice), then apply the accepted fixes and re-verify.
7. **Push** the branch and open a **PR** whose body summarizes the work + the
   applied review dispositions and ends with `Closes #<N>`.
8. The repo owner reviews and merges.

## Branching & dependencies

- Many issues depend on earlier ones. **A dependent issue waits until its
  parent has been merged to `main`**, then branches off the updated `main`.
- Don't stack on an unmerged branch unless the owner asks.
- If your branch falls behind `main` before merge, rebase onto `main` and
  regenerate `uv.lock` if it drifted.

## Scope discipline

- Stay strictly in your issue's lane. When you notice work that belongs to
  another issue, **leave a `TODO(#<N>)` note** rather than doing it here.
- Module ownership follows the MVP issues: feeds (#2), stops (#3),
  arrivals/countdowns (#4), API (#5), polling/cache (#6), frontend (#7).

## Housekeeping

- Keep `config.example.toml` and the README's config section in sync with any
  config schema change.
- Tests must run **offline** — vendor fixtures, mock network calls.
