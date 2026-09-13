// Daemon data shapes — ported verbatim from web/lib/api.ts (the Python daemon
// serves the same JSON to every client). Keep in sync with daemon/events.py.

// ---- GxP sign-off -----------------------------------------------------------
// 21 CFR 11.50(a)(3): a signature has to carry its MEANING. "reviewed" is what
// makes a two-person flow possible (A reviews, B approves) without a second
// mechanism.
export type SignMeaning = "approved" | "reviewed" | "rejected";

export interface Signature {
  seq: number;
  actor: string; actor_role: string;
  meaning: SignMeaning; reason: string;
  signed_at: string;                       // UTC, not host-local
  subject: { card: string; branch: string; head: string; base: string;
             commits: number; shortstat: string; files: string[] };
  auth: { method: string; components: string[] };
  git: { tag: string | null; tag_sha: string | null; merge_sha: string | null };
  consumed_by: { lane: string; at?: string } | null;
}

/** GET /sign/subject/<id> - what signing this card would commit to.
 *  `blocked` is set (and `subject` null) when the card cannot be signed at
 *  all - most often uncommitted work, because a signature has to name a commit
 *  that exists. */
export interface SignSubject {
  card: string;
  in_scope: boolean; four_eyes: boolean;
  dispatched_by?: string | null;
  signer: { name: string; role: string };
  subject: Signature["subject"] | null;
  blocked: string | null;
  signatures: Signature[];
}

export interface SignBatchItem { card: string; meaning: SignMeaning; reason: string }
/** One card's outcome in a batch. A card that drifted fails on its own without
 *  taking the others down - the result is a list, not all-or-nothing. */
export interface SignBatchResult { card: string; ok: boolean; error?: string; signature?: Signature }

/** GxP mode state (spine/auth/gxp.py's state(), card 6). `active: false` is
 *  the whole shape when the mode is off - never leaks the lock file's other
 *  fields (see gxp.py's own docstring on `state()`). */
export interface GxpState {
  active: boolean;
  activated_at?: string; activated_by?: string;
  four_eyes?: boolean;
  scope?: "workspace" | "repos";
  repos?: string[];
  disabled?: string[];
  /** GET-only: repos the server already knows about (settings.pm.repos +
   *  repo_hooks keys + default_repo) and aren't in scope yet - the picker's
   *  "known repos" checkbox list. Absent from the POST /gxp/activate reply. */
  known_repos?: string[];
  /** POST-only: which of the activated repos were freshly `git init`'d by
   *  this same call (the picker's "create new" option). */
  created_repos?: string[];
}

export interface Track {
  id: string; repo: string; branch: string; worktree: string; task: string;
  description?: string; attachments?: string[];
  billing?: "fixed" | "tm" | "none"; rate?: number | null; project_id?: string | null;
  client: string; session_id: string | null; perm: string; lane: string;
  status: string; turns: number; last_reply: string;
  value: number; driver: string; priority?: string; due?: string; rank?: number | null;
  ai_cost: number; tokens_in: number; tokens_out: number; models: string[];
  ctx_tokens?: number;   // current context-window size (last turn's input side) - for the meter
  /** the model's context WINDOW, derived daemon-side from the model id ([1m] =
   *  1M) and from evidence (a successful call proves a lower bound). The meter
   *  divides by this - hardcoded 200k showed 97% on a 1M card really at 23%. */
  ctx_window?: number;
  created: string; updated: string;
  mode?: string; process?: string; process_title?: string;
  /** 1-based step index within `process`, set at card creation. Read this, do
   *  NOT parse the branch name - branches carry a card-id tail now. */
  process_step?: number;
  up_next?: boolean; gate_report?: string[]; gate_failed?: boolean;
  merge_failed?: boolean; merge_kind?: string; merge_report?: string;
  review_preview?: boolean; review_report?: string;
  archived?: boolean; autopilot?: boolean; fast_track?: boolean;
  /** The one guided onboarding card owner first-run seeds (accounts-boards-prd
   *  phase 3): never dispatches (lanemachine._move_lane refuses every move off
   *  Backlog), excluded from PM/economics/Henry. Deletable like any card. */
  example?: boolean;
  // GxP, DERIVED server-side per read (lifecycle._present_gxp), never stored.
  // Absent entirely for a card outside the regulated scope, so `gxp_scope` is
  // the one flag the board branches on. `gxp_signed` is the cheap question
  // ("an unconsumed approved signature exists") - whether it still matches git
  // is checked when the dialog opens and again before the merge, because that
  // costs git calls the board's polling must not pay.
  gxp?: boolean; gxp_scope?: boolean; gxp_signed?: boolean; dispatched_by?: string;
  /** remote device execution (ops/docs/backlog/remote-device-execution): a card
   *  a team member's own PC runs. "local:<device-id>" when set; absent for a
   *  daemon-executed card. `device_stale` is DERIVED server-side per read
   *  (lifecycle._present_device) - true when a working device card has been
   *  claimed longer than the sweep's TTL, i.e. its device may be offline. Just
   *  a badge hint; dispatch.sweep_stale_device_claims is the authority. */
  exec_site?: string; device_stale?: boolean;
  forked_from?: string; forked_ref?: string; adopted?: boolean;
  question?: PendingQuestion;
  waiting_on?: "you" | "background";
  background?: BackgroundWait;
  /** Paseo ProviderSubagentStore: one descriptor per background task the worker
   *  launched, with an explicit lifecycle status - so the card can show what the
   *  worker is doing and how each task ended (clickable), not just a count. Keyed
   *  by the launching tool_use id. */
  bg_tasks?: Record<string, BgTask>;
}
export interface BgTask {
  title: string;
  status: "running" | "completed" | "failed" | "canceled";
  since?: number;      // epoch seconds it was launched
  updated?: number;    // epoch seconds of the last state change
  detail?: string;     // the command / prompt that launched it
  result?: string;     // the task-notification output, or why it was canceled
}
/** A worker's typed multiple-choice question (daemon/ask.py). Present only
 *  while the card is actually waiting on the owner's decision; answering it
 *  (POST /tracks/<id>/answer) continues the SAME session, so the worker picks
 *  up where it stopped instead of the card parking on unanswerable prose. */
