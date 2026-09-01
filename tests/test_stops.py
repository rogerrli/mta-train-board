"""Tests for app.stops -- fully offline against the vendored stations.csv.

Real resolution runs against the committed ``app/data/stations.csv``. Edge cases
use tiny in-memory CSVs via :meth:`StopIndex.from_text`. The auto-redownload path
mocks the network call so tests never touch the network.
"""

import httpx
import pytest

from app import stops
from app.stops import StationResolutionError, StopIndex

# --- tiny in-memory datasets -------------------------------------------------

# Only the three columns app.stops reads are required.
HEADER = "GTFS Stop ID,Stop Name,Daytime Routes"


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


# "Atlantic Av-Barclays Ctr" appears twice (BMT B/Q/R and, separately, the L) so
# lines must disambiguate; "Fulton St" is a distinct single station.
SMALL = _csv(
    "R30,Atlantic Av-Barclays Ctr,B Q R",
    "L16,Atlantic Av-Barclays Ctr,L",
    "233,Fulton St,2 3",
)


@pytest.fixture
def vendored() -> StopIndex:
    return StopIndex.from_csv()


# --- successful resolution (vendored data) -----------------------------------


def test_resolve_maps_name_and_lines_to_parent_stop(vendored):
    resolved = vendored.resolve("Times Sq-42 St", ["1", "2"], ["N"])
    assert resolved.name == "Times Sq-42 St"
    assert resolved.line_stops == {"1": "127", "2": "127"}
    assert resolved.lines == ("1", "2")
    # 1 and 2 share parent 127, so the concrete stop is listed once.
    assert resolved.stop_ids() == ["127N"]


def test_resolve_filters_unwanted_lines_at_shared_platform(vendored):
    # Grand Central-42 St serves 4/5/6 on stop 631; asking only for 6 still
    # resolves to 631 and never pulls in 4/5.
    resolved = vendored.resolve("Grand Central-42 St", ["6"], ["N", "S"])
    assert resolved.line_stops == {"6": "631"}
    assert set(resolved.stop_ids()) == {"631N", "631S"}


def test_resolve_disambiguates_shared_name_by_line(vendored):
    # "Fulton St" names several separate platforms across lines; the IRT 4/5
    # platform is stop 418, and asking for 4/5 selects it.
    resolved = vendored.resolve("Fulton St", ["4", "5"], ["N", "S"])
    assert set(resolved.line_stops.values()) == {"418"}


def test_resolve_is_case_and_whitespace_insensitive(vendored):
    resolved = vendored.resolve("  14   st-union sq ", ["L"], ["N"])
    assert resolved.name == "14 St-Union Sq"  # canonical spelling returned
    assert resolved.line_stops == {"L": "L03"}


def test_duplicate_lines_and_directions_are_deduped():
    index = StopIndex.from_text(SMALL)
    resolved = index.resolve("Atlantic Av-Barclays Ctr", ["Q", "Q", "R"], ["N", "N"])
    assert resolved.lines == ("Q", "R")
    assert resolved.directions == ("N",)
    assert resolved.watches() == [("Q", "N", "R30N"), ("R", "N", "R30N")]


def test_watches_enumerates_line_x_direction():
    index = StopIndex.from_text(SMALL)
    resolved = index.resolve("Atlantic Av-Barclays Ctr", ["Q", "R"], ["N", "S"])
    assert set(resolved.watches()) == {
        ("Q", "N", "R30N"),
        ("Q", "S", "R30S"),
        ("R", "N", "R30N"),
        ("R", "S", "R30S"),
    }


# --- walk time (#8) ----------------------------------------------------------


def test_resolve_carries_walk_minutes():
    index = StopIndex.from_text(SMALL)
    resolved = index.resolve("Fulton St", ["2"], ["N"], walk_minutes=4)
    assert resolved.walk_minutes == 4


