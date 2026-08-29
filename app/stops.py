"""Resolve configured station names + lines to concrete GTFS stop IDs.

Real-time feeds (:mod:`app.feeds`) key arrivals by GTFS ``stop_id`` with an ``N``
/ ``S`` direction suffix (e.g. ``"631N"``). The user, however, configures
stations by human name + the lines/directions they care about (see
``config.example.toml``) -- never by raw stop ID. This module bridges the two.

Static reference data
---------------------
Line-per-station data comes from the MTA "Subway Stations" open dataset
(``stations.csv``), vendored under ``app/data/`` so normal operation and tests
are fully offline and deterministic. Each row gives a parent ``GTFS Stop ID``
(e.g. ``"A41"``), a ``Stop Name``, and the space-separated ``Daytime Routes``
serving that platform. A station *name* is not unique -- "14 St-Union Sq" maps to
three GTFS stop IDs (one per division: ``635`` for 4/5/6, ``L03`` for L, ``R20``
for N/Q/R/W) -- so the requested *lines* disambiguate which stop a name resolves
to. Plain ``stops.txt`` from the GTFS-static zip carries no route column and so
cannot support this line-association check; this dataset can.

Direction suffix: concrete stop IDs are the parent ID plus the direction letter
(``"A41"`` + ``"N"`` -> ``"A41N"``), matching the feed's convention.

Refresh: ``scripts/refresh-stops`` re-downloads this dataset and overwrites the
vendored file. Additionally, if a configured station fails to resolve in a way
that stale data could explain (unknown name, or a requested line not associated
with the name), resolution re-downloads the dataset **once per run**, rebuilds
the lookup, and retries before giving up -- see :func:`resolve_stations`.

Scope note (#3): this resolves name + lines -> stop IDs (per direction) and
validates config. Computing countdowns / assembling arrivals is #4.
"""

from __future__ import annotations

import csv
import difflib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
VENDORED_STATIONS = _DATA_DIR / "stations.csv"

# MTA "Subway Stations" open dataset (data.ny.gov id 39hk-dx4f). Confirmed
# working on 2026-08-29. Used by scripts/refresh-stops and the auto-redownload
# fallback below.
STATIONS_URL = "https://data.ny.gov/api/views/39hk-dx4f/rows.csv?accessType=DOWNLOAD"

DOWNLOAD_TIMEOUT = 30.0

VALID_DIRECTIONS = ("N", "S")


class StationResolutionError(Exception):
    """A configured station could not be resolved to concrete stop IDs.

    ``stale_data_plausible`` marks the failures that vendored data going out of
    date could explain (unknown name, requested line not served). Only those
    trigger the one-shot auto-redownload in :func:`resolve_stations`; config
    mistakes (bad direction, ambiguous match) do not.
    """

    def __init__(self, message: str, *, stale_data_plausible: bool = False) -> None:
        super().__init__(message)
        self.stale_data_plausible = stale_data_plausible


@dataclass(frozen=True)
class Station:
    """One physical platform group from the static dataset.

    ``stop_id`` is the parent GTFS stop ID (no direction suffix); ``routes`` are
    the daytime routes serving it (e.g. ``{"A", "C", "F"}``).
    """

    stop_id: str
    name: str
    routes: frozenset[str]


@dataclass(frozen=True)
class ResolvedStation:
    """A configured station resolved to concrete stop IDs.

    ``line_stops`` maps each requested line to its parent GTFS stop ID (e.g.
    ``{"F": "A41"}``). ``directions`` are the requested ``N``/``S`` letters. The
    concrete, direction-suffixed stop IDs the feeds use come from
    :meth:`watches` / :meth:`stop_ids`. For subway service the GTFS ``route_id``
    equals the line label, so ``line_stops`` keys double as the routes #4 passes
    to :mod:`app.feeds`.
    """

    name: str
    directions: tuple[str, ...]
    line_stops: dict[str, str]

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.line_stops)

    def watches(self) -> list[tuple[str, str, str]]:
        """Return ``(line, direction, concrete_stop_id)`` for each line x direction."""
        return [
            (line, direction, parent + direction)
            for line, parent in self.line_stops.items()
            for direction in self.directions
        ]

    def stop_ids(self) -> list[str]:
        """Return the concrete, direction-suffixed stop IDs to watch."""
        return [stop_id for _, _, stop_id in self.watches()]


