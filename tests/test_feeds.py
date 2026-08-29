"""Tests for app.feeds that run offline against a committed feed fixture.

The fixture ``tests/fixtures/gtfs_numbered.pb`` is a real capture of the MTA
numbered-lines (1/2/3/4/5/6/7/S) GTFS-Realtime feed. Because the arrival times in
it are absolute and now in the past, the tests assert on structure (routes,
direction, stop ids) rather than on specific times.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import feeds

FIXTURE = Path(__file__).parent / "fixtures" / "gtfs_numbered.pb"
# Grand Central-42 St, northbound (4/5/6 platform).
KNOWN_STOP = "631N"


@pytest.fixture
def numbered_feed():
    return feeds.parse_feed(FIXTURE.read_bytes())


def test_parse_feed_returns_trips(numbered_feed):
    assert len(numbered_feed.trips) > 0


def test_extract_stop_updates_for_known_stop(numbered_feed):
    updates = feeds.extract_stop_updates(numbered_feed, stop_id=KNOWN_STOP)

    assert updates, f"expected stop-time updates for {KNOWN_STOP}"
    for u in updates:
        assert u.stop_id == KNOWN_STOP
        assert u.direction == "N"
        # Grand Central northbound is served by the 4/5/6.
        assert u.route_id in {"4", "5", "6"}
        assert isinstance(u.arrival, datetime)
        # Arrivals are timezone-aware in Eastern time.
        assert u.arrival.tzinfo is not None
        assert u.arrival.utcoffset() in {timedelta(hours=-4), timedelta(hours=-5)}
        assert u.trip_id


def test_route_filter_keeps_only_requested_route(numbered_feed):
    updates = feeds.extract_stop_updates(
        numbered_feed, routes=["6"], stop_id=KNOWN_STOP
    )

    assert updates
    assert {u.route_id for u in updates} == {"6"}


def test_feed_urls_for_routes_dedupes_to_needed_feeds():
    # 6 and Q live in different feed groups; L is its own group.
    urls = feeds.feed_urls_for_routes(["6", "Q", "L"])
    assert urls == {
        feeds.FEED_URLS["numbered"],
        feeds.FEED_URLS["nqrw"],
        feeds.FEED_URLS["l"],
    }
    # Two numbered-line routes collapse to a single feed URL.
    assert feeds.feed_urls_for_routes(["4", "5", "6"]) == {feeds.FEED_URLS["numbered"]}


def test_feed_urls_for_unknown_route_raises():
    with pytest.raises(ValueError):
        feeds.feed_urls_for_routes(["Q", "ZZ"])


def test_parse_feed_rejects_garbage_bytes():
    with pytest.raises(feeds.FeedError):
        feeds.parse_feed(b"this is not a protobuf")
