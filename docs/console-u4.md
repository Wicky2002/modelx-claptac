# U4 — data exploration and model review

Issue: [#12](https://github.com/Wicky2002/modelx-claptac/issues/12).

## Reviewed implementation plan

1. Preserve the existing console and hazard-history view. Add training-data exploration to Data and a separate read-only Model review page for technical staff.
2. Read D1's dataset-card YAML and committed split JSON contracts. Read aggregate profiling summaries and D2's native evaluation JSON from an administrator-configured report directory; never load weights or raw training data in a web request.
3. Use S1's registry records and S3's read-only `drift()` and `shadow_summary()` methods. Read model status changes from the ledger and requests from the existing Gateway. Do not call `review()` from a GET (it publishes an event), propose actions, or bypass human approvals.
4. Make sample mode an explicit opt-in with a persistent banner. Default to recorded data, with unavailable, insufficient-data, and failed-refresh states distinct from zero results or no drift.
5. Verify provenance, split/count denominators, malformed reports, role permissions, and absence of writes. Exercise both recorded and sample views in a browser, capture screenshots, rebuild the shipped bundle, and open a PR on an `aeshan/` branch.

Review adjustments: dependency code is on unmerged branches, and training is still running. The user confirmed proceeding with the available contracts and samples. Build on U3 without importing teammates' changes into this PR; the adapters activate when D1/S1/S3 land. Validate additionally against those actual branches. Do not claim final D2 performance or close the real-results acceptance gap while results are absent.

## Dependency contracts inspected

- D1 `dinuka/d1-dataset-cards`: dataset cards and split files (8a78cb5).
- D2 `dinuka/d2-flood-mapping`: `training/flood/evaluate.py`, `combine.py`, and `metrics.py` report formats (50338aa).
- S1/S3 `sumudu/s3-a10-data-learning`: registry, prediction ledger, A10 summaries and promotion/rollback controls (15f76b7).

The final real-results acceptance check remains dependent on completed training and the dependencies being integrated. Sample values are illustrative, never reported as model evaluation results.

## Using the views

Open **Data & history → Training datasets** or **Model review** under technical staff. Hazard history remains a separate tab on the existing Data page. Recorded data is the default; **Show illustrative sample data** loads isolated, clearly labelled fixtures. Samples never enter the registry, prediction ledger or approval queue. Refresh errors retain a labelled last snapshot only within the same mode; switching modes clears that data immediately.

The two GET endpoints are `/dev/data-exploration` (`run:read`) and `/dev/model-review` (`run:read`, `ledger:read`, `approval:read`). Both accept `sample=true`. Model review reads `runtime.models` and `system.learning` when available. It displays registered metrics without inferring a controlled performance comparison, uses A10's existing drift/shadow summaries, and links to the existing Approvals view. History is limited to the latest 200 model ledger records and requests to the latest 100 model-change requests. These limits are global, before the browser's model filter.

No map, globe, outer console styling, model settings or training dependencies are changed.

## Installing recorded results

D1 cards are discovered under `atlas/datasets/cards/*.yaml`, with each card's `split_file` resolved under `data/splits/`. Set `ATLAS_REVIEW_DATA_ROOT` to a different checkout/data root if needed. Event counts, image/article counts, hourly-row counts and MMFlood tile counts keep their own units. Cards supply metadata only: the loader never derives class balance from split sizes.

Set `ATLAS_REVIEW_REPORTS_DIR` to a directory containing `index.json` (default: `data/model-review` under the data root). Files referenced by the index must be relative to that directory, including after resolving symlinks, and at most 5 MB each. Publish complete JSON files with an atomic rename, then publish the index last. Invalid files produce visible warnings without hiding other valid reports. No files are fetched from URLs or generated during an HTTP request.

Example index (replace provenance with the actual run; `null` means unknown):

```json
{
  "schema_version": 1,
  "profiles": ["mmflood-train-profile.json"],
  "evaluations": [{
    "path": "report_test.json",
    "dataset": "mmflood",
    "dataset_version": null,
    "model_version": null,
    "seed": null,
    "generated_at": null,
    "source": "D2 training run: replace with its run identifier"
  }]
}
```

Copy D2's native `report_val.json` / `report_test.json` directly; no metric conversion is required. Both `evaluate.py` (`baseline`, `unet`) and `combine.py` (`baseline`, `combined`) formats are supported. The report itself supplies `split`, `tiles`, `all_pixels`, event means/counts and thresholds. Undefined NaN scores display as unavailable, while numeric zero remains zero. Pixel counts cannot be recovered from these metrics. Supply dataset/model version, seed and an ISO timestamp with timezone in the index when known; the UI explicitly identifies absent provenance.

Profiling summaries use this separate versioned contract (numbers below are **illustrative**, not measurements):

```json
{
  "schema_version": 1,
  "dataset": "mmflood",
  "dataset_version": null,
  "split": "train",
  "seed": null,
  "generated_at": "2026-01-01T00:00:00Z",
  "source": "Replace with profiling run identifier",
  "label_unit": "pixels",
  "labels": [],
  "flood_pixels": {"flood": 3, "non_flood": 97, "ignored": 2},
  "relationships": [],
  "notes": ["Example only; replace all counts with measured values."]
}
```

For label distributions, use `labels: [{"label": "flood", "count": 12}]` and an explicit unit, e.g. `articles per label`. Multi-label bars are not normalized into a pie chart. No-event articles are a negative class, not missing labels. For rain/soil plots, use `flood_pixels: null` and:

```json
"relationships": [{
  "x_label": "Rain",
  "y_label": "Soil moisture",
  "x_unit": null,
  "y_unit": null,
  "method": "Describe the aggregation and missing-pair exclusion",
  "total_pairs": 10,
  "bins": [{"x": 0, "y": 28, "count": 10}]
}]
```

All counts must be non-negative integers; coordinates must be finite; each bin has a positive count and bins must sum to `total_pairs`. Marker area represents count. Missing units remain unknown. Profiles contain at most 2,000 bins per relationship and 200 labels, not raw training rows. The schema is defined by `Profile` in `atlas/dashboard/dev/review.py`. Full illustrative fixtures are in `atlas/dashboard/dev/samples/`.

## Verification and remaining integration

- U4 browser checks cover sample opt-in, pixel denominators, dataset/version selection, missing versus zero metrics, failed refreshes, mode isolation, existing hazard history, and mobile overflow.
- D1's actual four cards and splits were loaded from commit `8a78cb5`; no warnings. MMFlood reports 54/7/34 train/val/test events and 1,242/120/386 tiles. AIFloodSense reports 325/50/95 images; disaster news 6,152/770/770 articles; Mawiongrim 487/104/105 hourly rows.
- A disposable source archive of S3 commit `15f76b7` ran `test_real_s1_s3_promote_drift_shadow_and_rollback`: real registry, inference, 35 distinct paired predictions, drift, approval-gated promotion and rollback, and unchanged ledger on read. This test skips on U4's current base because `atlas.learning` has not landed, and runs automatically once that module exists.
- The PR is based on U3 (`aeshan/u3-console-audit`) to preserve the prior console work without mixing teammates' implementation branches into this diff. After U3 merges, retarget this PR to `main`.
- **Still pending:** merge/install D1 and S1/S3, complete D2 training, export actual aggregate profiles, install reports, and repeat the recorded-results acceptance check for #12. This PR does not claim measured D2 performance or close that issue's final real-results acceptance criterion.

Validation on the U4 branch: **1,094 Python tests passed, 1 dependency integration test skipped**; that integration test passed separately against S3 as described above. **All 10 Playwright tests passed**, including existing U1/U2/U3 checks. Ruff and the TypeScript/Vite production build passed (the existing map chunk-size advisory remains).

## Screenshots

Screenshots show the actual browser-rendered bundle. Populated screenshots use the explicit sample switch; recorded-empty screenshots document the current dependency state.

| View | Screenshot |
| --- | --- |
| Flood imbalance and D2 evaluation | [Sample](screenshots/u4/data-flood-sample.png) |
| Label distribution | [Sample](screenshots/u4/data-labels-sample.png) |
| Rain and soil relationship | [Sample](screenshots/u4/data-soil-sample.png) |
| Model metrics, drift, shadow and history | [Sample](screenshots/u4/models-sample.png) |
| Data on mobile | [Sample](screenshots/u4/data-mobile-sample.png) |
| Model review on mobile | [Sample](screenshots/u4/models-mobile-sample.png) |
| Missing dataset results | [Recorded](screenshots/u4/data-recorded-empty.png) |
| Missing model registry | [Recorded](screenshots/u4/models-recorded-empty.png) |
