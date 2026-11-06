# GPS Distance --Directive

## 1. Objective
Make synthetic advertiser-billable GPS distance auditable, expose errors in an intentionally flawed baseline, and provide a corrected reference calculation with runnable regression checks. This is a reproducible investigation of a fictional GPS advertising case using synthetic data only. It includes a deliberately flawed baseline, a corrected reference calculation, a dataset generator, anomaly and comparison reports, and regression tests.

**Status:** Implementation and automated verification are complete for the assumptions below. The Quest submission itself is not ready until the real Loom URL, actual focused effort, and reviewer-accessible project links are supplied and checked. No video or effort estimate is fabricated here.

## 2. Scope
- **In scope:** Standard-library Python implementation for a fictional straight-road campaign. Synthetic data generation, flawed baseline calculation, corrected reference calculation, anomaly reporting, and automated regression testing.
- **Out of scope:** Real road-network map matching, curved roads, GPS accuracy distributions, spoofing detection, production deployment, scale, monitoring, and financial reconciliation. All drivers and pings are strictly synthetic.

## 3. Requirements (Business Rules Implemented)
The corrected calculation strictly enforces the following fictional platform rules:
- Pings are recorded every 10 seconds.
- Pings >100 m off the road path are ignored as GPS noise.
- Pings implying a speed >150 km/h are ignored as GPS noise.
- Duplicate pings (same driver, same timestamp) are counted exactly once.
- Late or out-of-order pings must be sorted and placed by their actual UTC timestamp, not file arrival order.
- Distance counts only while the vehicle is inside the campaign zone (5.0 km to 25.0 km).
- The daily report cuts off at 00:00 local time (UTC+9), not UTC.

## 4. Completion Criteria
- At least 2,000 clearly labelled synthetic pings containing duplicates, off-road points, speed spikes, and out-of-order arrivals.
- A runnable comparison of the intentionally flawed and corrected calculations, showing distance per driver and per day.
- A report identifying exact ping IDs and anomaly reasons.
- Automated tests covering the required behavior and important boundary cases that fail on the old code and pass on the new code.
- Known assumptions, remaining limitations, and submission evidence stated honestly.

## 5. Findings Ranked by Impact

| Rank | Problem | Advertiser impact | Driver impact | How it was found |
|---|---|---|---|---|
| 1 | Baseline uses file arrival order instead of event time | Can create artificial distance and overstate billing, or omit real movement | Can distort credited distance | Reordering the same test pings changes baseline output; corrected calculation sorts by UTC timestamp. The anomaly report marks late arrivals. |
| 2 | Duplicate timestamps are counted repeatedly | Repeated observations can inflate or distort billable distance | Can lead to inconsistent activity and settlement | The generated data has duplicate driver/timestamp keys; the checker reports each duplicate ping ID. |
| 3 | Off-road points and implausible speed spikes are included | GPS noise can inflate or distort campaign distance | Erroneous movement can affect driver credit | Generated faults are checked against 100 m and 150 km/h thresholds; exact ping IDs and reasons are reported. |
| 4 | Baseline does not reliably enforce campaign-zone membership or long-gap policy | Outside-zone or unsupported travel may be billed | Non-campaign movement can be attributed to the driver | Tests cover points outside the zone and intervals above the 30-second limit. |

**First issue addressed:** Event-time ordering. It is the foundation for comparing adjacent observations; arrival order can create distance that never occurred. The corrected implementation also applies the remaining validation and reporting rules.

## 6. Root Cause, Fix, and Measured Result
The baseline function `legacy_distance_by_driver_day` accumulates haversine distance using input arrival order and does not apply the corrected duplicate/noise checks. Both baseline and corrected outputs use the UTC+9 local date of the ending ping, so their daily comparison shares the same reporting boundaries. The event timestamps themselves remain UTC.

 ##*Success Criteria**:
