import { useState } from "react";
import { api, usePoll } from "../api";
import { clockTime } from "../components/SourceHealth";
import { friendly, missionStatus, place, teams, type Mission } from "../plain";

interface Ticket extends Mission { route: (string | number)[]; history: { at: string; status: string; note: string }[] }
export function MissionsPage() {
  const missions = usePoll<Mission[]>("/missions", 3000);
  const me = usePoll<{ permissions: string[] }>("/am/v1/me", 15000);
  const [teamFilter, setTeamFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const list = [...(missions.data ?? [])].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const filtered = teamFilter ? list.filter(m => (m.team ?? "").split(",").map(s => s.trim()).includes(teamFilter)) : list;
  const teamNames = [...new Set(list.flatMap(m => (m.team ?? "").split(",")).map(s => s.trim()).filter(Boolean))];
  return <div className="page ops">
    <p className="lead">Issued mission tickets and reports from field teams. An issued ticket is not proof of departure, progress or arrival.</p>
    <div className="audit-section-head"><label className="f">Field team<select aria-label="Filter by field team" value={teamFilter} onChange={e => { setTeamFilter(e.target.value); setSelected(null); }}><option value="">All teams</option>{teamNames.map(t => <option key={t} value={t}>{friendly(t)}</option>)}</select></label><span className="muted sm">{filtered.length} tickets · {filtered.filter(m => !m.acknowledged_at && m.status === "created").length} awaiting acknowledgement</span></div>
    {missions.error && <p className="banner warn" role="alert">Ticket updates unavailable: {missions.error}</p>}
    {selected ? <MissionTicket key={selected} id={selected} canUpdate={!!me.data?.permissions.includes("mission:update")} close={() => setSelected(null)} onUpdate={missions.reload} /> : <div className="grid g2">{filtered.map(m => <button className="card mission-ticket-button" key={m.id} onClick={() => setSelected(m.id)}><div className="audit-section-head"><span className="eyebrow">MISSION TICKET · {m.id}</span><span className={`chip ${m.status === "failed" || m.exception ? "bad" : ""}`}>{missionStatus(m.status)}</span></div><h3>{m.title.replace(/[a-z]+-shelter-(\d+)/g, "Shelter $1")}</h3><p>{teams(m.team ?? "") || "No team assigned"} · {place(m.incident_id)}</p><p className="sm">{m.acknowledged_at ? `Acknowledged ${clockTime(m.acknowledged_at)}` : "No acknowledgement recorded"}</p><div className="bar"><i style={{ width: `${m.progress}%` }} /></div><span className="sm muted">{m.progress}% reported progress · Open ticket →</span></button>)}</div>}
    {!filtered.length && !missions.loading && <p className="card muted">No tickets recorded for this team.</p>}
  </div>;
}

function MissionTicket({ id, canUpdate, close, onUpdate }: { id: string; canUpdate: boolean; close: () => void; onUpdate: () => void }) {
  const poll = usePoll<Ticket>(`/missions/${encodeURIComponent(id)}`, 3000);
  const [reporter, setReporter] = useState("");
  const [percent, setPercent] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const m = poll.data;
  const update = async (verb: "acknowledge" | "progress" | "complete") => {
    if (verb !== "complete" && !reporter.trim()) { setMessage("Enter the field reporter's name or callsign."); return; }
    if (verb === "progress" && (!percent.trim() || !Number.isInteger(Number(percent)) || Number(percent) < 0 || Number(percent) > 100)) { setMessage("Enter the reported progress from 0 to 100."); return; }
    setBusy(true);
    try {
      const json = verb === "acknowledge" ? { by: reporter.trim() } : verb === "progress" ? { percent: Number(percent), note: `${reporter.trim()}: ${note}` } : {};
      await api(`/missions/${encodeURIComponent(id)}/${verb}`, { method: "POST", json });
      setMessage("Field report recorded."); void poll.reload(); onUpdate();
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return <section className="card field-ticket" aria-label="Field mission ticket"><button className="btn" onClick={close}>← All tickets</button>{poll.error && <p role="alert" className="banner warn">{poll.error}</p>}{poll.loading && <p>Loading mission ticket…</p>}{m && <><div className="audit-section-head"><div><span className="eyebrow">{m.id} · {m.priority} priority</span><h2>{m.title}</h2></div><span className="chip acc">{missionStatus(m.status)}</span></div>
    <div className="preview-facts"><div><small>Assigned team</small><b>{teams(m.team ?? "") || "Not assigned"}</b></div><div><small>Destination</small><b>{friendly(m.destination) || "Not recorded"}</b></div><div><small>Committed resources</small><b>{m.resources_committed}</b></div><div><small>Issued</small><b>{clockTime(m.created_at)}</b></div><div><small>Acknowledged</small><b>{m.acknowledged_at ? clockTime(m.acknowledged_at) : "Awaiting team confirmation"}</b></div><div><small>Last reported progress</small><b>{m.progress}% · {clockTime(m.updated_at)}</b></div></div>
    <p className="sm">Affected area: <a href={`#/incidents/${encodeURIComponent(m.incident_id)}`}>{place(m.incident_id)}</a> · <a href="#/map">Inspect planned route on map</a></p><details><summary>Ticket route ({m.route.length} reference nodes)</summary><p className="sm route-nodes">{m.route.join(" → ") || "No route recorded"}</p></details>
    {m.exception && <p className="banner bad">{m.exception}</p>}
    <section className="field-report"><h3>Record a field report</h3><p className="sm muted">Record what the team actually reports by radio or phone. Acknowledgement records acceptance of the ticket.</p>{!canUpdate ? <p className="muted">Read-only access. A commander records field updates.</p> : ["completed", "cancelled", "failed"].includes(m.status) ? <p>This ticket is closed.</p> : <><div className="field-report-inputs"><label className="f">Reporter / callsign<input maxLength={80} value={reporter} onChange={e => setReporter(e.target.value)} placeholder="e.g. Rescue 02 / Perera" /></label><label className="f">Reported progress (%)<input type="number" min={0} max={100} value={percent} onChange={e => setPercent(e.target.value)} /></label><label className="f">Field note<input maxLength={400} value={note} onChange={e => setNote(e.target.value)} placeholder="What the team reported" /></label></div><div className="row">{!m.acknowledged_at && <button className="btn primary" disabled={busy} onClick={() => void update("acknowledge")}>Record team acknowledgement</button>}<button className="btn" disabled={busy || !m.acknowledged_at} onClick={() => void update("progress")}>Record progress</button><button className="btn" disabled={busy || !m.acknowledged_at} onClick={() => void update("complete")}>Record completion</button></div></>}{message && <p role="status" className="banner info">{message}</p>}</section>
    <section><h3>Acknowledgement & status history</h3><table className="t"><thead><tr><th>Time</th><th>Status</th><th>Recorded report</th></tr></thead><tbody>{m.history.map((h, i) => <tr key={i}><td>{clockTime(h.at)}</td><td>{missionStatus(h.status)}</td><td>{h.note || "No note recorded"}</td></tr>)}</tbody></table></section>
  </>}</section>;
}
