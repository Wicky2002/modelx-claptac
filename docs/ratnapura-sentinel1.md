# Sentinel-1 coverage of Ratnapura during Cyclone Ditwah

Searched on 9 November 2026, for the point 6.68°N, 80.40°E, from 14 November to 11 December 2025, in the
Copernicus Data Space catalogue and the Planetary Computer `sentinel-1-grd` collection. The two agree on
every GRD pass. Times are UTC, and Sri Lanka is 5 h 30 min ahead.

| Pass (UTC) | Satellite | Direction | Polarisation | GRD product | Relation to the flood |
|---|---|---|---|---|---|
| 14 Nov, 00:25 | S1A | Descending | VV, VH | `S1A_IW_GRDH_1SDV_20251114T002540_20251114T002606_061866_07BC30` | 12 days before; same geometry as 26 Nov 00:25 |
| 14 Nov, 12:49 | S1A | Ascending | VV, VH | `S1A_IW_GRDH_1SDV_20251114T124917_20251114T124946_061874_07BC77` | 12 days before; same geometry as 26 Nov 12:49 |
| **26 Nov, 00:25** | S1A | Descending | VV, VH | `S1A_IW_GRDH_1SDV_20251126T002540_20251126T002605_062041_07C2FF` | Inside the window, about two days before the peak |
| **26 Nov, 12:49** | S1A | Ascending | VV, VH | `S1A_IW_GRDH_1SDV_20251126T124916_20251126T124945_062049_07C34E` | Inside the window, under two days before the peak |
| 2 Dec, 00:24 | S1C | Descending | VV, VH | `S1C_IW_GRDH_1SDV_20251202T002429_20251202T002454_005265_00A742` | About four days after the peak |
| 2 Dec, 12:48 | S1C | Ascending | VV, VH | `S1C_IW_GRDH_1SDV_20251202T124832_20251202T124857_005273_00A78E` | About four days after the peak |
| 8 Dec, 00:25 | S1A | Descending | VV, VH | `S1A_IW_GRDH_1SDV_20251208T002539_20251208T002604_062216_07C9DD` | Ten days after the peak |
| 8 Dec, 12:49 | S1A | Ascending | VV, VH | `S1A_IW_GRDH_1SDV_20251208T124915_20251208T124944_062224_07CA2A` | Ten days after the peak |

## What this means

**There was no Sentinel-1 pass between 26 November 12:49 and 2 December 00:24.** The Kalu Ganga at Ratnapura
peaked at 10.21 m on 28 November (`docs/data-and-hazards.md`), so radar did not see the peak.

- A flood layer from 26 November can show early flooding at most. It cannot show peak extent.
- A flood layer from 2 December shows what was still under water about four days later. GDACS kept its flood
  event open until 5 December, but how much water remained at Ratnapura itself is unknown until a scene is read.
- Neither layer can support a claim about flood extent at the gauge peak.

## Consequences for evaluation (S4)

- The strict Ditwah replay (§9) must not use a radar flood layer before its acquisition time, plus processing delay.
- Between 26 November and 2 December, the replay has no radar evidence. It should report that as a gap and fall
  back to today's rules.
- Agreement between a layer and the gauge timing is not spatial validation (§9). That needs independently
  documented inundation evidence, which has not been found yet.
