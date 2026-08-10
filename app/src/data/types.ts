// Daemon data shapes — ported verbatim from web/lib/api.ts (the Python daemon
// serves the same JSON to every client). Keep in sync with daemon/events.py.

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
  up_next?: boolean; gate_report?: string[]; gate_failed?: boolean;
  merge_failed?: boolean; merge_kind?: string; merge_report?: string;
  review_preview?: boolean; review_report?: string;
  archived?: boolean; autopilot?: boolean; fast_track?: boolean;
  forked_from?: string; forked_ref?: string; adopted?: boolean;
  question?: PendingQuestion;
  waiting_on?: "you" | "background";
  background?: BackgroundWait;
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
export type LaneMove = Partial<Track> & { started?: string; gating?: boolean };
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
export interface Metrics {
  settings?: {
    currency: string; value_per_card: number; default_repo: string;
    capacity: { wip_limit: number; touch_budget_day: number;
      tariff: { steer: number; review: number; bounce: number } };
    drivers?: Record<string, { type: string; record?: boolean }>;
    registration?: { open: boolean; invite_code: string; default_role: string };
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
/** `ui` is the PUBLIC slice of policy every role may see (language + lane
 *  labels). The full settings blob stays owner-only on /settings. */
export interface Me {
  name: string; role: string;
  ui?: { lang?: string; lane_labels?: Record<string, string>;
    /** flat = Max subscription (quota, not cash) → cost surfaces show tokens;
     *  metered = API pay-per-token → $ amounts are real spend. */
    ai_billing?: "flat" | "metered" };
}
export interface HistoryRow { kind: string; detail: string; ts?: string; t?: number }
export interface Run { id: string; title: string; kind: string; status: string; steps?: number }
export interface UserRow {
  name: string; role: string; created?: string;
  tokens: { label: string; token: string; created?: string }[];
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
