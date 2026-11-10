import { usePoll } from "../api";
import { type AlertText, languageName } from "../plain";
import { clockTime } from "./SourceHealth";

interface Preview { target_area: string; event: string; severity: string; expires_at: string; expires_minutes: number; texts: Record<string, AlertText>; missing: string[]; excluded: string[]; delivery_mode: string; note: string }
export function CommunicationPreview({ approvalId }: { approvalId: string }) {
  const { data, error, loading, reload } = usePoll<Preview>(`/approvals/${encodeURIComponent(approvalId)}/preview`, 0);
  return <section className="communication-preview" aria-label="Communication preview">
    <div className="audit-section-head"><div><span className="eyebrow">BEFORE PUBLICATION</span><h3>Communication preview</h3></div><span className="chip warn">Proposed · not sent</span></div>
    {loading && <p>Rendering the message…</p>}{error && <p className="banner warn" role="alert">Preview unavailable: {error} <button className="btn" onClick={reload}>Retry preview</button></p>}
    {data && <><div className="preview-facts"><div><small>Target area</small><b>{data.target_area}</b></div><div><small>Severity</small><b>{data.severity}</b></div><div><small>Estimated expiry</small><b>{clockTime(data.expires_at)}</b><small>{data.expires_minutes} minutes after publication</small></div></div>
      <div className="preview-languages">{["si", "ta", "en"].map(lang => { const t = data.texts[lang]; return <article key={lang} lang={lang}><h4>{languageName(lang)}</h4>{t ? <><b>{t.headline}</b><p>{t.body}</p><p className="preview-instruction">{t.instruction}</p></> : <p className="banner warn">{data.excluded.includes(lang) ? "Not requested in this proposal." : "Translation unavailable in preview. Do not assume this language will be delivered."}</p>}</article>; })}</div>
      <p className="sm muted">{data.note}</p><p className="sm"><b>{data.delivery_mode === "simulation_log" ? "Local simulation log; no public delivery." : "Channel send; recipient receipt is unconfirmed."}</b> Sinhala and Tamil templates require native-speaker review before real public use.</p>
    </>}
  </section>;
}
