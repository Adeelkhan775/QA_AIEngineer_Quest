# GPS Campaign Distance QA Quest (synthetic)

**Purpose:** reproducible hiring-assessment artifact for the fictional GPS advertising case. All data and drivers are synthetic; no live product, employer, or customer data is used.

## Run it

Requirements: Python 3.10+; standard library only.

```bash
python src/generate_data.py
python src/analyze.py
python -m unittest discover -s tests -v
python -m unittest discover -s tests -v > reports/regression_test_results.txt 2>&1
```

Outputs are written to `reports/`:
- `distance_comparison.csv`: old vs corrected distance per driver and the same UTC+9 local reporting day
- `anomaly_report.csv`: exact suspect rows and reasons
- `summary.json`: run counts and totals
- `regression_test_results.txt`: saved test run evidence (regenerate with the final command above)

Dataset: `data/gps_pings_synthetic.csv` (2,520 rows: 2,400 base pings plus 120 duplicate rows). It contains 48 off-road pings and 32 speed spikes; fault categories are injected into distinct base pings. The `synthetic_truth_*` columns are explicit test  fields and should not be treated as production telemetry.

## Scope and assumptions

- A synthetic straight road is represented by longitude-derived along-road position `s_km`; latitude offset represents lateral GPS error.
- Campaign zone is the along-road interval 5.0–25.0 km, inclusive.
- Daily reporting uses local UTC+9 date.
- Duplicate policy: same driver + exact UTC timestamp counts once; first input row is retained.
- Late/out-of-order arrivals are reported and sorted by event timestamp before distance is calculated.
- A ping is invalid when lateral offset exceeds 100 m, or when speed between adjacent timestamp-ordered pings exceeds 150 km/h.
- Off-road and over-speed pings are excluded. The next valid ping may be measured from the preceding accepted ping if its elapsed time is no more than 30 seconds and the implied speed is plausible.
- Corrected distance sums consecutive accepted points only when both endpoints are inside the campaign zone. Long gaps are not bridged.
- Both baseline and corrected results use the UTC+9 local date of the segment's ending ping, so their daily comparison uses the same reporting-day boundaries. GPS timestamps remain stored and ordered as UTC.
- This is a reference implementation for a simplified synthetic straight-road model, not a production map-matching engine. Boundary interpolation, curved roads, multiple road candidates, GPS uncertainty distributions, daylight-saving zones, and real geodesic map matching are not implemented.
