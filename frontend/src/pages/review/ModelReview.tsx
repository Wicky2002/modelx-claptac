import { useState } from "react";
import { usePoll } from "../../api";
import { Empty, Mode, number, Refresh, time } from "./Common";
import type { ModelsReview } from "./types";

const driftLabels: Record<string, string> = { no_live_model: "No live model", no_reference: "No training reference distribution", insufficient_data: "Insufficient prediction data" };
export function ModelReviewPage() {
  const [sample, setSample] = useState(false);
  const [selected, setSelected] = useState("");
  const [version, setVersion] = useState("");
  const { data, error, reload } = usePoll<ModelsReview>(`/dev/model-review?sample=${sample}`, 15000);
  const names = [...new Set(data?.models.map(m => m.name) ?? [])];
  const name = names.includes(selected) ? selected : names[0];
  const models = data?.models.filter(m => m.name === name) ?? [];
  const live = models.find(m => m.status === "live");
  const candidates = models.filter(m => m.status !== "live");
  const candidate = candidates.find(m => m.version === version) ?? candidates.find(m => m.status === "shadow") ?? candidates[0];
  const review = data?.reviews.find(r => r.name === name);
  const metrics = [...new Set([...Object.keys(live?.metrics ?? {}), ...Object.keys(candidate?.metrics ?? {})])];
  const datasets = [...new Set([...Object.keys(live?.dataset_versions ?? {}), ...Object.keys(candidate?.dataset_versions ?? {})])];
  const history = data?.history.filter(h => h.name === name) ?? [];
  const requests = data?.requests.filter(r => r.action.params.name === name) ?? [];
  return <div className="page review-page"><h1>Model review</h1><p className="muted">Current and candidate models, prediction drift and recorded decisions.</p>
    <Mode sample={sample} setSample={setSample}/><Refresh error={error} asOf={data?.as_of} reload={reload}/>
    {!data && !error && <Empty>Loading model registry…</Empty>}
    {data && !data.registry_available && <Empty>Model registry unavailable. This view connects when S1 is integrated.</Empty>}
    {data?.registry_available && !names.length && <Empty>No model versions registered yet. Completed training results can be registered through S1.</Empty>}
    {names.length > 0 && <>
      <label className="review-select">Model <select value={name} onChange={e => { setSelected(e.target.value); setVersion(""); }}>{names.map(n => <option key={n}>{n}</option>)}</select></label>
      <div className="review-grid">
        <section className="card"><h2>Current live model</h2>{live ? <><div className="review-stat">{live.version}</div><p>{live.task}</p><p className="sm">Threshold: {number(live.operating_threshold)} · Updated {time(live.updated_at)}</p></> : <Empty>No live model registered.</Empty>}</section>
        <section className="card"><h2>Compare version</h2>{candidate ? <><label className="review-select">Version <select value={candidate.version} onChange={e => setVersion(e.target.value)}>{candidates.map(c => <option key={c.version} value={c.version}>{c.version} · {c.status}</option>)}</select></label><p>{candidate.task} · <span className="chip">{candidate.status}</span></p><p className="sm">Threshold: {number(candidate.operating_threshold)} · Registered {time(candidate.registered_at)}</p></> : <Empty>No candidate, shadow or retired versions.</Empty>}</section>
      </div>
      <section className="card"><h2>Registered metrics</h2><p className="muted sm">Scores are shown as registered. Evaluation split and seed are not part of the S1 record; these values alone do not establish which model is better. See Data & history for D2 report provenance.</p>
        {live && candidate && datasets.some(k => live.dataset_versions[k] !== candidate.dataset_versions[k]) && <p className="review-sample">Dataset versions differ. Do not treat these metrics as a controlled comparison.</p>}
        <div className="review-table"><table className="t"><thead><tr><th>Metric / dataset</th><th>Live · {live?.version ?? "Unavailable"}</th><th>{candidate?.status ?? "Comparison"} · {candidate?.version ?? "Unavailable"}</th></tr></thead><tbody>{metrics.map(m => <tr key={m}><td>{m}</td><td>{number(live?.metrics[m])}</td><td>{number(candidate?.metrics[m])}</td></tr>)}{datasets.map(k => <tr key={`data-${k}`}><td>Dataset · {k}</td><td>{live?.dataset_versions[k] ?? "Not recorded"}</td><td>{candidate?.dataset_versions[k] ?? "Not recorded"}</td></tr>)}</tbody></table></div>
      </section>
      <div className="review-grid">
        <section className="card"><h2>Input drift</h2>{!data?.learning_available ? <Empty>A10 drift checks unavailable until S3 is integrated.</Empty> : !review ? <Empty>No drift summary available.</Empty> : <>
          <p className={`chip ${review.drift.drifted ? "bad" : ""}`}>{review.drift.status === "checked" ? review.drift.drifted ? "Review suggested" : "No drift flagged" : driftLabels[review.drift.status] ?? review.drift.status}</p>
          <p className="sm">Version: {review.drift.version ?? "No live version"} · Samples: {number(review.drift.samples)}</p>
          {review.drift.features && <div className="review-table"><table className="t"><thead><tr><th>Feature</th><th>Mean shift (σ)</th><th>Missing rate</th><th>Review</th></tr></thead><tbody>{Object.entries(review.drift.features).map(([k, f]) => <tr key={k}><td>{k}</td><td>{number(f.shift_std)}</td><td>{(100 * f.missing_rate).toFixed(1)}%</td><td>{f.drifted ? "Suggested" : "Not flagged"}</td></tr>)}</tbody></table></div>}
          <p className="muted sm">S3 uses up to 500 successful predictions for the live version and requires at least 30. A mean shift ≥ 0.5 training standard deviations or a missing-rate change ≥ 0.2 prompts review. This heuristic is not a calibrated statistical test.</p>
        </>}</section>
        <section className="card"><h2>Shadow results</h2>{!data?.learning_available ? <Empty>A10 shadow summaries unavailable until S3 is integrated.</Empty> : !review?.shadows.length ? <Empty>No shadow versions registered.</Empty> : <><div className="review-table"><table className="t"><thead><tr><th>Version</th><th>Runs</th><th>Errors</th><th>Paired</th><th>Mean |difference|</th></tr></thead><tbody>{review.shadows.map(s => <tr key={s.version}><td>{s.version}</td><td>{number(s.runs)}</td><td>{number(s.errors)}</td><td>{number(s.compared_with_live)}</td><td>{number(s.mean_abs_difference)}</td></tr>)}</tbody></table></div><p className="muted sm">Difference from paired live predictions across shared numeric outputs; it is not accuracy. Pairs may span historical live versions. No comparable numeric output remains “Not recorded”.</p></>}</section>
      </div>
      <section className="card"><div className="review-heading"><h2>Promotion and rollback requests</h2><a href="#/approvals">Open approvals</a></div><p className="muted sm">Human approval is required. This page cannot promote, roll back or change thresholds.</p>{!requests.length ? <Empty>No model-change requests recorded in the latest 100 requests.</Empty> : <div className="review-table"><table className="t"><thead><tr><th>Action</th><th>Target version</th><th>Status</th><th>Reason</th></tr></thead><tbody>{requests.map(r => <tr key={r.action.idempotency_key}><td>{r.action.action_type}</td><td>{String(r.action.params.version ?? "Not recorded")}</td><td>{r.decision.status}</td><td>{r.decision.reason}</td></tr>)}</tbody></table></div>}</section>
      <section className="card"><h2>Registration and status history</h2><p className="muted sm">From the latest 200 registry ledger records. Status transitions and their recorded reasons include promotions and rollbacks.</p>{!history.length ? <Empty>No registry history recorded.</Empty> : <ol className="review-history">{history.map((h, i) => <li key={i}><div><b>{h.version}</b> · {h.phase === "status_changed" ? `${h.from} → ${h.to}` : h.phase}<time>{time(h.at)}</time></div>{h.actor && <span className="sm">{h.actor} · {h.reason || "No reason recorded"}</span>}</li>)}</ol>}</section>
    </>}
  </div>;
}
