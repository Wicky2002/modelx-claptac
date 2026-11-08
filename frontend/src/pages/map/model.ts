import type { Information } from "../../components/Information";

export type Point = [number, number]; // latitude, longitude at the API boundary
interface Located { lat: number; lon: number; information?: Information }
export interface Area extends Located { id: string; name: string; population: number | null; vulnerable: number; level: string | null; incident_id: string | null }
export interface Team extends Located { id: string; name: string; kind: string; busy: boolean }
export interface Shelter extends Located { id: string; name: string; capacity: number; occupancy: number | null; expected: number; elevation_m: number | null; approach_evidence_ids?: string[] }
export interface Gauge extends Located { node: string; type: string; value: number; unit: string; threshold: number | null }
export interface Route { mission_id: string; incident_id: string; title: string; status: string; points: Point[]; team?: string; people?: number; destination?: string | null; destination_id?: string | null; progress?: number; acknowledged_at?: string | null; information?: Information; road_ids?: string[] }
export interface Road { id: string; from: Point; to: Point; belief_open: number | null; confidence: number | null; closed_by_decision: boolean; information?: Information }
export interface Extent { id: string; geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon; information?: Information }
export interface MapData { site: string; bounds: [Point, Point]; areas: Area[]; teams: Team[]; edges: Road[]; routes: Route[]; shelters: Shelter[]; gauges: Gauge[]; likely_closed: number; observed_edges: number; flood_extents?: Extent[] }
export type Kind = "area" | "route" | "shelter" | "team" | "gauge" | "road" | "flood";
export interface Target { key: string; kind: Kind; id: string; title: string; subtitle: string; point: Point; information?: Information }
export type Layer = "area" | "road" | "route" | "shelter" | "team" | "gauge" | "flood";
export const LAYERS: { key: Layer; label: string; hint: string; color: string }[] = [
  { key: "area", label: "Areas of concern", hint: "Inferred · approximate radius", color: "#ffab68" },
  { key: "flood", label: "Flood extent", hint: "Source geometry", color: "#45c9f5" },
  { key: "road", label: "Road uncertainty", hint: "Inferred passability", color: "#f4b54f" },
  { key: "route", label: "Mission routes", hint: "Issued tickets · planned paths", color: "#57d8ff" },
  { key: "shelter", label: "Shelter occupancy", hint: "Reported / expected separately", color: "#68e4bf" },
  { key: "team", label: "Teams & vehicles", hint: "Synthetic fleet · base positions", color: "#b8abff" },
  { key: "gauge", label: "Sensors", hint: "Readings + source status", color: "#59c7e5" },
];
export const SENSOR: Record<string, string> = { water_level: "River gauge", rainfall: "Rainfall", soil_moisture: "Soil moisture", tilt: "Ground movement" };
export const SYMBOL: Record<Kind, string> = { area: "△", route: "↗", shelter: "⌂", team: "◇", gauge: "≋", road: "╱", flood: "≈" };
export const percent = (n: number | null | undefined) => n == null ? "Unknown" : `${Math.round(n * 100)}%`;
export function roadState(r: Road) {
  if (r.closed_by_decision) return { label: "Closure recorded", color: "#ff6679" };
  if (r.belief_open == null) return { label: "No passability evidence", color: "#65798c" };
  if (r.information?.labels.includes("stale")) return { label: "Stale assessment", color: "#c79c67" };
  if (r.belief_open < .3) return { label: "Probably closed", color: "#ff6679" };
  if (r.belief_open < .7) return { label: "Uncertain", color: "#f5bd5b" };
  return { label: "Probably open", color: "#64cbb0" };
}
export function metres(a: Point, b: Point) {
  const r = Math.PI / 180;
  const h = Math.sin((b[0] - a[0]) * r / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin((b[1] - a[1]) * r / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}
export const distance = (n: number) => n < 1000 ? `${Math.round(n)} m` : `${(n / 1000).toFixed(1)} km`;
export const midpoint = (a: Point, b: Point): Point => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
export function targets(data: MapData): Target[] {
  const target = (kind: Kind, id: string, title: string, subtitle: string, point: Point, information?: Information): Target => ({ key: `${kind}:${id}`, kind, id, title, subtitle, point, information });
  return [
    ...(data.flood_extents ?? []).map(e => {
      const ring = e.geometry.type === "Polygon" ? e.geometry.coordinates[0] : e.geometry.coordinates[0][0];
      const point: Point = [ring.reduce((n, p) => n + p[1], 0) / ring.length, ring.reduce((n, p) => n + p[0], 0) / ring.length];
      return target("flood", e.id, `Flood extent · ${e.id}`, e.information?.labels.join(" · ") ?? "Source assessment", point, e.information);
    }),
    ...data.areas.map(a => target("area", a.id, a.name, a.level ? `${a.level} · incident` : "No incident recorded", [a.lat, a.lon], a.information)),
    ...data.routes.map(r => target("route", r.mission_id, `${r.team ?? "Mission"} → ${r.destination ?? "standby"}`, r.status.replace(/_/g, " "), r.points[Math.floor(r.points.length / 2)], r.information)),
    ...data.shelters.map(s => target("shelter", s.id, s.name, `${s.occupancy ?? "?"} reported / ${s.capacity} capacity`, [s.lat, s.lon], s.information)),
    ...data.teams.map(t => target("team", t.id, t.name, t.busy ? "Assigned · base position" : "Unassigned · base position", [t.lat, t.lon], t.information)),
    ...data.gauges.map(g => target("gauge", `${g.node}:${g.type}`, SENSOR[g.type] ?? g.type, `${g.value.toFixed(1)} ${g.unit} · ${g.node}`, [g.lat, g.lon], g.information)),
    ...data.edges.map(r => target("road", r.id, `Road ${r.id}`, roadState(r).label, midpoint(r.from, r.to), r.information)),
  ];
}
export function ring([lat, lon]: Point, radius = 650): number[][] {
  return Array.from({ length: 65 }, (_, i) => {
    const t = i / 64 * Math.PI * 2;
    return [lon + radius / (111320 * Math.cos(lat * Math.PI / 180)) * Math.cos(t), lat + radius / 110540 * Math.sin(t)];
  });
}
