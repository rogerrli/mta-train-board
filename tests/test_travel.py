"""Offline tests for the travel-time model (#26).

Runtime logic (:meth:`TravelTimeModel.travel_time`) is tested against a small
hand-built schedule; the builder (:func:`build_schedule`) against a tiny
in-memory GTFS zip. A light smoke test loads the vendored artifact. No network.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.travel import VENDORED_TRAVEL_TIMES, TravelTimeModel, build_schedule

EASTERN = ZoneInfo("America/New_York")

# Parent stop IDs X1/X2/X3; suffixed with direction "N" in the schedule below.
# Weekday: two runs (dep X1 at 08:00 and 09:00); Sunday: one slower run.
_MODEL = TravelTimeModel.from_dict(
    {
        "feed_version": "test",
        "generated": "2026-08-30",
        "routes": ["N"],
        "schedule": {
            "N": {
                "N": {
                    "weekday": [
                        {"X1N": 28800, "X2N": 29400, "X3N": 30000},  # 08:00, +10m, +20m
                        {"X1N": 32400, "X2N": 33060, "X3N": 33660},  # 09:00, +11m, +21m
                    ],
                    "sunday": [
                        {"X1N": 28800, "X3N": 31200},  # 08:00 -> +40m
                    ],
                }
            }
        },
    }
)

# Tue 2026-09-01 = weekday; Sun 2026-08-30 = sunday; Sat 2026-08-29 = saturday.
_TUE_0805 = datetime(2026, 9, 1, 8, 5, tzinfo=EASTERN)
_TUE_0855 = datetime(2026, 9, 1, 8, 55, tzinfo=EASTERN)
_SUN_0800 = datetime(2026, 8, 30, 8, 0, tzinfo=EASTERN)
_SAT_0800 = datetime(2026, 8, 29, 8, 0, tzinfo=EASTERN)


def test_picks_nearest_departure_and_differences_within_that_trip() -> None:
    # 08:05 is nearest the 08:00 run -> 20 min ride.
    assert _MODEL.travel_time("X1", "X3", "N", "N", _TUE_0805) == timedelta(minutes=20)
    # 08:55 is nearest the 09:00 run -> 21 min ride.
    assert _MODEL.travel_time("X1", "X3", "N", "N", _TUE_0855) == timedelta(minutes=21)


def test_varies_by_service_day() -> None:
    assert _MODEL.travel_time("X1", "X3", "N", "N", _TUE_0805) == timedelta(minutes=20)
    assert _MODEL.travel_time("X1", "X3", "N", "N", _SUN_0800) == timedelta(minutes=40)


def test_intermediate_stop_pair() -> None:
    assert _MODEL.travel_time("X1", "X2", "N", "N", _TUE_0805) == timedelta(minutes=10)


def test_no_estimate_cases_return_none() -> None:
    # No service that day (no saturday trips at all).
    assert _MODEL.travel_time("X1", "X3", "N", "N", _SAT_0800) is None
    # Reversed order (destination before origin on the run).
    assert _MODEL.travel_time("X3", "X1", "N", "N", _TUE_0805) is None
    # Same stop.
    assert _MODEL.travel_time("X1", "X1", "N", "N", _TUE_0805) is None
    # Unknown route / stop / direction.
    assert _MODEL.travel_time("X1", "X3", "Z", "N", _TUE_0805) is None
    assert _MODEL.travel_time("X1", "Q9", "N", "N", _TUE_0805) is None
    assert _MODEL.travel_time("X1", "X3", "N", "S", _TUE_0805) is None
    # Invalid direction letter.
    assert _MODEL.travel_time("X1", "X3", "N", "E", _TUE_0805) is None


def test_normalizes_tzaware_at_time_across_zones() -> None:
    # Sun 23:00 ET == Mon 03:00 UTC. The ride must use the Eastern service day
    # (sunday -> 40 min), not the UTC weekday. Both forms agree once normalized.
    et = datetime(2026, 8, 30, 23, 0, tzinfo=EASTERN)
    utc = et.astimezone(UTC)
    assert _MODEL.travel_time("X1", "X3", "N", "N", utc) == timedelta(minutes=40)
    assert _MODEL.travel_time("X1", "X3", "N", "N", et) == timedelta(minutes=40)


def test_matches_after_midnight_trip_stored_as_24h() -> None:
    # A ~00:30 train is encoded on the prior service day as 24:30 (88200s). An
    # early-morning query must pick it, not a far same-day train.
    model = TravelTimeModel.from_dict(
        {
            "feed_version": "test",
            "generated": "2026-08-30",
            "routes": ["N"],
            "schedule": {
                "N": {
                    "N": {
                        "weekday": [
                            {"X1N": 88200, "X3N": 88800},  # 24:30 -> +10m
                            {"X1N": 0, "X3N": 1800},  # 00:00 -> +30m
                        ]
                    }
                }
            },
        }
    )
    at = datetime(2026, 9, 1, 0, 35, tzinfo=EASTERN)  # Tue 00:35
    assert model.travel_time("X1", "X3", "N", "N", at) == timedelta(minutes=10)


def _gtfs_zip(files: dict[str, str]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_build_schedule_trims_routes_and_drops_holiday_supplements() -> None:
    calendar = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "Weekday,1,1,1,1,1,0,0,20260526,20261031\n"
        "Weekday-H,1,1,1,1,1,0,0,20260907,20260907\n"  # holiday supplement, fewer trips
        "Saturday,0,0,0,0,0,1,0,20260526,20261031\n"
    )
    # Two Weekday trips vs one Weekday-H trip -> Weekday wins as representative.
    # Route "N" is watched; route "1" is not and must be dropped.
    trips = (
        "route_id,trip_id,service_id,trip_headsign,direction_id,shape_id\n"
        "N,tN1,Weekday,Astoria,0,s\n"
        "N,tN2,Weekday,Astoria,0,s\n"
        "N,tNH,Weekday-H,Astoria,0,s\n"
        "N,tSat,Saturday,Astoria,0,s\n"
        "1,t1,Weekday,South Ferry,1,s\n"
    )
    stop_times = (
        "trip_id,stop_id,arrival_time,departure_time,stop_sequence\n"
        "tN1,X1N,08:00:00,08:00:00,1\n"
        "tN1,X2N,08:12:00,08:12:00,2\n"
        "tN2,X1N,09:00:00,09:00:00,1\n"
        "tN2,X2N,09:13:00,09:13:00,2\n"
        "tNH,X1N,10:00:00,10:00:00,1\n"
        "tNH,X2N,10:30:00,10:30:00,2\n"
        "tSat,X1N,08:00:00,08:00:00,1\n"
        "tSat,X2N,08:15:00,08:15:00,2\n"
        "t1,Y1S,08:00:00,08:00:00,1\n"
        "t1,Y2S,08:20:00,08:20:00,2\n"
    )
    feed_info = "feed_version,feed_publisher_name\nv-test,MTA\n"
    zf = _gtfs_zip(
        {
            "calendar.txt": calendar,
            "trips.txt": trips,
            "stop_times.txt": stop_times,
            "feed_info.txt": feed_info,
        }
    )

    artifact = build_schedule(zf, {"N"})

    assert artifact["feed_version"] == "v-test"
    assert artifact["routes"] == ["N"]
    schedule = artifact["schedule"]
    assert set(schedule) == {"N"}  # route "1" dropped
    weekday = schedule["N"]["N"]["weekday"]
    assert len(weekday) == 2  # both Weekday trips kept, Weekday-H supplement dropped
    assert schedule["N"]["N"]["saturday"][0] == {"X1N": 28800, "X2N": 29700}

    # The built artifact drives the model correctly (12 min on the 08:00 run).
    model = TravelTimeModel.from_dict(artifact)
    at = datetime(2026, 9, 1, 8, 1, tzinfo=EASTERN)
    assert model.travel_time("X1", "X2", "N", "N", at) == timedelta(minutes=12)


def test_vendored_artifact_loads_and_answers() -> None:
    model = TravelTimeModel.load(VENDORED_TRAVEL_TIMES)
    assert model.routes  # non-empty
    assert model.feed_version
    # 14 St-Union Sq (R20) -> Times Sq-42 St (R16) on the Q, northbound: a real ride.
    at = datetime(2026, 9, 1, 8, 30, tzinfo=EASTERN)
    ride = model.travel_time("R20", "R16", "Q", "N", at)
    assert ride is not None and timedelta(minutes=5) <= ride <= timedelta(minutes=40)
    # A pair that shares no trip returns an explicit "no estimate".
    assert model.travel_time("R20", "127", "R", "N", at) is None
