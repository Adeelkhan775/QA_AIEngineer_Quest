"""Generate clearly labelled synthetic GPS pings for the fictional Quest."""
from __future__ import annotations
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "gps_pings_synthetic.csv"
RANDOM_GENERATOR = random.Random(20261104)
UTC_TIMEZONE = timezone.utc
REFERENCE_LATITUDE_DEGREES = 25.0
REFERENCE_LONGITUDE_DEGREES = 55.0
KM_PER_LATITUDE_DEGREE = 111.0
KM_PER_LONGITUDE_DEGREE = 111.0 * math.cos(
    math.radians(REFERENCE_LATITUDE_DEGREES)
)
ZONE_START_KM, ZONE_END_KM = 5.0, 25.0

def coords(along_road_distance_km: float, lateral_offset_meters: float = 0.0):
    latitude = (
        REFERENCE_LATITUDE_DEGREES
        + (lateral_offset_meters / 1000.0) / KM_PER_LATITUDE_DEGREE
    )
    longitude = (
        REFERENCE_LONGITUDE_DEGREES
        + along_road_distance_km / KM_PER_LONGITUDE_DEGREE
    )
    return round(latitude, 8), round(longitude, 8)

def spread_sample(candidates, sample_size):
    if len(candidates) < sample_size:
        raise ValueError(
            f"Need {sample_size} fault candidates, found {len(candidates)}"
        )
    return [
        candidates[sample_index * len(candidates) // sample_size]
        for sample_index in range(sample_size)
    ]

def main():
    pings = []
    ping_number = 0
    # Three sessions on distinct local dates. Each starts at 23:45 UTC+9 local time
    # (14:45 UTC), so the 00:00 local reporting boundary occurs within the session.
    session_start_timestamps = [
        datetime(2026, 10, 20, 14, 45, tzinfo=UTC_TIMEZONE),
        datetime(2026, 10, 22, 14, 45, tzinfo=UTC_TIMEZONE),
        datetime(2026, 10, 24, 14, 45, tzinfo=UTC_TIMEZONE),
    ]
    for driver_number in range(1, 5):
        driver_id = f"SYN-DRIVER-{driver_number:02d}"
        for session_start in session_start_timestamps:
            # 200 pings at 10-second intervals; 72 km/h = 0.2 km per interval.
            for ping_index in range(200):
                ping_number += 1
                timestamp = session_start + timedelta(seconds=10 * ping_index)
                along_road_distance_km = 0.2 * ping_index
                lateral_offset_meters = RANDOM_GENERATOR.uniform(-8, 8)
                latitude, longitude = coords(
                    along_road_distance_km, lateral_offset_meters
                )
                pings.append({
                    "ping_id": f"P{ping_number:05d}",
                    "driver_id": driver_id,
                    "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                    "latitude": latitude,
                    "longitude": longitude,
                    "campaign_zone": (
                        "inside"
                        if ZONE_START_KM <= along_road_distance_km <= ZONE_END_KM
                        else "outside"
                    ),
                    "synthetic_truth_s_km": round(along_road_distance_km, 4),
                    "synthetic_truth_offset_m": round(lateral_offset_meters, 3),
                    "injected_fault": "none",
                })
    # Inject 120 exact duplicate rows, 48 off-road pings, 32 speed spikes.
    original_pings = list(pings)
    duplicate_candidates = spread_sample(
        [
            ping
            for ping in original_pings
            if 6 < ping["synthetic_truth_s_km"] < 24
        ],
        120,
    )
    duplicate_driver_timestamps = {
        (ping["driver_id"], ping["timestamp_utc"])
        for ping in duplicate_candidates
    }
    for original_ping in duplicate_candidates:
        duplicate_ping = dict(original_ping)
        ping_number += 1
        duplicate_ping["ping_id"] = f"P{ping_number:05d}"
        duplicate_ping["injected_fault"] = "duplicate"
        pings.append(duplicate_ping)
    off_road_candidates_pool = [
        ping
        for ping in original_pings
        if 7 < ping["synthetic_truth_s_km"] < 23
        and (ping["driver_id"], ping["timestamp_utc"])
        not in duplicate_driver_timestamps
    ]
    off_road_candidates = spread_sample(off_road_candidates_pool, 48)
    for ping in off_road_candidates:
        ping["synthetic_truth_offset_m"] = 175.0
        ping["latitude"], ping["longitude"] = coords(
            ping["synthetic_truth_s_km"], 175.0
        )
        ping["injected_fault"] = "off_road_gt_100m"
    # Create implausible jumps by moving selected pings far along the road.
    off_road_ping_ids = {
        ping["ping_id"] for ping in off_road_candidates
    }
    speed_spike_candidates_pool = [
        ping
        for ping in original_pings
        if 8 < ping["synthetic_truth_s_km"] < 22
        and ping["ping_id"] not in off_road_ping_ids
        and (ping["driver_id"], ping["timestamp_utc"])
        not in duplicate_driver_timestamps
    ]
    speed_spike_candidates = spread_sample(speed_spike_candidates_pool, 32)
    for ping in speed_spike_candidates:
        speed_spike_distance_km = min(
            39.0, ping["synthetic_truth_s_km"] + 2.0
        )
        ping["latitude"], ping["longitude"] = coords(
            speed_spike_distance_km, ping["synthetic_truth_offset_m"]
        )
        ping["injected_fault"] = "speed_spike_gt_150kmh"
    # Reorder arrival sequence deterministically; event timestamps remain unchanged.
    # Keep some original order while swapping selected windows to simulate late pings.
    for window_start_index in range(0, len(pings), 120):
        if (window_start_index // 120) % 2 == 1:
            pings[window_start_index:window_start_index + 120] = reversed(
                pings[window_start_index:window_start_index + 120]
            )
    # Duplicate timestamp records are exact coordinate copies; shuffle introduces out-of-order arrivals.
    fieldnames = ["ping_id","driver_id","timestamp_utc","latitude","longitude","campaign_zone",
                  "synthetic_truth_s_km","synthetic_truth_offset_m","injected_fault"]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as output_file:
        csv_writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(pings)
    print(f"Wrote {len(pings)} synthetic pings to {OUTPUT_PATH}")

if __name__ == "__main__":
    main() 
