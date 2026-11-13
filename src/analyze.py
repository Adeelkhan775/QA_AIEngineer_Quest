"""Compare intentionally flawed baseline with corrected synthetic reference."""
from __future__ import annotations
import csv, json, math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "gps_pings_synthetic.csv"
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"
UTC_TIMEZONE = timezone.utc
LOCAL_TIME_OFFSET = timedelta(hours=9)
ZONE_START_KM, ZONE_END_KM = 5.0, 25.0
MAX_LATERAL_OFFSET_METERS = 100.0
MAX_SPEED_KILOMETERS_PER_HOUR = 150.0
MAX_GAP_SECONDS = 30.0
REFERENCE_LATITUDE_DEGREES = 25.0
KM_PER_LONGITUDE_DEGREE = 111.0 * math.cos(math.radians(REFERENCE_LATITUDE_DEGREES))

def parse_timestamp(timestamp_text: str) -> datetime:
    return datetime.fromisoformat(timestamp_text.replace("Z", "+00:00")).astimezone(UTC_TIMEZONE)

def calculate_along_road_km(ping) -> float:
    return (float(ping["longitude"]) - 55.0) * KM_PER_LONGITUDE_DEGREE

def haversine_km(first_ping, second_ping) -> float:
    radius = 6371.0088
    first_latitude = math.radians(float(first_ping["latitude"]))
    second_latitude = math.radians(float(second_ping["latitude"]))
    latitude_difference = second_latitude - first_latitude
    longitude_difference = math.radians(
        float(second_ping["longitude"]) - float(first_ping["longitude"])
    )
    haversine_value = (
        math.sin(latitude_difference / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(longitude_difference / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(haversine_value)))

def load_rows():
    with DATA_PATH.open(newline="", encoding="utf-8") as input_file:
        pings = list(csv.DictReader(input_file))
    for ping in pings:
        ping["_timestamp"] = parse_timestamp(ping["timestamp_utc"])
        ping["_along_road_km"] = calculate_along_road_km(ping)
        ping["_utc_calendar_date"] = ping["_timestamp"].date().isoformat()
        ping["_local_calendar_date"] = (
            ping["_timestamp"] + LOCAL_TIME_OFFSET
        ).date().isoformat()
        ping["_lateral_offset_meters"] = (
            abs(float(ping["latitude"]) - REFERENCE_LATITUDE_DEGREES) * 111_000.0
        )
    return pings

def legacy_distance_by_driver_day(pings):
    """Intentionally wrong: arrival order, no dedupe/noise rejection."""
    distance_totals = defaultdict(float)
    previous_ping_by_driver = {}
    for ping in pings:
        driver_id = ping["driver_id"]
        if driver_id in previous_ping_by_driver:
            previous_ping = previous_ping_by_driver[driver_id]
            if (
                ZONE_START_KM <= previous_ping["_along_road_km"] <= ZONE_END_KM
                and ZONE_START_KM <= ping["_along_road_km"] <= ZONE_END_KM
            ):
                # Keep the reporting calendar comparable to the corrected calculation.
                distance_totals[(driver_id, ping["_local_calendar_date"])] += haversine_km(
                    previous_ping, ping
                )
        previous_ping_by_driver[driver_id] = ping
    return distance_totals

def corrected_distance_by_driver_day(pings):
    """Corrected reference for this synthetic straight-road scenario."""
    segment_distances_by_driver_day = defaultdict(list)
    seen_driver_timestamps = set()
    anomalies = []
    # Detect arrival-order issues and deduplicate by normalized UTC timestamp.
    unique_pings = []
    previous_arrival_timestamp_by_driver = {}
    for ping in pings:
        driver_id = ping["driver_id"]
        timestamp = ping["_timestamp"]
        if (
            driver_id in previous_arrival_timestamp_by_driver
            and timestamp < previous_arrival_timestamp_by_driver[driver_id]
        ):
            anomalies.append((ping["ping_id"], "out_of_order_arrival"))
        previous_arrival_timestamp_by_driver[driver_id] = timestamp
        driver_timestamp = (driver_id, timestamp)
        if driver_timestamp in seen_driver_timestamps:
            anomalies.append((ping["ping_id"], "duplicate_driver_timestamp"))
            continue
        seen_driver_timestamps.add(driver_timestamp)
        unique_pings.append(ping)
    pings_by_driver = defaultdict(list)
    for ping in unique_pings:
        pings_by_driver[ping["driver_id"]].append(ping)
    accepted_pings_by_driver = {}
    # First flag off-road points. Then speed-check chronological adjacent points.
    for driver_id, driver_pings in pings_by_driver.items():
        driver_pings.sort(key=lambda ping: ping["_timestamp"])
        accepted_pings = []
        for ping in driver_pings:
            if ping["_lateral_offset_meters"] > MAX_LATERAL_OFFSET_METERS:
                anomalies.append(
                    (
                        ping["ping_id"],
                        f"off_road_offset_m={ping['_lateral_offset_meters']:.1f}",
                    )
                )
                continue
            if accepted_pings:
                previous_ping = accepted_pings[-1]
                time_gap_seconds = (
                    ping["_timestamp"] - previous_ping["_timestamp"]
                ).total_seconds()
                distance_km = abs(
                    ping["_along_road_km"] - previous_ping["_along_road_km"]
                )
                implied_speed_kmh = (
                    distance_km / (time_gap_seconds / 3600)
                    if time_gap_seconds > 0
                    else float("inf")
                )
                if time_gap_seconds <= 0:
                    anomalies.append((ping["ping_id"], "non_positive_time_delta"))
                    continue
                if implied_speed_kmh > MAX_SPEED_KILOMETERS_PER_HOUR:
                    anomalies.append(
                        (ping["ping_id"], f"implied_speed_kmh={implied_speed_kmh:.1f}")
                    )
                    continue
            accepted_pings.append(ping)
        accepted_pings_by_driver[driver_id] = accepted_pings
    for driver_id, driver_pings in accepted_pings_by_driver.items():
        for previous_ping, current_ping in zip(driver_pings, driver_pings[1:]):
            time_gap_seconds = (
                current_ping["_timestamp"] - previous_ping["_timestamp"]
            ).total_seconds()
            if time_gap_seconds > MAX_GAP_SECONDS:
                anomalies.append(
                    (current_ping["ping_id"], f"gap_seconds={time_gap_seconds:.0f}")
                )
                continue
            previous_along_road_km = previous_ping["_along_road_km"]
            current_along_road_km = current_ping["_along_road_km"]
            # Count only if both endpoints are inside the campaign zone.
            if (
                ZONE_START_KM <= previous_along_road_km <= ZONE_END_KM
                and ZONE_START_KM <= current_along_road_km <= ZONE_END_KM
            ):
                # Use along-road projection rather than noisy GPS chord distance.
                segment_distance_km = abs(
                    current_along_road_km - previous_along_road_km
                )
                # Explicit accounting convention: attribute segment to ending ping's UTC+9 day.
                report_day = current_ping["_local_calendar_date"]
                segment_distances_by_driver_day[(driver_id, report_day)].append(
                    segment_distance_km
                )
    distance_totals = defaultdict(float)
    for driver_day, segment_distances in segment_distances_by_driver_day.items():
        distance_totals[driver_day] = sum(segment_distances)
    return distance_totals, anomalies, accepted_pings_by_driver

def write_csv(output_path, column_names, output_rows):
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        csv_writer = csv.DictWriter(output_file, fieldnames=column_names)
        csv_writer.writeheader()
        csv_writer.writerows(output_rows)

def main():
    REPORTS_DIRECTORY.mkdir(exist_ok=True)
    pings = load_rows()
    legacy_totals = legacy_distance_by_driver_day(pings)
    corrected_totals, anomalies, _accepted_pings_by_driver = (
        corrected_distance_by_driver_day(pings)
    )
    driver_day_keys = sorted(set(legacy_totals) | set(corrected_totals))
    comparison = []
    for driver_id, report_day in driver_day_keys:
        legacy_distance_km = legacy_totals.get((driver_id, report_day), 0.0)
        corrected_distance_km = corrected_totals.get((driver_id, report_day), 0.0)
        comparison.append({
            "driver_id": driver_id,
            "report_day": report_day,
            "legacy_distance_km": round(legacy_distance_km, 4),
            "corrected_distance_km": round(corrected_distance_km, 4),
            "difference_km_corrected_minus_legacy": round(
                corrected_distance_km - legacy_distance_km, 4
            ),
        })
    write_csv(
        REPORTS_DIRECTORY / "distance_comparison.csv",
        [
            "driver_id",
            "report_day",
            "legacy_distance_km",
            "corrected_distance_km",
            "difference_km_corrected_minus_legacy",
        ],
        comparison,
    )
    anomaly_rows = [
        {"ping_id": anomaly_ping_id, "reason": reason}
        for anomaly_ping_id, reason in sorted(set(anomalies))
    ]
    write_csv(
        REPORTS_DIRECTORY / "anomaly_report.csv",
        ["ping_id", "reason"],
        anomaly_rows,
    )
    anomaly_reason_counts = defaultdict(int)
    for _ping_id, reason in anomalies:
        anomaly_reason_counts[reason.split("=", 1)[0]] += 1
    fault_counts = defaultdict(int)
    for ping in pings:
        fault_counts[ping["injected_fault"]] += 1
    summary = {
        "label": "SYNTHETIC TEST DATA — NOT LIVE PRODUCT DATA",
        "input_ping_rows": len(pings),
        "unique_driver_timestamp_keys": len(
            set((ping["driver_id"], ping["timestamp_utc"]) for ping in pings)
        ),
        "drivers": len(set(ping["driver_id"] for ping in pings)),
        "injected_fault_label_counts": dict(sorted(fault_counts.items())),
        "anomaly_rows_reported": len(anomaly_rows),
        "anomaly_reason_counts": dict(sorted(anomaly_reason_counts.items())),
        "comparison_rows": len(comparison),
        "legacy_total_km": round(sum(legacy_totals.values()), 4),
        "corrected_total_km": round(sum(corrected_totals.values()), 4),
        "assumptions": {
            "timezone": "UTC+09:00 fixed offset",
            "zone_km": [5.0, 25.0],
            "max_lateral_offset_m": 100,
            "max_speed_kmh": 150,
            "max_gap_seconds": 30,
            "segment_day_attribution": "UTC+9 date of ending ping",
        },
    }
    (REPORTS_DIRECTORY / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
