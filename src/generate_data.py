"""Generate clearly labelled synthetic GPS pings for the fictional Quest."""
from __future__ import annotations
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gps_pings_synthetic.csv"
RNG = random.Random(20261104)
UTC = timezone.utc
LAT0, LON0 = 25.0, 55.0
KM_PER_LAT_DEG = 111.0
KM_PER_LON_DEG = 111.0 * math.cos(math.radians(LAT0))
ZONE_START_KM, ZONE_END_KM = 5.0, 25.0

def coords(s_km: float, offset_m: float = 0.0):
    lat = LAT0 + (offset_m / 1000.0) / KM_PER_LAT_DEG
    lon = LON0 + s_km / KM_PER_LON_DEG
    return round(lat, 8), round(lon, 8)

def spread_sample(items, count):
    if len(items) < count:
        raise ValueError(f"Need {count} fault candidates, found {len(items)}")
    return [items[i * len(items) // count] for i in range(count)]

def main():
    rows = []
    seq = 0
    # Three sessions on distinct local dates. Each starts at 23:45 UTC+9 local time
    # (14:45 UTC), so the 00:00 local reporting boundary occurs within the session.
    session_dates = [datetime(2026, 10, 20, 14, 45, tzinfo=UTC),
                     datetime(2026, 10, 22, 14, 45, tzinfo=UTC),
                     datetime(2026, 10, 24, 14, 45, tzinfo=UTC)]
    for driver_num in range(1, 5):
        driver = f"SYN-DRIVER-{driver_num:02d}"
        for session_idx, start in enumerate(session_dates):
            # 200 pings at 10-second intervals; 72 km/h = 0.2 km per interval.
            for i in range(200):
                seq += 1
                ts = start + timedelta(seconds=10*i)
                s = 0.2*i
                offset = RNG.uniform(-8, 8)
                lat, lon = coords(s, offset)
                rows.append({
                    "ping_id": f"P{seq:05d}", "driver_id": driver,
                    "timestamp_utc": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat, "longitude": lon,
                    "campaign_zone": "inside" if ZONE_START_KM <= s <= ZONE_END_KM else "outside",
                    "synthetic_truth_s_km": round(s, 4),
                    "synthetic_truth_offset_m": round(offset, 3),
                    "injected_fault": "none",
                })
    # Inject 120 exact duplicate rows, 48 off-road pings, 32 speed spikes.
    originals = list(rows)
    duplicate_candidates = spread_sample(
        [r for r in originals if 6 < r["synthetic_truth_s_km"] < 24], 120)
    duplicate_keys = {(r["driver_id"], r["timestamp_utc"]) for r in duplicate_candidates}
    for r in duplicate_candidates:
        dup = dict(r)
        seq += 1
        dup["ping_id"] = f"P{seq:05d}"
        dup["injected_fault"] = "duplicate"
        rows.append(dup)
    offroad_pool = [r for r in originals
                    if 7 < r["synthetic_truth_s_km"] < 23
                    and (r["driver_id"], r["timestamp_utc"]) not in duplicate_keys]
    offroad_candidates = spread_sample(offroad_pool, 48)
    for r in offroad_candidates:
        r["synthetic_truth_offset_m"] = 175.0
        r["latitude"], r["longitude"] = coords(r["synthetic_truth_s_km"], 175.0)
        r["injected_fault"] = "off_road_gt_100m"
    # Create implausible jumps by moving selected pings far along the road.
    offroad_ids = {r["ping_id"] for r in offroad_candidates}
    speed_pool = [r for r in originals
                  if 8 < r["synthetic_truth_s_km"] < 22
                  and r["ping_id"] not in offroad_ids
                  and (r["driver_id"], r["timestamp_utc"]) not in duplicate_keys]
    speed_candidates = spread_sample(speed_pool, 32)
    for r in speed_candidates:
        s_bad = min(39.0, r["synthetic_truth_s_km"] + 2.0)
        r["latitude"], r["longitude"] = coords(s_bad, r["synthetic_truth_offset_m"])
        r["injected_fault"] = "speed_spike_gt_150kmh"
    # Reorder arrival sequence deterministically; event timestamps remain unchanged.
    # Keep some original order while swapping selected windows to simulate late pings.
    for start_i in range(0, len(rows), 120):
        if (start_i // 120) % 2 == 1:
            rows[start_i:start_i+120] = reversed(rows[start_i:start_i+120])
    # Duplicate timestamp records are exact coordinate copies; shuffle introduces out-of-order arrivals.
    fieldnames = ["ping_id","driver_id","timestamp_utc","latitude","longitude","campaign_zone",
                  "synthetic_truth_s_km","synthetic_truth_offset_m","injected_fault"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} synthetic pings to {OUT}")

if __name__ == "__main__":
    main() 