def test_walk_minutes_defaults_to_none_when_omitted():
    index = StopIndex.from_text(SMALL)
    assert index.resolve("Fulton St", ["2"], ["N"]).walk_minutes is None


def test_config_walk_minutes_flows_through_resolve_stations():
    index = StopIndex.from_text(SMALL)
    config = {
        "stations": [
            {
                "name": "Fulton St",
                "lines": ["2"],
                "directions": ["N"],
                "walk_minutes": 3,
            }
        ]
    }
    (resolved,) = stops.resolve_stations(config, index=index, allow_refresh=False)
    assert resolved.walk_minutes == 3


@pytest.mark.parametrize("bad", [-1, "5", True])
def test_bad_walk_minutes_raises_and_is_not_stale_data(bad):
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Fulton St", ["2"], ["N"], walk_minutes=bad)
    assert exc.value.stale_data_plausible is False
    assert "walk_minutes" in str(exc.value)


# --- error cases -------------------------------------------------------------


def test_unknown_name_raises_with_suggestion():
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Atlantic Av-Barclay", ["Q"], ["N"])
    assert exc.value.stale_data_plausible is True
    assert "Atlantic Av-Barclays Ctr" in str(exc.value)  # close-match suggestion


def test_requested_line_not_served_raises():
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Fulton St", ["A"], ["N"])
    assert exc.value.stale_data_plausible is True
    assert "does not serve line 'A'" in str(exc.value)
    assert "['2', '3']" in str(exc.value)  # lists what it does serve


def test_bad_direction_raises_and_is_not_stale_data():
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Fulton St", ["2"], ["E"])
    assert exc.value.stale_data_plausible is False


def test_ambiguous_line_raises_and_is_not_stale_data():
    # Two genuinely distinct stations share a name AND a line.
    ambiguous = _csv("A01,Twin,7", "B02,Twin,7")
    index = StopIndex.from_text(ambiguous)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Twin", ["7"], ["N"])
    assert exc.value.stale_data_plausible is False
    assert "ambiguous" in str(exc.value)


# --- whole-config resolution -------------------------------------------------


def test_resolve_stations_resolves_all_blocks_offline():
    index = StopIndex.from_text(SMALL)
    config = {
        "stations": [
            {
                "name": "Atlantic Av-Barclays Ctr",
                "lines": ["Q", "R"],
                "directions": ["N", "S"],
            },
            {"name": "Fulton St", "lines": ["2", "3"], "directions": ["N"]},
        ]
    }
    resolved = stops.resolve_stations(config, index=index, allow_refresh=False)
    assert [r.name for r in resolved] == ["Atlantic Av-Barclays Ctr", "Fulton St"]


def test_resolve_stations_requires_at_least_one_station():
    with pytest.raises(StationResolutionError):
        stops.resolve_stations({"stations": []}, index=StopIndex.from_text(SMALL))


# --- auto-redownload fallback (network mocked) -------------------------------


def test_auto_redownload_retries_and_succeeds(monkeypatch, tmp_path):
    # Start from stale data that lacks the station...
    stale = StopIndex.from_text(_csv("233,Fulton St,2 3"))
    # ...and have the "download" return fresh data that includes it.
    fresh_csv = _csv("233,Fulton St,2 3", "R30,Atlantic Av-Barclays Ctr,B Q R")
    calls = {"n": 0}

    def fake_download(*a, **k):
        calls["n"] += 1
        return fresh_csv

    monkeypatch.setattr(stops, "download_stations_csv", fake_download)
    # Persist to a throwaway path, not the real vendored file.
    monkeypatch.setattr(stops, "VENDORED_STATIONS", tmp_path / "stations.csv")

    config = {
        "stations": [
            {"name": "Atlantic Av-Barclays Ctr", "lines": ["Q"], "directions": ["N"]}
        ]
    }
    resolved = stops.resolve_stations(config, index=stale, allow_refresh=True)

    assert calls["n"] == 1  # downloaded exactly once
    assert resolved[0].line_stops == {"Q": "R30"}


