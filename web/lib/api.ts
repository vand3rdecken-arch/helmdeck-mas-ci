// All data comes from the Python daemon, proxied same-origin at /backend/*
// (next.config.ts rewrite) so the session cookie just works.
export const API = "/backend";

export class AuthRequired extends Error {}

export async function get<T = unknown>(path: string): Promise<T> {
  const r = await fetch(API + path);
  if (r.status === 401) throw new AuthRequired();
  return r.json();
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (r.status === 401) throw new AuthRequired();
  return r.json();
}

/* ---- daemon types (the shapes tracks.json / events.py serve) ---- */
export interface Track {
  id: string; repo: string; branch: string; worktree: string; task: string;
  client: string; session_id: string | null; perm: string; lane: string;
  status: string; turns: number; last_reply: string;
  value: number; driver: string; priority?: string; due?: string;
  ai_cost: number; tokens_in: number; tokens_out: number; models: string[];
  created: string; updated: string;
  mode?: string; process?: string; process_title?: string;
  up_next?: boolean; gate_report?: string[]; gate_failed?: boolean;
}
export interface EconCard {
  id: string; task: string; branch: string; lane: string; ai_cost: number;
  touches: number; value: number; mode: string | null; models: string[];
  tokens_in: number; tokens_out: number;
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
    dashboard?: { tiles?: string[]; panels?: string[] };
    appearance?: { backdrop?: string };
  };
  cards: EconCard[];
  capacity: { wip: number; wip_limit: number; touches_today: number;
    touch_budget_day: number; headroom: number; actors?: Record<string, number> };
  yield_first_pass: [number, number];
  automation: [number, number];
  gate_failures: [string, number][];
  totals: { value_delivered: number; ai_spend: number; margin: number;
    leverage_per_touch: number };
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
export interface HistoryRow { kind: string; detail: string; t?: number }
export interface Run { id: string; title: string; kind: string; status: string; steps?: number }
export interface UserRow {
  name: string; role: string; created?: string;
  tokens: { label: string; token: string; created?: string }[];
}