1. Detects arrival-order regressions, then sorts each driver's unique observations by parsed UTC timestamp.
2. Deduplicates by driver and normalized timestamp, retaining the first input row.
3. Excludes points over 100 m off-road and points whose implied speed from the preceding accepted point exceeds 150 km/h.
4. Counts distance only when both accepted endpoints are in the inclusive 5–25 km zone and their gap is at most 30 seconds.
5. Uses along-road position difference and attributes each segment to the UTC+9 date of its ending ping.

**Measured Result (Before and After):**

| Measure | Result |
|---|---:|
| Baseline total (Flawed) | 764.139 km |
| Corrected total (Fixed) | 240.000 km |
| Synthetic clean in-zone reference | 240.000 km |
| Comparison rows | 24 (four drivers × six report dates) |
| Reported anomaly entries | 1,402 |

The report's anomaly breakdown is 1,194 out-of-order arrivals, 120 duplicate timestamps, 48 off-road points, 32 speed spikes, and 8 long-gap warnings. A representative arrival-order anomaly is identified by its exact `ping_id` and `out_of_order_arrival` reason in the anomaly CSV.

**Daily comparison:** Both calculations assign each segment to the UTC+9 local date of its ending ping. This makes the per-day comparison like-for-like by date boundary. It remains a synthetic reference result, not a production invoice reconciliation.

## 7. Results

Run these commands from the project root using Python 3.10+:

```bash
python src/generate_data.py
python src/analyze.py
python -m unittest discover -s tests -v
```

Project evidence:
- Tool and corrected/baseline calculations: [src/analyze.py](./src/analyze.py)
- Synthetic dataset generator: [src/generate_data.py](./src/generate_data.py)
- Synthetic dataset (2,520 rows): [data/gps_pings_synthetic.csv](./data/gps_pings_synthetic.csv)
- Regression tests: [tests/test_distance.py](./tests/test_distance.py)
- Per-driver/per-local-day before-and-after results: [reports/distance_comparison.csv](./reports/distance_comparison.csv)
- Ping IDs and anomaly reasons: [reports/anomaly_report.csv](./reports/anomaly_report.csv)
- Generated totals and fault counts: [reports/summary.json](./reports/summary.json)
- Saved test output: [reports/regression_test_results.txt](./reports/regression_test_results.txt)
- Run instructions: [README.md](./README.md)

## 8. AI Use, Human Checks, and Prior Work

This Quest adapted the GPS synthetic-data project already present in the workspace; it was not built from a blank project. AI assistance was used to inspect and modify the generator, analyzer, tests, and documentation. The AI output was checked against the Quest rules and repeatable test results.

| What AI initially got wrong | How it was checked and corrected |
|---|---|
| An early generator used stepped candidate selection and claimed exact fault counts, but actually produced 2,507 rows and fewer injected faults than intended. | An exact dataset-count test revealed the mismatch. Candidate selection was changed to spread a requested count across the available pool, with distinct candidates for each fault type. Regeneration confirmed 2,520 rows with exactly 120 duplicates, 48 off-road pings, and 32 speed spikes. |
| An early off-road fix broke continuity at every rejected point and expected zero distance across the gap. | The stated rule says to ignore the bad ping; it does not require discarding nearby valid travel. The implementation and test were changed so accepted endpoints can still form a segment when within 30 seconds and under the speed threshold. The test verifies 0.4 km for the valid endpoints and separately verifies that the off-road ping is flagged. |
| An early test used exact equality for a floating-point distance and reversed only two points to test order sensitivity, even though their pairwise distance is symmetric. | The test now compares with a tolerance and uses three points with a nontrivial arrival order. |
| The initial comparison grouped the baseline by UTC date and corrected results by UTC+9 local date. | The mismatch was identified by reviewing the report cutoff requirement. Both calculations now use the UTC+9 date of the segment's ending ping, and a regression test asserts that they share the same local-day key. |

Human checks performed: regenerated the dataset and reports, reviewed the recorded row/fault counts, ran all 13 regression tests successfully, and compiled the Python files. These checks verify the stated synthetic assumptions only; they are not validation against a live billing system.