def test_auto_redownload_persists_fresh_data(monkeypatch, tmp_path):
    # The heal should overwrite the vendored file so the next boot skips it.
    dest = tmp_path / "stations.csv"
    dest.write_text(_csv("233,Fulton St,2 3"), encoding="utf-8")  # stale on disk
    monkeypatch.setattr(stops, "VENDORED_STATIONS", dest)
    fresh_csv = _csv("233,Fulton St,2 3", "R30,Atlantic Av-Barclays Ctr,B Q R")
    monkeypatch.setattr(stops, "download_stations_csv", lambda *a, **k: fresh_csv)

    stale = StopIndex.from_text(dest.read_text(encoding="utf-8"))
    config = {
        "stations": [
            {"name": "Atlantic Av-Barclays Ctr", "lines": ["Q"], "directions": ["N"]}
        ]
    }
    stops.resolve_stations(config, index=stale, allow_refresh=True)

    assert dest.read_text(encoding="utf-8") == fresh_csv  # persisted


def test_auto_redownload_retry_passes_config_errors_through(monkeypatch, tmp_path):
    # First station is unknown (triggers refresh); a later station has a bad
    # direction. After the refresh the first resolves, the second raises a plain
    # config error that must NOT be re-labeled as a stale-data / refresh failure.
    stale = StopIndex.from_text(_csv("233,Fulton St,2 3"))
    fresh_csv = _csv("233,Fulton St,2 3", "R30,Atlantic Av-Barclays Ctr,B Q R")
    monkeypatch.setattr(stops, "download_stations_csv", lambda *a, **k: fresh_csv)
    # Persist to a throwaway path, not the real vendored file.
    monkeypatch.setattr(stops, "VENDORED_STATIONS", tmp_path / "stations.csv")

    config = {
        "stations": [
            {"name": "Atlantic Av-Barclays Ctr", "lines": ["Q"], "directions": ["N"]},
            {"name": "Fulton St", "lines": ["2"], "directions": ["E"]},
        ]
    }
    with pytest.raises(StationResolutionError) as exc:
        stops.resolve_stations(config, index=stale, allow_refresh=True)
    assert exc.value.stale_data_plausible is False
    assert "refresh" not in str(exc.value).lower()


def test_auto_redownload_failure_reports_attempt(monkeypatch):
    stale = StopIndex.from_text(_csv("233,Fulton St,2 3"))

    def boom(*a, **k):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(stops, "download_stations_csv", boom)

    config = {
        "stations": [
            {"name": "Atlantic Av-Barclays Ctr", "lines": ["Q"], "directions": ["N"]}
        ]
    }
    with pytest.raises(StationResolutionError) as exc:
        stops.resolve_stations(config, index=stale, allow_refresh=True)
    assert "refresh" in str(exc.value).lower()
    assert "network down" in str(exc.value)


def test_auto_redownload_not_triggered_for_config_error(monkeypatch):
    stale = StopIndex.from_text(SMALL)

    def fail_if_called(*a, **k):
        raise AssertionError("download must not be attempted for a config error")

    monkeypatch.setattr(stops, "download_stations_csv", fail_if_called)

    # Bad direction is a config mistake, not stale data -> no re-download.
    config = {"stations": [{"name": "Fulton St", "lines": ["2"], "directions": ["E"]}]}
    with pytest.raises(StationResolutionError) as exc:
        stops.resolve_stations(config, index=stale, allow_refresh=True)
    assert exc.value.stale_data_plausible is False


def test_refresh_vendored_validates_before_writing(monkeypatch, tmp_path):
    dest = tmp_path / "stations.csv"
    dest.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr(stops, "download_stations_csv", lambda *a, **k: "garbage,data")
    with pytest.raises(ValueError):
        stops.refresh_vendored_stations(dest=dest)
    assert dest.read_text(encoding="utf-8") == "ORIGINAL"  # unchanged