class StopIndex:
    """Name (+ line) -> GTFS stop ID lookup built from the static dataset."""

    def __init__(self, stations: list[Station]) -> None:
        self._by_name: dict[str, list[Station]] = {}
        for station in stations:
            self._by_name.setdefault(_norm(station.name), []).append(station)
        # Display names (canonical spelling) for error suggestions.
        self._names = sorted({s.name for s in stations})

    @classmethod
    def from_text(cls, text: str) -> StopIndex:
        """Build an index from raw ``stations.csv`` text."""
        stations: list[Station] = []
        for row in csv.DictReader(text.splitlines()):
            stop_id = row["GTFS Stop ID"].strip()
            name = row["Stop Name"].strip()
            routes = frozenset(row["Daytime Routes"].split())
            if not stop_id or not name:
                continue
            stations.append(Station(stop_id=stop_id, name=name, routes=routes))
        if not stations:
            raise ValueError("no stations parsed from CSV text (unexpected format)")
        return cls(stations)

    @classmethod
    def from_csv(cls, path: Path = VENDORED_STATIONS) -> StopIndex:
        """Build an index from a vendored ``stations.csv`` file."""
        return cls.from_text(path.read_text(encoding="utf-8"))

    def stations_named(self, name: str) -> list[Station]:
        return self._by_name.get(_norm(name), [])

    def resolve(
        self, name: str, lines: list[str], directions: list[str]
    ) -> ResolvedStation:
        """Resolve one station name + lines + directions to concrete stop IDs.

        Raises :class:`StationResolutionError` on an unknown name, a requested
        line not served there, an ambiguous match, or a bad direction.
        """
        bad_dirs = [d for d in directions if d not in VALID_DIRECTIONS]
        if bad_dirs or not directions:
            raise StationResolutionError(
                f"Station {name!r}: invalid directions {directions!r}; "
                f"each must be one of {list(VALID_DIRECTIONS)} "
                f'("N" = northbound, "S" = southbound).'
            )
        if not lines:
            raise StationResolutionError(f"Station {name!r}: no lines configured.")

        matches = self.stations_named(name)
        if not matches:
            raise StationResolutionError(
                f"Unknown station name {name!r}. {self._suggest(name)}",
                stale_data_plausible=True,
            )

        served = sorted({route for s in matches for route in s.routes})
        line_stops: dict[str, str] = {}
        for line in lines:
            hosts = [s for s in matches if line in s.routes]
            if not hosts:
                raise StationResolutionError(
                    f"Station {name!r} does not serve line {line!r}. "
                    f"Lines here: {served}. Fix the config (or the line may have "
                    f"changed since the static data was captured).",
                    stale_data_plausible=True,
                )
            if len(hosts) > 1:
                ids = sorted(s.stop_id for s in hosts)
                raise StationResolutionError(
                    f"Station {name!r} line {line!r} is ambiguous: it maps to "
                    f"multiple stops {ids}. This usually means two distinct "
                    f"stations share a name; disambiguate by using a more "
                    f"specific name."
                )
            line_stops[line] = hosts[0].stop_id

        # Use the canonical dataset spelling of the name.
        canonical = matches[0].name
        return ResolvedStation(
            name=canonical,
            directions=tuple(directions),
            line_stops=line_stops,
        )

    def _suggest(self, name: str) -> str:
        close = difflib.get_close_matches(name, self._names, n=5, cutoff=0.5)
        if close:
            return "Did you mean: " + ", ".join(repr(c) for c in close) + "?"
        return "No similar station names found."


