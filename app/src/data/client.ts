import { useConfig } from "./config";
import { open, seal } from "./e2ee";
import { useHealth } from "./health";
import { t } from "@/i18n/core";

import type { Attach } from "./attachments";
import type { Track, LaneMove, Metrics, Me, Usage } from "./types";

export class AuthRequired extends Error {}
// Transport never reached the daemon (relay down, network, crypto mismatch).
// Feeds the global HealthBanner; message is UI-ready German.
export class TransportError extends Error {}
// The daemon answered with an error status. Message = the daemon's own
// {error} body when present - so a 409 ("pairing code expired…"), 403, 500
// SURFACE at the call site instead of parsing into fake data. That silent
// parse was exactly the req-dispatch-failure-is-invisible bug class.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

function authHeaders(): Record<string, string> {
  const { token } = useConfig.getState();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

// Relay path: seal {method,path,headers,body} to the daemon's pubkey, POST it to
// the relay room, open the sealed {status,headers,body} reply. Byte-compatible
// with daemon/relay_client.py + e2ee.py. The relay only ever sees ciphertext.
// Every failure mode gets a DISTINCT message - "offline", "timeout", "wrong
// keys" and "no network" need different owner actions.
async function relayReq(method: string, path: string, bodyStr: string): Promise<{ status: number; body: string }> {
  const { relayUrl, room, daemonPub, mySec, myPub } = useConfig.getState();
  const inner = JSON.stringify({ method, path, headers: authHeaders(), body: bodyStr });
  const cipher = seal(inner, mySec, daemonPub);
  let r: Response;
  try {
    r = await fetch(`${relayUrl}/relay?room=${room}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pub: myPub, cipher }),
    });
  } catch {
    throw new TransportError(t("net.relayUnreachable"));
  }
  if (r.status === 503) throw new TransportError(t("net.desktopOffline"));
  if (r.status === 504) throw new TransportError(t("net.desktopTimeout"));
  if (!r.ok) throw new TransportError(t("net.relayError", { status: r.status }));
  const out = JSON.parse(await r.text());
  if (!out.cipher) throw new TransportError(t("net.desktopSilent"));
  let resp: { status?: number; body?: string };
  try {
    resp = JSON.parse(open(out.cipher, mySec, daemonPub));
  } catch {
    throw new TransportError(t("net.badKeys"));
  }
  return { status: resp.status ?? 200, body: resp.body ?? "" };
}

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const cfg = useConfig.getState();
  const bodyStr = method === "GET" ? "" : JSON.stringify(body ?? {});
  let status: number, txt: string;
  try {
    if (cfg.relayMode()) {
      ({ status, body: txt } = await relayReq(method, path, bodyStr));
    } else {
      let r: Response;
      try {
        r = await fetch(cfg.baseUrl + path, {
          method, headers: authHeaders(),
          body: method === "GET" ? undefined : bodyStr, signal,
        });
      } catch (e) {
        if ((e as Error)?.name === "AbortError") throw e;   // caller cancelled, not a health event
        throw new TransportError(t("net.lanFailed"));
      }
      status = r.status; txt = await r.text();
    }
  } catch (e) {
    if (e instanceof TransportError) useHealth.getState().reportFail(e.message);
    throw e;
  }
  // The daemon answered: the CONNECTION is healthy even if this call failed.
  useHealth.getState().reportOk();
  if (status === 401) throw new AuthRequired();
  if (status >= 400) {
    let msg = "";
    try { msg = String(JSON.parse(txt)?.error ?? ""); } catch { /* not json */ }
    throw new ApiError(status, msg || t("net.httpError", { status, method, path }));
  }
  return (txt ? JSON.parse(txt) : {}) as T;
}

/** One transcript/feed row — a loose shape woven from the daemon's transcript
 *  turns + lifecycle notes; rendered by the card feed. */
export interface Step {
  cls?: string; kind?: string; role?: string; text?: string; ts?: string;
  tool?: string; input?: unknown; result?: string; name?: string;
}
export interface ChatMsg { cls: string; text: string; ts?: string }
// POST /chat returns the copilot's answer, not a ChatMsg: {reply, actions, ...}
// (or {error} on a rejection). Keep ChatMsg for /chat/history entries.
export interface ChatReply { reply?: string; error?: string; cost?: number;
  actions?: { tool?: string; detail?: string }[]; usage?: unknown }

// `attachments` was dropped when the archived web composer (SendOpts, which had
// it) was ported to RN - the daemon has accepted it the whole time. Both /steer
// and /chat spread these opts into the request body, so adding it here wires it.
export interface SteerOpts {
  model?: string; thinking?: string; mode?: string; attachments?: Attach[];
}

// legacy shape (pre-PMP-epic plans on disk) - kept optional so an old
// plan-YYYYMMDD.json artifact doesn't crash the panel after an upgrade.
export interface PmTask { title: string; card?: string | null; priority?: string; status?: string; est_turns?: number; stream?: string; why?: string }
export interface PmMilestone {
  name: string; card?: string | null; priority?: string; status?: string; repo?: string | null; stream?: string;
  user_story?: string; done_when?: string[]; why_now?: string; steps?: string[];
  est_turns?: number; eta_days?: number; cumulative_eta_days?: number; target_date?: string;
  why?: string; tasks?: PmTask[];
}
export interface PmBudget { plan?: string; fixed_monthly_eur?: number; cash_to_goal_eur?: number; shadow_eur_to_goal?: number;
  spent_to_date_eur?: number; est_turns_to_goal?: number; velocity_turns_per_day?: number; pace_turns_per_day?: number; eta_days?: number; note?: string }
export interface PmBrief {
  summary?: string; done_pct?: number; milestones?: PmMilestone[];
  next?: { title: string; reason?: string; card?: string | null }[]; risks?: string[];
  budget?: PmBudget; economics?: Record<string, unknown>; goal?: string; generated_at?: string;
  // the golden triage + gate (PM planning gate)
  plan_status?: "ready" | "blocked" | "needs_spike"; gate?: string;
  triage?: { budget?: "ok" | "blocked"; timeline?: "ok" | "blocked"; scope?: "ok" | "blocked" };
  feasibility?: { budget?: string; earliest_done?: string; note?: string };
  open_questions?: string[];
}
export interface PmConfig { loop_enabled?: boolean; autonomy?: "notify" | "ask" | "act"; repos?: string[];
  idle_minutes?: number; max_dispatch_per_day?: number; window?: string }
export interface PmActivity {
  loop_enabled?: boolean; autonomy?: string; state?: string; state_reason?: string;
  now: string[]; next?: string | null; next_count?: number;
  needs_you: string[]; blockers: string[]; quota_paused?: boolean; last_plan?: string;
  feed: { ts: string; kind: string; msg: string; card?: string | null }[];
}
export interface PmData { goal: string; economics: Record<string, unknown>; plan: PmBrief | null; config?: PmConfig; activity?: PmActivity }
export interface ConsolidationStream { name: string; title: string; members: string[]; why?: string }
export interface ConsolidationRepo { repo: string; streams: ConsolidationStream[] }
export interface ConsolidationProposal { repos: ConsolidationRepo[]; generated_at?: string }

export interface LoopNode { key: string; label?: string; kind?: "fixed" | "policy"; instruction: string }
export interface LoopMap {
  runtime: { title: string; lanes: LoopNode[]; gate: LoopNode & { between: string[] } };
  build: { title: string; states: { key: string; instruction: string }[] };
  laws: { key: string; text: string }[];
  charter: string;
}

export const api = {
  get: <T,>(path: string) => req<T>("GET", path),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) => req<T>("POST", path, body, signal),
  // Board PUSH long-poll: blocks until the data version passes `v` (or ~22s),
  // returns the new version. Works over the sealed relay AND direct; the app
  // loops it and invalidates queries on change (replaces the direct-only SSE).
  boardWait: (v: number) => req<{ v: number }>("GET", `/stream/wait?v=${v}`),

  // board / cards
  tracks: () => req<Track[]>("GET", "/tracks"),
  metrics: () => req<Metrics>("GET", "/dashboard/data"),
  usage: () => req<Usage>("GET", "/usage"),
  me: () => req<Me>("GET", "/me"),
  // ->working/review/done are run in the BACKGROUND by the daemon (the gate is a
  // subprocess, the merge + deploy hook follow it), so those reply {started,
  // gating} instead of the finished Track. The verdict arrives on the card
  // (status/gate_report/merge_report), in the chat and by push - not here.
  moveLane: (id: string, lane: string) => req<LaneMove>("POST", `/tracks/${id}/lane`, { lane }),
  reorder: (ids: string[]) => req("POST", "/tracks/reorder", { ids }),
  newTrack: (b: Record<string, unknown>) => req("POST", "/tracks/new", b),
  update: (id: string, patch: Record<string, unknown>) => req("POST", `/tracks/${id}/update`, patch),
  archive: (id: string) => req("POST", `/tracks/${id}/archive`),
  fork: (id: string, from = "") => req("POST", `/tracks/${id}/fork`, { from }),
  del: (id: string) => req("POST", `/tracks/${id}/delete`),
  cancel: (id: string) => req("POST", `/tracks/${id}/cancel`),
  steer: (id: string, text: string, o: SteerOpts = {}) =>
    req("POST", `/tracks/${id}/steer`, { text, ...o }),
  // Answer the worker's pending question (daemon/ask.py). `answers` maps each
  // question's header -> the chosen option label (an array when multiSelect).
  // Backgrounded by the daemon like a steer, because it RUNS the continuing
  // turn. `requestId` is echoed back so a stale panel is rejected instead of
  // answering a question the worker has already moved past.
  answer: (id: string, answers: Record<string, string | string[]>, requestId: string) =>
    req<{ started: string; answered: boolean }>(
      "POST", `/tracks/${id}/answer`, { answers, request_id: requestId }),

  // card detail feeds
  transcript: (id: string) => req<Step[]>("GET", `/tracks/${id}/transcript`),
  // Long-poll PUSH: the daemon holds this until the transcript changes (or ~22s)
  // then returns {v, steps}. Works over the sealed relay AND direct — the phone
  // loops it, passing back the last v, for real streaming latency (no SSE).
  // `have` = number of steps the client already holds -> the daemon returns only
  // the tail from `base` (delta), so a live turn doesn't re-send the whole 100-227KB
  // transcript over the relay on every tick. `base` absent -> treat as 0 (full).
  transcriptLive: (id: string, v: string, have: number) =>
    req<{ v: string; base?: number; total?: number; steps: Step[] }>(
      "GET", `/tracks/${id}/transcript/live?v=${encodeURIComponent(v)}&have=${have}`),
  history: (id: string) => req<Step[]>("GET", `/tracks/${id}/history`),
  // attachments already on the card (daemon serves name+size; the file itself
  // comes from /tracks/<id>/attachment/<name>)
  attachments: (id: string) => req<{ name: string; size: number }[]>("GET", `/tracks/${id}/attachments`),
  addAttachments: (id: string, attachments: Attach[]) =>
    req("POST", `/tracks/${id}/attach`, { attachments }),
  removeAttachment: (id: string, name: string) =>
    req("POST", `/tracks/${id}/attach/remove`, { name }),
  turns: (id: string) => req<unknown[]>("GET", `/tracks/${id}/turns`),

  // copilot chat
  chat: (text: string, o: SteerOpts & { card?: string } = {}) => req<ChatReply>("POST", "/chat", { text, ...o }),
  chatCancel: () => req("POST", "/chat/cancel", {}),
  chatHistory: () => req<{ messages: ChatMsg[]; session_id?: string }>("GET", "/chat/history"),

  models: () => req<{ id: string; label?: string; desc?: string }[]>("GET", "/models"),
  loopMap: () => req<LoopMap>("GET", "/loop/map"),
  // PM/CTO: cached briefing (no LLM) vs a fresh report (one model turn).
  pmPlan: () => req<PmData>("GET", "/pm/plan"),
  pmReport: (goal?: string, model?: string) => req<PmBrief>("POST", "/pm/report", { goal, model }),
  pmConfig: (patch: Record<string, unknown>) => req<PmConfig>("POST", "/pm/config", patch),
  pmConsolidatePropose: () => req<ConsolidationProposal>("POST", "/pm/consolidate", { mode: "propose" }),
  pmConsolidateApply: (repos: ConsolidationRepo[]) =>
    req<{ created: { id: string }[]; archived: string[] }>("POST", "/pm/consolidate", { mode: "apply", repos }),
  automation: () => req<Record<string, unknown>>("GET", "/automation"),

  // Phase 2 section lists
  processes: () => req<any[]>("GET", "/processes"),
  runs: () => req<any[]>("GET", "/runs"),
  claudeSessions: () => req<any[]>("GET", "/sessions/claude"),
  adoptClaude: (b: Record<string, unknown>) => req<{ id?: string; error?: string }>("POST", "/sessions/claude/adopt", b),
  gitHistory: () => req<any[]>("GET", "/history"),

  // settings / users / connectors
  settings: () => req<Record<string, any>>("GET", "/settings"),
  saveSettings: (patch: Record<string, unknown>) => req("POST", "/settings", patch),
  users: () => req<import("./types").UserRow[]>("GET", "/users"),
  setRole: (name: string, role: string) => req("POST", `/users/${name}/role`, { role }),
  issueToken: (name: string, label: string) => req<{ token: string }>("POST", `/users/${name}/tokens`, { label }),
  connectors: () => req<any[]>("GET", "/connectors"),
  runConnector: (name: string) => req<{ cards?: number }>("POST", `/connectors/${name}/run`),
  rollbackConnector: (name: string) => req("POST", `/connectors/${name}/rollback`),
};

