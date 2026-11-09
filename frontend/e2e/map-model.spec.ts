import { test, expect } from "@playwright/test";
import { roadState, searchTargets, targets, type MapData, type Road, type Target } from "../src/pages/map/model";

const road: Road = { id: "settled-road", from: [6.68, 80.39], to: [6.69, 80.4], belief_open: .05, confidence: .9, closed_by_decision: false };

test("a settled 5%-passable road remains red when its assessment becomes stale", () => {
  const fresh = roadState(road);
  const staleRoad = { ...road, information: { labels: ["inferred", "stale"], age_seconds: 301 } };
  expect(fresh).toEqual({ label: "Probably closed", color: "#ff6679" });
  expect(roadState(staleRoad)).toEqual({ label: "Probably closed · stale", color: fresh.color });
});

test("staleness still takes precedence for uncertain and probably-open roads", () => {
  for (const belief_open of [.3, .5, .7, .95]) {
    expect(roadState({ ...road, belief_open, information: { labels: ["inferred", "stale"] } }))
      .toEqual({ label: "Stale assessment", color: "#c79c67" });
  }
  expect(roadState({ ...road, belief_open: .3 }).label).toBe("Uncertain");
  expect(roadState({ ...road, belief_open: .7 }).label).toBe("Probably open");
  expect(roadState({ ...road, belief_open: null, information: { labels: ["stale"] } }).label).toBe("No passability evidence");
  expect(roadState({ ...road, closed_by_decision: true, information: { labels: ["stale"] } }))
    .toEqual({ label: "Closure recorded", color: "#ff6679" });
});

test("a shelter name outranks routes to it before the eight-result limit", () => {
  const data: MapData = {
    site: "ratnapura", bounds: [[6.68, 80.39], [6.69, 80.4]], areas: [], teams: [], edges: [], gauges: [],
    likely_closed: 0, observed_edges: 0,
    routes: Array.from({ length: 10 }, (_, i) => ({ mission_id: `mission-${i}`, incident_id: "incident-1", title: "Evacuate", status: "created", team: `Vehicle ${i + 1}`, destination: "Shelter 01", points: [[6.68, 80.39], [6.69, 80.4]] })),
    shelters: [{ id: "shelter-01", name: "Shelter 01", lat: 6.69, lon: 80.4, capacity: 120, occupancy: null, expected: 0, elevation_m: null }],
  };
  const all = targets(data);
  expect(all[0].kind).toBe("route");
  for (const query of ["Shelter 01", "  SHELTER 01  ", "shel"]) {
    const hits = searchTargets(all, query);
    expect(hits).toHaveLength(8);
    expect(hits[0].key).toBe("shelter:shelter-01");
    expect(hits[1].kind).toBe("route");
  }
  expect(all[0].kind).toBe("route"); // Ranking does not reorder the underlying roster.
});

test("search ranks exact titles, prefixes, title substrings, then subtitles", () => {
  const target = (id: string, title: string, subtitle = ""): Target => ({ key: `area:${id}`, id, kind: "area", title, subtitle, point: [6.68, 80.39] });
  const all = [target("subtitle", "River intake", "Shelter 01 access"), target("substring", "Route to Shelter 01"),
    target("prefix", "Shelter 01 annex"), target("exact", "Shelter 01")];
  expect(searchTargets(all, "Shelter 01").map(t => t.id)).toEqual(["exact", "prefix", "substring", "subtitle"]);
  expect(searchTargets(all, " ")).toEqual([]);
  expect(searchTargets(all, "no matching asset")).toEqual([]);
});
