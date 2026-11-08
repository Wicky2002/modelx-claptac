import { useCallback, useEffect, useRef, useState } from "react";

// ---- types mirror the Python models in atlas/dashboard/dev ---------------------------------

import type { Information } from "./components/Information";

export interface Span {
  id: string;
  parent_id: string | null;
  name: string;
  agent: string;
  kind: "handler" | "executor" | "llm" | "input";
  event_id: string;
  event_type: string;
  incident_id: string | null;
  start: number;
  duration_ms: number;
  status: "ok" | "error" | "escalated" | "blocked";
  summary: string;
  error: string | null;
  outputs: number;
  depth: number;
}

export interface Run {
  incident_id: string;
  area_id: string | null;
  hazard: string | null;
  state: string | null;
  cycles: number;
  replans: number;
  needs_human: boolean;
  started: number;
  ended: number;
  duration_ms: number;
  spans: number;
  errors: number;
  events: number;
  agents: string[];
  summary: string;
}

export interface SpanDetail {
  id: string;
  agent: string;
  kind: string;
  input: { information?: Information; id: string; type: string; source: string; incident_id: string | null; created_at: string; summary: string; payload: unknown };
  outputs: { information?: Information; id: string; type: string; source: string; summary: string; payload: unknown; seq: number }[];
  caused_by: { event_id: string; by: string } | null;
  metadata: { duration_ms: number; started_at: number | null; ok: boolean; error: string | null; chain: string[] };
}

export interface TraceEvent {
  information?: Information;
  seq: number;
  id: string;
  type: string;
  source: string;
  raw_source: string;
  incident_id: string | null;
  created_at: string;
  summary: string;
  handled_by: string[];
  caused_by: string | null;
  payload: unknown;
}

export interface FlowEdge {
  source: string;
  target: string;
  kind: "delivered" | "execute" | "review";
  label: string;
  count: number;
  last_seq: number;
}

export interface AgentCard {
  name: string;
  title: string;
  layer: "sense" | "plan" | "act" | "control" | "world";
  purpose: string;
  reads: string[];
  writes: string[];
  uses_llm: boolean;
  deterministic_tools: string[];
  owner: string;
  subscribed: string[];
  received: number;
  produced: number;
  last_received: string | null;
  last_produced: string | null;
}

export interface Metrics {
  agents: { agent: string; kind: string; runs: number; errors: number; p50_ms: number; p95_ms: number; max_ms: number; total_ms: number }[];
  events_by_type: Record<string, number>;
  latency: {
    incident_id: string;
    detection_latency_seconds: number | null;
    milestones: Record<string, { sim_seconds_after_trigger: number; wall_ms_after_start: number | null }>;
  }[];
  control: {
    actions?: number;
    by_status?: Record<string, number>;
    by_consequence?: Record<string, number>;
    escalated?: number;
    pending_approvals?: number;
    resolved?: Record<string, number>;
    autonomous?: number;
    autonomy_rate?: number | null;
    human_edit_or_reject_rate?: number;
    median_decision_seconds?: number | null;
    blocked?: number;
  };
  llm: { calls: number; tokens: number; cost_usd: number };
}

export interface ScenarioInfo {
  key: string;
  title: string;
  real: boolean;
  hazard: string | null;
  area_id: string | null;
  events: number;
  replay_minutes: number;
  story: string;
  assumptions: string[];
}

export interface HazardEvent {
  id: string;
  hazard: string;
  source: string;
  name: string;
  start: string;
  end: string | null;
  lat: number | null;
  lon: number | null;
  severity: number | null;
  severity_unit: string;
  severity_label: string;
  url: string | null;
  detail: Record<string, unknown>;
}

export interface Approval {
  id: string;
  incident_id: string;
  action: { action_type: string; executor: string; params: Record<string, unknown>; rationale?: string };
  reason: string;
  status: string;
  created_at: string;
}

// ---- plumbing --------------------------------------------------------------------------------

