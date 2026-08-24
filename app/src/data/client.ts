import { track } from "./analytics";
import { useAuthGate } from "./authgate";
import { useConfig } from "./config";
import { demoRespond, useDemo } from "./demo";
import { open, seal } from "./e2ee";
import { useHealth } from "./health";
import { t } from "@/i18n/core";

import type { Attach } from "./attachments";
import type { Track, LaneMove, Metrics, Me, Usage, UsageWindow,
  SignMeaning, SignSubject, Signature, SignBatchItem, SignBatchResult } from "./types";
import type { VoiceClip } from "./voice";

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

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal, skipAuthGate = false): Promise<T> {
  // DEMO seam (the one data/demo.ts documents): with the sample board active,
  // answer from the fixture and never touch the network. Unmodelled endpoints
  // answer {} - empty, not a fake success payload. Pairing a real daemon calls
  // useDemo.disable(), so this path is unreachable in real use.
  if (useDemo.getState().active) {
    // The version long-poll must BLOCK like the real daemon (~22s): the global
    // stream loop re-calls it immediately on success, so an instant answer
    // would spin that loop hot and starve the UI.
    if (path.startsWith("/stream/wait")) await new Promise((r) => setTimeout(r, 8000));
    const d = demoRespond(method, path, body);
    return (d === undefined ? {} : d) as T;
  }
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
  // /auth/login's OWN 401 (wrong password) must NOT be treated as "the
  // session went bad" - skipAuthGate lets it fall through to the generic
  // ApiError path below instead, which surfaces the daemon's real
  // {"error": "wrong name or password"} text to the login screen.
  if (status === 401 && !skipAuthGate) {
    // Demo mode has no real session and never should be forced into a login
    // screen - it's local sample data, not a daemon-backed account.
    if (!useDemo.getState().active) useAuthGate.getState().reportAuthRequired();
    throw new AuthRequired();
  }
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
/** The PM session's measured economics (daemon: copilot._fold_stats) — the
 *  board chat's card-parity context meter + usage line read this. ctx_tokens/
 *  ctx_window mirror a card's fields (window derived from model evidence, not
 *  assumed); plan_pct is the flat plan's share-of-subscription when calibrated. */
export interface ChatStats {
  turns: number; cost: number; tokens_in: number; tokens_out: number;
  ctx_tokens?: number; ctx_window?: number; plan_pct?: number | null;
}
// POST /chat returns the copilot's answer, not a ChatMsg: {reply, actions, ...}
// (or {error} on a rejection). Keep ChatMsg for /chat/history entries.
export interface ChatReply { reply?: string; error?: string; cost?: number;
  actions?: { tool?: string; detail?: string }[]; usage?: unknown;
  /** Henry's prose as speech, rendered by the daemon and inlined as base64 —
   *  present only when the request asked for it (`voice: true`). It rides inside
   *  this JSON because the phone reaches the daemon through the E2EE relay,
   *  which seals one request/response and offers no second binary channel
   *  (spine/media/voice.py render_b64). Absent when speech was
   *  unavailable, which is a soft failure: the text reply is still here. */
  voice?: VoiceClip | null }

// `attachments` was dropped when the archived web composer (SendOpts, which had
// it) was ported to RN - the daemon has accepted it the whole time. Both /steer
// and /chat spread these opts into the request body, so adding it here wires it.
export interface SteerOpts {
  model?: string; thinking?: string; mode?: string; attachments?: Attach[];
  /** Ask the daemon to also render the reply as speech. Per REQUEST, not a
   *  server setting, because only the client knows whether the owner is looking
   *  at the screen or driving (cells/copilot/routes_copilot.py).
   *
   *  `true` renders ONE clip after the turn finishes and returns it inline.
   *  `"stream"` renders sentence by sentence WHILE the turn runs; those clips
   *  are collected from `chatLive(voiceFrom)` instead, so speech starts about a
   *  second in rather than after the whole answer. Only a caller that actually
   *  polls may ask for "stream" — the daemon then skips the one-shot render, so
   *  a client that asked and did not collect would simply hear nothing. */
  voice?: boolean | "stream";
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
/** The PM computes a plan-aware budget block the board renders GENERICALLY by
 *  `kind`: "usage" (Max plan - the subscription allowance IS the budget, so it
 *  carries the real /usage windows + a measured verdict) or "cash" (API plan -
 *  euro spend vs the monthly cap). Adding a plan = a new kind + a render branch,
 *  nothing hardcoded per screen. `state` (measured) drives the triage colour. */
export interface PmBudget {
  plan?: string; kind?: "usage" | "cash"; state?: "ok" | "warn" | "blocked";
  note?: string; est_turns_to_goal?: number; velocity_turns_per_day?: number;
  pace_turns_per_day?: number; eta_days?: number;
  // kind === "usage" (Max)
  windows?: UsageWindow[]; usage_plan?: string | null;
  // kind === "cash" (API)
  monthly_eur?: number; spent_to_date_eur?: number; cash_to_goal_eur?: number; projected_eur?: number;
}
export interface PmBrief {
  summary?: string; done_pct?: number; milestones?: PmMilestone[];
  next?: { title: string; reason?: string; card?: string | null }[]; risks?: string[];
  budget?: PmBudget; economics?: Record<string, unknown>; goal?: string; generated_at?: string;
  // the golden triage + gate (PM planning gate)
  plan_status?: "ready" | "blocked" | "needs_spike"; gate?: string;
  triage?: { budget?: "ok" | "blocked"; timeline?: "ok" | "blocked"; scope?: "ok" | "blocked" };
  // WHY a corner is red - filled by the measured triangle gate (pm._gate_triangle),
  // so a downgrade shows its reason instead of an unexplained red.
  triage_reasons?: { budget?: string; timeline?: string; scope?: string };
  feasibility?: { budget?: string; earliest_done?: string; note?: string };
  open_questions?: string[];
  // the independent verifier's findings (pm._verify_plan) - why plan_status
  // got downgraded, shown as detail on tap in a blocked corner.
  verify?: { ready?: boolean; gate?: string; issues?: string[]; must_ask?: string[] };
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

// The harness exports its REAL state machine (daemon: sessions.flow() +
// loop_state.machine()), so these graphs are derived from the code that runs
// them rather than re-described here. `settings` names the exact settings key
// that governs a policy node, so a node can link straight to its knob.
export interface LoopNode {
  key: string; label?: string; kind?: "fixed" | "policy"; instruction: string;
  settings?: string[];
  /** "tools/loop_state.py:472" - read out of the source at call time, so a
   *  fixed node can cite the code it IS instead of only claiming to be code. */
  source?: string;
  /** WHY this node is fixed, or what exactly is adjustable when it is policy.
   *  Declared next to `kind` in the daemon (loop_state.LOOP_STATES /
   *  sessions.LANE_FLOW), never composed here: a padlock the UI cannot explain
   *  reads as arbitrary, and a reason the UI invents is a claim about code it
   *  cannot see. Optional so an older daemon degrades to the generic legend. */
  why?: string;
}
export interface LoopEdge {
  from: string; to: string; verb?: string; when?: string;
  kind?: "fixed" | "policy"; instruction?: string; settings?: string[];
}
/** A build-loop state. `active` marks where the checkout currently sits. */
export interface LoopState extends LoopNode { modes?: string[]; active?: boolean }
/** Which brief + settings layer each agent surface resolved to (harness/). */
export interface HarnessAgent {
  name: string; source: string; settings: string;
  setting_sources?: string; ask_protocol: boolean; chars: number;
}
export interface LoopMap {
  runtime: { title: string; lanes: LoopNode[]; gate: LoopNode & { between: string[] }; edges?: LoopEdge[] };
  build: {
    title: string; states: LoopState[]; edges?: LoopEdge[];
    /** "card" = a card's worktree (no workorder ceremony) vs "repo". */
    mode?: "card" | "repo"; mode_note?: string; active?: string;
    current?: { state: string; action: string }[];
  };
  /** Present only when the daemon could read harness/ - errors is empty when healthy. */
  harness?: { agents: HarnessAgent[]; errors: Record<string, string> };
  /** `source` names the module that ENFORCES the law, so it is traceable to code. */
  laws: { key: string; text: string; source?: string }[];
  charter: string;
  /** The dotted paths /automation actually renders a control for (derived from
   *  the daemon's _config_schema). A node's `settings` entry is only offered as
   *  a tap-through when it is in here - capacity.wip_limit and
   *  env.SWARM_WIP_MINUTES are real knobs that live in settings.json / the
   *  environment, and linking them to a screen that has no field for them is a
   *  promise the app cannot keep. */
  editable?: string[];
  /** Where lane RENAMES live - every lane's name is data, whatever its kind. */
  lane_labels_path?: string;
}

// ---------------------------------------------------------------------------
// /harness - the editable policy behind each agent surface, plus the spawn
// preview. The preview is "effective config with provenance" (git config
// --show-origin): not what the harness is configured to do, but the resolved
// command and where every piece of it came from.
// ---------------------------------------------------------------------------
export interface HarnessSurface {
  key: "card" | "machine" | "pm"; agent: string; label: string;
  /** the ONE daemon function that assembles this surface's argv */
  builder: string; cwd: string;
}
export interface HarnessVersion { id: string; ts: string; actor: string; bytes: number }
export interface HarnessAgentDoc {
  name: string; path: string; exists: boolean; text: string; sha256: string;
  resolved_chars: number; ask_protocol: boolean;
  frontmatter: Record<string, unknown>; versions: HarnessVersion[];
}
export interface HarnessSettingsDoc {
  key: string; path: string; exists: boolean; text: string; sha256: string;
  versions: HarnessVersion[];
}
/** One settings layer the CLI would load, and whether this surface gets it. */
export interface HarnessLayer {
  layer: "user" | "project" | "local"; path: string; exists: boolean;
  included: boolean; note: string; reason: string;
}
/** One hook, flattened. `included: false` = present on the box but excluded. */
export interface HarnessHook {
  event: string; matcher: string; command: string; timeout?: number;
  origin: string; layer: string; included: boolean; broken?: boolean;
}
export interface HarnessPreview {
  key: string; agent: string; label: string; builder: string; cwd: string;
  /** the logical argv the builder produced */
  argv: string[];
  /** what is REALLY exec'd: drivers._cmd_line rewrites a claude.cmd shim to the
   *  real bin/claude.exe, because routing a .cmd through cmd.exe mangles quoted
   *  args — the bug that once ate --resume. */
  exec?: string[]; exec_rewritten?: boolean; exec_form?: string;
  argv_error?: string; note?: string;
  brief: {
    source: string; exists: boolean; file_sha256: string;
    resolved_sha256: string; resolved_chars: number; ask_protocol: boolean;
  };
  settings_layer: { path: string; active: boolean; declared: string; note: string };
  /** Is the shared, non-git auto-memory directory writable from THIS surface?
   *  Read out of the real settings file's permissions.deny at preview time -
   *  see daemon/harness.py's _memory_isolation. */
  memory: { denied: boolean; patterns?: string[]; note: string };
  layers: HarnessLayer[];
  hooks: HarnessHook[]; hooks_active: number;
  /** settings files setting disableAllHooks — the matrix cannot be trusted
   *  while non-empty, and we deliberately do not guess which rows it kills. */
  hooks_disabled_by?: string[];
  errors: Record<string, string>;
}
export interface HarnessDocument {
  surfaces: HarnessSurface[];
  agents: HarnessAgentDoc[];
  settings: HarnessSettingsDoc[];
  previews: HarnessPreview[];
  errors: Record<string, string>;
}
export interface HarnessWriteResult {
  path: string; kept_version: string; validator: string; sha256: string;
  resolved_chars?: number; document: HarnessDocument;
}

// GET /cells manifest shape (cells.py manifest()) - one entry per
// registered agentic-system cell, live enable-state derived from policy.
// logicFiles/harnessFile/uiFiles are real repo-relative paths; routes is
// DERIVED daemon-side from the cell's actual route module dispatch tables
// (never hand-duplicated) - all of it is also the read_source() allowlist,
// so anything listed here is exactly what GET /cells/<id>/source can serve.
export interface CellInfo {
  id: string;
  enabled: boolean;
  enabledKey: string;
  role: string;
  surface: string;
  modes: string[];
  logicFiles: string[];
  storage: string;
  harnessFile: string;
  routes: string[];
  uiFiles: string[];
  tools: string[];
}

export const api = {
  get: <T,>(path: string) => req<T>("GET", path),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) => req<T>("POST", path, body, signal),
  // Restores what the old Next.js web app's AuthGate (web/components/
  // auth.tsx, archived at the Expo cutover) used to do - a real username/
  // password login, lost when that component was never ported. skipAuthGate
  // (the 5th req() arg) so a wrong password surfaces as a normal ApiError
  // with the daemon's real message, not a message-less AuthRequired.
  login: (name: string, password: string) =>
    req<{ ok: boolean; token?: string; error?: string }>("POST", "/auth/login", { name, password }, undefined, true),
  // Drives the login screen's mode (first-run setup vs. sign-in vs. optional
  // self-registration) - mirrors the shape routes_auth.py's auth_state
  // actually returns. skipAuthGate: an expired/garbage token must not block
  // finding out whether setup is needed in the first place.
  authState: () => req<{ setup_needed: boolean; user: unknown; registration: boolean; registration_open: boolean }>(
    "GET", "/auth/state", undefined, undefined, true),
  authSetup: (name: string, password: string) =>
    req<{ ok: boolean; token?: string; error?: string }>("POST", "/auth/setup", { name, password }, undefined, true),
  authRegister: (name: string, password: string, invite: string) =>
    req<{ ok: boolean; token?: string; error?: string }>("POST", "/auth/register", { name, password, invite }, undefined, true),
  // Board PUSH long-poll: blocks until the data version passes `v` (or ~22s),
  // returns the new version. Works over the sealed relay AND direct; the app
  // loops it and invalidates queries on change (replaces the direct-only SSE).
  boardWait: (v: number) => req<{ v: number }>("GET", `/stream/wait?v=${v}`),

  // board / cards
  tracks: () => req<Track[]>("GET", "/tracks"),
  metrics: () => req<Metrics>("GET", "/dashboard/data"),
  usage: () => req<Usage>("GET", "/usage"),
  me: () => req<Me>("GET", "/me"),
  // The cell registry manifest (cells.py) - which agentic systems exist
  // and whether each is enabled. Used to gate nav (see (tabs)/_layout.tsx) and
  // the Modules screen's CELLS section.
  cells: () => req<{ cells: CellInfo[] }>("GET", "/cells"),
  // One file's real source text for the code-map diagram's click-to-code
  // panel. Owner-only server-side; `file` must be one of that cell's OWN
  // declared files (the manifest above IS the allowlist) or this 404s.
  cellSource: (id: string, file: string) =>
    req<{ file: string; text: string }>("GET", `/cells/${encodeURIComponent(id)}/source?file=${encodeURIComponent(file)}`),
  // ->working/review/done are run in the BACKGROUND by the daemon (the gate is a
  // subprocess, the merge + deploy hook follow it), so those reply {started,
  // gating} instead of the finished Track. The verdict arrives on the card
  // (status/gate_report/merge_report), in the chat and by push - not here.
  // Card actions carry a coarse analytics event at the call site (the api layer
  // is their single owner) - action names + lane only, never ids or titles.
  moveLane: (id: string, lane: string) => { track("card_move", { lane }); return req<LaneMove>("POST", `/tracks/${id}/lane`, { lane }); },

  // ---- GxP sign-off -------------------------------------------------------
  // What signing this card would commit to. The subject (the head/base commit
  // pair) is computed SERVER-side from git and only read here - a
  // client-supplied commit id would let a signature name a state the signer
  // never saw, which is the one thing the binding exists to prevent.
  signSubject: (id: string) => req<SignSubject>("GET", `/sign/subject/${id}`),
  // skipAuthGate: a wrong password answers 401, and without it the global auth
  // gate would throw the user out to the login screen instead of saying
  // "password not accepted" in the dialog they are standing in.
  sign: (card: string, meaning: SignMeaning, reason: string, password: string) => {
    track("card_sign", { meaning });
    return req<{ ok: boolean; signature: Signature }>(
      "POST", "/sign", { card, meaning, reason, password }, undefined, true);
  },
  signBatch: (cards: SignBatchItem[], password: string) => {
    track("card_sign_batch", { n: cards.length });
    return req<{ results: SignBatchResult[] }>(
      "POST", "/sign/batch", { cards, password }, undefined, true);
  },

  reorder: (ids: string[]) => req("POST", "/tracks/reorder", { ids }),
  newTrack: (b: Record<string, unknown>) => { track("card_new"); return req("POST", "/tracks/new", b); },
  update: (id: string, patch: Record<string, unknown>) => req("POST", `/tracks/${id}/update`, patch),
  archive: (id: string) => { track("card_archive"); return req("POST", `/tracks/${id}/archive`); },
  fork: (id: string, from = "") => { track("card_fork"); return req("POST", `/tracks/${id}/fork`, { from }); },
  // Split the CONVERSATION into a new card (keeps context) - distinct from
  // fork() above, which forks the code at a ref with a fresh session.
  forkChat: (id: string, first = "") =>
    req<{ id?: string; error?: string }>("POST", `/tracks/${id}/fork-chat`, { first }),
  del: (id: string) => { track("card_delete"); return req("POST", `/tracks/${id}/delete`); },
  cancel: (id: string) => { track("card_cancel"); return req("POST", `/tracks/${id}/cancel`); },
  steer: (id: string, text: string, o: SteerOpts = {}) => {
    track("card_steer");
    return req("POST", `/tracks/${id}/steer`, { text, ...o });
  },
  // Answer the worker's pending question (daemon/ask.py). `answers` maps each
  // question's header -> the chosen option label (an array when multiSelect).
  // Backgrounded by the daemon like a steer, because it RUNS the continuing
  // turn. `requestId` is echoed back so a stale panel is rejected instead of
  // answering a question the worker has already moved past.
  answer: (id: string, answers: Record<string, string | string[]>, requestId: string) => {
    track("card_answer");
    return req<{ started: string; answered: boolean }>(
      "POST", `/tracks/${id}/answer`, { answers, request_id: requestId });
  },

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
  chat: (text: string, o: SteerOpts & { card?: string } = {}) => {
    track("chat_message", { scope: o.card ? "card" : "board" });
    return req<ChatReply>("POST", "/chat", { text, ...o });
  },
  chatCancel: () => req("POST", "/chat/cancel", {}),
  /** LIVE voice pipeline STT: one VAD-cut utterance (WAV, base64) -> text.
   *  Server-side faster-whisper (spine/media/stt.py); 501 with the
   *  install hint when the daemon lacks the package - surfaced, never mute. */
  transcribe: (audioB64: string, lang?: string) =>
    req<{ text: string; info?: { lang?: string; p?: number; dur?: number } }>(
      "POST", "/voice/transcribe", { audio: audioB64, lang }),
  chatHistory: () => req<{ messages: ChatMsg[]; session_id?: string; stats?: ChatStats | null }>("GET", "/chat/history"),
  /** The live turn. `voiceFrom` is a READ CURSOR (the highest chunk seq already
   *  taken): pass it to also collect the speech the daemon has rendered so far,
   *  omit it to stay the text-only poller the board chat has always been — the
   *  clips are by far the heaviest part of this response, and the text chat has
   *  no use for them. `voice_pending` is why the loop cannot simply stop when
   *  `running` goes false: the turn can be over while the last sentence is
   *  still rendering. */
  chatLive: (voiceFrom?: number, voiceTurn?: number) => req<{
    text: string; thinking?: string; running: boolean;
    voice?: (VoiceClip & { turn?: number; seq: number; text?: string })[];
    voice_pending?: boolean;
  }>("GET", voiceFrom === undefined ? "/chat/live"
    // `voice_turn` names the turn the cursor counts in — seq restarts at 1
    // every turn, so after a steer a bare seq would silently swallow the new
    // answer's clips (voice_stream.take). An old daemon ignores the param.
    : `/chat/live?voice_from=${voiceFrom}${voiceTurn ? `&voice_turn=${voiceTurn}` : ""}`),

  // Render text the phone already holds (a decrypted push's title/body) as
  // speech - the proactive-blocker half of phone voice (data/push.ts). Same
  // daemon-renders/client-plays split as chat's voice:true; `clip` is null
  // when speech is unavailable (offline, no edge-tts) and the caller just
  // stays with the visual notification.
  speak: (text: string) => req<{ clip: VoiceClip | null }>("POST", "/notify/speak", { text }),

  // The daemon guarantees a non-empty list (manifest fallback), so an empty or
  // non-array answer is a transport artifact - throw so react-query retries
  // instead of caching a picker that only shows "Auto".
  models: () => req<{ id: string; label?: string; desc?: string }[]>("GET", "/models").then((m) => {
    if (!Array.isArray(m) || m.length === 0) throw new TransportError("empty /models");
    return m;
  }),
  loopMap: () => req<LoopMap>("GET", "/loop/map"),
  escalations: () => req<{ id: string; ts: string; kind: string; card?: string; detail?: string;
    attempts: number; closed: boolean; action?: string; why?: string }[]>("GET", "/escalations"),
  harness: () => req<HarnessDocument>("GET", "/harness"),
  /** Write a brief or a settings layer, or roll one back with `restore`.
   *  The daemon validates BEFORE writing and returns the fresh document, so the
   *  editor re-renders argv/hashes/hooks from what is now actually on disk. */
  harnessSave: (b: { kind: "agents" | "settings"; name: string; text?: string; restore?: string }) =>
    req<HarnessWriteResult>("POST", "/harness", b),
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

