# Team split: what is left and who does it

Each person owns one area from start to finish. Every task below has a GitHub issue with the same ID
in its title. Background on why each task exists is in [data-ml-scope.md](data-ml-scope.md), and section
numbers (§) refer to the Phase 1 proposal.

| Person | GitHub | Area | Tasks |
|---|---|---|---|
| Dinuka | `Wicky2002` | Datasets and GPU training | D1–D4 |
| Hasindu | `HasinduNimesh` | Field hardware and sensor data | H1–H4 |
| Aeshan | `Aeshan-Rosa` | Console and map | U1–U4 |
| Sumudu | `Lilvamp237` | Agents, model integration, evaluation | S1–S4 |

## Start here

Two tasks unblock everyone else, so they go first:

- **S1** publishes the `predict()` interface and the model record. Model and UI work builds against it.
- **D1** publishes the dataset cards and the split files. All model scores depend on them.

```
D1 ─► D2 ─► D3 ─┐
D1 ─► D4 ───────┤
D1 ─► H4 ───────┼─► S2 ─► S4
S1 ─────────────┘    S3 ─► S4
S1 ─► U4
U1 ─► U2
H1 ─► H2 ─► H3
```

U1, U3, H1 and S3's design work do not wait for anyone.

## Ground rules

- **Training:** heavy GPU runs happen on Dinuka's PC, overnight by default. To get a run into the queue,
  test on a small sample first and hand over a ready-to-run config by evening.
- **Data:** the raw datasets are in the team Drive folder "Model X/ Innova datasets". Never commit raw data
  or model weights to git. This repo is public.
- **Keep the rules as they are today as the fallback.** A missing model or a mismatched input must never
  look like "no hazard" (§5.3, §10).
- **Report honestly:** every number states its dataset, split, seed and limits. Replays and synthetic data
  are always labelled as such.
- **Branches:** one branch and PR per issue. CI must pass (`pytest`, `ruff check atlas tests`).

## What the datasets contain

Checked directly from the files.

| Dataset | Contents | Watch out for |
|---|---|---|
| MMFlood | 1,748 tiles, 95 events, 27.2 GB unpacked. Split by event: 1,242 train, 120 val, 386 test. | Hydrography exists for only 1,012 tiles (58%). No Sri Lankan events. |
| Disaster-news | 7,692 articles, 126,150 sentences, with event, location and impact labels. | Event labels have 9 columns but the proposal lists 8 categories, and no column names are included. 962 articles have no event label. Sentence labels stop at 40 per article (190 articles are longer). Almost all English. |
| AIFloodSense | 470 images with flood, building and sky masks. CC BY 4.0. | 64 of the 94 test images come from flood events that are also in the training set. Mostly aerial images. No Sri Lankan images. |
| Mawiongrim | One CSV: 696 hourly rows, 1–30 December 2022. | **No landslide labels.** Rain in only 13 hours (1.5 max). Soil sensors barely move. |

---

## Dinuka: datasets and GPU training

### D1. Dataset cards and split files
- `DatasetCard` model and one card per dataset with the §5.1 fields: origin, version, DOI/URL, licence,
  coverage, variables, label meaning, missingness, permitted use.
- Commit split files as JSON, created before any tiling or windowing. Use MMFlood's own event split.
- Re-split AIFloodSense so that no flood event is in both train and test.
- **Done when:** a command lists every dataset with its card and every split is committed.

### D2. Radar flood mapping: threshold baseline and U-Net
- Fixed VV backscatter threshold first, then a U-Net with a pretrained encoder and small tiles.
- Inputs: VV/VH, elevation, hydrography. Add a "hydrography present" channel for the 42% of tiles without it.
- Choose the operating threshold on validation data only.
- **Done when:** flood-class IoU and F1 for both, on the same held-out events, with weights stored outside git.

### D3. Ratnapura Sentinel-1 scenes for the Ditwah window
- Search Copernicus for passes over Ratnapura on 26–29 November 2025. Record what exists, including if nothing does.
- Run the trained model over them and export a flood layer for A2.
- Spatial agreement needs independently documented inundation evidence. Gauge timing is not a substitute (§9).
- **Done when:** a flood layer with its acquisition time exists, or the gap is documented and S4 is told.

### D4. Report understanding: classifier and extraction
- Work out what the 9 event columns mean, from the dataset's paper or by inspecting examples.
- Keyword baseline first, then a multilingual transformer. Split by article.
- **Done when:** macro-F1 for both, location and impact precision and recall reported separately, and the
  results are stated as English-only.

Not issued: the flood-photo model. It is first on the proposal's cut list, so it only happens if time is left.

---

## Hasindu: field hardware and sensor data

### H1. Slope tilt driver
- `hardware/README.md` lists the MPU6050 as "driver not written yet", though `tilt` is already a sensor type.
- Add the driver and the config entry, reporting degrees from the installed angle, which is what A1 expects.
- **Done when:** a tilted board produces correct `tilt` readings on the console.

