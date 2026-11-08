import { usePoll } from "../api";
import { InformationBadges, type Information } from "./Information";

export const clockTime = (value: string | number | null | undefined) => value == null ? "Not recorded" : new Date(value).toLocaleString();
export const ageLabel = (seconds: number | null | undefined) => seconds == null ? "Unknown" : seconds < 60 ? `${Math.floor(seconds)} s` : seconds < 3600 ? `${Math.floor(seconds / 60)} min` : `${(seconds / 3600).toFixed(1)} h`;
interface Source { source: string; attribute: string; observed_at: string | null; arrived_at: string; last_accepted_at: string | null; last_successful_refresh: string | null; refresh_note: string; age_seconds: number | null; value: unknown; unit: string; status: string; information?: Information }

export function SourceHealth() {
  const poll = usePoll<{ as_of: string; sources: Source[] }>("/dev/sources", 5000);
  return <section className="card source-health" aria-label="Source health">
    <div className="audit-section-head"><div><span className="eyebrow">OBSERVABILITY</span><h2>Source health</h2></div><span className="muted sm">Console refreshed {clockTime(poll.refreshedAt)}</span></div>
    <p className="muted sm">Observation time describes the measurement. Arrival describes when ATLAS received it. A successful console refresh does not mean a source refreshed.</p>
    {poll.error && <p className="banner warn" role="alert">Source updates unavailable: {poll.error}. Retaining the last received records.</p>}
    {poll.loading && <p>Loading source records…</p>}
    {poll.data?.sources.length === 0 && <p className="muted">No source observations recorded. Source health is unknown.</p>}
    <div className="table-scroll"><table className="t"><thead><tr><th>Source / reading</th><th>Observation time</th><th>Arrival time</th><th>Last accepted input</th><th>Last successful refresh</th><th>Source age</th></tr></thead><tbody>
      {poll.data?.sources.map(s => <tr key={`${s.source}:${s.attribute}`}><td><b>{s.source}</b><small>{s.attribute.replace(/_/g, " ")} · {String(s.value ?? "Unknown")} {s.unit}</small><InformationBadges info={s.information} /><small>{s.status.replace(/_/g, " ")}</small></td><td>{clockTime(s.observed_at)}</td><td>{clockTime(s.arrived_at)}</td><td>{clockTime(s.last_accepted_at)}</td><td><span title={s.refresh_note}>{clockTime(s.last_successful_refresh)}</span></td><td><strong>{ageLabel(s.age_seconds)}</strong></td></tr>)}
    </tbody></table></div>
    <p className="sm muted">Adapter fetch attempts and successful polls without new observations are not recorded upstream. “Not recorded” is an unknown state.</p>
  </section>;
}
