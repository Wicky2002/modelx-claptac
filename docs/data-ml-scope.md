# Data and ML workstream: scope

What is left to build to match proposal sections 5, 6, 7.1 (A10), 8 and 9. Everything else in the
proposal already exists in this repo (imported from `codesplash26-ai/team-claptac`, 41 commits).

## Where we are

| Proposal item | In the repo today | Gap |
|---|---|---|
| Operational inputs: gauges, Open-Meteo/ERA5, GDACS, IBTrACS, USGS, NOAA (§5.1) | `atlas/datasets/`, verified, cached, Ditwah replays | none for the demo |
| Training datasets: MMFlood, Mawiongrim, disaster-news, AIFloodSense (§5.1) | nothing | acquire, audit, card |
| Dataset cards: origin, version, DOI, licence, coverage, label meaning, missingness, permitted use (§5.1) | `SourceInfo` for live sources only | schema + one card per training set |
| Cleaning, event-level splits, EDA, EDA in the console (§5.2) | console `Data` page lists live sources | pipeline, split files, EDA plots and console panel |
| Radar flood segmentation, U-Net vs backscatter threshold (§6) | nothing; A2 floods roads by a gauge rule | baseline + model + IoU/F1 |
| Landslide model, LightGBM vs LSTM (§6) | nothing; A1 uses soil/tilt thresholds from `sensor_map.yaml` | baseline + model + metrics |
| Report classification + location/impact extraction, transformer vs keyword rules (§6) | `atlas/intelligence/extraction.py` (LLM/rules, no trained model) | classifier + extractor + macro-F1 |
| Flood-photo segmentation on AIFloodSense (§6) | nothing | optional (on the §8 cut list) |
| Model registry with feature schema, dataset versions, metrics, threshold (§6) | `atlas/manager/registry.py` is an *agent* registry, not models | model registry |
| A10 Data & Learning: drift, shadow mode, promotion request, rollback (§6, §7.1) | no A10 agent; no `promote_model` in `config/policy.yaml` | agent + policy rule + console view |
| Model tests and Ditwah strict replay with availability-time gating (§9) | Ditwah replays exist, not availability-gated for models | evaluation harness + model cards |

## Workstreams

Sized for a small team; **M** = must have for the demo, **S** = should, **C** = cut first (proposal §8).

### W1. Acquisition and dataset cards (M) — do first, it unblocks everything

1. Confirm access and licence for each dataset; record the result even when it fails (proposal §10).
   - MMFlood: Zenodo public mirror, ~10.4 GB. Download only Sri Lanka-relevant + a fixed training subset if disk/GPU is tight.
   - Mawiongrim (10.21227/hyf5-3c15), disaster-news (10.21227/hsdv-2t76), AIFloodSense (10.21227/qxs5-2e20): IEEE DataPort, may need a subscription/account. Check who on the team has access.
2. `atlas/datasets/cards/` — a Pydantic `DatasetCard` and one YAML per dataset (the §5.1 field list). Expose it on the API and the console `Data` page.
3. Download scripts under `atlas/learning/acquire.py` writing to `data/cache/` (git-ignored). Never commit raw data or weights to git; record checksums in the card.

Done when: `python -m atlas.learning cards` lists every dataset with verified/not-verified and the reason.

### W2. Cleaning, splits and EDA (M)

- Event-level (MMFlood) and period-level (Mawiongrim) split files committed as JSON, created **before** tiling/windowing.
- Features from §5.2: antecedent rain 1/3/7 d, soil-moisture trend, slope, distance to permanent water. Fit scalers/imputers on train only; missing stays distinguishable from zero.
- EDA notebook or script producing: flood-pixel imbalance, label distribution by event/country/language, rain–soil–slope relationships. Save as JSON/PNG and show in the console (§5.2 promises reviewers can see it).

### W3. Models (baseline first, then the learned model)