### H2. End-to-end bring-up over LoRa
- Two sensor nodes and one gateway on the bench (§7.2), sending signed frames to ATLAS.
- Confirm that bad signatures and repeated frames are rejected on real radios.
- Fill in the range test and airtime budget that `hardware/lora/README.md` leaves open.
- Check 433 MHz spectrum, power and site permissions before any field deployment (§7.2).
- **Done when:** frames from both nodes reach A1 and link health shows on the console.

### H3. Recorded sensor session as a replay
- Record a bench session with real signals: wet and dry soil, rising water, a tilting slope.
- Save it as a scenario clearly labelled as a bench test, and compare sensor ranges with `data/reference/sensor_map.yaml`.
- **Done when:** the recording replays through A1 and triggers as expected.

### H4. Landslide measurement study (CPU only)
- Use Mawiongrim to forecast a sensor measurement: LightGBM against a "next value equals last value" baseline,
  split by time. Report MAE, RMSE and forecast horizon.
- The dataset has no landslide events, so **do not present this as landslide warning** (§8, §10).
- Write the field-to-feature mapping between Mawiongrim's sensors and ours (§5.2). If a sensor has no equivalent, say so.
- **Done when:** the results and the mapping are committed.

---

## Aeshan: console and map

### U1. Show what kind of information each item is (do this first)
§7.3 requires the interface to separate these. A text search of `frontend/src` finds no "disputed" or
"inferred" anywhere, and no replay clock.
- Label information as observed, inferred, disputed, stale or synthetic, on the map and in evidence panels.
- Separate a proposed plan from an approved action, and a sent message from an acknowledged delivery.
- Show the simulated clock prominently during a replay.
- **Done when:** a Ditwah replay cannot be mistaken for a live emergency, and each map item shows its status.

### U2. Map rework
Inspiration: [gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view). It uses Vue and Cesium and we use
React and MapLibre, so take the ideas rather than the code, and read its licence before copying anything.
- Heads-up display, independently switchable layers, smooth camera moves to a target.
- A roster of what is near a selected point: roads, shelters, teams and gauges near an incident.
- Layers for flood extent, routes with uncertainty, shelter occupancy and sensors.
- The console was deliberately simplified for disaster managers, so keep it readable for them. Advanced 3D is on
  the proposal's cut list and comes after U1.
- **Done when:** a coordinator can go from incident to route, shelter and evidence on the map alone.

### U3. Audit the console against §5.3 and §7.3
- Source health: observation time, arrival time, last successful refresh and source age.
- Incident view: what changed, affected area, conflicting reports, route alternatives, why approval is needed.
- Communication preview: target area, severity, expiry, and text in Sinhala, Tamil and English.
- Shortages shown explicitly, and field-team views for mission tickets and acknowledgements.
- **Done when:** each item is confirmed present or built, with the checklist in the PR.

### U4. Data exploration and model-review views
- Data charts on the `Data` page: flood-pixel imbalance, label distributions, rain and soil relationships (§5.2).
- Model review: drift, candidate against current metrics, shadow results, promotion and rollback history (§7.3).
- Build against S1's API, using clearly marked sample data until real results exist.
- **Done when:** both views show real results from D1, D2 and S3.

---

## Sumudu: agents, model integration and evaluation

### S1. Model registry, `predict()` interface and ledger logging (do this first)
- Each model version records feature schema, dataset versions, metrics, operating threshold and status
  (`candidate`, `shadow`, `live`, `retired`). `atlas/manager/registry.py` tracks agents, so this is new.
- A small `predict()` interface for agents, which reports "no model" rather than guessing.
- Log every prediction to the ledger with its input evidence and model version (§7.1).
- Keep ML libraries in an optional install so the Docker demo stays light.
- **Done when:** a dummy model can be registered, called and traced in the ledger.

### S2. Connect models to the agents
- A2: radar flood layer into road-access evidence for A4.
- A1: report classifier as corroborating evidence.
- Today's rules stay as the fallback and warning floors stay in place. H4's forecasts are not a landslide trigger.
- **Done when:** a replay runs with and without models, and tests cover the fallback.

### S3. A10 Data & Learning agent
- Drift checks on incoming features, shadow runs of a candidate next to the live model, and promotion requests.
- Add `promote_model` to `config/policy.yaml` as always needing human approval, with one-step rollback.
- `policy.yaml` allows only A3 to submit proposals, so decide how A10's request reaches the Gateway.
- A10 must not change live thresholds, policy, model weights or the ledger (§6, §7.1).
- Add a model-promotion attack to the red-team suite.
- **Done when:** unapproved promotions are refused, and rollback works in a test.

### S4. Evaluation
- Strict Ditwah replay: gate each input by when it was actually available, and report reanalysis-assisted results separately (§9).
- Compare warning time with the rule-only baseline. Check the 10.21 m peak and 9.5 m threshold against original station records first.
- Rerun `python -m atlas.benchmark` with models in the loop, and generate model cards from the registry.
- **Done when:** the results table is in the docs with its limits stated.

---

## If time runs short

Cut in this order: flood-photo model, transformer (keep keyword rules), advanced 3D, H3. The core is a
Ratnapura flood scenario, a defensible data pipeline, human approvals, logging and evaluation (§8).