export const token = {
  get: () => sessionStorage.getItem("atlas-operator-token") ?? "",
  set: (v: string) => sessionStorage.setItem("atlas-operator-token", v),
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(url: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string>) };
  if (init?.json !== undefined) headers["Content-Type"] = "application/json";
  if (token.get()) headers["X-Operator-Token"] = token.get();
  const response = await fetch(url, {
    ...init,
    headers,
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

/** Poll a GET endpoint. ``null`` url pauses. Keeps the last good data if a poll fails. */
export function usePoll<T>(url: string | null, ms = 2000) {
  const [state, setState] = useState<{ url: string | null; data: T | null; error: string | null; loading: boolean; refreshedAt: number | null }>({ url, data: null, error: null, loading: true, refreshedAt: null });
  const generation = useRef(0);
  const sequence = useRef(0);
  const activeUrl = useRef(url); activeUrl.current = url;
  const load = useCallback(async () => {
    if (!url) return;
    const gen = generation.current, seq = ++sequence.current;
    const current = () => gen === generation.current && seq === sequence.current && activeUrl.current === url;
    try {
      const next = await api<T>(url);
      if (current()) setState({ url, data: next, error: null, loading: false, refreshedAt: Date.now() });
    } catch (e) {
      if (current()) setState(previous => ({ url, data: previous.url === url ? previous.data : null, refreshedAt: previous.url === url ? previous.refreshedAt : null, loading: false, error: e instanceof Error ? e.message : String(e) }));
    }
  }, [url]);
  useEffect(() => {
    ++generation.current;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      await load();
      if (active && url && ms > 0) timer = setTimeout(tick, ms);
    };
    void tick();
    return () => { active = false; ++generation.current; clearTimeout(timer); };
  }, [url, ms, load]);
  return { data: state.url === url ? state.data : null, error: state.url === url ? state.error : null, loading: !!url && (state.url !== url || state.loading), refreshedAt: state.url === url ? state.refreshedAt : null, reload: load };
}

export function fmtMs(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(0)} µs`;
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60000).toFixed(1)} min`;
}

export function shortAgent(name: string): string {
  const m = /^a(\d)_/.exec(name);
  return m ? `A${m[1]}` : name;
}

// ---- agent manager (/am/v1) ------------------------------------------------------------------

export interface AgentRecord {
  name: string;
  title: string;
  layer: "sense" | "plan" | "act" | "control" | "world";
  purpose: string;
  kind: "internal" | "external";
  version: string;
  owner: string;
  status: "active" | "suspended";
  suspended_by: string | null;
  suspended_reason: string | null;
  environments: string[];
  uses_llm: boolean;
  subscribed: string[];
  reads: string[];
  writes: string[];
  tools: string[];
  received: number;
  produced: number;
  last_received: string | null;
  last_produced: string | null;
  pending: number;
}

export interface Me {
  name: string;
  role: string;
  dev_mode: boolean;
  permissions: string[];
  roles: string[];
}

export interface OtelSpan {
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  start_ns: number;
  end_ns: number;
  status: string;
  status_message: string | null;
  attributes: Record<string, string | number | boolean>;
  agent: string;
  depth: number;
}

export interface TraceSummary {
  trace_id: string;
  incident_id: string;
  name: string;
  duration_ms: number;
  spans: number;
  errors: number;
  status: string;
}

export interface EvaluatorInfo {
  name: string;
  level: "span" | "trace" | "agent";
  description: string;
  threshold: number | null;
  unit: string;
  critical: boolean;
  builtin: boolean;
  tags: string[];
}

export interface EvalRun {
  id: string;
  at: number;
  mode: string;
  trigger: string;
  traces: number;
  summary: {
    scored: number;
    passed: number;
    failed: number;
    skipped: number;
    critical_failures: number;
    pass_rate: number | null;
    evaluators: Record<string, { scored: number; passed: number; failed: number; pass_rate: number | null; critical: boolean; level: string }>;
  };
}

export interface EvalScore {
  evaluator: string;
  level: string;
  target: string;
  value: number | null;
  passed: boolean | null;
  threshold: number | null;
  unit: string;
  detail: string;
  critical: boolean;
}

export interface Monitor {
  id: string;
  name: string;
  evaluators: string[];
  interval_s: number;
  enabled: boolean;
  last_run: number | null;
}

export interface Guardrails {
  proposers: string[];
  identities: { agent: string; allowed_actions: string[]; high_consequence: string[] }[];
  actions: Record<string, { consequence: string; when: Record<string, unknown> }>;
  gateway: Record<string, unknown>;
  principles: string[];
}

export interface AuditEntry {
  seq: number;
  at: number;
  actor: string;
  role: string;
  method: string;
  route: string;
  permission: string | null;
  status: number;
  params: Record<string, string>;
}