export interface PendingQuestion {
  /** echoed back when answering, so a stale panel can't answer a question the
   *  worker has already moved past */
  id: string;
  kind: "tool" | "plan" | "question" | "mode";
  asked: string;
  ta?: number;
  questions: AskQuestion[];
}
export interface AskQuestion {
  question: string;
  /** short chip label, also the answer key */
  header: string;
  options: AskOption[];
  multiSelect: boolean;
  idx?: number;
}
export interface AskOption { label: string; description?: string }
/** What a parked card is waiting on, when it is NOT the owner: a background
 *  task the worker launched and is still running (Phase 2.5). */
export interface BackgroundWait { n: number; names?: string[]; since?: number }
/** POST /tracks/<id>/lane. ->backlog still returns the finished Track;
 *  ->working/review/done are backgrounded by the daemon (gate subprocess +
 *  merge + deploy hook) and answer {started, gating} right away. The card then
 *  carries status "gating" until the real verdict lands on it. */
// gxp_refused: the daemon declined the landing (no signature, drifted, or
// the actor is not a real account). Carries the reason, ready to show.
// example_refused: the card is the onboarding guide (Track.example) - it
// never dispatches, whatever lane the move targeted.
export type LaneMove = Partial<Track> & {
  started?: string; gating?: boolean; gxp_refused?: string; example_refused?: string;
};
export interface EconCard {
  id: string; task: string; branch: string; lane: string; ai_cost: number;
  touches: number; value: number; mode: string | null; models: string[];
  tokens_in: number; tokens_out: number;
  billing?: "fixed" | "tm" | "none"; rate?: number | null;
  billed?: number; margin?: number; time_seconds?: number;
  /** flat plan only: this card's share of the subscription, in percent of a
   *  weekly quota. null when the daemon can't calibrate → fall back to tokens. */
  plan_pct?: number | null;
}
export interface Sow {
  id: string; name: string; client: string; status?: string; due?: string;
  cards: number; done: number; hours: number; billed: number;
  ai_cost: number; margin: number; all_done: boolean; plan_pct?: number | null;
}
/** How the daemon converted tokens into "% of the plan". source "measured" =
 *  calibrated against the live weekly quota window (an estimate — it divides
 *  OUR tokens by the ACCOUNT's utilization); "configured" = owner-set
 *  settings.pm.plan_tokens_week. Absent/null = not calibratable right now. */
export interface PlanCalibration {
  tokens_per_pct: number; source: "measured" | "configured"; window: string;
  used_pct?: number | null; observed_tokens?: number | null; resets_at?: string;
}
/** One row of GET /engines (spine/agent/engines.py): a driver a card may
 *  carry, with its CLI probed live. `status` is derived at probe time,
 *  `verified` says whether HelmDeck's driver for it has ever run a real turn. */
