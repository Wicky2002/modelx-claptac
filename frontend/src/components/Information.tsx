import { usePoll } from "../api";

export interface Information {
  labels: string[];
  observed_at?: string | null;
  age_seconds?: number | null;
  evidence_ids?: string[];
  sources?: string[];
  note?: string | null;
  workflow?: string | null;
}

export function InformationBadges({ info }: { info?: Information }) {
  return <span className="information-badges" aria-label="Information status">{(info?.labels ?? ["unknown"]).map(label =>
    <span key={label} className={`info-tag info-${label}`}>{label}</span>)}</span>;
}

export function InformationDetail({ info }: { info?: Information }) {
  return <div className="information-detail"><InformationBadges info={info} />
    {info?.workflow && <p><b>{info.workflow}</b></p>}
    {info?.note && <p>{info.note}</p>}
    {info?.observed_at && <p className="sm">Observation: <time>{new Date(info.observed_at).toLocaleString()}</time>
      {info.age_seconds != null && ` · ${Math.floor(info.age_seconds / 60)} min old`}</p>}
    {!!info?.sources?.length && <p className="sm">Sources: {info.sources.join(", ")}</p>}
  </div>;
}

interface ReplayContext {
  state: string; contains_replay: boolean; title?: string; scenario?: string;
  simulated_at?: string; elapsed_seconds?: number; speed?: number;
}

export function ReplayBanner() {
  const { data, error } = usePoll<ReplayContext>("/dev/context", 1000);
  if (!data?.contains_replay) return error ? <div className="replay-banner" role="status">Operating context unavailable — verify whether this is a rehearsal.</div> : null;
  const elapsed = Math.floor(data.elapsed_seconds ?? 0);
  const clock = data.simulated_at ? new Date(data.simulated_at).toISOString().replace("T", " ").slice(0, 19) + " UTC"
    : `T+${String(Math.floor(elapsed / 3600)).padStart(2, "0")}:${String(Math.floor(elapsed / 60) % 60).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  return <div className="replay-banner" role="status">
    <div><strong>REPLAY / TRAINING</strong><span>{data.title ?? data.scenario} · {data.state}</span></div>
    <div className="replay-clock"><small>SIMULATED CLOCK{error ? " · CONNECTION LOST" : ""}</small><b>{clock}</b></div>
    <span className="replay-disclaimer">Contains rehearsal data. Do not use as a live emergency picture.</span>
  </div>;
}

export function EvidenceInformation({ value }: { value: unknown }) {
  const info = value && typeof value === "object" && "information" in value
    ? (value as { information: Information }).information
    : { labels: ["inferred"], note: "Recorded snapshot; source status is not available in this historical record." };
  return <InformationDetail info={info} />;
}
