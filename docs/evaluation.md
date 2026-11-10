# Evaluation

The trained models (D2 radar flood, D4 report reading) were each scored once on their own held-out test
sets; those results are below. They have not yet been run inside the live replay, for the reasons given in
the Ditwah table. Their weights stay outside git.

To reproduce:

```
python -m atlas.benchmark.ditwah
python -m atlas.benchmark run --seeds 42,43,44
python -m atlas.benchmark run --seeds 42,43,44 --stand-in-models
python -m atlas.benchmark run --seeds 42,43,44 --stand-in-models --tasks data/benchmarks/model-tasks
```

## Ditwah replay, Ratnapura (Kalu Ganga), November 2025

Dataset: `data/scenarios/ratnapura_ditwah_2025.json`, 53 gauge readings and 122 ERA5 readings.
Deterministic, so no seed applies.

| Run | Inputs | First flood trigger (UTC) | Reason | Lead before 9.5 m crossing |
|---|---|---|---|---|
| **Strict: gauge only, real speed** | 53 | 27 Nov 08:35 | water level | **21.96 h** |
| Reanalysis-assisted: gauge + ERA5, real speed | 175 | 27 Nov 08:35 | water level | 21.96 h |
| Demo at 240x (not a result) | 175 | 27 Nov 03:58 | rainfall | 26.57 h |
| Rules + trained models | not run in the replay | | | Would equal strict, see below |

The gauge crossed 9.5 m at 06:32:58 UTC on 28 November.

**Reading these numbers**

- The system under test is the rule-only baseline. A model-backed run cannot currently change the
  trigger time: by design (S2) models cannot raise or hold back a trigger, and this scenario contains
  no field reports or radar scenes for a model to read.
- The lead time is from a level-threshold crossing to a later, higher level. It is **not a forecast**.
  The Sentinel's alarm (25 cm on the tabletop scale, which is 5.0 m) was set to sit near the department's
  5.2 m alert level, so it fires roughly when the river reaches alert level.
- A trigger starts the agents. It is not a public alert, which also needs a person's approval.
- The 240x run shows why compressed replays are not evidence: compression changes which rule fires
  and moves the trigger by about 4.6 h.
- This is one event at one station. It says nothing about false alarms.

**Why a trained-model run would not change this row.** Models cannot raise or hold back a trigger (S2), and
this scenario has no field reports. The first radar pass usable after the trigger is 2 Dec 00:24 UTC, four days
after the peak, and the D3 layers for Ratnapura show no flood above the level seen on the pre-flood passes of
14 Nov (`docs/ratnapura-sentinel1.md`). So the radar model would add no evidence before the 9.5 m crossing.

**What "strict" does and does not gate**

| Input | Treatment | Limit |
|---|---|---|
| River gauge | Replayed at its own recorded time | Assumes no delay between the reading and ATLAS receiving it |
| ERA5 rain and soil | Excluded from strict | Assisted run uses nominal time, which no operator could have had |
| Sentinel-1 radar | Not in this replay | D3 found no pass between 26 Nov 12:49 and 2 Dec 00:24 UTC, so radar did not see the peak. A trained run must gate each scene by acquisition plus processing time |

## Checking the anchors

| Value | Checked against | Result |
|---|---|---|
| 9.5 m major-flood level (also 5.2 m alert, 7.5 m minor) | Irrigation Department gauge table of 30 Nov 2025, published by the Ministry of Foreign Affairs | Matches |
| Ratnapura reached major flood on 28 Nov | Press report of the department's 28 Nov situation update | Matches, no level in metres given |
| 10.21 m peak, 12:32 UTC (18:02 local) on 28 Nov | The upstream `nuuuwan/lk_irrigation` records, re-fetched on 9 Nov 2026 | Matches the scenario |
| 10.21 m against a department record | Not found | **Open.** The upstream repository is a scrape of the department's dashboard, so it is not independent. A hydrology bulletin for 28 Nov is still needed |

Sources: [gauge table, 30 Nov 2025](https://mfa.gov.lk/en/wp-content/uploads/2025/11/Water-level-Rainfall-2025.11.30-at-12.00-Noon.pdf),
[situation update, 28 Nov 2025](https://www.newswire.lk/2025/11/28/critical-flood-situation-in-kelani-maha-oya-and-kalu-ganga-basins-new-update/),
[lk_irrigation](https://github.com/nuuuwan/lk_irrigation).

**Data notes**

- The gauge has a 7.2 h gap in the window, from 16:33 UTC on 28 Nov, after the peak. The true
  peak could only be higher if it fell in a gap between readings.
- The scenario's `real_start` says 00:00 UTC on 27 Nov, but its first reading is 18:42 UTC on 26 Nov
  (00:12 local on 27 Nov). The upstream file names are in local time. Times here use the readings'
  own timestamps. The label in `atlas/datasets/scenarios.py` is unchanged.

## Benchmark

Seeds 42, 43, 44, with no LLM. Synthetic and offline, so these numbers show that the software still
behaves, not how good a hazard model is.

| Run | Cases passed | Model calls that ran a model |
|---|---|---|
| Rules only, 10 standard tasks | 30 / 30 | none |
| Stand-in models loaded, 10 standard tasks | 30 / 30 | **0** |
| Stand-in models, `model-tasks` (1 task) | 3 / 3 | 3 (`report_classifier`, all `ok`) |

**The second row shows only that loading models breaks nothing.** The standard tasks never reach a
model: their one field report with text conflicts with a gauge, and A1 skips the classifier then.
The extra task in `data/benchmarks/model-tasks` is an uncontested field report, so the classifier
runs. It is kept apart so the standard suite stays the same 10 tasks.

The stand-in classifier agrees with every report. No benchmark task contains a radar scene, so the
radar path is tested only in `tests/learning/test_agent_models.py`.

## Trained models: held-out test results

Each test set was scored once, after every choice was fixed on validation.

**D2 radar flood mapping** (MMFlood test split: 34 events, 386 tiles). Three U-Nets averaged, no flood on
slopes over 10°, threshold chosen on validation.

| | VV threshold baseline | Trained model |
|---|---|---|
| Mean event F1 | 0.215 | **0.340** |
| Pixel F1 | 0.301 | **0.497** |
| Pixel IoU | 0.177 | **0.330** |
| Calibration error (after temperature) | | 1.9% |

Limits: MMFlood events are mostly lowland floods. On Ratnapura (D3) the model does not separate flood from
the pre-flood false-alarm level, and no independent inundation map exists to check it against.

**D4 report reading** (disaster-news test split, 770 English articles).

| | Keyword rules | XLM-R transformer |
|---|---|---|
| Hazard labels, macro-F1 | **0.866** | 0.667 |
| Location sentences, F1 | 0.648 | **0.948** |
| Impact sentences, F1 | 0.657 | **0.988** |

Limits: the labels appear to be machine-generated from keyword and gazetteer rules, so these scores
measure agreement with the labelling rules, not report understanding. English only; no Sinhala or Tamil
text was available.

The same reports are shown on the console's Data page (`data/model-review/`).

## Model cards

Generated from the registry, so a card cannot disagree with what was registered:

```
python -m atlas.learning.cards --database data/atlas.db --out outputs/model-cards
```

No cards are committed because no real model is registered yet.

## Still to do

1. Write and register the model wrappers described in `docs/model-registry.md`, then run the replay with
   them, gating radar scenes by availability.
2. A hand-checked set of report labels, before any claim about report understanding.
3. Spatial agreement needs independently documented flood extents. Gauge timing does not count (§9).
4. Find a department record for the 10.21 m peak.