export interface EngineEntry {
  id: string; label: string; type: string;
  status: "ready" | "unavailable"; version: string; error: string;
  verified: boolean; configured: boolean; exe?: string;
  /** settings toggle (Paseo's provider switch): off = hidden from the picker, refused at filing */
  enabled: boolean;
  /** the editable settings row - send it back WHOLE on save (one-level merge) */
  config: { exe?: string; env?: Record<string, string>; enabled?: boolean };
}
export interface Metrics {
  settings?: {
    currency: string; value_per_card: number; default_repo: string;
    capacity: { wip_limit: number; touch_budget_day: number;
      tariff: { steer: number; review: number; bounce: number } };
    drivers?: Record<string, { type: string; record?: boolean }>;
    // Only `open` is live (anyone may sign up, always as a client). The other
    // two are retired keys the daemon keeps declared purely so
    // invites.migrate_legacy() can blank them once - see spine/storage/
    // events.py. Optional here so nothing in the app reads them by accident.
    registration?: { open: boolean; invite_code?: string; default_role?: string };
    policy?: { lane_labels?: Record<string, string>; auto_dispatch_modes?: string[];
      auto_accept_green?: boolean; auto_dispatch_priority?: string; chat_configure_roles?: string[] };
    jira?: { base: string; email: string; api_token: string; default_jql: string };
    relay?: { url?: string; room?: string; phone_pub?: string };
    dashboard?: { tiles?: string[]; panels?: string[] };
    appearance?: { backdrop?: string };
  };
  /** flat = Max subscription: ai_cost/ai_spend are API-equivalent references,
   *  not spend, and margins already exclude them daemon-side. */
  ai_billing?: "flat" | "metered";
  plan_calibration?: PlanCalibration | null;
  cards: EconCard[];
  sows: Sow[];
  capacity: { wip: number; wip_limit: number; touches_today: number;
    touch_budget_day: number; headroom: number; actors?: Record<string, number> };
  yield_first_pass: [number, number];
  automation: [number, number];
  gate_failures: [string, number][];
  ai_by_model?: Record<string, { turns: number; cost: number; tok_in: number; tok_out: number;
    avg_cost_per_turn: number; plan_pct_per_turn?: number | null }>;
  totals: { value_delivered: number; ai_spend: number; margin: number; leverage_per_touch: number;
    ai_tokens?: number; plan_pct?: number | null };
}
export interface Step {
  title: string; desc: string; mode: string; days: number; status: string;
  track: string | null; due: string; state?: string; lane?: string | null;
  ready?: boolean; done?: boolean;
}
export interface Process {
  id: string; request: string; client: string; due: string; status: string;
  steps: Step[]; cost: number; created: string; error?: string;
}
/** MY ACCOUNT's view preferences (accounts-boards-prd phase 1). Resolved
 *  server-side: the account's own rows overlaid on the workspace defaults, so
 *  every field is always present and always renderable. Written back with
 *  `PUT /me/config`, which accepts exactly these keys and nothing else - the
 *  whitelist lives in spine/storage/userconfig.py and adding a key here
 *  without adding it there (or the reverse) fails the ts-contract test in
 *  ops/tests/test_harness_layer.py. */
export interface Profile {
  lang?: string;
  appearance?: { backdrop?: string };
}
/** One column of a board (accounts-boards-prd phase 2). `station` is a real
 *  lane, so the drag handler can translate a drop straight into
 *  `move_lane(station)` - a column can never name something the lane machine
 *  would refuse a card into.
 *
 *  `label` MAY BE EMPTY, and empty is not "missing": it means "render this
 *  station's own name", which is what keeps a board translatable instead of
 *  freezing whatever language it was created in. Never render `label` raw -
 *  go through `columnLabel()` in data/boards.ts. */
export interface BoardColumn {
  id: string;
  label: string;
  station: string;
}
/** A saved VIEW over the one card pool. Cards exist once; a board only says
 *  which columns to draw over them. `owner: ""` is the shared default board
 *  (owner-role edits it, nobody deletes it); anything else is that account's
 *  private board. Shape held against spine/storage/boards.py by the
 *  ts-contract test in ops/tests/test_harness_layer.py. */
export interface Board {
  id: string;
  name: string;
  owner: string;
  columns: BoardColumn[];
  created?: string;
}
/** `ui` is the PUBLIC slice of policy every role may see (language + lane
 *  labels). The full settings blob stays owner-only on /settings. */
