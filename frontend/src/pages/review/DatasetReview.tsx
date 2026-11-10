import { useState } from "react";
import { usePoll } from "../../api";
import { Empty, Mode, number, ProvenanceLine, Refresh } from "./Common";
import type { DataReview, Profile } from "./types";

function ProfileCharts({ profile: p }: { profile: Profile }) {
  const f = p.flood_pixels;
  const total = f ? f.flood + f.non_flood : 0;
  const max = Math.max(1, ...p.labels.map(l => l.count));
  return <>
    <ProvenanceLine item={p} />
    <div className="review-grid">
      {f && <section className="card"><h2>Flood-pixel imbalance</h2>
        {total ? <><div className="review-stat">{(100 * f.flood / total).toFixed(2)}% <span>flood among valid pixels</span></div>
          <svg viewBox="0 0 600 44" role="img" aria-label={`${f.flood} flood pixels and ${f.non_flood} non-flood pixels`}><rect width="600" height="36" rx="5" fill="var(--line)"/><rect width={600 * f.flood / total} height="36" rx="5" fill="#287fb8"/></svg></> : <Empty>No valid pixels recorded; a percentage cannot be calculated.</Empty>}
        <table className="t"><thead><tr><th>Pixel class</th><th>Count</th></tr></thead><tbody><tr><td>Flood</td><td>{number(f.flood)}</td></tr><tr><td>Non-flood</td><td>{number(f.non_flood)}</td></tr><tr><td>Ignored / no data</td><td>{number(f.ignored)}</td></tr></tbody></table><p className="muted sm">Ignored pixels are excluded from the denominator. Non-flood is not a missing label.</p>
      </section>}
      {p.labels.length > 0 && <section className="card"><h2>Label distribution</h2><p className="muted sm">{p.label_unit}. Multi-label counts can overlap.</p><div className="review-bars">{p.labels.map(l => <div key={l.label}><span>{l.label}</span><div><i style={{ width: `${100 * l.count / max}%` }}/></div><b>{number(l.count)}</b></div>)}</div></section>}
      {p.relationships.map((r, idx) => {
        const xs = r.bins.map(b => b.x), ys = r.bins.map(b => b.y);
        const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
        const countMax = Math.max(1, ...r.bins.map(b => b.count));
        return <section className="card" key={idx}><h2>{r.x_label} and {r.y_label.toLowerCase()}</h2><p className="muted sm">{r.method} · {number(r.total_pairs)} paired readings</p>
          {r.bins.length ? <svg viewBox="0 0 600 260" role="img" aria-label={`${r.x_label} versus ${r.y_label}; ${r.total_pairs} paired readings`}>
            {[0, .5, 1].map(t => <g key={t}><line x1="65" x2="565" y1={210 - t * 180} y2={210 - t * 180} stroke="var(--line)"/><text x="55" y={215 - t * 180} textAnchor="end">{number(ymin + t * (ymax - ymin))}</text><text x={65 + t * 500} y="232" textAnchor="middle">{number(xmin + t * (xmax - xmin))}</text></g>)}
            {r.bins.map((b, i) => <circle key={i} cx={65 + (xmax === xmin ? .5 : (b.x - xmin) / (xmax - xmin)) * 500} cy={210 - (ymax === ymin ? .5 : (b.y - ymin) / (ymax - ymin)) * 180} r={Math.max(3, 18 * Math.sqrt(b.count / countMax))} fill="#287fb8" fillOpacity=".6"><title>{r.x_label}: {b.x}; {r.y_label}: {b.y}; count: {b.count}</title></circle>)}
            <text x="315" y="256" textAnchor="middle">{r.x_label} ({r.x_unit ?? "units not supplied"})</text><text transform="translate(14 120) rotate(-90)" textAnchor="middle">{r.y_label} ({r.y_unit ?? "units not supplied"})</text>
          </svg> : <Empty>No paired readings.</Empty>}
          <details><summary>View chart values</summary><div className="review-table"><table className="t"><thead><tr><th>{r.x_label}</th><th>{r.y_label}</th><th>Count</th></tr></thead><tbody>{r.bins.map((b, i) => <tr key={i}><td>{number(b.x)}</td><td>{number(b.y)}</td><td>{number(b.count)}</td></tr>)}</tbody></table></div></details>
          <p className="muted sm">Association does not establish causation or landslide risk.</p>
        </section>;
      })}
    </div>
    {p.notes.length > 0 && <ul className="muted sm">{p.notes.map(n => <li key={n}>{n}</li>)}</ul>}
    {!f && !p.labels.length && !p.relationships.length && <Empty>No chart measurements in this profile.</Empty>}
  </>;
}

