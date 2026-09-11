import { track } from "./analytics";
import { useAuthGate } from "./authgate";
import { deviceLabel, useConfig } from "./config";
import { demoRespond, useDemo } from "./demo";
import { diag } from "./diag";
import { open, seal } from "./e2ee";
import { useHealth } from "./health";
import { t } from "@/i18n/core";

import type { Attach } from "./attachments";
import type { Track, LaneMove, Metrics, Me, Profile, Board, BoardColumn, Usage, UsageWindow,
  PendingQuestion, SignMeaning, SignSubject, Signature, SignBatchItem, SignBatchResult,
  GxpState } from "./types";
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

/** True when the daemon never PROCESSED the request: the transport never got
 *  there, or the session was refused before any work happened. Only these two
 *  classes mean an owner message is still undelivered and belongs in the outbox
 *  (data/outbox.ts) - an ApiError means the daemon did receive it and answered,
 *  and a turn the owner cancelled with Stop must not come back as "not sent". */
export const neverDelivered = (e: unknown) =>
  e instanceof TransportError || e instanceof AuthRequired;

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
//
// `timeoutMs` (chat-load-latency phase A.3): this fetch had NO client bound at
// all, so a hanging request held the spinner all the way to the relay's own
// 504 after REPLY_TIMEOUT (120s) instead of failing fast. `undefined` means
// "do not abort" - the ONLY caller that passes it is req()'s POST /chat, since
// a client abort there leaves the send un-acked, which is exactly what drives
// the chat_dedupe replay-duplicate path (already paid for once, see req()).
async function relayReq(method: string, path: string, bodyStr: string, timeoutMs?: number): Promise<{ status: number; body: string }> {
  const { relayUrl, room, daemonPub, mySec, myPub } = useConfig.getState();
  const inner = JSON.stringify({ method, path, headers: authHeaders(), body: bodyStr });
  const cipher = seal(inner, mySec, daemonPub);
  const ctl = timeoutMs !== undefined ? new AbortController() : undefined;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : undefined;
  let r: Response;
  try {
    r = await fetch(`${relayUrl}/relay?room=${room}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pub: myPub, cipher }),
      signal: ctl?.signal,
    });
  } catch (e) {
    if (ctl && (e as Error)?.name === "AbortError") throw new TransportError(t("net.relayTimeout"));
    throw new TransportError(t("net.relayUnreachable"));
  } finally {
    if (timer) clearTimeout(timer);
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
  // Shared by both transports (chat-load-latency phase A.3): /stream/wait and
  // /tracks/:id/transcript/live are held server-side for ~22-25s by design
  // (spine/http/server.py, routes_tracks.py - "22s < relay REPLY_TIMEOUT").
  const isLongPoll = path.startsWith("/stream/wait") || path.includes("/transcript/live");
  let status: number, txt: string;
  try {
    if (cfg.relayMode()) {
      // Relay ladder: 35s for a long-poll (> the server's ~22s hold + tunnel
      // margin), 20s for a normal request, and POST /chat left UNBOUNDED
      // (timeoutMs undefined) - see relayReq's docstring for why a chat abort
      // is worse than the hang it would fix.
      ({ status, body: txt } = await relayReq(method, path, bodyStr,
        path === "/chat" ? undefined : isLongPoll ? 35_000 : 20_000));
    } else {
      // Bare fetch has NO default timeout (Paseo's daemon client bounds every
      // probe to 6-10s; this had none). Measured failure: a fresh install's
      // default baseUrl is the ANDROID EMULATOR loopback (10.0.2.2) - dead on
      // a real phone - and an unreachable host doesn't reject a plain fetch
      // promptly, it hangs. The Dashboard's query then sits in isLoading
      // forever with no error to show a HealthBanner or a pairing prompt -
      // an unrecoverable spinner on first launch. Wrap the CALLER's signal (if
      // any - React Query's unmount-abort) so both cancellation and timeout
      // still fire the fetch's own AbortError, then tell them apart below.
      const timeoutCtl = new AbortController();
      // 8s is the right bound for a PROBE (an unreachable host must not hang
      // the dashboard). It is the wrong bound for an endpoint that runs a model
      // turn: POST /chat regularly takes 2-3 minutes (measured 176s on
      // 2026-08-28), so an 8s abort guaranteed the client abandoned every real
      // turn and left the send unacked — which is the state a lower layer
      // answers by REPLAYING the POST (see cells/copilot/chat_dedupe.py for the
      // duplicate-message evidence). The composer's Stop button, not a
      // stopwatch, is what bounds a turn.
      // Same mismatch hit the hanging-GET long-polls: /stream/wait and
      // /tracks/:id/transcript/live are held server-side for ~22-25s by design
      // (spine/http/server.py, routes_tracks.py - "22s < relay REPLY_TIMEOUT")
      // and the app re-arms them in a tight loop (_layout.tsx's useLiveWait).
      // The blanket 8s probe bound aborted EVERY idle cycle before the server
      // could ever answer, so direct-mode clients (the desktop shell always is
      // one - surfaces/desktop/main.js has no relay config) racked up transport
      // failures continuously and the reconnect banner never cleared - owner
      // report 2026-09-09 ("banner die ganze Zeit" on desktop). 30s clears the
      // server's own bound with margin and is still a real bound if the LAN
      // host is actually gone.
      const timer = setTimeout(() => timeoutCtl.abort(),
        path === "/chat" ? 900_000 : isLongPoll ? 30_000 : 8000);
      if (signal) {
        if (signal.aborted) timeoutCtl.abort();
        else signal.addEventListener("abort", () => timeoutCtl.abort(), { once: true });
      }
      let r: Response;
      try {
        r = await fetch(cfg.baseUrl + path, {
          method, headers: authHeaders(),
          body: method === "GET" ? undefined : bodyStr, signal: timeoutCtl.signal,
        });
      } catch (e) {
        if ((e as Error)?.name === "AbortError") {
          if (signal?.aborted) throw e;   // caller cancelled, not a health event
          throw new TransportError(t("net.lanTimeout"));   // OUR timeout fired
        }
        throw new TransportError(t("net.lanFailed"));
      } finally {
        clearTimeout(timer);
      }
      status = r.status; txt = await r.text();
    }
  } catch (e) {
    if (e instanceof TransportError) useHealth.getState().reportFail(e.message);
    // Only FAILURES are recorded here, never the successes: this client carries
    // the whole app (polls included), so logging every round-trip would push a
    // real fault out of the buffer within seconds. The health store keeps the
    // "still fine" signal; the black box keeps the faults.
    diag("net", `${method} ${path.split("?")[0]}`, String((e as Error)?.message || e));
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
    // The class of failure that until now was thrown and forgotten unless some
    // call site happened to render it - a silent 4xx is the hardest kind to
    // diagnose on a device precisely because nothing shows.
    diag("net", `${method} ${path.split("?")[0]}`, `${status}${msg ? " " + msg : ""}`);
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
/** `client_msg_id` is the `mid` the sender minted for this message, echoed back
 *  by the daemon on the persisted `you` entry. It is what lets the chat retire
 *  an optimistic copy by IDENTITY instead of by comparing text — optional
 *  because older daemons, the watch and the glasses do not send one. */
export interface ChatMsg { cls: string; text: string; ts?: string; client_msg_id?: string;
  /** `cls: "card"` — the EVENT MIRROR (cells/copilot/card_mirror.py). A working
   *  card's question, result or blocker, folded into the Henry chat at event
   *  time so the owner has ONE inbox instead of one transcript per card.
   *  `card` is the binding an inline reply is routed by — never the text; see
   *  routes_copilot._route_to_card for why guessing is ruled out. `cardName` is
   *  the short label, `kind` which of the three this is. `question` carries the
   *  whole ask block when the card is asking, so the EXISTING QuestionPanel can
   *  offer the real options and answer with a request_id.
   *  All optional: absent on every other `cls`, and absent entirely from an
   *  older daemon — the chat must render such a message as ordinary text. */
  card?: string; cardName?: string; kind?: "question" | "result" | "blocker";
  /** The whole ask block, so the SHARED QuestionPanel can offer the real
   *  options. It rides TWO kinds of message and they settle through different
   *  doors (see openChatQuestion in app/chat.tsx):
   *    * `cls:"card"` — a worker asked; `card` says which one, and the answer
   *      goes to POST /tracks/<id>/answer with the request_id.
   *    * `cls:"bot"`  — HENRY asked. Parsed off his reply at event time by
   *      cells/copilot/copilot.chat and persisted beside the prose, so the
   *      panel survives a reload and shows on every device. Answered with
   *      POST /chat `answer_to`, which turns the choice into the owner's next
   *      message. Before that parse existed the block reached the app as raw
   *      TEXT and the transcript printed its JSON at the owner. */
  question?: PendingQuestion;
  /** "YYYY-MM-DD", stamped by copilot._append_log since 2026-08-29 and absent on
   *  everything written before it — which means "not recorded", not "today". */
  date?: string }
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
  voice?: VoiceClip | null;
  /** The daemon recognised this POST as a REPLAY of a message it already has
   *  (cells/copilot/chat_dedupe.py) and did not run a second turn. `reply` then
   *  carries the ORIGINAL turn's answer; it is empty only when that turn was
   *  still running when the daemon gave up waiting, in which case the answer
   *  arrives through the /chat/history poll like any other persisted turn. */
  duplicate?: boolean;
  /** Present when the message was routed to a CARD instead of answered by
   *  Henry (`reply_to_card`). `as` says which door it went through: "answer"
   *  settled the card's pending question, "steer" was a plain instruction.
   *  `reply` is empty in both cases — the card's response arrives in its own
   *  turn, mirrored back into this chat when it ends. */
  routed?: { card: string; as: "answer" | "steer" } }

// `attachments` was dropped when the archived web composer (SendOpts, which had
// it) was ported to RN - the daemon has accepted it the whole time. Both /steer
// and /chat spread these opts into the request body, so adding it here wires it.
export interface SteerOpts {
  model?: string; thinking?: string; mode?: string; attachments?: Attach[];
  /** Team-chat recipient picked in the composer ("henry" | "worker") — read
   *  client-side to route the send (api.chat vs api.steer) and echoed onto
   *  the rendered message; harmless if it rides along in a steer POST body,
   *  the server ignores unknown fields there. */
  to?: string;
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
  // no date field of any kind (pm-lean-advisor, 2026-09-04): CODE derives the
  // one ETA the app shows, as a RANGE, from measured pace - see PmBrief.eta.
  // calendar_wait still means "this is a wait, not your effort" for that sum.
  est_turns?: number; confidence?: "high" | "medium" | "low"; blocked_by?: string;
  calendar_wait?: boolean; why?: string; tasks?: PmTask[];
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
/** "Der Weg" (pm-lean-advisor phase 3.1, 2026-09-04): the causal chain a
 *  senior PM reports ("X blockiert → danach Y → dann Z"), not the parallel
 *  milestone list - `who` says whose move each step is. This is the ONE
 *  roadmap-shaped thing StatusPanel shows standing; milestones (the work
 *  breakdown behind it) stay behind Details. Empty when the plan has none
 *  (an old artifact, or the model omitted it) - the UI falls back to
 *  milestones so nothing goes blank. */
export interface PmCriticalPathStep {
  step: string; who: "du" | "agent" | "extern"; why?: string; card?: string | null;
}
export interface PmBrief {
  summary?: string; done_pct?: number; milestones?: PmMilestone[];
  critical_path?: PmCriticalPathStep[];
  next?: { title: string; reason?: string; card?: string | null }[]; risks?: string[];
  budget?: PmBudget; economics?: Record<string, unknown>; goal?: string; generated_at?: string;
  // plan_status/triage/gate are ENTIRELY code-derived now (pm_triangle.
  // _gate_triangle, pm-lean-advisor 2026-09-04) - no LLM writes any of these
  // three anymore, so there is no second pass to disagree with the first.
  plan_status?: "ready" | "blocked"; gate?: string;
  triage?: { budget?: "ok" | "blocked"; timeline?: "ok" | "blocked"; scope?: "ok" | "blocked" };
  // WHY a corner is red - filled by the measured triangle gate (pm._gate_triangle),
  // so a downgrade shows its reason instead of an unexplained red.
  triage_reasons?: { budget?: string; timeline?: string; scope?: string };
  // a RANGE from measured pace, never a single invented date - unknown until
  // at least one turn has been spent (pace > 0).
  eta?: { known: boolean; days_min?: number | null; days_max?: number | null };
  feasibility?: { budget?: string; note?: string };
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

// The harness exports its REAL state machine (daemon: sessions.flow() +
// loop_state.machine()), so these graphs are derived from the code that runs
// them rather than re-described here. `settings` names the exact settings key
// that governs a policy node, so a node can link straight to its knob.
export interface LoopNode {
  key: string; label?: string; kind?: "fixed" | "policy"; instruction: string;
  settings?: string[];
  /** "ops/tools/loop_state.py:472" - read out of the source at call time, so a
   *  fixed node can cite the code it IS instead of only claiming to be code. */
  source?: string;
  /** WHY this node is fixed, or what exactly is adjustable when it is policy.
   *  Declared next to `kind` in the daemon (loop_state.LOOP_STATES /
   *  sessions.LANE_FLOW), never composed here: a padlock the UI cannot explain
   *  reads as arbitrary, and a reason the UI invents is a claim about code it
   *  cannot see. Optional so an older daemon degrades to the generic legend. */
  why?: string;
  /** Only present when /loop/map was asked about a REPO (?repo=). Whether this
   *  station runs for that repo under its chosen template. Absent = the general
   *  machine was asked about, and every station is shown plainly. */
  active?: boolean;
  /** Why it is NOT active, in the owner's words - a station the template leaves
   *  out reads differently from a deploy step with no command behind it, and
   *  the map must not blur the two into one grey dot. */
  off_reason?: string;
  /** Active, but here is what it actually MEANS for this repo type: the gate in
   *  a document repo runs and reports PASS with nothing to compile. Honest
   *  labelling is what keeps "on" from over-promising. */
  note?: string;
  /** Whether a template may switch it at all. Exactly one station (deploy) is
   *  switchable; the daemon says which, so the app never renders a toggle that
   *  the server would refuse. */
  switchable?: boolean;
}
/** How ONE repo runs - spine/ops/projects.resolve(). The repo IS the project
 *  (owner decree 2026-08-30), so this is that record's repo half. */
export interface RepoView {
  repo: string; known: boolean;
  project: { id: string; name: string } | null;
  template: string; template_label: string; template_who: string;
  card_kind: string;
  /** The stations the template declares active. The app does NOT decide from
   *  this what a station is - it renders the graph the daemon sends. */
  stations: string[];
  station_notes?: Record<string, string>;
  deploy_hook: string;
  applied?: Record<string, unknown>;
  overrides?: Record<string, unknown>;
  /** Values the owner moved away from what the template set - RECORDED when it
   *  happened, not deduced by the app. PRD §5: a silently overwritten value was
   *  the original complaint, so the deviation is data. */
  deviations?: { key: string; template_value: unknown; value: unknown; explicit: boolean }[];
  applied_at?: string; applied_by?: string;
  error?: string;
}
/** One repo TYPE from the catalog (ops/harness/templates/*.md). */
export interface RepoTemplate {
  id: string; label: string; who: string;
  /** The one line the PICKER shows. `body` is the template file's full prose -
   *  reference for whoever edits it, far too much for a choice card. */
  summary: string;
  card_kind: string;
  stations: string[]; deploy_hook: string; body: string; source: string;
  settings?: Record<string, unknown>; notes?: Record<string, string>;
}
export interface RepoTemplates {
  templates: RepoTemplate[]; repos: RepoView[];
  /** Which stations a template may switch AT ALL - sent by the daemon so the
   *  picker cannot grow a toggle the server refuses (sessions.SWITCHABLE_STATIONS). */
  switchable: string[];
  stations: string[];
}
export interface LoopEdge {
  from: string; to: string; verb?: string; when?: string;
  kind?: "fixed" | "policy"; instruction?: string; settings?: string[];
}
/** A build-loop state. `active` marks where the checkout currently sits. */
export interface LoopState extends LoopNode { modes?: string[]; active?: boolean }
/** Which brief + settings layer each agent surface resolved to (ops/harness/). */
export interface HarnessAgent {
  name: string; source: string; settings: string;
  setting_sources?: string; ask_protocol: boolean; chars: number;
}
/** One station Henry acts at. `rules` are the behaviour-rule keys that put him
 *  there, so a tap can open exactly the rows responsible instead of guessing. */
export interface HenrySegment {
  station: string; labelKey: string; rules: string[]; count: number;
}
/** One cell's band under the pipeline: where this agent acts and what it does
 *  there. Copilot's segments are derived from its rules' binds, every other
 *  cell's from its declared `board` metadata in spine/registry/cells.py - the
 *  client keeps no cell list and no station list, it only draws what arrives. */
export interface CellTrack {
  cell: string; label: string;
  /** `labelKeys` (not `labelKey`) because one station can carry more than one
   *  verb for the same cell - e.g. copilot/backlog, where Henry's rule-derived
   *  "steuert" and the merged-in planning loop's "plant" both apply. Render
   *  every key and join; almost always a single-element array. */
  segments: { station: string; labelKeys: string[] }[];
}

/** One rule's value on ONE surface, with the provenance the badge is made of.
 *
 *  `layer` is where the effective value came from (default | seed | workspace |
 *  project) and `inherited` is simply "this project did not set it" - which is
 *  what "Geerbt vom Workspace" vs "Fuer dieses Projekt gesetzt" and the presence
 *  of a reset link are both driven by. Both are DERIVED by the daemon's
 *  resolution chain; the app never re-computes provenance, because two screens
 *  deriving it independently is exactly how they come to disagree. */
export interface RuleSurface {
  surface: string; path: string;
  value: unknown; default: unknown;
  layer: string; inherited: boolean;
}
/** One of Henry's behaviour rules, as the harness screen receives it.
 *
 *  `wire` says how it reaches reality (slot = renders into a brief, code = read
 *  at runtime by a named module, readonly = shown and never set) and `kind`
 *  says whether it is a knob at all. A `fixed` rule renders a LOCK with `why`
 *  and `source`, never a dead control - the same honesty SWITCHABLE_STATIONS
 *  already applies to stations.
 *
 *  The client holds NO rule list of its own: all of this arrives from
 *  spine/registry/behavior.py, so a rule added in the daemon shows up here with
 *  no app change - the same contract repo_pipeline.tsx already lives under. */
export interface BehaviorRule {
  key: string; block: string;
  wire: "slot" | "code" | "readonly";
  kind: "policy" | "fixed";
  control: string; options?: string[] | null;
  scope?: string; binds: string[];
  labelKey: string; descKey: string;
  why: string; source: string; reads?: string | null;
  /** The registered cell this rule governs (behavior.cell_of, derived from the
   *  rule's own reads/source against the cell registry), or null for a
   *  spine-owned rule. Optional so the app survives a daemon that predates it. */
  cell?: string | null;
  surfaces: RuleSurface[];
}
/** GET /harness/config - Henry's rules resolved for one project.
 *
 *  Deliberately NOT a superset of /loop/map: the stations, their knobs, the
 *  laws and the Henry track arrive there and the screen reads both, so neither
 *  route describes the machine twice. */
/** One run of the brief: fixed prose, or a value a rule put there.
 *
 *  The Mailchimp/HubSpot merge-tag shape - highlighted means adjustable,
 *  dimmed means fixed. `rule` is the key that produced a value, so tapping the
 *  chip can open the row that sets it instead of leaving the owner to find it. */
export interface BriefSegment { kind: "prose" | "rule"; text: string; rule?: string }
/** GET /harness/brief - one surface's brief, read-only, as the owner may read
 *  it. The daemon segments the SAME render the spawn uses, so this view cannot
 *  reassure him about a brief that is not the brief. */
export interface HarnessBrief {
  surface: string; label: string; agent: string; project: string;
  segments: BriefSegment[]; chars: number;
}
/** WHAT IS PHYSICALLY STORED, as opposed to what currently resolves.
 *
 *  `rules` above answers "which value applies here, and from which layer"; this
 *  answers "which rows exist at all". The two are genuinely different questions
 *  and the resolved view cannot answer the second by construction - it is scoped
 *  to one project, so a value set against another repo is invisible in it, and
 *  it filters to keys some table still declares, so a row left behind by a
 *  retired knob is invisible too. Both of those are exactly what an audit is
 *  looking for, which is why they arrive here instead.
 *
 *  Derived by spine/storage/configreview.py on every read - nothing here is a
 *  cached summary, and the app resolves nothing from it. */
export interface StoredProjectRow {
  project: string; key: string; value: unknown;
  /** Some table still declares this key. False means the row is on disk and the
   *  daemon has stopped honouring it - a value the owner set that silently went
   *  inert, which is the one thing no other screen can show. */
  declared: boolean;
  /** Belongs to the project the screen is currently resolving. Used to MARK the
   *  row, never to filter it. */
  selected: boolean;
}
export interface StoredBoardRow {
  id: string; name: string; owner: string;
  /** An empty label means "render this station's own name" (boards.py invariant
   *  1) and is reported as empty rather than resolved - resolving it here would
   *  make an unlabelled column look like a stored one. */
  columns: { station: string; label: string }[];
}
/** A pre-rules global settings.json key that has not moved onto its declared
 *  path. Normally absent; `refuse` carries the reason when the daemon declined
 *  to adopt a value rather than dropping it. */
export interface StoredLegacyRow { key: string; path: string; refuse?: string | null }
export interface StoredConfig {
  projectRows: StoredProjectRow[];
  boardRows: StoredBoardRow[];
  legacyRows: StoredLegacyRow[];
}
export interface HarnessConfig {
  project: string; repo: string;
  layers: string[];
  blocks: { key: string; labelKey: string; descKey: string }[];
  rules: BehaviorRule[];
  surfaces: { key: string; label: string }[];
  /** Optional so the app survives a daemon that predates this block - the same
   *  contract every Profile field lives under. */
  stored?: StoredConfig;
}

export interface LoopMap {
  runtime: {
    title: string; lanes: LoopNode[]; gate: LoopNode & { between: string[] };
    /** Deploy is a STEP, not a lane: it runs inside the accept transition
     *  (lanemachine._repo_hook), which is why it arrives beside `gate` with an
     *  `on` edge rather than in `lanes`. The owner still has to see it. */
    deploy?: LoopNode & { on?: string[] };
    /** The station VOCABULARY in flow order (backlog..deploy): what gets a
     *  config PAGE, what the owner may name in chat. NOT the picture - it
     *  contains gate and deploy, which are steps, and omits `done`, which is a
     *  lane. Use it for navigation; use `row` to draw. */
    stations?: string[];
    /** THE PICTURE, derived by the daemon (sessions._draw_row): `lanes` are the
     *  real columns - count and names straight from the nodes policy.lane_labels
     *  renames - and each step names the lane whose OUTGOING connector it sits
     *  on. Drawing `stations` as a flat row was the bug this replaced: it showed
     *  five equal columns for a four-lane board and dropped "Fertig" entirely.
     *  Absent on an older daemon, which falls back to the plain lane row. */
    row?: { lanes: string[]; steps: { key: string; after: string; on?: string[] }[] };
    edges?: LoopEdge[];
    /** THE HENRY TRACK (harness-config-ui phase 4): the band under the station
     *  row saying where Henry acts and what he does there. Aggregated by the
     *  daemon from the behaviour rules' `binds`, so a rule ADDED IN THE DAEMON
     *  lights its station up with no client change - the client keeps no rule
     *  list, exactly as it keeps no station list. Absent on an older daemon,
     *  which simply draws no band. */
    henry?: HenrySegment[];
    /** THE CELL TRACKS: one band per acting agent ("Henry steuert, engineer
     *  baut"), aggregated by the daemon (apimeta._cell_tracks) from the cell
     *  registry + the behaviour rules. Absent on an older daemon, which falls
     *  back to drawing the Henry band alone. */
    cells?: CellTrack[];
  };
  /** Present only when ?repo= was passed: how that one repo runs. */
  repo?: RepoView | null;
  build: {
    title: string; states: LoopState[]; edges?: LoopEdge[];
    /** "card" = a card's worktree (no workorder ceremony) vs "repo". */
    mode?: "card" | "repo"; mode_note?: string; active?: string;
    current?: { state: string; action: string }[];
  };
  /** Present only when the daemon could read ops/harness/ - errors is empty when healthy. */
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
// PUT /me/config's reply (accounts-boards-prd phase 1). It answers with the new
// resolved state so a write needs no follow-up GET.
//
// `skipped` is the load-bearing field and the reason this is not just {ok}: a
// MIGRATING device learns from it that the account already held those keys and
// its local values lost. Without it the device would report a successful push
// and quietly believe it won - which is the precise failure "never overwrite an
// account that has values" exists to prevent, made invisible.
// ---------------------------------------------------------------------------
export interface MyConfigResult {
  ok: boolean;
  /** keys that actually landed */
  written: string[];
  /** valid keys the daemon declined to write (a migration onto an account that
   *  already has a profile) */
  skipped: string[];
  profile: Profile;
  /** what the account has now CHOSEN, after this write */
  profile_keys: string[];
}

// ---------------------------------------------------------------------------
// /harness - the editable policy behind each agent surface, plus the spawn
// preview. The preview is "effective config with provenance" (git config
// --show-origin): not what the harness is configured to do, but the resolved
// command and where every piece of it came from.
// ---------------------------------------------------------------------------
export interface HarnessSurface {
  /** FOUR SPAWNED surfaces and four OVERLAYS (harness-config-ui phase 2). An
   *  overlay rides on an existing turn instead of starting a process, so its
   *  `builder` is empty; it is in this list because the behaviour rules key on
   *  surface, and a rule naming a surface the app did not know would render
   *  nowhere. voice/wear/glass/ship were Python string constants before.
   *  "ship-worker" (owner decree 2026-09-09, 18:04 correction) is the SPAWNED
   *  card that actually runs a ship - distinct from the "ship" OVERLAY above,
   *  which is only Henry's ship/no-ship DECISION riding on his own turn. */
  key: "card" | "machine" | "ship-worker" | "pm" | "voice" | "wear" | "glass" | "ship";
  agent: string; label: string;
  /** the ONE daemon function that assembles this surface's argv ("" = overlay) */
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
  /** The FULL surface list (primary + absorbed) - a merged cell keeps its
   *  absorbed systems' tabs (engineer carries surfaces.processes +
   *  surfaces.connectors), and tab-hiding iterates THIS so one switch hides
   *  them all. Optional so the app survives an older daemon (falls back to
   *  [surface]). */
  surfaces?: string[];
  modes: string[];
  logicFiles: string[];
  storage: string;
  harnessFile: string;
  routes: string[];
  uiFiles: string[];
  tools: string[];
}

/** Which installation is asking. Read fresh per call rather than captured at
 *  module load: config hydrates asynchronously, and a login that happened to
 *  race that would otherwise send an empty id and silently fall back to the
 *  old one-token-per-sign-in behaviour. */
const whoAmI = () => ({ device: useConfig.getState().deviceId, device_label: deviceLabel() });

export const api = {
  get: <T,>(path: string) => req<T>("GET", path),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) => req<T>("POST", path, body, signal),
  // Restores what the old Next.js web app's AuthGate (web/components/
  // auth.tsx, archived at the Expo cutover) used to do - a real username/
  // password login, lost when that component was never ported. skipAuthGate
  // (the 5th req() arg) so a wrong password surfaces as a normal ApiError
  // with the daemon's real message, not a message-less AuthRequired.
  //
  // Every credential-minting call carries THIS installation's id and label, so
  // the daemon replaces this device's previous token instead of stacking a new
  // permanent one beside it on every sign-in (routes_auth.py's _device_id).
  login: (name: string, password: string) =>
    req<{ ok: boolean; token?: string; error?: string }>("POST", "/auth/login", { name, password, ...whoAmI() }, undefined, true),
  // Drives the login screen's mode (first-run setup vs. sign-in vs. optional
  // self-registration) - mirrors the shape routes_auth.py's auth_state
  // actually returns. skipAuthGate: an expired/garbage token must not block
  // finding out whether setup is needed in the first place.
  authState: () => req<{ setup_needed: boolean; user: unknown; registration: boolean; registration_open: boolean }>(
    "GET", "/auth/state", undefined, undefined, true),
  authSetup: (name: string, password: string) =>
    req<{ ok: boolean; token?: string; error?: string }>("POST", "/auth/setup", { name, password, ...whoAmI() }, undefined, true),
  authRegister: (name: string, password: string, invite: string) =>
    req<{ ok: boolean; token?: string; error?: string }>("POST", "/auth/register", { name, password, invite, ...whoAmI() }, undefined, true),

  // Invitations (spine/auth/invites.py) - the ONE way a person joins this
  // workspace. The role is chosen HERE, when the invitation is created, and
  // travels inside the code; there is no workspace-wide default role to
  // inherit any more.
  invites: () => req<import("./types").InviteRow[]>("GET", "/invites"),
  createInvite: (role: "client" | "operator", ttlDays: number) =>
    req<import("./types").InviteRow>("POST", "/invites", { role, ttl_days: ttlDays }),
  revokeInvite: (code: string) => req<import("./types").InviteRow>("POST", `/invites/${code}/revoke`),
  // Board PUSH long-poll: blocks until the data version passes `v` (or ~22s),
  // returns the new version. Works over the sealed relay AND direct; the app
  // loops it and invalidates queries on change (replaces the direct-only SSE).
  // TWO cursors, one hanging request: `v` = board data, `c` = chat transcript.
  // Sending `c` is what opts this client into chat wake-ups (the daemon answers
  // board-only when it is absent, so an older bundle keeps working unchanged).
  boardWait: (v: number, c: number) =>
    req<{ v: number; c?: number }>("GET", `/stream/wait?v=${v}&c=${c}`),

  // board / cards
  tracks: () => req<Track[]>("GET", "/tracks"),
  metrics: () => req<Metrics>("GET", "/dashboard/data"),
  usage: () => req<Usage>("GET", "/usage"),
  me: () => req<Me>("GET", "/me"),
  // MY OWN profile rows (accounts-boards-prd phase 1). PUT, not POST: the
  // daemon answers this verb on exactly one path, deliberately kept off
  // do_POST because that chain carries the "clients can file and comment only"
  // denial - and a self-scoped view preference is precisely what a client role
  // MUST be able to write. There is no `user` parameter and there never will
  // be one: the account is taken from the session, which is what makes this
  // route safe without a capability.
  saveMyConfig: (config: Partial<Profile>) =>
    req<MyConfigResult>("PUT", "/me/config", { config }),
  // The one-time device->account push. Same route, same whitelist, but the
  // daemon fills only keys the account does NOT already have - so this is
  // idempotent and safe to call on every login (see data/profile.ts for why
  // the "once" is not tracked on the device).
  migrateMyConfig: (config: Partial<Profile>) =>
    req<MyConfigResult>("PUT", "/me/config", { config, migrate: true }),
  // MY OWN boards (accounts-boards-prd phase 2), on the same self-scoped PUT
  // for the same reason as the profile above. Create vs. update is decided by
  // `board.id`, not by the verb: omit it and the daemon MINTS one (so no
  // caller can squat an id), pass it and the daemon checks the row is yours -
  // or, for the shared default board, that you are the owner role. Which makes
  // this idempotent: a retry over a flaky relay updates instead of duplicating.
  saveBoard: (board: { id?: string; name: string; columns: BoardColumn[] }) =>
    req<{ ok: boolean; board: Board; boards: Board[] }>("PUT", "/me/boards", { board }),
  // The id rides in the query string, not the path: do_DELETE is a CLOSED
  // exact-match table (see its docstring), which is what keeps "every delete
  // ran the same three gates" readable in one block.
  deleteBoard: (id: string) =>
    req<{ ok: boolean; boards: Board[] }>("DELETE", `/me/boards?id=${encodeURIComponent(id)}`),
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

  // ---- GxP mode activation (card 6) ----------------------------------------
  gxpState: () => req<GxpState>("GET", "/gxp/state"),
  // Same re-auth shape as sign() above: skipAuthGate=true so a wrong password
  // answers 401 inline instead of bouncing the whole app to the login screen.
  // `repos` = picked from the known-repos list; `newRepos` = paths to create
  // + git-init server-side (spine.git.gitutil.init_repo) before being folded
  // into scope. Both omitted/empty = workspace-wide (spine/auth/gxp.py).
  activateGxp: (repos: string[] | undefined, newRepos: string[] | undefined, fourEyes: boolean, password: string) => {
    track("gxp_activate", { scope: (repos?.length || newRepos?.length) ? "repos" : "workspace" });
    return req<GxpState>(
      "POST", "/gxp/activate", { repos, new_repos: newRepos, four_eyes: fourEyes, password }, undefined, true);
  },

  reorder: (ids: string[]) => req("POST", "/tracks/reorder", { ids }),
  newTrack: (b: Record<string, unknown>) => { track("card_new"); return req("POST", "/tracks/new", b); },
  update: (id: string, patch: Record<string, unknown>) => req("POST", `/tracks/${id}/update`, patch),
  // Archiving is REVERSIBLE server-side (cardadmin.archive_track takes on=,
  // and the route reads body.on) - but this call sent no body at all, so the
  // app could only ever archive. An archived card was reachable only through
  // the board's Archive scope, with no way back from anywhere in the UI.
  archive: (id: string, on = true) => {
    track(on ? "card_archive" : "card_unarchive");
    return req("POST", `/tracks/${id}/archive`, { on });
  },
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
  // `reply_to_card` is deliberately NOT `card`. `card` means "the owner is
  // looking at this card, resolve 'it' against it" and still reaches Henry;
  // `reply_to_card` means "do not ask Henry at all, this belongs to that
  // card's worker" and is routed to steer/answer server-side. Two meanings on
  // one field would have silently turned the card chat's Henry tab into a
  // steer at the worker, with nothing in the UI to show why.
  // `answer_to` + `answers`: the owner TAPPED an option on one of Henry's own
  // <helmdeck-ask> questions. The daemon validates the choice against the
  // options Henry actually offered, renders it into the owner's next message
  // (spine/ops/ask.chat_answer_text) and runs the turn — so a tapped answer and
  // a typed one are the same message on the same path. `text` may be empty for
  // these: the daemon writes it. `answer_to` is the question id, rejected with
  // 409 once the conversation has moved past it.
  chat: (text: string, o: SteerOpts & { card?: string; reply_to_card?: string; mid?: string;
    answer_to?: string; answers?: Record<string, string | string[]> } = {}) => {
    track("chat_message", { scope: o.reply_to_card ? "card_reply" : o.card ? "card" : "board" });
    // `mid` is minted HERE, once per call, and travels inside the body - which
    // is precisely what makes it a replay detector. A chat turn runs for
    // minutes while three layers below this line (OkHttp's connection retry,
    // the relay's 120s REPLY_TIMEOUT, the daemon's own 115s urlopen) are
    // willing to resend an unacked POST; a resend replays these same bytes, so
    // it carries this same id and the daemon drops it (cells/copilot/
    // chat_dedupe.py). A genuine second send is a new call and mints a new id,
    // so repeating yourself on purpose still works. Minting it inside req()
    // would be wrong for the same reason - the relay path seals the body once,
    // per call, and that is the granularity we need.
    // The CALLER may mint it instead, and the board chat now does: it needs the
    // id on its optimistic message BEFORE the request goes out, so the daemon's
    // echo can retire exactly that copy later. Minting it here stays the default
    // for every other caller, and the replay semantics above are unchanged
    // either way — one id per call, travelling in the body.
    const mid = o.mid || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    return req<ChatReply>("POST", "/chat", { text, ...o, mid });
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
    /** The tool action currently executing ("Bash: py ..."), so the wait shows
     *  WHAT is happening while prose and thinking are silent (tool rounds went
     *  dark before - owner report 2026-09-02). Absent on an old daemon. */
    status?: string;
    /** Card id the running turn is scoped to, null for a board-chat turn. The
     *  feed is per USER, so a card chat must check this before rendering the
     *  prose as its own (copilot._running_card). Absent on an old daemon. */
    card?: string | null;
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
  // `repo` makes the map answer for ONE repo (which stations its template
  // leaves on, where it deviates). Omit it for the general machine.
  loopMap: (repo?: string) =>
    req<LoopMap>("GET", "/loop/map" + (repo ? `?repo=${encodeURIComponent(repo)}` : "")),
  // Henry's rules, resolved for one project. `repo` picks the project layer;
  // omitting it asks the workspace, which is the honest answer for a screen
  // opened without a repo rather than a fallback to some default one.
  harnessConfig: (repo?: string) =>
    req<HarnessConfig>("GET", "/harness/config" + (repo ? `?repo=${encodeURIComponent(repo)}` : "")),
  // THE write path for a rule. A null value CLEARS it, which is what restores
  // inheritance - the daemon deletes the row rather than storing a null, so
  // "absent" stays a property of the table. The server picks the layer from the
  // rule's own scope; this call deliberately cannot ask for one.
  saveHarnessConfig: (repo: string, values: Record<string, unknown>) =>
    req<{ ok?: boolean; before?: Record<string, unknown>; error?: string }>(
      "POST", "/harness/config", { repo, values }),
  // One surface's brief, read-only, with the values tagged (design doc 4.3).
  harnessBrief: (surface: string, repo?: string) =>
    req<HarnessBrief>("GET", `/harness/brief?surface=${encodeURIComponent(surface)}`
      + (repo ? `&repo=${encodeURIComponent(repo)}` : "")),
  repoTemplates: () => req<RepoTemplates>("GET", "/repo/templates"),
  // THE write path for a repo's type - the same mutator Henry's chat verb
  // calls, so a tap and a sentence can never produce different answers.
  applyRepoTemplate: (repo: string, template: string) =>
    req<RepoView & { error?: string }>("POST", "/repo/template", { repo, template }),
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
  // Fire-and-forget re-plan: the daemon answers INSTANTLY and runs the model
  // turn in a background thread (vs pmReport, which holds one HTTP request
  // open for as long as the turn takes - a self-repair + verify pass can run
  // several minutes, and over the relay round trip that left the UI spinning
  // forever with no way to tell success from a dead connection). Callers poll
  // pmPlan for plan.generated_at to move.
  pmReplan: () => req<{ planning: boolean; repos: string[] }>("POST", "/nightshift/plan", {}),
  pmConfig: (patch: Record<string, unknown>) => req<PmConfig>("POST", "/pm/config", patch),
  pmConsolidatePropose: () => req<ConsolidationProposal>("POST", "/pm/consolidate", { mode: "propose" }),
  pmConsolidateApply: (repos: ConsolidationRepo[]) =>
    req<{ created: { id: string }[]; archived: string[]; refused?: string[] }>(
      "POST", "/pm/consolidate", { mode: "apply", repos }),
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

  // remote devices (ops/docs/backlog/remote-device-execution)
  devices: () => req<import("./types").DeviceRow[]>("GET", "/devices/mine"),
  registerDevice: (label: string, billingScope: "external" | "shared" = "external") =>
    req<{ id: string; token: string }>("POST", "/devices/register", { label, billing_scope: billingScope }),
  revokeDevice: (id: string) => req("POST", `/devices/${id}/revoke`),
  reassignCard: (track: string, toDevice: string) =>
    req<import("./types").Track>("POST", "/devices/reassign", { track, to_device: toDevice }),
};

