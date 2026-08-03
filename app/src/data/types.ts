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
  created: string; updated: string;
  mode?: string; process?: string; process_title?: string;
  up_next?: boolean; gate_report?: string[]; gate_failed?: boolean;
  merge_failed?: boolean; merge_kind?: string; merge_report?: string;
  review_preview?: boolean; review_report?: string;
  archived?: boolean;
  forked_from?: string; forked_ref?: string; adopted?: boolean;
}
export interface EconCard {
  id: string; task: string; branch: string; lane: string; ai_cost: number;
  touches: number; value: number; mode: string | null; models: string[];
  tokens_in: number; tokens_out: number;
  billing?: "fixed" | "tm" | "none"; rate?: number | null;
  billed?: number; margin?: number; time_seconds?: number;
}
export interface Sow {
  id: string; name: string; client: string; status?: string; due?: string;
  cards: number; done: number; hours: number; billed: number;
  ai_cost: number; margin: number; all_done: boolean;
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
  cards: EconCard[];
  sows: Sow[];
  capacity: { wip: number; wip_limit: number; touches_today: number;
    touch_budget_day: number; headroom: number; actors?: Record<string, number> };
  yield_first_pass: [number, number];
  automation: [number, number];
  gate_failures: [string, number][];
  ai_by_model?: Record<string, { turns: number; cost: number; tok_in: number; tok_out: number; avg_cost_per_turn: number }>;
  totals: { value_delivered: number; ai_spend: number; margin: number; leverage_per_touch: number };
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
export interface Me { name: string; role: string }
export interface HistoryRow { kind: string; detail: string; ts?: string; t?: number }
export interface Run { id: string; title: string; kind: string; status: string; steps?: number }
export interface UserRow {
  name: string; role: string; created?: string;
  tokens: { label: string; token: string; created?: string }[];
}
