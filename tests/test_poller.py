"""Tests for app.poller -- the background feed poller + cache. Fully offline.

The loop is driven synchronously with ``asyncio.run``; ``fetch_arrivals`` and
``asyncio.sleep`` are monkeypatched so nothing hits the network and the loop is
broken deterministically after a fixed number of cycles (via a sentinel raised
from the patched sleep).
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import poller as poller_mod
from app.arrivals import ArrivalGroup
from app.feeds import FeedError
from app.poller import Poller, Snapshot
from app.stops import StationResolutionError

EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=EASTERN)


class _StopLoop(Exception):
    """Sentinel raised from the patched sleep to break the poll loop in tests."""


def _group(station="14 St-Union Sq") -> ArrivalGroup:
    return ArrivalGroup(
        station=station,
        line="Q",
        direction="N",
        direction_label="Northbound",
        color="#FCCC0A",
        arrivals=[],
    )


def _sleep_recorder(delays: list[float], stop_after: int):
    """Return a fake asyncio.sleep that records delays and stops after N cycles."""

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= stop_after:
            raise _StopLoop

    return fake_sleep


# --- staleness helpers -------------------------------------------------------


def test_age_and_is_stale():
    p = Poller(stale_after_seconds=90)
    fresh = Snapshot(groups=[], updated_at=NOW - timedelta(seconds=30))
    old = Snapshot(groups=[], updated_at=NOW - timedelta(seconds=120))

    assert p.age_seconds(fresh, now=NOW) == pytest.approx(30)
    assert p.is_stale(fresh, now=NOW) is False
    assert p.is_stale(old, now=NOW) is True


def test_is_stale_at_boundary_is_not_stale():
    p = Poller(stale_after_seconds=90)
    exactly = Snapshot(groups=[], updated_at=NOW - timedelta(seconds=90))
    # Strictly greater-than is stale; exactly at the threshold is not.
    assert p.is_stale(exactly, now=NOW) is False


# --- from_config -------------------------------------------------------------


def test_from_config_reads_intervals(monkeypatch):
    monkeypatch.setattr(
        poller_mod,
        "load_config",
        lambda: {"refresh_interval_seconds": 15, "stale_after_seconds": 45},
    )
    p = Poller.from_config()
    assert p.refresh_seconds == 15
    assert p.stale_after_seconds == 45


def test_from_config_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})
    p = Poller.from_config()
    assert p.refresh_seconds == poller_mod.DEFAULT_REFRESH_SECONDS
    assert p.stale_after_seconds == poller_mod.DEFAULT_STALE_AFTER_SECONDS


# --- poll loop ---------------------------------------------------------------


def test_run_caches_snapshot_and_sleeps_normal_interval(monkeypatch):
    groups = [_group()]
    monkeypatch.setattr(poller_mod, "fetch_arrivals", lambda *a, **k: groups)
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})
    delays: list[float] = []
    monkeypatch.setattr(asyncio, "sleep", _sleep_recorder(delays, stop_after=1))

    p = Poller(refresh_seconds=30)
    with pytest.raises(_StopLoop):
        asyncio.run(p._run())

    assert p.snapshot is not None
    assert p.snapshot.groups == groups
    assert delays == [30]  # success -> normal interval, no backoff


def test_run_keeps_last_snapshot_and_backs_off_on_error(monkeypatch):
    # First cycle succeeds and caches; then every cycle fails.
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_group()]
        raise FeedError("feed down")

    monkeypatch.setattr(poller_mod, "fetch_arrivals", flaky)
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})
    delays: list[float] = []
    monkeypatch.setattr(asyncio, "sleep", _sleep_recorder(delays, stop_after=4))

    p = Poller(refresh_seconds=30, max_backoff_seconds=200)
    with pytest.raises(_StopLoop):
        asyncio.run(p._run())

    # Success then three failures: normal interval, then exponential backoff
    # capped at max_backoff_seconds.
    assert delays == [30, 60, 120, 200]
    # The good snapshot from the first cycle is still served through the outage.
    assert p.snapshot is not None
    assert p.snapshot.groups[0].station == "14 St-Union Sq"


def test_run_recovers_interval_after_a_failure(monkeypatch):
    # fail, fail, succeed -> backoff grows then resets to the normal interval.
    seq = [FeedError("x"), FeedError("x"), [_group()]]

    def scripted(*a, **k):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(poller_mod, "fetch_arrivals", scripted)
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})
    delays: list[float] = []
    monkeypatch.setattr(asyncio, "sleep", _sleep_recorder(delays, stop_after=3))

    p = Poller(refresh_seconds=30)
    with pytest.raises(_StopLoop):
        asyncio.run(p._run())

    assert delays == [60, 120, 30]  # backoff, backoff, reset on success


def test_run_survives_unexpected_exception(monkeypatch):
    # An error type the loop doesn't anticipate must not end polling: the loop
    # catches broadly, keeps serving, and backs off.
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_group()]
        raise RuntimeError("unexpected deep failure")

    monkeypatch.setattr(poller_mod, "fetch_arrivals", flaky)
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})
    delays: list[float] = []
    monkeypatch.setattr(asyncio, "sleep", _sleep_recorder(delays, stop_after=3))

    p = Poller(refresh_seconds=30)
    with pytest.raises(_StopLoop):
        asyncio.run(p._run())

    # Success then two unexpected failures -> loop keeps going and backs off.
    assert delays == [30, 60, 120]
    assert p.snapshot is not None  # last good board still served through the outage


def test_clamps_bad_config_intervals():
    # Zero/negative can't busy-loop or crash sleep(); non-numeric fails fast.
    p = Poller(refresh_seconds=0, stale_after_seconds=-5, max_backoff_seconds=1)
    assert p.refresh_seconds == poller_mod.MIN_REFRESH_SECONDS
    assert p.stale_after_seconds == 0.0
    # Backoff cap is never below the refresh interval.
    assert p.max_backoff_seconds == poller_mod.MIN_REFRESH_SECONDS
    with pytest.raises(ValueError):
        Poller(refresh_seconds="not-a-number")


def test_run_backs_off_on_station_and_value_errors(monkeypatch):
    # Config/route errors are caught like feed errors -- the loop keeps going.
    seq = [StationResolutionError("bad station"), ValueError("bad route")]

    def scripted(*a, **k):
        raise seq.pop(0)

    monkeypatch.setattr(poller_mod, "fetch_arrivals", scripted)
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})
    delays: list[float] = []
    monkeypatch.setattr(asyncio, "sleep", _sleep_recorder(delays, stop_after=2))

    p = Poller(refresh_seconds=30)
    with pytest.raises(_StopLoop):
        asyncio.run(p._run())

    assert delays == [60, 120]
    assert p.snapshot is None  # never a successful poll


# --- start/stop lifecycle ----------------------------------------------------


def test_start_and_stop_are_clean(monkeypatch):
    monkeypatch.setattr(poller_mod, "fetch_arrivals", lambda *a, **k: [_group()])
    monkeypatch.setattr(poller_mod, "load_config", lambda: {})

    async def scenario():
        p = Poller(refresh_seconds=0.01)
        p.start()
        p.start()  # idempotent: still one task
        assert p._task is not None
        # Let the loop run at least one cycle so the cache fills.
        for _ in range(50):
            if p.snapshot is not None:
                break
            await asyncio.sleep(0.01)
        await p.stop()
        assert p._task is None
        return p.snapshot

    snapshot = asyncio.run(scenario())
    assert snapshot is not None
