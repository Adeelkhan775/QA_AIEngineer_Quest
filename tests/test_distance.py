import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
import analyze


def create_ping(
    ping_id,
    driver_id,
    timestamp_text,
    along_road_distance_km,
    lateral_offset_meters=0,
    latitude=None,
):
    # Along-road projection is longitude-based; synthetic latitude controls lateral offset.
    longitude = 55.0 + along_road_distance_km / analyze.KM_PER_LONGITUDE_DEGREE
    latitude = (
        25.0 + (lateral_offset_meters / 1000) / 111.0
        if latitude is None
        else latitude
    )
    timestamp = datetime.fromisoformat(
        timestamp_text.replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    return {
        "ping_id": ping_id,
        "driver_id": driver_id,
        "timestamp_utc": timestamp_text,
        "latitude": str(latitude),
        "longitude": str(longitude),
        "_timestamp": timestamp,
        "_along_road_km": along_road_distance_km,
        "_utc_calendar_date": timestamp.date().isoformat(),
        "_local_calendar_date": (timestamp + timedelta(hours=9)).date().isoformat(),
        "_lateral_offset_meters": abs(latitude - 25.0) * 111000,
    }


class DistanceRegressionTests(unittest.TestCase):
    def test_local_day_differs_from_utc_day(self):
        ping = create_ping("p1", "d1", "2026-10-20T15:05:00Z", 10)
        self.assertEqual(ping["_utc_calendar_date"], "2026-10-20")
        self.assertEqual(ping["_local_calendar_date"], "2026-10-21")

    def test_legacy_is_sensitive_to_arrival_order(self):
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 10)
        second_ping = create_ping("b", "d1", "2026-10-20T15:00:10Z", 10.2)
        third_ping = create_ping("c", "d1", "2026-10-20T15:00:20Z", 10.5)
        ordered_totals = analyze.legacy_distance_by_driver_day(
            [first_ping, second_ping, third_ping]
        )
        reordered_totals = analyze.legacy_distance_by_driver_day(
            [first_ping, third_ping, second_ping]
        )
        self.assertNotEqual(sum(ordered_totals.values()), sum(reordered_totals.values()))

    def test_corrected_result_is_arrival_order_independent_and_flags_late_ping(self):
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 10)
        second_ping = create_ping("b", "d1", "2026-10-20T15:00:10Z", 10.2)
        third_ping = create_ping("c", "d1", "2026-10-20T15:00:20Z", 10.4)
        ordered_totals, _, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, second_ping, third_ping]
        )
        late_totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, third_ping, second_ping]
        )
        self.assertAlmostEqual(
            sum(ordered_totals.values()), sum(late_totals.values()), places=6
        )
        self.assertTrue(
            any(
                ping_id == "b" and reason == "out_of_order_arrival"
                for ping_id, reason in anomalies
            )
        )

    def test_duplicate_timestamp_counts_once(self):
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 10)
        duplicate_ping = create_ping("b", "d1", "2026-10-20T15:00:00+00:00", 10)
        next_ping = create_ping("c", "d1", "2026-10-20T15:00:10Z", 10.2)
        distance_totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, duplicate_ping, next_ping]
        )
        self.assertAlmostEqual(sum(distance_totals.values()), 0.2, places=6)
        self.assertTrue(
            any(
                "duplicate_driver_timestamp" in reason
                for _, reason in anomalies
            )
        )

    def test_segment_is_attributed_to_ending_ping_local_day(self):
        first_ping = create_ping("a", "d1", "2026-10-20T14:59:50Z", 10)
        ending_ping = create_ping("b", "d1", "2026-10-20T15:00:00Z", 10.2)
        distance_totals, _, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, ending_ping]
        )
        self.assertAlmostEqual(distance_totals[("d1", "2026-10-21")], 0.2, places=6)
        self.assertNotIn(("d1", "2026-10-20"), distance_totals)

    def test_baseline_and_corrected_reports_use_same_local_day(self):
        first_ping = create_ping("a", "d1", "2026-10-20T14:59:50Z", 10)
        ending_ping = create_ping("b", "d1", "2026-10-20T15:00:00Z", 10.2)
        legacy_totals = analyze.legacy_distance_by_driver_day(
            [first_ping, ending_ping]
        )
        corrected_totals, _, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, ending_ping]
        )
        self.assertIn(("d1", "2026-10-21"), legacy_totals)
        self.assertIn(("d1", "2026-10-21"), corrected_totals)
        self.assertNotIn(("d1", "2026-10-20"), legacy_totals)
        self.assertNotIn(("d1", "2026-10-20"), corrected_totals)

    def test_offroad_point_is_rejected(self):
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 10)
        off_road_ping = create_ping(
            "b", "d1", "2026-10-20T15:00:10Z", 10.2, lateral_offset_meters=180
        )
        next_ping = create_ping("c", "d1", "2026-10-20T15:00:20Z", 10.4)
        distance_totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, off_road_ping, next_ping]
        )
        self.assertTrue(
            any(
                ping_id == "b" and "off_road" in reason
                for ping_id, reason in anomalies
            )
        )
        self.assertAlmostEqual(sum(distance_totals.values()), 0.4, places=6)

    def test_speed_spike_is_rejected_and_valid_segments_continue(self):
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 10)
        speed_spike_ping = create_ping("spike", "d1", "2026-10-20T15:00:10Z", 12.2)
        next_ping = create_ping("after", "d1", "2026-10-20T15:00:20Z", 10.4)
        later_ping = create_ping("later", "d1", "2026-10-20T15:00:30Z", 10.6)
        distance_totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, speed_spike_ping, next_ping, later_ping]
        )
        self.assertAlmostEqual(sum(distance_totals.values()), 0.6, places=6)
        self.assertTrue(
            any(
                ping_id == "spike" and "implied_speed" in reason
                for ping_id, reason in anomalies
            )
        )

    def test_long_gap_is_not_counted(self):
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 10)
        next_ping = create_ping("b", "d1", "2026-10-20T15:00:40Z", 10.2)
        distance_totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, next_ping]
        )
        self.assertEqual(sum(distance_totals.values()), 0.0)
        self.assertTrue(
            any(
                ping_id == "b" and reason == "gap_seconds=40"
                for ping_id, reason in anomalies
            )
        )

    def test_exact_speed_and_zone_boundaries_are_included(self):
        first_ping = create_ping(
            "a", "d1", "2026-10-20T15:00:00Z", 5.0, lateral_offset_meters=0
        )
        next_ping = create_ping(
            "b", "d1", "2026-10-20T15:00:12Z", 5.5, lateral_offset_meters=0
        )
        first_ping["_lateral_offset_meters"] = next_ping["_lateral_offset_meters"] = 100.0
        distance_totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, next_ping]
        )
        self.assertAlmostEqual(sum(distance_totals.values()), 0.5, places=6)
        self.assertFalse(
            any(
                "off_road" in reason or "implied_speed" in reason
                for _, reason in anomalies
            )
        )

    def test_dataset_has_expected_size_and_fault_counts(self):
        pings = analyze.load_rows()
        fault_counts = {}
        for ping in pings:
            fault_label = ping["injected_fault"]
            fault_counts[fault_label] = fault_counts.get(fault_label, 0) + 1
        self.assertEqual(len(pings), 2520)
        self.assertEqual(fault_counts["duplicate"], 120)
        self.assertEqual(fault_counts["off_road_gt_100m"], 48)
        self.assertEqual(fault_counts["speed_spike_gt_150kmh"], 32)

    def test_generated_dataset_is_large_and_faulty(self):
        data_path = PROJECT_ROOT / "data" / "gps_pings_synthetic.csv"
        if not data_path.exists():
            self.skipTest("Run python src/generate_data.py first")
        pings = analyze.load_rows()
        self.assertGreaterEqual(len(pings), 2000)
        fault_labels = {ping["injected_fault"] for ping in pings}
        self.assertIn("duplicate", fault_labels)
        self.assertIn("off_road_gt_100m", fault_labels)
        self.assertIn("speed_spike_gt_150kmh", fault_labels)

    def test_outside_zone_is_not_counted(self):
        """
        KNOWN LIMITATION: Segments that straddle the zone boundary (e.g., 4.8 to 5.0)
        are currently discarded entirely because the logic requires BOTH endpoints
        to be inside the zone. A future refinement would clip the segment to count
        the partial distance (0.2km in this case). For this Quest, this strict
        boundary check is accepted to ensure auditable, deterministic behavior.
        """
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 4.8)
        boundary_ping = create_ping("b", "d1", "2026-10-20T15:00:10Z", 5.0)
        next_ping = create_ping("c", "d1", "2026-10-20T15:00:20Z", 5.2)
        distance_totals, _, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, boundary_ping, next_ping]
        )
        self.assertAlmostEqual(sum(distance_totals.values()), 0.2, places=6)

    def test_outside_zone_is_not_counted(self):
        """
        KNOWN LIMITATION: Segments that straddle the zone boundary (e.g., 4.8 to 5.0)
        are currently discarded entirely because the logic requires BOTH endpoints
        to be inside the zone. A future refinement would clip the segment to count
        the partial distance (0.2km in this case). For this Quest, this strict
        boundary check is accepted to ensure auditable, deterministic behavior.
        """
        first_ping = create_ping("a", "d1", "2026-10-20T15:00:00Z", 4.8)
        boundary_ping = create_ping("b", "d1", "2026-10-20T15:00:10Z", 5.0)
        next_ping = create_ping("c", "d1", "2026-10-20T15:00:20Z", 5.2)
        distance_totals, _, _ = analyze.corrected_distance_by_driver_day(
            [first_ping, boundary_ping, next_ping]
        )
        self.assertAlmostEqual(sum(distance_totals.values()), 0.2, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
