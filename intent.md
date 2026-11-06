# GPS Distance — Intent

## Objective
Make synthetic advertiser-billable GPS distance auditable, expose errors in an intentionally flawed baseline, and provide a corrected reference calculation with runnable regression checks.

## Problems found, ranked, and discovery method

I identified three distinct calculation flaws in the legacy baseline. They are ranked by their financial and operational impact on the advertiser and driver:

1. **Arrival-Order Dependency (Highest Impact - Chosen to solve first)**
   - **The Problem:** The legacy code calculates distance based on the order pings arrive in the CSV, rather than sorting by their actual `timestamp_utc`. Late or out-of-order pings create massive artificial "teleportation" jumps.
   - **Impact:** Causes extreme, volatile overcharging for advertisers and fake distance credits for drivers.
   - **How I found it:** I wrote a specific unit test (`test_legacy_is_sensitive_to_arrival_order`) that shuffled the input rows. The legacy output changed drastically, proving it relies on file order rather than event time.

2. **Duplicate, off-road, and speed-spike observations are not filtered (High Impact)**
   - **The Problem:** The legacy calculation accepts repeated pings, points over 100 m from the road, and jumps implying speeds over 150 km/h.
   - **Impact:** Noise can inflate or distort advertiser billing and driver credits.
   - **How I found it:** The generated dataset labels each injected fault; the anomaly report flags exact ping IDs with duplicate, offset, and implied-speed reasons.

3. **Reporting day must use UTC+9 local midnight (High Impact)**
   - **The Problem:** UTC timestamps can fall on a different calendar day than the required local reporting date.
   - **Impact:** Daily advertiser and driver totals can be assigned to the wrong day.
   - **How I found it:** Sessions start at 14:45 UTC, or 23:45 UTC+9. A test checks a segment that crosses 15:00 UTC and verifies both baseline and corrected outputs use the ending ping's UTC+9 date.

**Why I chose to solve arrival-order first:** Arrival-order dependency creates unpredictable segment jumps and makes speed checks unreliable. Sorting by event timestamp is necessary before validating adjacent points. The final implementation also applies the other reporting and data-quality rules.

## Scope and assumptions
This is a standard-library Python example for a fictional straight-road campaign. All drivers and pings are synthetic. The zone is 5–25 km along the road; the daily cutoff is fixed UTC+9. Pings more than 100 m off-road or implying speeds above 150 km/h are excluded. Remaining accepted points are connected only when the time gap is at most 30 seconds; each segment is assigned to the local day of its ending ping. This is a reference implementation, not a production map-matching system.

## Known limitations (What is still not solved)
- **Zone Boundary Clipping:** Segments that straddle the zone boundary (e.g., starting at 4.8km and ending at 5.0km) are currently discarded entirely because the logic requires BOTH endpoints to be inside the zone. A future refinement would clip the segment to count the partial distance.
- **30-Second Gap Policy:** The prompt does not explicitly define a maximum time gap between pings. I introduced a 30-second heuristic to prevent teleportation artifacts when pings are missing. This requires product-owner review to confirm if legitimate long stops (e.g., at a red light or in traffic) should be handled differently.

## What success means
- At least 2,000 clearly labelled synthetic pings containing duplicates, off-road points, speed spikes, and out-of-order arrivals.
- A runnable comparison of the intentionally flawed and corrected calculations.
- A report identifying exact ping IDs and anomaly reasons.
- Tests covering the required behavior and important boundary cases.
- Known assumptions, remaining limitations, and submission evidence stated honestly.

## AI use and verification
This Quest adapted the GPS synthetic-data project already present in the workspace; it was not created from a blank project. AI assistance was used to inspect and modify the generator, analyzer, tests, and documentation. I checked the generated counts, calculation behavior, and tests rather than treating AI output as verified.

**Concrete AI mistakes and corrections:**
- **Dataset count assumption:** An early generator version claimed to add 120 duplicates, 48 off-road points, and 32 speed spikes, but its stepped candidate selection generated only 2,507 rows and fewer injected faults. The exact-count test exposed the mismatch. I changed selection to spread a requested number of candidates through a sufficiently large pool, kept fault categories separate, regenerated the CSV, and verified 2,520 rows with exactly 120, 48, and 32 labeled faults.
- **Off-road interpretation:** An early fix treated every rejected off-road ping as a hard break and made the test expect zero distance. Comparing this with the stated rule (“ignore” the noisy ping) and the existing 30-second/speed checks showed that the valid pings on either side may still form a segment if they are close enough in time and imply a plausible speed. I changed the calculation and test accordingly; the fixture now verifies that 0.4 km is counted for the two valid endpoints while the off-road point is reported and excluded.
- **Test design:** An initial duplicate test used exact floating-point equality for a distance represented imprecisely as a binary float, and an arrival-order test reversed only two points whose distance was symmetric. I replaced exact equality with a tolerance and used three points in a nontrivial order. The corrected tests check the intended behaviors.
- **Reporting-date comparison:** I initially left the baseline on UTC dates while the corrected result used UTC+9. That made per-day comparisons inconsistent. I changed both calculations to use the UTC+9 date of the ending ping and added a regression test asserting the same date key.

**Verification performed:** regenerated the dataset and reports; ran the 13-test `unittest` suite successfully; and compiled the Python source and test files. Latest evidence is saved in `reports/regression_test_results.txt` and `reports/summary.json`. The remaining video, actual effort declaration, and reviewer-accessible link checks are not complete; no Loom video or effort total is claimed here.