export function DatasetReview() {
  const [sample, setSample] = useState(false);
  const [selected, setSelected] = useState("");
  const [profileIndex, setProfileIndex] = useState(0);
  const { data, error, reload } = usePoll<DataReview>(`/dev/data-exploration?sample=${sample}`, 30000);
  const keys = [...new Set([...(data?.cards.map(c => c.key) ?? []), ...(data?.profiles.map(p => p.dataset) ?? []), ...(data?.evaluations.map(e => e.dataset) ?? [])])];
  const key = keys.includes(selected) ? selected : keys[0];
  const card = data?.cards.find(c => c.key === key);
  const profiles = data?.profiles.filter(p => p.dataset === key) ?? [];
  const profile = profiles[profileIndex] ?? profiles[0];
  const evaluations = data?.evaluations.filter(e => e.dataset === key) ?? [];
  return <div className="review-page"><h1>Training datasets</h1><p className="muted">Dataset coverage, label balance and evaluation reports.</p>
    <Mode sample={sample} setSample={v => { setSample(v); setProfileIndex(0); }} /><Refresh error={error} asOf={data?.as_of} reload={reload}/>
    {!data && !error && <Empty>Loading dataset summaries…</Empty>}
    {data?.warnings.map((w, i) => <p className="err" role="alert" key={i}>{w}</p>)}
    {data && !keys.length && <Empty>No dataset cards or profiling reports available. D1 cards and completed training summaries will appear here when installed. You can enable illustrative sample data above.</Empty>}
    {keys.length > 0 && <><label className="review-select">Dataset <select value={key} onChange={e => { setSelected(e.target.value); setProfileIndex(0); }}>{keys.map(k => <option value={k} key={k}>{data?.cards.find(c => c.key === k)?.name ?? k}</option>)}</select></label>
      {card && <section className="card"><div className="review-heading"><h2>{card.name}</h2><span className="chip">{card.version}</span></div><p>{card.coverage}</p><p className="sm">{card.label_meaning}</p>
        <div className="review-splits">{card.splits.map(s => <div key={s.name}><b>{number(s.count)}</b><span>{s.name} · {s.unit}{s.tiles != null && ` · ${number(s.tiles)} tiles`}</span></div>)}</div>
        <details><summary>Coverage, missingness and licence</summary><p>{card.missingness}</p><p>{card.licence} · {card.verified ? "Verified" : "Not fully verified"}</p><p>{card.verification}</p><ul>{(card.limits ?? []).map(l => <li key={l}>{l}</li>)}</ul></details>
      </section>}
      <h2>Data profile</h2>
      {profiles.length > 1 && <label className="review-select">Profile <select value={Math.min(profileIndex, profiles.length - 1)} onChange={e => setProfileIndex(+e.target.value)}>{profiles.map((p, i) => <option value={i} key={i}>{p.dataset_version ?? "Unknown version"} · {p.split} · {p.generated_at}</option>)}</select></label>}
      {profile ? <ProfileCharts profile={profile}/> : <Empty>No profiling measurements recorded for this dataset. Split counts cannot establish pixel imbalance or label distributions.</Empty>}
      <h2>Flood-model evaluation</h2>
      {!evaluations.length && <Empty>No completed D2 evaluation report for this dataset.</Empty>}
      {evaluations.map((e, i) => <section className="card" key={i}><ProvenanceLine item={e}/><p className="sm">Model version: {e.model_version ?? "Not recorded"} · {number(e.tiles)} tiles · {e.file}</p><div className="review-table"><table className="t"><thead><tr><th>Variant</th><th>Pixel IoU</th><th>Pixel F1</th><th>Precision</th><th>Recall</th><th>Mean event IoU</th><th>Mean event F1</th><th>Events</th><th>Threshold</th></tr></thead><tbody>{e.variants.map(v => <tr key={v.name}><td>{v.name}</td>{["iou", "f1", "precision", "recall", "mean_event_iou", "mean_event_f1"].map(m => <td key={m}>{number(v.metrics[m])}</td>)}<td>{number(v.events)}</td><td>{number(v.threshold)}</td></tr>)}</tbody></table></div><p className="muted sm">Pixel metrics pool valid pixels; event metrics weight events equally. Undefined scores remain “Not recorded”.</p></section>)}
    </>}
  </div>;
}
