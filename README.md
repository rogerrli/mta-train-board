# mta-train-board

A glanceable NYC subway arrivals board for a small touchscreen mounted in my
apartment. It polls the MTA real-time subway feeds, figures out which trains are
coming to the stations I care about, and renders the countdowns fullscreen — so
one glance tells me whether to run for the train.

## The idea

- **Backend:** a small Python service polls the MTA GTFS-Realtime feeds, parses
  arrivals for a configured set of stations + directions, and serves them as
  simple JSON.
- **Frontend:** a fullscreen web UI, designed for a small touchscreen, shows the
  arrivals as a clean board that auto-refreshes. Touch interactions let me drill
  into a specific train or station for more detail.
- **Hardware:** a Raspberry Pi driving a small touchscreen, running the UI in a
  kiosk-mode browser and starting on boot.

## Data source

The NYC MTA publishes real-time subway data as
[GTFS-Realtime](https://gtfs.org/realtime/) protobuf feeds, grouped by line.
As of 2021 these subway feeds **no longer require an API key**. Feeds are split
across line groups (numbered lines, ACE, BDFM, G, JZ, NQRW, L, SIR), so the app
needs to map each station's lines to the right feed(s).

Station/stop identifiers come from the MTA's **GTFS static** `stops.txt`. The
app maps human station names to GTFS stop IDs so arrivals can be filtered to the
stops and directions I actually use.

> Exact feed URLs and hosting have changed over time — confirming the current
> endpoints is an early task (see issues).

## Planned features

- Configurable list of stations + directions to watch
- Live countdowns per line/direction, sorted by soonest
- Tap a train → detailed breakdown of upcoming arrivals for that line/direction
- Tap a station → more info (all lines, both directions, service notes)
- On-screen control buttons for alternative views/controls
- An on/off control for the display
- Auto-refresh with graceful handling of feed outages / network loss
- Runs on a Raspberry Pi in kiosk mode, starting on boot

## Development

The backend is a Python 3.12 project managed with
[uv](https://docs.astral.sh/uv/).

### Install

```sh
uv sync
```

This creates a virtualenv and installs the app plus dev dependencies from
`pyproject.toml` / `uv.lock`.

### Run the dev server

```sh
uv run uvicorn app.server:app --reload --host 127.0.0.1
```

Bind to `127.0.0.1` so the board is reachable only from the local device.

The server exposes a small local JSON API and serves the frontend from the same
origin, so the device runs a single process:

- **`GET /api/state`** — the whole board in one atomic payload: watched stations
  with their upcoming arrivals (grouped by line + direction), plus `alerts`, an
  `updated_at` timestamp (the last successful feed poll), and `stale`/
  `age_seconds` staleness flags. Served from the background cache, so it answers
  instantly. The UI polls this one endpoint.
- **`GET /api/health`** — liveness check, `{"status":"ok"}`.
- **`GET /`** — the built board UI (`frontend/dist/`; see [The board UI](#the-board-ui)).

```sh
curl http://127.0.0.1:8000/api/health
# {"status":"ok"}

curl http://127.0.0.1:8000/api/state
```

`/api/state` shape:

```json
{
  "updated_at": "2026-08-29T21:59:10-04:00",
  "stale": false,
  "age_seconds": 12,
  "refresh_interval_seconds": 30,
  "stations": [
    {
      "name": "14 St-Union Sq",
      "arrivals": [
        {
          "line": "Q",
          "direction": "N",
          "direction_label": "Northbound",
          "terminal": "96 St-2 Av",
          "borough": "Man",
          "color": "#FCCC0A",
          "walk_minutes": 6,
          "arrivals": [
            {
              "minutes": 6, "arrival": "...", "trip_id": "...",
              "headsign": "...", "catchability": "CATCHABLE"
            }
          ]
        }
      ]
    }
  ],
  "alerts": []
}
```

Each group also carries a `terminal` + `borough` label (`null` when
unconfigured; see [Configuration](#configuration)): the board shows the terminal
station as the primary direction text with the borough as smaller secondary
text, falling back to `direction_label` ("Northbound"/"Southbound") when unset.

`refresh_interval_seconds` tells the board how often to re-poll. Each arrival's
`catchability` (`CATCHABLE`/`HURRY`/`MISSED`, or `null` when the station has no
`walk_minutes`) and the group's `walk_minutes` let the board style urgency and
recompute the countdowns + catchability every second from `arrival` between polls
(issue #8). `alerts` is an empty placeholder until service alerts land (issue
#13). A background task polls the feeds every `refresh_interval_seconds` and
caches the board; the endpoint serves that cache (never a live per-request fetch).
On a feed outage the last-known board keeps being served, flagged `stale` once
older than `stale_after_seconds`; before the first successful poll the endpoint
returns 503.

### Configuration

User settings (watched stations, directions, refresh interval) live in a TOML
file. You identify stations by **name + the lines you want + directions** —
never by raw stop ID. At startup the app resolves each station to concrete GTFS
stop IDs from vendored MTA static data (`app/data/stations.csv`).
`config.example.toml` is committed and documents the schema:

```toml
refresh_interval_seconds = 30   # feed poll + UI refresh cadence, seconds
stale_after_seconds = 90        # flag the board `stale` past this age
walk_best_case_delta_minutes = 1 # best case is this many min faster than walk_minutes

[[stations]]
name = "Times Sq-42 St"          # exact MTA station name
lines = ["1", "2", "3"]          # only these lines show; others are filtered out
directions = ["N", "S"]          # "N" = northbound, "S" = southbound
walk_minutes = 5                 # optional; worst-case walk here from home
```

Lines a station serves but you omit are filtered out (their trains never show),
and the lines you list also disambiguate stations that share a name (e.g.
"Fulton St" names several separate platforms across different lines). An unknown name or a line the
station doesn't serve produces a helpful error listing what was found.

`walk_minutes` lets the board flag whether you can actually make each train: a
train arriving in more minutes than the walk is **catchable**, one within
`walk_best_case_delta_minutes` of the walk is **hurry** (makeable only if you
move fast), and any sooner is **missed**. Omit `walk_minutes` to leave a
station's arrivals unclassified. When a station spans multiple `[[stations]]`
blocks, repeat the same `walk_minutes` on each.

Optional `[[direction_labels]]` blocks relabel a line/direction by its
**terminal station** instead of "Northbound"/"Southbound" — riders think in
terminals ("the uptown A to Inwood"), not compass words:

```toml
[[direction_labels]]
line = "A"                       # subway line
direction = "N"                  # "N" or "S" — the platform this applies to
terminal = "Inwood-207 St"       # primary text shown in place of the compass word
borough = "Man"                  # smaller secondary text (Man / Bklyn / Bx / Qns / SI)
```

The board shows `terminal` as the primary direction text and `borough` as
smaller secondary text. For a branchy direction (e.g. the southbound A splits to
Far Rockaway / Ozone Park / Lefferts) write whatever combined label reads best,
e.g. `terminal = "Rockaway / Lefferts"`. Both `terminal` and `borough` are
required in a block. A line/direction with no block falls back to
"Northbound"/"Southbound", so you only label the ones you watch.

#### Arrive-by trips

A `[[trips]]` block turns the board into a decision tool: given a destination and
a target arrival time, it recommends the **latest** train that still gets you
there on time (so you don't leave earlier than you must), a safer earlier
fallback, and a clear "you can't make it" state when even the best train arrives
late. The recommendation shows as a strip above the station board and appears in
`/api/state` under `trips`.

```toml
[[trips]]
name = "morning-uptown"          # stable id (referenced by focus mode, #39)
boarding = "Fulton St"           # must match a [[stations]] block by name
line = "A"                       # one line for the whole ride (no transfers)
direction = "N"                  # matches the boarding station block
destination = "59 St-Columbus Circle" # by name; must be a stop served by `line`
arrive_buffer_minutes = 0        # optional; aim to be there this many min early

[trips.target]                   # recurring target arrival (Eastern, 24h HH:MM)
default = "09:00"                # any *weekday* (Mon–Fri) not listed below
tue = "08:45"                    # Tuesdays specifically
```

The `boarding` station must also be configured as a `[[stations]]` block on the
same line/direction, **with a `walk_minutes` set** — that's where the live
countdowns and walk time come from. The `[trips.target]` table is keyed by
weekday abbreviation (`mon`…`sun`) plus an optional `default`. For "today"
(Eastern): an explicit weekday key wins; otherwise a **weekday** falls back to
`default`; a **weekend** with no explicit key has *no target*, so the board
simply shows no recommendation that day. The block above (generic placeholder
stations/times) means 8:45 on Tuesdays, 9:00 the rest of the workweek, and
nothing on weekends. Ride durations come from the vendored travel-time model —
after adding a `line` the model wasn't built with, rebuild it with `uv run
scripts/refresh-travel-times`.

To customize, copy it to a local override (gitignored so your settings stay
private):

```sh
cp config.example.toml config.local.toml
```

`app/config.py` loads `config.local.toml` if present, otherwise falls back to
`config.example.toml`.

To see how your config resolves to stop IDs:

```sh
uv run python -m app.stops
```

### Static station data

Station → stop-ID resolution uses a vendored snapshot of the MTA "Subway
Stations" open dataset (`app/data/stations.csv`), so the app and its tests run
fully offline. Refresh it manually when the MTA changes stations or routes:

```sh
uv run scripts/refresh-stops
```

If a configured station fails to resolve in a way stale data could explain (an
unknown name, or a line not associated with the station), the app also
re-downloads this dataset once and retries automatically before erroring.

### Travel-time data

Scheduled station-to-station ride durations (`app/travel.py`, used by the
arrive-by recommendation) come from the MTA **GTFS static** timetable. The full
`stop_times.txt` is ~36 MB, so we vendor a compact artifact
(`app/data/travel_times.json.gz`) trimmed to the routes in your config and
tagged with the feed version + build date. Rebuild it when the timetable
changes:

```sh
uv run scripts/refresh-travel-times
```

Look up a single ride (parent stop IDs + direction, optional `HH:MM`):

```sh
uv run python -m app.travel R30 R20 Q N 08:30
```

### Lint & format

```sh
uv run ruff check .
uv run ruff format .
```

CI (`.github/workflows/ci.yml`) runs the ruff lint and format checks on every
push and pull request.

### The board UI

The fullscreen board is a [Vite](https://vite.dev/) + [Svelte](https://svelte.dev/)
app in `frontend/`. It's designed for the wall panel in **landscape** (the panels
are natively portrait, e.g. 720×1280, rotated 90° in software, so the UI targets
1280×720), with big high-contrast type readable across the room. It polls
`/api/state` on the configured interval and, between polls, recomputes each
countdown and its catchability every second from the absolute `arrival` times, so
trains visibly tick down and cross CATCHABLE → HURRY → MISSED. Trains you can't
make (MISSED) are shown dimmed and struck through rather than hidden.

Build it (needs Node 20+; only at build time — the Pi serves static files):

```sh
cd frontend
npm ci          # or: npm install
npm run build   # outputs frontend/dist/, which app/server.py serves at "/"
```

`frontend/dist/` is gitignored; build it after cloning (and on the Pi at deploy
time). If it isn't built, the server still boots and serves a short build hint at
`/`. For UI development with hot reload, run the API and the Vite dev server
side by side — Vite proxies `/api` to the backend:

```sh
uv run uvicorn app.server:app --reload --host 127.0.0.1  # terminal 1
cd frontend && npm run dev                                # terminal 2
```

## Public demo (Render)

The board runs as a public demo on its **default config**: with no
`config.local.toml` it falls back to `config.example.toml` (real Brooklyn
stations) and pulls **live** MTA data. The subway GTFS-Realtime feeds are
keyless, so the demo needs no secrets or environment variables.

Deployment is packaged as a [`render.yaml`](render.yaml) blueprint plus a
multi-stage [`Dockerfile`](Dockerfile) (a Node stage builds `frontend/dist`, a
Python stage serves it with uvicorn). To deploy:

1. On [Render](https://render.com), **New → Blueprint** and pick this repo.
2. Render reads `render.yaml`, builds the Dockerfile, and starts the service on
   the free plan — no env vars to set. `healthCheckPath` is `/api/health`.
3. Open the assigned `*.onrender.com` URL to see the live board.

The service binds `0.0.0.0:$PORT` (intentionally public, unlike the Pi's
localhost bind). On the free plan it spins down when idle and cold-starts on the
next request (~30–50s); a caller can warm it by pinging `/api/health` ahead of
time. Build the image locally the same way Render does:

```sh
docker build -t mta-train-board .
docker run --rm -p 8000:8000 mta-train-board
curl http://127.0.0.1:8000/api/health   # {"status":"ok"}
```

## Status

Early setup. Work is tracked in
[GitHub issues](https://github.com/rogerrli/mta-train-board/issues).

## Stack

- Python backend (feed polling + JSON API)
- Web frontend (fullscreen touchscreen UI)
- Runs on Raspberry Pi OS in a kiosk browser

## License

MIT — see [LICENSE](LICENSE).
