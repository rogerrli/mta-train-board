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


# "DeKalb Av" appears twice (BMT B/Q/R and, separately, the L) so lines must
# disambiguate; "Hoyt St" is a distinct single station.
SMALL = _csv(
    "R30,DeKalb Av,B Q R",
    "L16,DeKalb Av,L",
    "233,Hoyt St,2 3",
)


@pytest.fixture
def vendored() -> StopIndex:
    return StopIndex.from_csv()


# --- successful resolution (vendored data) -----------------------------------


def test_resolve_maps_name_and_lines_to_parent_stop(vendored):
    resolved = vendored.resolve("Hoyt-Schermerhorn Sts", ["A", "C"], ["N"])
    assert resolved.name == "Hoyt-Schermerhorn Sts"
    assert resolved.line_stops == {"A": "A42", "C": "A42"}
    assert resolved.lines == ("A", "C")
    assert resolved.stop_ids() == ["A42N", "A42N"]


def test_resolve_filters_unwanted_lines_at_shared_platform(vendored):
    # Jay St-MetroTech serves A/C/F on stop A41; asking only for F still resolves
    # to A41 and never pulls in A/C.
    resolved = vendored.resolve("Jay St-MetroTech", ["F"], ["N", "S"])
    assert resolved.line_stops == {"F": "A41"}
    assert set(resolved.stop_ids()) == {"A41N", "A41S"}


def test_resolve_disambiguates_shared_name_by_line(vendored):
    # "DeKalb Av" exists on both the BMT (R30) and the L (L16); B/Q/R picks R30.
    resolved = vendored.resolve("DeKalb Av", ["Q", "R"], ["N", "S"])
    assert set(resolved.line_stops.values()) == {"R30"}


def test_resolve_is_case_and_whitespace_insensitive(vendored):
    resolved = vendored.resolve("  hoyt   st ", ["2"], ["N"])
    assert resolved.name == "Hoyt St"  # canonical spelling returned
    assert resolved.line_stops == {"2": "233"}


def test_watches_enumerates_line_x_direction():
    index = StopIndex.from_text(SMALL)
    resolved = index.resolve("DeKalb Av", ["Q", "R"], ["N", "S"])
    assert set(resolved.watches()) == {
        ("Q", "N", "R30N"),
        ("Q", "S", "R30S"),
        ("R", "N", "R30N"),
        ("R", "S", "R30S"),
    }


# --- error cases -------------------------------------------------------------


def test_unknown_name_raises_with_suggestion():
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Dekald Ave", ["Q"], ["N"])
    assert exc.value.stale_data_plausible is True
    assert "DeKalb Av" in str(exc.value)  # close-match suggestion


def test_requested_line_not_served_raises():
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Hoyt St", ["A"], ["N"])
    assert exc.value.stale_data_plausible is True
    assert "does not serve line 'A'" in str(exc.value)
    assert "['2', '3']" in str(exc.value)  # lists what it does serve


def test_bad_direction_raises_and_is_not_stale_data():
    index = StopIndex.from_text(SMALL)
    with pytest.raises(StationResolutionError) as exc:
        index.resolve("Hoyt St", ["2"], ["E"])
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
            {"name": "DeKalb Av", "lines": ["Q", "R"], "directions": ["N", "S"]},
            {"name": "Hoyt St", "lines": ["2", "3"], "directions": ["N"]},
        ]
    }
    resolved = stops.resolve_stations(config, index=index, allow_refresh=False)
    assert [r.name for r in resolved] == ["DeKalb Av", "Hoyt St"]


def test_resolve_stations_requires_at_least_one_station():
    with pytest.raises(StationResolutionError):
        stops.resolve_stations({"stations": []}, index=StopIndex.from_text(SMALL))


# --- auto-redownload fallback (network mocked) -------------------------------


def test_auto_redownload_retries_and_succeeds(monkeypatch):
    # Start from stale data that lacks the station...
    stale = StopIndex.from_text(_csv("233,Hoyt St,2 3"))
    # ...and have the "download" return fresh data that includes it.
    fresh_csv = _csv("233,Hoyt St,2 3", "R30,DeKalb Av,B Q R")
    calls = {"n": 0}

    def fake_download(*a, **k):
        calls["n"] += 1
        return fresh_csv

    monkeypatch.setattr(stops, "download_stations_csv", fake_download)

    config = {"stations": [{"name": "DeKalb Av", "lines": ["Q"], "directions": ["N"]}]}
    resolved = stops.resolve_stations(config, index=stale, allow_refresh=True)

    assert calls["n"] == 1  # downloaded exactly once
    assert resolved[0].line_stops == {"Q": "R30"}


def test_auto_redownload_failure_reports_attempt(monkeypatch):
    stale = StopIndex.from_text(_csv("233,Hoyt St,2 3"))

    def boom(*a, **k):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(stops, "download_stations_csv", boom)

    config = {"stations": [{"name": "DeKalb Av", "lines": ["Q"], "directions": ["N"]}]}
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
    config = {"stations": [{"name": "Hoyt St", "lines": ["2"], "directions": ["E"]}]}
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
