import { useEffect, useMemo, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import { usePoll, type Approval } from "../api";
import { InformationBadges, InformationDetail, type Information } from "../components/Information";
import { Json } from "../components/Json";
import { missionStatus } from "../plain";
import { distance, LAYERS, metres, percent, roadState, SYMBOL, targets, type Kind, type Layer, type MapData, type Point, type Target } from "./map/model";
import { useScene } from "./map/useScene";
import "./map/command-map.css";

const DEFAULT_LAYERS: Record<Layer, boolean> = { area: true, flood: true, road: true, route: true, shelter: true, team: true, gauge: true };
const GROUPS: { kind: Kind; label: string }[] = [
  { kind: "area", label: "Incidents & areas" }, { kind: "route", label: "Mission routes" },
  { kind: "shelter", label: "Shelters" }, { kind: "team", label: "Teams & vehicles" },
  { kind: "gauge", label: "Sensors" }, { kind: "road", label: "Roads" },
  { kind: "flood", label: "Flood extent assessments" },
];

export function MapPage() {
  const { data, error } = usePoll<MapData>("/dev/map", 4000);
  const approvals = usePoll<Approval[]>("/approvals", 5000);
  const [layers, setLayers] = useState(DEFAULT_LAYERS);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [pin, setPin] = useState<Point | null>(null);
  const [path, setPath] = useState<string[]>([]);
  const [satellite, setSatellite] = useState(false);
  const [terrain, setTerrain] = useState(false);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"nearby" | "details">("nearby");
  const [mobilePanel, setMobilePanel] = useState<"layers" | "intel" | null>(null);
  const [copied, setCopied] = useState(false);
  const [shareError, setShareError] = useState("");
  const all = useMemo(() => data ? targets(data) : [], [data]);
  const selected = all.find(t => t.key === selectedKey);
  function choose(key: string | null, point?: Point) {
    setSelectedKey(key); setPin(point ?? null); setTab(key ? "details" : "nearby");
    if (key) setPath(old => [...old.filter(k => k !== key), key].slice(-4)); else setPath([]);
    if (key) setMobilePanel("intel");
  }
  const scene = useScene(data, layers, selected, choose, satellite, terrain);
  const anchor: Point = selected?.point ?? pin ?? [scene.view.lat, scene.view.lon];
  const nearby = useMemo(() => all.map(t => ({ ...t, distance: metres(anchor, t.point) })).sort((a, b) => a.distance - b.distance), [all, anchor[0], anchor[1]]);
  const hits = query.trim() ? all.filter(t => `${t.title} ${t.subtitle}`.toLowerCase().includes(query.toLowerCase())).slice(0, 8) : [];
  const active = data?.routes.filter(r => !["completed", "cancelled", "failed"].includes(r.status)) ?? [];
  const incident = data?.areas.find(a => a.incident_id);
  const uncertain = data?.edges.filter(e => e.belief_open != null && e.belief_open >= .3 && e.belief_open < .7).length ?? 0;
  const river = data?.gauges.find(g => g.type === "water_level");
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  function fit() {
    choose(null); const map = scene.map.current;
    if (data && map) map.fitBounds(data.bounds.map(([lat, lon]) => [lon, lat]) as [[number, number], [number, number]], { padding: 100, duration: reduced() ? 0 : 1100, bearing: 0 });
  }
  async function share() {
    const map = scene.map.current; if (!map) return;
    const c = map.getCenter();
    const hash = `#/map?c=${c.lat.toFixed(5)},${c.lng.toFixed(5)}&z=${map.getZoom().toFixed(2)}`;
    try { await navigator.clipboard.writeText(`${location.origin}${location.pathname}${hash}`); setCopied(true); setShareError(""); }
    catch { setShareError("Clipboard unavailable. The address bar now contains this view."); }
    history.replaceState(null, "", hash);
  }
  function search(e: React.FormEvent) {
    e.preventDefault();
    const point = query.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
    if (point) {
      const lat = Number(point[1]), lon = Number(point[2]);
      if (Math.abs(lat) <= 85 && Math.abs(lon) <= 180) { choose(null, [lat, lon]); scene.map.current?.flyTo({ center: [lon, lat], zoom: 15, duration: reduced() ? 0 : 1000 }); setQuery(""); }
    } else if (hits[0]) { choose(hits[0].key); setQuery(""); }
  }
  const row = (t: Target, trailing?: string) => <button key={t.key} className={`asset-row ${selectedKey === t.key ? "selected" : ""}`} onClick={() => { choose(t.key); setQuery(""); }}>
    <span className={`asset-icon icon-${t.kind}`}>{SYMBOL[t.kind]}</span><span className="asset-text"><b>{t.title}</b><small>{t.subtitle}</small></span><span className="asset-distance">{trailing ?? "↗"}</span>
  </button>;

  return <div className="command-map" aria-label="Situation map command view">
    <div ref={scene.container} className="scene-canvas" />
    <div className="scene-vignette" aria-hidden="true" />
    <div className="scene-grid" aria-hidden="true" />
    <header className="command-header">
      <div className="command-identity"><span className="eye-mark" aria-hidden="true">◎</span><div><small>ATLAS / SITUATIONAL AWARENESS</small><h1>{data?.site ?? "Connecting"}<span> / operations</span></h1></div></div>
      <form className="command-search" onSubmit={search}><span aria-hidden="true">⌕</span><input aria-label="Search the map" placeholder="Find an incident, shelter, team or coordinates" value={query} onChange={e => setQuery(e.target.value)} /><kbd>↵</kbd>
        {query && <div className="search-results">{hits.map(t => row(t))}{!hits.length && <p>No matching assets. Try latitude, longitude.</p>}</div>}
      </form>
      <div className="connection-readout"><i className={error ? "lost" : ""} /><span>{error ? "CONNECTION LOST" : data ? "COP CONNECTED" : "CONNECTING"}<small>{data ? `${data.edges.length} road segments · refresh 4s` : "Waiting for operating picture"}</small></span></div>
    </header>

    <div className="mobile-map-tabs"><button aria-pressed={mobilePanel === "layers"} onClick={() => setMobilePanel(mobilePanel === "layers" ? null : "layers")}>Layers & situation</button><button aria-pressed={mobilePanel === "intel"} onClick={() => setMobilePanel(mobilePanel === "intel" ? null : "intel")}>Nearby & details</button></div>
    <aside className={`command-left ${mobilePanel === "layers" ? "mobile-open" : ""}`} aria-label="Situation and layers">
      <section className="glass-panel situation-panel">
        <div className="panel-kicker"><span>01 / SITUATION</span><span className="signal-bars" aria-hidden="true">▂▄▆</span></div>
        <div className="situation-level"><span className="severity-orb" /><div><small>AREA ASSESSMENT</small><h2>{incident?.level ?? "Unassessed"}</h2></div></div>
        <p>{incident?.name ?? "Select an area to inspect its evidence."}</p>
        <div className="situation-metrics"><div><b>{data?.likely_closed ?? "—"}</b><small>likely closed roads</small></div><div><b>{uncertain}</b><small>uncertain roads</small></div><div><b>{active.length}</b><small>active mission tickets</small></div><div><b>{data?.shelters.length ?? "—"}</b><small>reference shelters</small></div></div>
        {river && <div className="gauge-readout"><span>RIVER INPUT <InformationBadges info={river.information} /></span><strong>{river.value.toFixed(1)}<small> {river.unit}</small></strong><div className="gauge-meter"><i style={{ width: `${Math.min(100, river.value / Math.max(river.threshold ?? 1, 1) * 65)}%` }} /></div><small>Scenario input units · inspect source before use</small></div>}
        {!!approvals.data?.length && <a className="decision-link" href="#/decisions"><span>{approvals.data.length} decisions awaiting approval</span><b>↗</b></a>}
      </section>
      <section className="glass-panel layer-panel">
        <div className="panel-kicker"><span>02 / MAP LAYERS</span><span>{Object.values(layers).filter(Boolean).length - (!(data?.flood_extents?.length) && layers.flood ? 1 : 0)} ON</span></div>
        {LAYERS.map(l => { const unavailable = l.key === "flood" && !data?.flood_extents?.length; return <button key={l.key} className={`layer-control ${layers[l.key] && !unavailable ? "enabled" : ""}`} disabled={unavailable} aria-pressed={layers[l.key] && !unavailable} aria-label={l.label} onClick={() => setLayers(old => ({ ...old, [l.key]: !old[l.key] }))}>
          <i className="layer-dot" style={{ background: l.color }} /><span><b>{l.label}</b><small>{unavailable ? "No geometry supplied" : l.hint}</small></span><i className="layer-switch" aria-hidden="true" />
        </button>; })}
      </section>
      <div className="map-key"><span><i style={{ background: "#64cbb0" }} />Probably open</span><span><i style={{ background: "#f5bd5b" }} />Uncertain</span><span><i style={{ background: "#ff6679" }} />Probably closed</span><p>Road state is inferred. Dashed areas are not flood extent.</p></div>
    </aside>

    <aside className={`command-right glass-panel ${mobilePanel === "intel" ? "mobile-open" : ""}`} aria-label="Map intelligence">
      <div className="panel-kicker"><span>03 / LOCAL INTELLIGENCE</span><span>⌖</span></div>
      <div className="intel-tabs"><button aria-pressed={tab === "nearby"} onClick={() => setTab("nearby")}>Proximity roster</button><button aria-pressed={tab === "details"} disabled={!selected} onClick={() => setTab("details")}>Selected asset</button><button className="mobile-close" onClick={() => setMobilePanel(null)} aria-label="Close map panel">×</button></div>
      {tab === "nearby" ? <div className="intel-scroll nearby-roster"><div className="roster-anchor"><small>MEASURED FROM</small><b>{selected?.title ?? (pin ? "Selected map point" : "Map centre")}</b><span>{anchor[0].toFixed(5)}° N / {anchor[1].toFixed(5)}° E</span></div>
        {GROUPS.map(g => <section className="roster-group" key={g.kind}><h3>{g.label}<span>{all.filter(t => t.kind === g.kind).length}</span></h3>{nearby.filter(t => t.kind === g.kind).slice(0, 3).map(t => row(t, distance(t.distance)))}{!all.some(t => t.kind === g.kind) && <p className="map-empty">None recorded</p>}</section>)}
        <p className="map-fineprint">Straight-line proximity, not travel time. Teams are shown at their bases.</p>
      </div> : selected && data ? <div className="intel-scroll map-inspector">
        <nav className="map-breadcrumbs" aria-label="Map selection history">{path.map((k, i) => { const t = all.find(a => a.key === k); return t && <button key={k} onClick={() => choose(k)}>{i > 0 && "› "}{t.kind === "area" ? "Incident" : t.kind === "route" ? "Route" : t.title}</button>; })}</nav>
        <div className="asset-heading"><span className={`asset-icon icon-${selected.kind}`}>{SYMBOL[selected.kind]}</span><div><small>{selected.kind.toUpperCase()}</small><h2>{selected.title}</h2></div><button aria-label="Clear selection" onClick={() => choose(null)}>×</button></div>
        {!layers[selected.kind] && <p className="map-notice">This asset’s map layer is hidden.</p>}
        <AssetDetails key={selected.key} target={selected} data={data} choose={choose} />
      </div> : <p className="map-empty">Select an asset from the map or proximity roster.</p>}
    </aside>

    <div className="map-reticle" aria-hidden="true"><span /><small>AREA OF OPERATIONS</small></div>
    {(error || scene.sceneError || scene.tileError) && <div className="scene-warning" role="status">{error ? `Updates unavailable. Displaying last received data. ${error}` : scene.sceneError ?? "Some basemap tiles are unavailable. Operational overlays remain visible."}</div>}
    <div className="camera-dock" aria-label="Map camera controls">
      <button onClick={fit} title="Fit the whole area">⌗ <span>Fit area</span></button>
      <button onClick={() => scene.map.current?.easeTo({ bearing: 0, duration: reduced() ? 0 : 800 })} title="Point the camera north">↑ <span>North</span></button>
      <i />
      <button aria-pressed={!satellite} onClick={() => setSatellite(false)}>Tactical</button><button aria-pressed={satellite} onClick={() => setSatellite(true)}>Satellite</button>
      <i /><button aria-pressed={terrain} onClick={() => setTerrain(!terrain)}>{terrain ? "◈ 3D terrain" : "◇ 2D view"}</button>
      <button onClick={() => void share()}>{copied ? "✓ Copied" : "↗ Share"}</button>
    </div>
    {shareError && <div className="share-note" role="status">{shareError}</div>}
    <footer className="map-telemetry"><span><i /> ATLAS / COMMON OPERATING PICTURE</span><span>{scene.view.lat.toFixed(5)}° N <b> / </b>{scene.view.lon.toFixed(5)}° E</span><span>ZOOM {scene.view.zoom.toFixed(1)} <b> / </b> HDG {Math.round((scene.view.bearing + 360) % 360)}°</span></footer>
  </div>;
}

function AssetDetails({ target: t, data, choose }: { target: Target; data: MapData; choose: (key: string) => void }) {
  const [evidence, setEvidence] = useState<string | null>(null);
  let body: React.ReactNode = null;
  let refs = t.information?.evidence_ids ?? [];
  let evidenceTitle = "Source evidence";
  const jump = (key: string, label: string, sub?: string) => <button key={key} className="detail-link" onClick={() => choose(key)}><span>{label}<small>{sub}</small></span><b>↗</b></button>;
  if (t.kind === "area") {
    const a = data.areas.find(a => a.id === t.id)!;
    const routes = data.routes.filter(r => r.incident_id === a.incident_id);
    body = <><div className="detail-stats"><div><small>ASSESSMENT</small><b>{a.level ?? "Unknown"}</b></div><div><small>POPULATION · SYNTHETIC</small><b>{a.population?.toLocaleString() ?? "Unknown"}</b></div></div><p>Approximate area of concern. The radius does not represent measured inundation.</p><h3>Response routes <span>{routes.length}</span></h3>{routes.map(r => jump(`route:${r.mission_id}`, r.destination ?? r.title, `${r.team ?? "Team"} · ${missionStatus(r.status)}`))}{!routes.length && <p className="map-empty">No issued mission route recorded for this incident.</p>}</>;
  } else if (t.kind === "route") {
    const r = data.routes.find(r => r.mission_id === t.id)!;
    body = <><div className="route-status">{missionStatus(r.status)}</div><p>{r.title}</p><dl><dt>Assigned people</dt><dd>{r.people ?? "Not recorded"}</dd><dt>Progress reported</dt><dd>{r.progress ?? 0}%</dd><dt>Team acknowledgement</dt><dd>{r.acknowledged_at ? new Date(r.acknowledged_at).toLocaleString() : "Awaiting confirmation"}</dd></dl>
      {r.destination_id && jump(`shelter:${r.destination_id}`, `Inspect ${r.destination ?? "destination shelter"}`, "Occupancy, expected arrivals and approach evidence")}
      <h3>Road evidence</h3>{data.edges.filter(e => r.road_ids?.includes(e.id)).sort((a, b) => (a.belief_open ?? .5) - (b.belief_open ?? .5)).slice(0, 3).map(e => jump(`road:${e.id}`, roadState(e).label, `${percent(e.belief_open)} passable · ${percent(e.confidence)} confidence`))}</>;
  } else if (t.kind === "shelter") {
    const s = data.shelters.find(s => s.id === t.id)!;
    body = <><div className="occupancy-display"><strong>{s.occupancy ?? "?"}<span> / {s.capacity}</span></strong><small>reported occupancy / synthetic capacity</small><div className={`occupancy-meter ${s.occupancy == null ? "unknown" : ""}`}><i style={{ width: `${Math.min(100, (s.occupancy ?? 0) / Math.max(s.capacity, 1) * 100)}%` }} /></div></div><dl><dt>Expected on mission tickets</dt><dd>{s.expected}</dd><dt>Available after arrivals</dt><dd>{s.occupancy == null ? "Unknown until occupancy is reported" : s.capacity - s.occupancy - s.expected}</dd><dt>Reference elevation</dt><dd>{s.elevation_m == null ? "Unknown" : `${Math.round(s.elevation_m)} m`}</dd></dl><p>Expected arrivals do not confirm departure or arrival.</p></>;
    refs = [...new Set([...refs, ...(s.approach_evidence_ids ?? [])])]; evidenceTitle = "Approach evidence · not an occupancy report";
  } else if (t.kind === "gauge") {
    const g = data.gauges.find(g => `${g.node}:${g.type}` === t.id)!;
    body = <><div className="sensor-value">{g.value.toFixed(1)}<small>{g.unit}</small></div><p>{g.node}</p><p>Configured threshold: {g.threshold ?? "not configured"} {g.unit}. During replay these may be rescaled scenario units.</p></>;
  } else if (t.kind === "flood") {
    body = <p>Source-supplied polygon assessment. Its boundary is not a safe-travel boundary. Check provenance, age and disagreements before using it.</p>;
  } else if (t.kind === "team") {
    const team = data.teams.find(x => x.id === t.id)!;
    body = <><div className="route-status">{team.busy ? "Assigned to a mission" : "No active assignment"}</div><p>Synthetic {team.kind}. This location is its reference base, not a real-time position.</p></>;
  } else {
    const r = data.edges.find(r => r.id === t.id)!;
    body = <><h3 style={{ color: roadState(r).color }}>{roadState(r).label}</h3><dl><dt>Passability belief</dt><dd>{percent(r.belief_open)}</dd><dt>Confidence</dt><dd>{percent(r.confidence)}</dd></dl><p>A road assessment inferred from nearby observations is not a field clearance.</p></>;
  }
  return <>{body}<InformationDetail info={t.information} /><section className="map-evidence"><h3>{evidenceTitle}</h3>{refs.slice(0, 12).map((ref, i) => <button key={ref} className="detail-link" onClick={() => setEvidence(ref)}><span>Observation {i + 1}<small>{ref.slice(0, 16)}…</small></span><span>↗</span></button>)}{!refs.length && <p className="map-empty">No observation evidence is linked. Reference assumptions are described above.</p>}{refs.length > 12 && <p className="map-fineprint">Showing 12 of {refs.length} linked observations.</p>}</section>{evidence && <EvidenceView key={evidence} id={evidence} close={() => setEvidence(null)} />}</>;
}

function EvidenceView({ id, close }: { id: string; close: () => void }) {
  const { data, error } = usePoll<{ source: string; payload: Record<string, unknown>; information: Information }>(`/dev/evidence/${encodeURIComponent(id)}`, 0);
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    const panel = card.current?.closest(".intel-scroll");
    if ((data || error) && panel && card.current) panel.scrollTop += card.current.getBoundingClientRect().top - panel.getBoundingClientRect().top;
  }, [data, error]);
  return <section ref={card} className="evidence-card" aria-label="Observation evidence"><div className="panel-kicker"><span>OBSERVATION EVIDENCE</span><button onClick={close} aria-label="Close evidence">×</button></div>{error ? <p role="alert">{error}</p> : data ? <><h3>{data.source}</h3><InformationDetail info={data.information} /><Json value={data.payload} /></> : <p>Loading source record…</p>}</section>;
}
