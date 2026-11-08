# U2 — situation map

Issue: [#10](https://github.com/Wicky2002/modelx-claptac/issues/10). Built on U1's provenance and replay context; review U1 first.

## Design reference

Read the actual [gods-eye-view source](https://github.com/bilawalsidhu/gods-eye-view/tree/52187c91d188504188ea9e9ae33e5b6e24cab7f2) before implementation: `IntelHudView.vue`, `UiPanel.vue`, `LayerPanelsView.vue`, `AwarenessPanel.vue`, `foundation.css`, and `cameraMotion.js`. Adapted its glass HUD, compact information hierarchy, grouped awareness roster, and cancellable camera motion as original React/MapLibre code. No upstream source, assets, datasets, or models were copied. The reference source is MIT licensed; that license does not cover its third-party datasets/assets.

The tactical basemap uses [OpenFreeMap](https://openfreemap.org/quick_start/) vector tiles with an original dark style and visible attribution. Satellite imagery and terrain are optional. Operational road geometry, routes and assets remain available when basemap requests fail.

## Implemented

- Dark command view with situation metrics, layer controls, camera dock, coordinate telemetry, and responsive panels.
- Independent incident, flood-extent, road-uncertainty, route, shelter, fleet, and sensor layers.
- Keyboard-accessible proximity roster measured from a selection, clicked map point, or map centre; groups include roads, shelters, teams and gauges. Distances are straight-line, not travel estimates.
- Incident → mission route → destination shelter → source evidence, without navigating away. Selection remains current across polling; polling does not steal the camera.
- Camera fit, north, satellite, terrain, shareable view coordinates; reduced-motion preference respected and transitions cancelled on a new selection.
- Readable evidence provenance and composable observed/inferred/disputed/stale/synthetic/replay labels inherited from U1.

## Data boundaries

No existing upstream feed supplies flood polygons. Inferred area radii are explicitly **not inundation boundaries**. `/dev/map` accepts valid GeoJSON Polygon/MultiPolygon values from COP beliefs with attribute `flood_extent`, carrying provenance and age into selectable map assessments. Invalid geometry is omitted. Without source geometry, the flood layer says “No geometry supplied” and is disabled.

Shelter capacity and fleet are synthetic reference data. Unknown occupancy stays unknown; expected arrivals are ticket totals, not confirmed movement. Shelter approach evidence concerns roads, not occupancy. Team markers are base locations, not tracking. These are data dependencies, not new integrations or U4 work.

## Verification and screenshots

Backend tests check route-to-incident/destination/evidence links and flood geometry validation. Browser tests use a real isolated FastAPI server and replay: toggle layers, follow the whole map workflow, inspect source evidence, block tiles, verify narrow-screen navigation, and check browser exceptions. The frontend production build is committed.

```sh
source .venv/bin/activate
pytest -q
ruff check atlas tests
cd frontend
npm run build
npx playwright install chromium  # only if no local browser is available
npm run test:e2e
```

For screenshots, set `ATLAS_SCREENSHOT_DIR` and run `npm run test:e2e -- map.spec.ts`. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` optionally selects an installed Chromium browser.

![Command map](screenshots/u2/u2-command-map.png)
![Shelter approach evidence](screenshots/u2/u2-shelter-evidence.png)
![Mobile with unavailable tiles](screenshots/u2/u2-mobile-offline.png)
