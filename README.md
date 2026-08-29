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
uv run uvicorn app.server:app --reload
```

Then check the health endpoint:

```sh
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

The arrivals endpoints land in later issues; for now the server just exposes
`/health` so a fresh clone can confirm everything runs.

### Configuration

User settings (watched stations, directions, refresh interval) live in a TOML
file. `config.example.toml` is committed and documents the schema:

```toml
refresh_interval_seconds = 30

[[stations]]
name = "Grand Central-42 St"
stop_id = "631"
directions = ["N", "S"]
```

To customize, copy it to a local override (gitignored so your settings stay
private):

```sh
cp config.example.toml config.local.toml
```

`app/config.py` loads `config.local.toml` if present, otherwise falls back to
`config.example.toml`.

### Lint & format

```sh
uv run ruff check .
uv run ruff format .
```

CI (`.github/workflows/ci.yml`) runs the ruff lint and format checks on every
push and pull request.

## Status

Early setup. Work is tracked in
[GitHub issues](https://github.com/rogerrli/mta-train-board/issues).

## Stack

- Python backend (feed polling + JSON API)
- Web frontend (fullscreen touchscreen UI)
- Runs on Raspberry Pi OS in a kiosk browser

## License

MIT — see [LICENSE](LICENSE).
