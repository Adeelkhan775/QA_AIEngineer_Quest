"""Compare intentionally flawed baseline with corrected synthetic reference."""
from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "gps_pings_synthetic.csv"
REPORTS = ROOT / "reports"
UTC = timezone.utc
LOCAL_OFFSET = timedelta(hours=9)
ZONE_START_KM, ZONE_END_KM = 5.0, 25.0
MAX_OFFSET_M, MAX_SPEED_KMH, MAX_GAP_SECONDS = 100.0, 150.0, 30.0
LAT0 = 25.0
KM_PER_LON_DEG = 111.0 * math.cos(math.radians(LAT0))

def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

def along_km(row) -> float:
    return (float(row["longitude"]) - 55.0) * KM_PER_LON_DEG

def haversine_km(a, b) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(float(a["latitude"])), math.radians(float(b["latitude"]))
    dlat = lat2 - lat1
    dlon = math.radians(float(b["longitude"]) - float(a["longitude"]))
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * radius * math.asin(min(1.0, math.sqrt(h)))

def load_rows():
    with DATA.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_ts"] = parse_ts(r["timestamp_utc"])
        r["_s"] = along_km(r)
        r["_utc_day"] = r["_ts"].date().isoformat()
        r["_local_day"] = (r["_ts"] + LOCAL_OFFSET).date().isoformat()
        r["_offset_m"] = abs(float(r["latitude"]) - LAT0) * 111_000.0
    return rows

def legacy_distance_by_driver_day(rows):
    """Intentionally wrong: arrival order, no dedupe/noise rejection."""
    totals = defaultdict(float)
    previous = {}
    for r in rows:
        d = r["driver_id"]
        if d in previous:
            p = previous[d]
            if ZONE_START_KM <= p["_s"] <= ZONE_END_KM and ZONE_START_KM <= r["_s"] <= ZONE_END_KM:
                # Keep the reporting calendar comparable to the corrected calculation.
                totals[(d, r["_local_day"])] += haversine_km(p, r)
        previous[d] = r
    return totals

def corrected_distance_by_driver_day(rows):
    """Corrected reference for this synthetic straight-road scenario."""
    grouped = defaultdict(list)
    seen = set()
    anomalies = []
    # Detect arrival-order issues and deduplicate by normalized UTC timestamp.
    unique = []
    previous_arrival = {}
    for r in rows:
        driver = r["driver_id"]
        timestamp = r["_ts"]
        if driver in previous_arrival and timestamp < previous_arrival[driver]:
            anomalies.append((r["ping_id"], "out_of_order_arrival"))
        previous_arrival[driver] = timestamp
        key = (driver, timestamp)
        if key in seen:
            anomalies.append((r["ping_id"], "duplicate_driver_timestamp"))
            continue
        seen.add(key)
        unique.append(r)
    by_driver = defaultdict(list)
    for r in unique:
        by_driver[r["driver_id"]].append(r)
    accepted_by_driver = {}
    # First flag off-road points. Then speed-check chronological adjacent points.
    for driver, points in by_driver.items():
        points.sort(key=lambda x: x["_ts"])
        accepted = []
        for r in points:
            if r["_offset_m"] > MAX_OFFSET_M:
                anomalies.append((r["ping_id"], f"off_road_offset_m={r['_offset_m']:.1f}"))
                continue
            if accepted:
                prev = accepted[-1]
                seconds = (r["_ts"] - prev["_ts"]).total_seconds()
                distance = abs(r["_s"] - prev["_s"])
                speed = distance / (seconds / 3600) if seconds > 0 else float("inf")
                if seconds <= 0:
                    anomalies.append((r["ping_id"], "non_positive_time_delta"))
                    continue
                if speed > MAX_SPEED_KMH:
                    anomalies.append((r["ping_id"], f"implied_speed_kmh={speed:.1f}"))
                    continue
            accepted.append(r)
        accepted_by_driver[driver] = accepted
    for driver, points in accepted_by_driver.items():
        for prev, curr in zip(points, points[1:]):
            seconds = (curr["_ts"] - prev["_ts"]).total_seconds()
            if seconds > MAX_GAP_SECONDS:
                anomalies.append((curr["ping_id"], f"gap_seconds={seconds:.0f}"))
                continue
            s1, s2 = prev["_s"], curr["_s"]
            # Count only if both endpoints are inside the campaign zone.
            if ZONE_START_KM <= s1 <= ZONE_END_KM and ZONE_START_KM <= s2 <= ZONE_END_KM:
                # Use along-road projection rather than noisy GPS chord distance.
                km = abs(s2 - s1)
                # Explicit accounting convention: attribute segment to ending ping's UTC+9 day.
                day = curr["_local_day"]
                grouped[(driver, day)].append(km)
    totals = defaultdict(float)
    for key, distances in grouped.items():
        totals[key] = sum(distances)
    return totals, anomalies, accepted_by_driver

def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def main():
    REPORTS.mkdir(exist_ok=True)
    rows = load_rows()
    legacy = legacy_distance_by_driver_day(rows)
    corrected, anomalies, accepted = corrected_distance_by_driver_day(rows)
    keys = sorted(set(legacy) | set(corrected))
    comparison = []
    for driver, day in keys:
        old = legacy.get((driver, day), 0.0)
        new = corrected.get((driver, day), 0.0)
        comparison.append({"driver_id": driver, "report_day": day,
                           "legacy_distance_km": round(old, 4),
                           "corrected_distance_km": round(new, 4),
                           "difference_km_corrected_minus_legacy": round(new-old, 4)})
    write_csv(REPORTS/"distance_comparison.csv",
              ["driver_id","report_day","legacy_distance_km","corrected_distance_km","difference_km_corrected_minus_legacy"],
              comparison)
    anomaly_rows = [{"ping_id": pid, "reason": reason} for pid, reason in sorted(set(anomalies))]
    write_csv(REPORTS/"anomaly_report.csv", ["ping_id","reason"], anomaly_rows)
    anomaly_reason_counts = defaultdict(int)
    for _, reason in anomalies:
        anomaly_reason_counts[reason.split("=", 1)[0]] += 1
    fault_counts = defaultdict(int)
    for r in rows:
        fault_counts[r["injected_fault"]] += 1
    summary = {
        "label": "SYNTHETIC TEST DATA — NOT LIVE PRODUCT DATA",
        "input_ping_rows": len(rows),
        "unique_driver_timestamp_keys": len(set((r["driver_id"], r["timestamp_utc"]) for r in rows)),
        "drivers": len(set(r["driver_id"] for r in rows)),
        "injected_fault_label_counts": dict(sorted(fault_counts.items())),
        "anomaly_rows_reported": len(anomaly_rows),
        "anomaly_reason_counts": dict(sorted(anomaly_reason_counts.items())),
        "comparison_rows": len(comparison),
        "legacy_total_km": round(sum(legacy.values()), 4),
        "corrected_total_km": round(sum(corrected.values()), 4),
        "assumptions": {"timezone": "UTC+09:00 fixed offset", "zone_km": [5.0,25.0],
                        "max_lateral_offset_m": 100, "max_speed_kmh": 150, "max_gap_seconds": 30,
                        "segment_day_attribution": "UTC+9 date of ending ping"}
    }
    (REPORTS/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
