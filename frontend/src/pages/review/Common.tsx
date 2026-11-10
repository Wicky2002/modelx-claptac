import type { Provenance } from "./types";
import "./review.css";
export const number = (value: number | null | undefined) => value == null ? "Not recorded" : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
export const time = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : "Not recorded";
export function Mode({ sample, setSample }: { sample: boolean; setSample: (v: boolean) => void }) {
  return <div className="review-mode"><label><input type="checkbox" checked={sample} onChange={e => setSample(e.target.checked)} /> Show illustrative sample data</label>
    {sample ? <div role="status" className="review-sample"><b>SAMPLE DATA</b> · Illustrative values only. These are not training results or live model decisions.</div> : <p className="muted sm">Recorded data only. Missing results remain unavailable until they are supplied.</p>}</div>;
}
export function ProvenanceLine({ item }: { item: Provenance }) {
  return <div className="review-provenance"><span>Dataset <b>{item.dataset}</b></span><span>Version <b>{item.dataset_version ?? "Not recorded"}</b></span><span>Split <b>{item.split}</b></span><span>Seed <b>{item.seed ?? "Not recorded"}</b></span><span>Generated <b>{time(item.generated_at)}</b></span><span>Source <b>{item.source}</b></span></div>;
}
export function Empty({ children }: { children: React.ReactNode }) { return <p className="review-empty">{children}</p>; }
export function Refresh({ error, asOf, reload }: { error: string | null; asOf?: string; reload: () => void }) {
  return <div className="review-refresh"><span className="muted sm">{asOf ? `Snapshot ${time(asOf)}` : "No snapshot loaded"}</span><button className="btn" onClick={reload}>Refresh</button>{error && <div className="err" role="alert">Refresh failed. {asOf ? "Showing the last loaded snapshot. " : ""}{error}</div>}</div>;
}
