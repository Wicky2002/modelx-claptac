# H4: forecasting a slope sensor on Mawiongrim (CPU only)

**This is sensor forecasting, not landslide warning.** The Mawiongrim file has no landslide events (§8, §10).

```
python -m training.sensors.forecast --csv <mawiongrim.csv> --out <dir>
```

## Set-up

- **Data:** Mawiongrim, Meghalaya, 696 hourly rows, 1–30 December 2022 (`atlas/datasets/cards/mawiongrim.yaml`).
- **Splits:** by time, from `data/splits/mawiongrim.json`: the first 70% of hours for training, the next 15% for
  validation, the last 15% for test. Features are built inside each split, so no window crosses a boundary.
- **Targets:** the 30 m upslope inclinometer (the nearest thing to our tilt sensor) and water level, 1, 3 and
  6 hours ahead.
- **Features:** the last 6 hours of every sensor, the target's 1 h and 3 h change, and hour of day.
- **Model:** LightGBM predicting the change from now, with fixed settings and seed 0. It is compared with
  persistence, which says the next value equals the last.
- **Test:** scored once, after the settings were fixed.

## Results

Units are as in the file, which does not state them.

| Target | Horizon | Persistence MAE / RMSE (test) | LightGBM MAE / RMSE (test) | Validation, LightGBM vs persistence MAE |
|---|---|---|---|---|
| Inclinometer 30 m up | 1 h | **5.25** / **8.44** | 6.67 / 9.33 | 5.17 vs 6.79 |
| Inclinometer 30 m up | 3 h | **8.60** / 14.25 | 9.94 / **13.65** | 5.93 vs 11.87 |
| Inclinometer 30 m up | 6 h | 10.95 / 17.66 | **10.71** / **13.87** | 6.14 vs 15.21 |
| Water level | 1 h | **156.9** / **249.8** | 194.2 / 279.6 | 143.9 vs 173.0 |
| Water level | 3 h | **243.5** / 389.2 | 261.7 / **348.5** | 167.8 vs 316.4 |
| Water level | 6 h | 282.1 / 437.4 | **265.6** / **352.9** | 159.6 vs 360.8 |

Test has 94–99 rows per case.

## What this shows

- **Validation suggested a large gain, and it did not hold on test.**
  - At 1 hour, persistence is better on test.
  - At 6 hours, LightGBM cuts RMSE by about 20% and is level on MAE. That means it avoids the large misses
    persistence makes, but is no better on typical hours.
- **Reasons:**
  - One month at one site, with rain in only 13 hours, is too little to learn sensor dynamics.
  - The last five days, the test split, behave differently from the rest.
- **Conclusion:** for our own tilt and water readings, A1's threshold and rate-of-rise rules stay the
  baseline. A learned forecast needs longer records and real slope-failure events before it could inform
  a trigger.

## Mapping Mawiongrim's sensors to ours

| Mawiongrim | ATLAS sensor | Match |
|---|---|---|
| Rainfall | `rainfall` (tipping bucket, mm) | Same quantity; Mawiongrim's unit is not stated |
| Water level | `water_level` (ultrasonic, cm) | Same quantity, different meaning: theirs is groundwater or drainage at a slope (range −573 to 1023, unit not stated), ours is river or container depth |
| Inclinometers at 10, 20 and 30 m, up and down | `tilt` (degrees) | Partial. Theirs are borehole inclinometers at depth; our H1 tilt sensor is a surface tilt board. Same kind of signal, not the same instrument |
| Five tensiometers | `soil_moisture` (capacitive, %) | Partial. Tensiometers measure soil suction, ours measures moisture content. Related but not convertible without a soil-water curve |
| None | `temperature`, `humidity`, `pressure` (BME280) | No equivalent in Mawiongrim |