| Model | Baseline (M) | Learned model | Metric | Feeds |
|---|---|---|---|---|
| Radar flood | fixed VV backscatter threshold | U-Net, pretrained encoder, small tiles (M if GPU, else S) | flood-class IoU, F1 on held-out events | A2 flood layer → road passability evidence for A4 |
| Landslide / slope | rules already in `sensor_map.yaml` | LightGBM on engineered features (M); LSTM (C) | P/R/F1, ROC-AUC, false-alarm rate — or MAE/RMSE if the label is a measurement | A1 trigger score |
| Field reports | keyword rules (M) | multilingual transformer, e.g. XLM-R fine-tune (S) | macro-F1; location/impact extraction P/R separately | A1 corroboration, `intelligence/extraction.py` |
| Flood photos | — | lightweight segmentation (C) | IoU by image type | A1 evidence |

Rules from the proposal: thresholds chosen on validation only; class-weighted losses; report measurement
forecasting and event warning separately; if landslide event labels are insufficient, label the work a
measurement-modelling study (§8, §10).

### W4. Model registry and inference wiring (M)

- `atlas/learning/registry.py`: each model version records feature schema, dataset versions, metrics, operating threshold, status (`candidate | shadow | live | retired`). Store in SQLite next to the ledger.
- Inference behind a small interface so A1/A2 call `predict()` and fall back to today's rules when no live model exists or input schema doesn't match.
- Every prediction is logged to the ledger with its input evidence and model version (§7.1), so it can later be linked to the outcome.

### W5. A10 Data & Learning agent (M minimal, S full)

- Minimal: drift check on incoming features vs training distribution, shadow-mode run of a candidate alongside live, and a `promote_model` request.
- Add `promote_model` to `config/policy.yaml` as **always human-approval**, plus one-step rollback. Extend the red-team suite with a promotion attack (§9: unapproved promotions must be zero).
- A10 cannot change live thresholds, policy or the ledger — enforce through the existing Control Boundary identities.
- Console: model-review view (drift, candidate vs current, shadow results, promotion/rollback history) (§7.3).

### W6. Evaluation (M)

- Model cards generated from the registry.
- Strict Ditwah replay: gate each input by its historical availability time; report reanalysis-assisted results separately; compare warning time vs the 9.5 m major-flood crossing and vs the rule-only baseline. Re-check the 10.21 m / 9.5 m anchors against station records.
- Add model-backed variants to `python -m atlas.benchmark` so the existing 10 tasks × 3 seeds still pass with models in the loop.

## Suggested order and owners

Owners follow who built the neighbouring code; change as the team prefers.

| Order | Work | Suggested owner | Depends on |
|---|---|---|---|
| 1 | W1 access checks + dataset cards | Dinuka (data sources) | — |
| 2 | W2 splits, features, EDA | Dinuka + Aeshan | W1 |
| 3a | Landslide LightGBM + A1 wiring | Aeshan (Sentinel) | W2 |
| 3b | Radar threshold baseline → U-Net + A2 → road evidence | Sumudu (routing) | W2, GPU |
| 3c | Report keyword baseline → transformer | Aeshan (intelligence) | W1 |
| 4 | W4 model registry + ledger logging | Dinuka (control boundary) | can start in parallel with 3 |
| 5 | W5 A10 + promotion policy + console view | Dinuka | W4 |
| 6 | W6 evaluation, model cards, Ditwah strict replay | whole team | 3, 4 |
| — | LoRa: real sensor sequences for landslide validation if hardware time allows | Hasindu | — |

## Decisions needed from the team

1. Milestone dates (the proposal's Phase 1/2/3 mapping to ModelX milestones is still open).
2. GPU: who has one, or which cloud credits — decides whether the U-Net is M or S.
3. IEEE DataPort access for Mawiongrim, disaster-news and AIFloodSense.
4. Where weights live (Git LFS, GitHub release, or a download script from cloud storage).
5. New dependencies (PyTorch, LightGBM, rasterio, transformers) in an optional `[ml]` extra so the Docker demo stays light.
