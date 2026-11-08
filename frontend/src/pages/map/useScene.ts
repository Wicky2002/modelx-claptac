import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import { ring, roadState, SYMBOL, targets, type Layer, type MapData, type Point, type Target } from "./model";

const empty: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const coord = ([lat, lon]: Point): [number, number] => [lon, lat];
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export function useScene(data: MapData | null, layers: Record<Layer, boolean>, selected: Target | undefined,
  select: (key: string | null, point?: Point) => void, satellite: boolean, terrain: boolean) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState({ lat: 6.6828, lon: 80.3992, zoom: 14, bearing: 0 });
  const [tileError, setTileError] = useState(false);
  const [sceneError, setSceneError] = useState<string | null>(null);
  const callbacks = useRef({ select }); callbacks.current = { select };
  const markerRefs = useRef(new Map<string, maplibregl.Marker>());
  const fitted = useRef(false);
  const restored = useRef(false);
  useEffect(() => {
    if (!container.current) return;
    const query = new URLSearchParams(window.location.hash.split("?")[1]);
    const center = query.get("c")?.split(",").map(Number);
    const valid = center?.length === 2 && center.every(Number.isFinite) && Math.abs(center[0]) <= 85 && Math.abs(center[1]) <= 180;
    restored.current = !!valid;
    let scene: maplibregl.Map;
    try {
      scene = new maplibregl.Map({
        container: container.current, center: valid ? [center[1], center[0]] : [80.3992, 6.6828],
        zoom: valid ? Math.max(4, Math.min(19, Number(query.get("z")) || 14)) : 14,
        pitch: 0, bearing: 0, maxPitch: 65,
        attributionControl: { compact: false },
        style: { version: 8, glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf", sources: {
          base: { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: '<a href="https://openfreemap.org/">OpenFreeMap</a> © <a href="https://openmaptiles.org/">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' },
          satellite: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" },
          dem: { type: "raster-dem", tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"], tileSize: 256, encoding: "terrarium", maxzoom: 15, attribution: "Terrain: Mapzen / AWS Open Data" },
        }, layers: [
          { id: "background", type: "background", paint: { "background-color": "#0a141b" } },
          { id: "base-land", type: "fill", source: "base", "source-layer": "landcover", paint: { "fill-color": "#12251f", "fill-opacity": .6 } },
          { id: "base-water", type: "fill", source: "base", "source-layer": "water", paint: { "fill-color": "#153646" } },
          { id: "base-waterway", type: "line", source: "base", "source-layer": "waterway", paint: { "line-color": "#21485b", "line-width": 2 } },
          { id: "base-building", type: "fill", source: "base", "source-layer": "building", paint: { "fill-color": "#253540", "fill-opacity": .6 } },
          { id: "base-roads", type: "line", source: "base", "source-layer": "transportation", paint: { "line-color": "#334753", "line-width": ["interpolate", ["linear"], ["zoom"], 10, .5, 17, 3] } },
          { id: "base-road-label", type: "symbol", source: "base", "source-layer": "transportation_name", layout: { "symbol-placement": "line", "text-field": ["coalesce", ["get", "name_en"], ["get", "name"]], "text-font": ["Noto Sans Regular"], "text-size": 10 }, paint: { "text-color": "#92a4ac", "text-halo-color": "#0a141b", "text-halo-width": 2 } },
          { id: "base-place", type: "symbol", source: "base", "source-layer": "place", layout: { "text-field": ["coalesce", ["get", "name_en"], ["get", "name"]], "text-font": ["Noto Sans Regular"], "text-size": 12 }, paint: { "text-color": "#a7b8be", "text-halo-color": "#0a141b", "text-halo-width": 2 } },
          { id: "satellite", type: "raster", source: "satellite", layout: { visibility: "none" }, paint: { "raster-saturation": -.45, "raster-brightness-max": .6 } },
        ] },
      });
    } catch {
      setSceneError("The map renderer is unavailable. Use the asset list to inspect the same operational data.");
      return;
    }
    map.current = scene;
    scene.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    scene.on("error", e => { if ("sourceId" in e) setTileError(true); });
    scene.on("moveend", () => { const c = scene.getCenter(); setView({ lat: c.lat, lon: c.lng, zoom: scene.getZoom(), bearing: scene.getBearing() }); });
    scene.on("click", e => {
      if (!scene.getLayer("route-hit")) return;
      const hits = scene.queryRenderedFeatures(e.point, { layers: ["route-hit", "road-hit", "flood-fill", "area-fill"] });
      const hit = hits[0];
      if (hit?.properties?.key) callbacks.current.select(String(hit.properties.key));
      else callbacks.current.select(null, [e.lngLat.lat, e.lngLat.lng]);
    });
    scene.once("style.load", () => {
      for (const id of ["area", "flood", "road", "route"]) scene.addSource(id, { type: "geojson", data: empty });
      scene.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": "#ff9860", "fill-opacity": .07 } });
      scene.addLayer({ id: "area-outline", type: "line", source: "area", paint: { "line-color": "#f8b36c", "line-width": 1.5, "line-dasharray": [3, 3], "line-opacity": .6 } });
      scene.addLayer({ id: "flood-fill", type: "fill", source: "flood", paint: { "fill-color": "#35bdf3", "fill-opacity": .25 } });
      scene.addLayer({ id: "flood-outline", type: "line", source: "flood", paint: { "line-color": "#54d4ff", "line-width": 2, "line-dasharray": [3, 2] } });
      scene.addLayer({ id: "road-line", type: "line", source: "road", paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1, 17, 3], "line-opacity": ["get", "opacity"] } });
      scene.addLayer({ id: "road-hit", type: "line", source: "road", paint: { "line-width": 14, "line-opacity": 0 } });
      scene.addLayer({ id: "route-glow", type: "line", source: "route", paint: { "line-color": "#21c5ff", "line-width": 12, "line-blur": 6, "line-opacity": .55 } });
      scene.addLayer({ id: "route-line", type: "line", source: "route", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#72dfff", "line-width": 3, "line-dasharray": [4, 2] } });
      scene.addLayer({ id: "route-hit", type: "line", source: "route", paint: { "line-width": 20, "line-opacity": 0 } });
      scene.addLayer({ id: "selected-route", type: "line", source: "route", filter: ["==", ["get", "key"], ""], paint: { "line-color": "#f6f6d4", "line-width": 4 } });
      for (const id of ["route-hit", "road-hit", "area-fill"]) {
        scene.on("mouseenter", id, () => { scene.getCanvas().style.cursor = "pointer"; });
        scene.on("mouseleave", id, () => { scene.getCanvas().style.cursor = ""; });
      }
      setReady(true);
    });
    const observer = new ResizeObserver(() => scene.resize()); observer.observe(container.current);
    return () => { observer.disconnect(); markerRefs.current.clear(); scene.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const scene = map.current;
    if (!scene || !ready || !data) return;
    const put = (id: string, features: GeoJSON.Feature[]) => (scene.getSource(id) as GeoJSONSource).setData({ type: "FeatureCollection", features });
    put("road", data.edges.map(r => ({ type: "Feature", properties: { key: `road:${r.id}`, color: roadState(r).color, opacity: r.belief_open == null ? .2 : .35 + .55 * (r.confidence ?? .3) }, geometry: { type: "LineString", coordinates: [coord(r.from), coord(r.to)] } })));
    put("route", data.routes.filter(r => !["completed", "cancelled", "failed"].includes(r.status)).map(r => ({ type: "Feature", properties: { key: `route:${r.mission_id}` }, geometry: { type: "LineString", coordinates: r.points.map(coord) } })));
    put("area", data.areas.filter(a => a.incident_id).map(a => ({ type: "Feature", properties: { key: `area:${a.id}` }, geometry: { type: "Polygon", coordinates: [ring([a.lat, a.lon])] } })));
    put("flood", (data.flood_extents ?? []).map(e => ({ type: "Feature", properties: { key: `flood:${e.id}` }, geometry: e.geometry })));
    if (!fitted.current && !restored.current) { scene.fitBounds([coord(data.bounds[0]), coord(data.bounds[1])], { padding: 100, duration: 0 }); fitted.current = true; }
    const wanted = new Set<string>();
    const stack = new Map<string, number>();
    for (const t of targets(data).filter(t => !["road", "route", "flood"].includes(t.kind))) {
      wanted.add(t.key);
      let marker = markerRefs.current.get(t.key);
      if (!marker) {
        const button = document.createElement("button");
        button.type = "button";
        button.addEventListener("click", e => { e.stopPropagation(); callbacks.current.select(t.key); });
        marker = new maplibregl.Marker({ element: button, anchor: "center" }).setLngLat(coord(t.point)).addTo(scene);
        markerRefs.current.set(t.key, marker);
      }
      const spot = t.point.map(n => n.toFixed(4)).join(","), slot = stack.get(spot) ?? 0;
      stack.set(spot, slot + 1);
      marker.setLngLat(coord(t.point)).setOffset(slot ? [Math.cos(slot * 2.4) * (24 + slot * 10), Math.sin(slot * 2.4) * (24 + slot * 10)] : [0, 0]);
      const el = marker.getElement();
      el.className = `scene-marker marker-${t.kind}`;
      el.setAttribute("aria-label", `${t.title} · ${t.information?.labels.join(", ") ?? "unknown status"}`);
      el.title = `${t.title} · ${t.subtitle}`;
      // DOM text avoids interpreting source-provided labels as markup.
      el.replaceChildren();
      const icon = document.createElement("span"); icon.className = "marker-symbol"; icon.textContent = SYMBOL[t.kind]; el.append(icon);
      const label = document.createElement("span"); label.className = "marker-label"; label.textContent = t.title; el.append(label);
      const tag = document.createElement("small"); tag.className = "marker-status"; tag.textContent = t.information?.labels.join(" · ") ?? "unknown"; el.append(tag);
    }
    for (const [key, marker] of markerRefs.current) if (!wanted.has(key)) { marker.remove(); markerRefs.current.delete(key); }
  }, [data, ready]);

  useEffect(() => {
    const scene = map.current;
    if (!scene || !ready) return;
    const groups: Partial<Record<Layer, string[]>> = { area: ["area-fill", "area-outline"], flood: ["flood-fill", "flood-outline"], road: ["road-line", "road-hit"], route: ["route-line", "route-glow", "route-hit", "selected-route"] };
    for (const [key, ids] of Object.entries(groups)) for (const id of ids) scene.setLayoutProperty(id, "visibility", layers[key as Layer] ? "visible" : "none");
    for (const [key, marker] of markerRefs.current) {
      const kind = key.split(":")[0] as Layer;
      marker.getElement().hidden = !layers[kind];
      marker.getElement().classList.toggle("is-selected", selected?.key === key);
    }
    scene.setFilter("selected-route", ["==", ["get", "key"], selected?.key ?? ""]);
  }, [layers, selected?.key, data, ready]);

  useEffect(() => {
    const scene = map.current;
    if (!scene || !ready) return;
    scene.setLayoutProperty("satellite", "visibility", satellite ? "visible" : "none");
    for (const layer of scene.getStyle().layers) if (layer.id.startsWith("base-")) scene.setLayoutProperty(layer.id, "visibility", satellite ? "none" : "visible");
    scene.setTerrain(terrain ? { source: "dem", exaggeration: 1.25 } : null);
    scene.easeTo({ pitch: terrain ? 45 : 0, duration: reduced() ? 0 : 900 });
  }, [satellite, terrain, ready]);

  // Selection is an ID, so refreshed data does not steal the camera every four seconds.
  useEffect(() => {
    const scene = map.current;
    if (!scene || !ready || !selected) return;
    scene.stop();
    if (selected.kind === "route") {
      const route = data?.routes.find(r => r.mission_id === selected.id);
      if (!route) return;
      const bounds = new maplibregl.LngLatBounds(); route.points.forEach(p => bounds.extend(coord(p)));
      const wide = scene.getContainer().clientWidth > 1100;
      scene.fitBounds(bounds, { padding: wide ? { left: 320, right: 380, top: 130, bottom: 120 } : 80, maxZoom: 16, duration: reduced() ? 0 : 1300 });
    } else scene.flyTo({ center: coord(selected.point), zoom: selected.kind === "area" ? 14.8 : 16, duration: reduced() ? 0 : 1300, essential: false });
  }, [selected?.key, ready]);

  return { container, map, view, ready, tileError, sceneError };
}
