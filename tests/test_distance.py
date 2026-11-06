import sys, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
import analyze

def row(pid, driver, ts, s, offset=0, lat=None):
    # Along-road projection is longitude-based; synthetic latitude controls lateral offset.
    longitude = 55.0 + s / analyze.KM_PER_LON_DEG
    latitude = 25.0 + (offset/1000)/111.0 if lat is None else lat
    dt = datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)
    return {"ping_id":pid,"driver_id":driver,"timestamp_utc":ts,
            "latitude":str(latitude),"longitude":str(longitude),
            "_ts":dt,"_s":s,"_utc_day":dt.date().isoformat(),
            "_local_day":(dt+timedelta(hours=9)).date().isoformat(),
            "_offset_m":abs(latitude-25.0)*111000}

class DistanceRegressionTests(unittest.TestCase):
    def test_local_day_differs_from_utc_day(self):
        r = row("p1","d1","2026-10-20T15:05:00Z",10)
        self.assertEqual(r["_utc_day"],"2026-10-20")
        self.assertEqual(r["_local_day"],"2026-10-21")

    def test_legacy_is_sensitive_to_arrival_order(self):
        a = row("a","d1","2026-10-20T15:00:00Z",10)
        b = row("b","d1","2026-10-20T15:00:10Z",10.2)
        c = row("c","d1","2026-10-20T15:00:20Z",10.5)
        ordered = analyze.legacy_distance_by_driver_day([a,b,c])
        reordered = analyze.legacy_distance_by_driver_day([a,c,b])
        self.assertNotEqual(sum(ordered.values()),sum(reordered.values()))

    def test_corrected_result_is_arrival_order_independent_and_flags_late_ping(self):
        a = row("a","d1","2026-10-20T15:00:00Z",10)
        b = row("b","d1","2026-10-20T15:00:10Z",10.2)
        c = row("c","d1","2026-10-20T15:00:20Z",10.4)
        ordered, _, _ = analyze.corrected_distance_by_driver_day([a,b,c])
        late, anomalies, _ = analyze.corrected_distance_by_driver_day([a,c,b])
        self.assertAlmostEqual(sum(ordered.values()),sum(late.values()), places=6)
        self.assertTrue(any(pid=="b" and reason=="out_of_order_arrival"
                            for pid,reason in anomalies))

    def test_duplicate_timestamp_counts_once(self):
        a = row("a","d1","2026-10-20T15:00:00Z",10)
        b = row("b","d1","2026-10-20T15:00:00+00:00",10)
        c = row("c","d1","2026-10-20T15:00:10Z",10.2)
        totals, anomalies, _ = analyze.corrected_distance_by_driver_day([a,b,c])
        self.assertAlmostEqual(sum(totals.values()),0.2, places=6)
        self.assertTrue(any("duplicate_driver_timestamp" in reason for _,reason in anomalies))

    def test_segment_is_attributed_to_ending_ping_local_day(self):
        a = row("a","d1","2026-10-20T14:59:50Z",10)
        b = row("b","d1","2026-10-20T15:00:00Z",10.2)
        totals, _, _ = analyze.corrected_distance_by_driver_day([a,b])
        self.assertAlmostEqual(totals[("d1","2026-10-21")],0.2, places=6)
        self.assertNotIn(("d1","2026-10-20"),totals)

    def test_baseline_and_corrected_reports_use_same_local_day(self):
        a = row("a","d1","2026-10-20T14:59:50Z",10)
        b = row("b","d1","2026-10-20T15:00:00Z",10.2)
        legacy = analyze.legacy_distance_by_driver_day([a,b])
        corrected, _, _ = analyze.corrected_distance_by_driver_day([a,b])
        self.assertIn(("d1","2026-10-21"),legacy)
        self.assertIn(("d1","2026-10-21"),corrected)
        self.assertNotIn(("d1","2026-10-20"),legacy)
        self.assertNotIn(("d1","2026-10-20"),corrected)

    def test_offroad_point_is_rejected(self):
        a = row("a","d1","2026-10-20T15:00:00Z",10)
        b = row("b","d1","2026-10-20T15:00:10Z",10.2,offset=180)
        c = row("c","d1","2026-10-20T15:00:20Z",10.4)
        totals, anomalies, _ = analyze.corrected_distance_by_driver_day([a,b,c])
        self.assertTrue(any(pid=="b" and "off_road" in reason for pid,reason in anomalies))
        self.assertAlmostEqual(sum(totals.values()),0.4, places=6)

    def test_speed_spike_is_rejected_and_valid_segments_continue(self):
        a = row("a","d1","2026-10-20T15:00:00Z",10)
        spike = row("spike","d1","2026-10-20T15:00:10Z",12.2)
        after = row("after","d1","2026-10-20T15:00:20Z",10.4)
        later = row("later","d1","2026-10-20T15:00:30Z",10.6)
        totals, anomalies, _ = analyze.corrected_distance_by_driver_day(
            [a,spike,after,later])
        self.assertAlmostEqual(sum(totals.values()),0.6, places=6)
        self.assertTrue(any(pid=="spike" and "implied_speed" in reason
                            for pid,reason in anomalies))

    def test_long_gap_is_not_counted(self):
        a = row("a","d1","2026-10-20T15:00:00Z",10)
        b = row("b","d1","2026-10-20T15:00:40Z",10.2)
        totals, anomalies, _ = analyze.corrected_distance_by_driver_day([a,b])
        self.assertEqual(sum(totals.values()),0.0)
        self.assertTrue(any(pid=="b" and reason=="gap_seconds=40"
                            for pid,reason in anomalies))

    def test_exact_speed_and_zone_boundaries_are_included(self):
        a = row("a","d1","2026-10-20T15:00:00Z",5.0,offset=0)
        b = row("b","d1","2026-10-20T15:00:12Z",5.5,offset=0)
        a["_offset_m"] = b["_offset_m"] = 100.0
        totals, anomalies, _ = analyze.corrected_distance_by_driver_day([a,b])
        self.assertAlmostEqual(sum(totals.values()),0.5, places=6)
        self.assertFalse(any("off_road" in reason or "implied_speed" in reason
                             for _,reason in anomalies))

    def test_outside_zone_is_not_counted(self):
        a = row("a","d1","2026-10-20T15:00:00Z",4.8)
        b = row("b","d1","2026-10-20T15:00:10Z",5.0)
        c = row("c","d1","2026-10-20T15:00:20Z",5.2)
        totals, _, _ = analyze.corrected_distance_by_driver_day([a,b,c])
        self.assertAlmostEqual(sum(totals.values()),0.2, places=6)

    def test_dataset_has_expected_size_and_fault_counts(self):
        rows = analyze.load_rows()
        counts = {}
        for r in rows:
            label = r["injected_fault"]
            counts[label] = counts.get(label, 0) + 1
        self.assertEqual(len(rows),2520)
        self.assertEqual(counts["duplicate"],120)
        self.assertEqual(counts["off_road_gt_100m"],48)
        self.assertEqual(counts["speed_spike_gt_150kmh"],32)

    def test_generated_dataset_is_large_and_faulty(self):
        data = ROOT/"data"/"gps_pings_synthetic.csv"
        if not data.exists():
            self.skipTest("Run python src/generate_data.py first")
        rows = analyze.load_rows()
        self.assertGreaterEqual(len(rows),2000)
        labels = {r["injected_fault"] for r in rows}
        self.assertIn("duplicate",labels)
        self.assertIn("off_road_gt_100m",labels)
        self.assertIn("speed_spike_gt_150kmh",labels)
    
    def test_outside_zone_is_not_counted(self):
        """
        KNOWN LIMITATION: Segments that straddle the zone boundary (e.g., 4.8 to 5.0) 
        are currently discarded entirely because the logic requires BOTH endpoints 
        to be inside the zone. A future refinement would clip the segment to count 
        the partial distance (0.2km in this case). For this Quest, this strict 
        boundary check is accepted to ensure auditable, deterministic behavior.
        """
        a = row("a","d1","2026-10-20T15:00:00Z",4.8)
        b = row("b","d1","2026-10-20T15:00:10Z",5.0)
        c = row("c","d1","2026-10-20T15:00:20Z",5.2)
        totals, _, _ = analyze.corrected_distance_by_driver_day([a,b,c])
        # 4.8->5.0 is discarded. 5.0->5.2 is counted (0.2km).
        self.assertAlmostEqual(sum(totals.values()), 0.2, places=6)
if __name__ == "__main__":
    unittest.main(verbosity=2)