def _norm(name: str) -> str:
    """Normalize a station name for matching (case- and whitespace-insensitive)."""
    return " ".join(name.split()).casefold()


def download_stations_csv(
    url: str = STATIONS_URL, timeout: float = DOWNLOAD_TIMEOUT
) -> str:
    """Download the MTA Subway Stations dataset and return its CSV text.

    Raises :class:`httpx.HTTPError` on any network/HTTP failure.
    """
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text


def refresh_vendored_stations(
    url: str = STATIONS_URL, dest: Path = VENDORED_STATIONS
) -> Path:
    """Download the dataset and overwrite the vendored ``stations.csv``.

    Validates that the download parses before writing, so a bad response never
    replaces good vendored data. Returns the written path.
    """
    text = download_stations_csv(url)
    StopIndex.from_text(text)  # validate before overwriting
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def _station_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    stations = config.get("stations", [])
    if not stations:
        raise StationResolutionError(
            "No [[stations]] configured. Add at least one station block "
            "(name + lines + directions) to your config."
        )
    return stations


def _resolve_all(
    index: StopIndex, station_cfgs: list[dict[str, Any]]
) -> list[ResolvedStation]:
    return [
        index.resolve(
            name=cfg.get("name", ""),
            lines=list(cfg.get("lines", [])),
            directions=list(cfg.get("directions", [])),
        )
        for cfg in station_cfgs
    ]


def resolve_stations(
    config: dict[str, Any],
    *,
    index: StopIndex | None = None,
    allow_refresh: bool = True,
) -> list[ResolvedStation]:
    """Resolve every configured station to concrete stop IDs.

    On the first stale-data-plausible failure (unknown name, or a requested line
    not served) this re-downloads the static dataset **once**, rebuilds the
    lookup, and retries. Any other failure -- or a failed re-download -- surfaces
    as a :class:`StationResolutionError`. Pass ``allow_refresh=False`` (or a
    prebuilt ``index``, e.g. in tests) to keep resolution fully offline.
    """
    if index is None:
        index = StopIndex.from_csv()
    station_cfgs = _station_configs(config)

    try:
        return _resolve_all(index, station_cfgs)
    except StationResolutionError as first_error:
        if not (allow_refresh and first_error.stale_data_plausible):
            raise

        logger.warning(
            "Station resolution failed (%s). The vendored static station data "
            "may be stale; re-downloading it once from %s and retrying.",
            first_error,
            STATIONS_URL,
        )
        try:
            fresh_index = StopIndex.from_text(download_stations_csv())
        except Exception as download_error:
            raise StationResolutionError(
                f"{first_error} (a one-shot refresh of the static station data "
                f"was attempted but failed: {download_error})",
                stale_data_plausible=first_error.stale_data_plausible,
            ) from download_error

        try:
            resolved = _resolve_all(fresh_index, station_cfgs)
        except StationResolutionError as retry_error:
            raise StationResolutionError(
                f"{retry_error} (a one-shot refresh of the static station data "
                f"was attempted but the station still did not resolve).",
                stale_data_plausible=retry_error.stale_data_plausible,
            ) from retry_error

        logger.warning("Re-download succeeded; stations resolved after refresh.")
        return resolved


def _main() -> int:
    """Print each configured station and its resolved stop IDs.

    Run with ``uv run python -m app.stops`` -- satisfies the acceptance
    criterion "list stations by name in config -> app resolves them to stop IDs".
    """
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    from app.config import config_path, load_config

    print(f"Config: {config_path()}")
    try:
        resolved = resolve_stations(load_config())
    except StationResolutionError as exc:
        print(f"\nerror: {exc}")
        return 1

    for station in resolved:
        print(f"\n{station.name}  directions={list(station.directions)}")
        for line, direction, stop_id in station.watches():
            print(f"  line {line:>2} {direction} -> {stop_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