export interface Me {
  name: string; role: string;
  /** Effective capabilities for this role (spine/auth/permissions.py CAPS),
   *  derived live server-side - never recompute this client-side from
   *  `role`, that's exactly the drift rbac-gxp card 4 closes. See
   *  src/kernel/caps.ts's `can()`. */
  caps?: string[];
  /** The account's resolved view - the same on every device it signs in on. */
  profile?: Profile;
  /** Which profile keys this account actually CHOSE, as opposed to inherited
   *  from the workspace. NOT derivable from `profile` (a resolved value looks
   *  identical either way), and two flows turn on it: the first-login language
   *  step only appears while "lang" is absent from it, and the device->account
   *  migration only offers when it is empty. */
  profile_keys?: string[];
  /** The SCHEMA for the account's own knobs (accounts-boards-prd phase 4,
   *  spine/http/apimeta.py `_profile_schema`). Same entry shape as
   *  /automation's `config_schema`, and the settings hub concatenates the two
   *  - these rows ride here rather than there because /automation is
   *  settings.read (owner-only) and door 1 "Mein Profil" exists precisely for
   *  the roles that are not the owner. Typed loosely as ConfigItem[] via the
   *  hub's own import; OPTIONAL, because a daemon older than this bundle
   *  omits it and door 1 must then simply render its device rows. */
  config_schema?: unknown[];
  /** The boards this account may render: the shared default first, then its
   *  own. OPTIONAL, and the app must survive its absence - a daemon older than
   *  this bundle omits it, and the demo fixture has none. data/boards.ts falls
   *  back to the four stations, which is exactly the board the app drew before
   *  boards existed. */
  boards?: Board[];
  ui?: { lang?: string; lane_labels?: Record<string, string>;
    /** flat = Max subscription (quota, not cash) → cost surfaces show tokens;
     *  metered = API pay-per-token → $ amounts are real spend. */
    ai_billing?: "flat" | "metered" };
}
export interface HistoryRow { kind: string; detail: string; ts?: string; t?: number }
export interface Run { id: string; title: string; kind: string; status: string; steps?: number }
// One token = one DEVICE in the Team panel. `device` is the installation id
// the client sent at sign-in (routes_auth.py's _device_id) - present only for
// tokens minted since that existed, absent for a script/curl token, which is
// then simply its own row.
export interface TokenRow {
  label: string; id: string; tail: string; created?: string; device?: string | null;
  last_used?: string | null; expires?: string | null; stale?: boolean;
}
export interface UserRow {
  name: string; role: string; created?: string;
  // Newest device activity on this account, computed server-side from the
  // tokens' own last_used stamps (auth.last_active) - never re-derived here.
  last_active?: string | null;
  // No `token`: the daemon hashes device tokens at rest and never hands the
  // plaintext back. `id` is the revoke handle, `tail` the last six characters
  // so a human can tell two devices apart. The full value exists exactly once,
  // in the response to issueToken.
  // last_used/expires/stale: card 5 debt (rbac-audit-hardening-partial) -
  // access-review signal. `stale` is computed server-side (auth._token_stale,
  // >90d unused), never recomputed client-side from a cached timestamp.
  tokens: TokenRow[];
}

// An invitation (spine/auth/invites.py). The CODE is present because it is
// only useful until someone signs up with it - unlike a device token there is
// nothing to hide, and the owner has to be able to re-copy a link he sent.
// `state` is derived server-side on every read, never a stored flag.
export interface InviteRow {
  code: string; role: "client" | "operator";
  state: "open" | "used" | "revoked" | "expired";
  created?: string; created_by?: string; expires?: string;
  used_by?: string | null; used_at?: string | null; note?: string;
}

// A registered remote-execution device (ops/docs/backlog/remote-device-
// execution). Same "no token" rule as UserRow: the plaintext exists once, in
// the register response. `billing_scope` = whose Claude account pays
// ("external" = the device's own; "shared" = the daemon's).
export interface DeviceRow {
  id: string; owner: string; label: string;
  billing_scope?: "external" | "shared";
  created?: string; last_seen?: string | null;
}

// Claude subscription usage (from /usage) - the 5h + weekly rate-limit windows.
export type UsageTone = "ok" | "warning" | "danger" | "default";
export interface UsagePacing {
  elapsed_pct: number; ahead_pct: number; projected_pct: number | null;
  exhaust_at: string | null; reset_hours_left: number;
  exhaust_before_reset: boolean; flag: boolean;
}
export interface UsageWindow {
  id: string; label: string; usedPct: number | null; remainingPct: number | null;
  resetsAt: string | null; tone: UsageTone; pacing?: UsagePacing;
}
export interface Usage {
  status: "ok" | "unavailable" | "error"; plan: string | null;
  windows: UsageWindow[]; fetchedAt?: string; error?: string;
}
