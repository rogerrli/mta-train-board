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

1. **Clarify first — grill the owner.** Read the issue, its acceptance
   criteria, and the related code. Before writing any code, interview the owner
   about anything underspecified or any decision that needs a call (library
   choice, data source, scope boundary, UX). Ask as **selectable
   multiple-choice questions with a recommended option**, not open-ended walls
   of text. Don't build on unstated assumptions.
2. **Branch** `issue-<N>-<slug>` off the latest `main`. One issue per branch.
3. **Implement** to the issue's acceptance criteria — nothing more (see Scope).
4. **Verify**: ruff clean, mypy clean, `pytest` green. Include real evidence
   (commands + output) — never claim done without running it.
5. Run **`/simplify`** on the diff; commit any cleanup.
6. Run **`/code-review`** in report mode (no `--fix`).
7. **Disposition** the findings with the owner: present each finding **one at a
   time as a selectable choice** (apply-as-suggested / apply-differently / skip
   / defer), each with a recommendation. **Bundle** the answers, then apply the
   accepted fixes in one pass and re-verify.
8. **Push** the branch and open a **PR** whose body summarizes the work + the
   applied review dispositions and ends with `Closes #<N>`.
9. The repo owner reviews and merges.

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

## Recording decisions in the tracker

Context lives in GitHub, not in chat. When a decision made while working one
issue **affects or informs another issue's scope or design**, record it as a
comment on that other issue with `gh issue comment <N> --body "..."` — don't
leave it only in the conversation. Examples: a data-source or API-shape choice
a later issue must consume, a deferred sub-task, a constraint you discovered.
The tracker should be enough for a fresh session to pick up any issue cold.

## Interaction & reporting

- Talk to the owner in **selectable multiple-choice questions with a
  recommended option first**, not open-ended prose — for both up-front grilling
  and review-finding dispositions.
- Disposition review findings **one at a time**, then bundle the answers and
  apply them in a single pass.
- Keep status and summaries **terse**: links + one-liners. Show `/code-review`
  findings verbatim (the owner needs them to decide), but keep build recaps
  short.
- **Evidence before claims**: never say something works without pasting the
  command + output that proves it.

## Housekeeping

- Keep `config.example.toml` and the README's config section in sync with any
  config schema change.
- Tests must run **offline** — vendor fixtures, mock network calls.
