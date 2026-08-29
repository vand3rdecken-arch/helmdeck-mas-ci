import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { create } from "zustand";

import { t } from "@/i18n/core";

import type { Step } from "./client";
import type { Metrics, Me, Track } from "./types";

// DEMO MODE — the app without a daemon.
//
// HelmDeck is a companion app: without a paired daemon every screen is an empty
// board behind a pairing wall. That is fine for owners (they run the daemon) but
// it makes the app unevaluable for anyone else — a store visitor, and every Play
// closed-testing tester, who cannot judge the product they are asked to test.
// Demo mode answers the daemon's HTTP surface from this fixture instead, at ONE
// seam (data/client.ts `req`), so no screen needs to know about it.
//
// The board is MUTABLE in memory: moving a lane, steering a card or filing a new
// request all stick for the session. A read-only mock feels dead, and "did the
// testers use all features?" is exactly what Play asks on the production-access
// questionnaire. Nothing is persisted and nothing leaves the device.
//
// Every user-visible string comes from i18n/dict/demo.ts and is resolved at
// RESPONSE time, not at module load — the sample board follows the language
// switch like the rest of the app.

const KEY = "helmdeck.demo";
const isWeb = Platform.OS === "web";

interface DemoState {
  active: boolean;
  hydrated: boolean;
  enable: () => void;
  disable: () => void;
  hydrate: () => Promise<void>;
}

async function persist(active: boolean) {
  try {
    if (isWeb) globalThis.localStorage?.setItem(KEY, active ? "1" : "");
    else if (active) await SecureStore.setItemAsync(KEY, "1");
    else await SecureStore.deleteItemAsync(KEY);
  } catch { /* unavailable */ }
}

export const useDemo = create<DemoState>((set) => ({
  active: false,
  hydrated: false,
  enable: () => { reset(); set({ active: true }); persist(true); },
  disable: () => { set({ active: false }); persist(false); },
  hydrate: async () => {
    try {
      const raw = isWeb ? globalThis.localStorage?.getItem(KEY) : await SecureStore.getItemAsync(KEY);
      if (raw) set({ active: true });
    } catch { /* ignore */ }
    set({ hydrated: true });
  },
}));

// ---------------------------------------------------------------- fixture ---
// Rows carry i18n KEYS; `materialize` turns them into display text per request.

const iso = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
const epoch = (minutesAgo: number) => Math.round(Date.now() / 1000 - minutesAgo * 60);

type Row = Omit<Track, "task" | "client" | "last_reply"> & {
  taskKey?: string; task?: string;
  replyKey?: string; last_reply?: string;
  gateKeys?: string[];
};

function row(p: Partial<Row> & { id: string; lane: string }): Row {
  return {
    repo: "helmdeck", branch: `req-${p.id}`, worktree: `/worktrees/${p.id}`,
    description: "", session_id: null, perm: "write",
    status: "idle", turns: 0, value: 0, driver: "claude",
    ai_cost: 0, tokens_in: 0, tokens_out: 0, models: ["claude-opus-4-8"],
    created: iso(600), updated: iso(30), billing: "fixed", rate: null,
    ...p,
  } as Row;
}

const SEED: Row[] = [
  row({
    id: "d1", taskKey: "demo.c1.task", replyKey: "demo.c1.reply",
    lane: "done", status: "done", turns: 14, value: 1200, ai_cost: 3.42,
    tokens_in: 184_000, tokens_out: 22_400, priority: "normal",
    gateKeys: ["tests42", "lint", "types"],
    merge_kind: "merge", created: iso(2600), updated: iso(220),
  }),
  row({
    id: "d2", taskKey: "demo.c2.task", replyKey: "demo.c2.reply",
    lane: "review", status: "review", turns: 9, value: 800, ai_cost: 2.05,
    tokens_in: 121_000, tokens_out: 15_800, priority: "hoch",
    gateKeys: ["tests18", "lint", "types"], review_preview: true,
    created: iso(1400), updated: iso(24),
  }),
  row({
    id: "d3", taskKey: "demo.c3.task", replyKey: "demo.c3.reply",
    lane: "working", status: "running", turns: 5, value: 600, ai_cost: 1.18,
    tokens_in: 64_000, tokens_out: 9_100, priority: "normal",
    created: iso(300), updated: iso(2),
  }),
  row({
    id: "d4", taskKey: "demo.c4.task", replyKey: "demo.c4.reply",
    lane: "working", status: "needs_you", turns: 3, value: 400, ai_cost: 0.62,
    tokens_in: 31_000, tokens_out: 4_200, priority: "hoch",
    created: iso(180), updated: iso(6),
    // parked ON a background task (Phase 2.5): shows the compact one-line
    // task track (expandable) instead of the "waiting for you" pill.
    // Commands/tool output stay untranslated, like every branch name here.
    waiting_on: "background",
    bg_tasks: {
      tu1: { title: "npx expo export --platform web", status: "running",
             since: epoch(8), detail: "npx expo export --platform web" },
      tu2: { title: "py -3.12 -m pytest ops/tests/", status: "completed",
             since: epoch(40), updated: epoch(12),
             detail: "py -3.12 -m pytest ops/tests/", result: "142 passed, 0 failed" },
      tu3: { title: "eas build --platform android", status: "canceled",
             since: epoch(90), updated: epoch(60),
             detail: "eas build --platform android --profile preview" },
    },
  }),
  row({
    id: "d5", taskKey: "demo.c5.task", lane: "backlog",
    value: 300, priority: "niedrig", up_next: true, created: iso(90), updated: iso(90),
  }),
  row({
    id: "d6", taskKey: "demo.c6.task", lane: "backlog",
    value: 250, priority: "hoch", created: iso(60), updated: iso(60),
  }),
  // a remote-device card whose worker went offline (Phase G): shows the
  // "device offline?" board chip and the settings stuck-card rescue row.
  row({
    id: "d7", taskKey: "demo.c7.task", lane: "working", status: "running",
    turns: 2, value: 500, priority: "normal", created: iso(200), updated: iso(40),
    exec_site: "local:demo-laptop", device_stale: true,
  }),
];

let rows: Row[] = SEED.map((r) => ({ ...r }));
let version = 1;

// `mirror` marks the EVENT-MIRROR row (cells/copilot/card_mirror.py): a working
// card's question folded into the Henry chat, the one-inbox decree. Kept as a
// flag + keys here and EXPANDED at response time in /chat/history below - the
// question block is full of user-visible strings, and this module's rule is
// that those resolve when answered, never at module load.
type ChatRow = { cls: string; textKey?: string; text?: string; ts?: string;
  mirror?: boolean };
const CHAT_SEED: ChatRow[] = [
  { cls: "user", textKey: "demo.chat.q", ts: iso(120) },
  { cls: "assistant", textKey: "demo.chat.a", ts: iso(119) },
  // a mirrored card QUESTION: exercises the label header in the transcript, the
  // QuestionPanel above the composer, and the composer's routing chip. Bound to
  // d2 - the demo's running card - so answering routes somewhere real.
  { cls: "card", textKey: "demo.chat.mirrorQ", ts: iso(8), mirror: true },
];
let chatLog: ChatRow[] = CHAT_SEED.map((c) => ({ ...c }));

// Extra transcript turns produced by steering, per card id.
let extraSteps: Record<string, { cls: string; role?: string; textKey?: string; text?: string; ts: string }[]> = {};

function reset() {
  rows = SEED.map((r) => ({ ...r }));
  chatLog = CHAT_SEED.map((c) => ({ ...c }));
  extraSteps = {};
  version = 1;
}

const gateText = (k: string) =>
  k === "tests42" ? t("demo.gate.tests", { n: 42 })
  : k === "tests18" ? t("demo.gate.tests", { n: 18 })
  : k === "lint" ? t("demo.gate.lint")
  : t("demo.gate.types");

/** Row -> the Track shape the screens consume, with copy resolved now. */
function materialize(r: Row): Track {
  const { taskKey, replyKey, gateKeys, ...rest } = r;
  return {
    ...(rest as unknown as Track),
    task: taskKey ? t(taskKey) : (r.task ?? ""),
    client: t("demo.client"),
    last_reply: replyKey ? t(replyKey) : (r.last_reply ?? ""),
    gate_report: gateKeys?.map(gateText),
    merge_report: r.merge_kind ? t("demo.merge.report") : undefined,
  };
}

function transcript(id: string): Step[] {
  const base: Record<string, Step[]> = {
    d3: [
      { cls: "note", kind: "lifecycle", text: t("demo.step.started"), ts: iso(300) },
      { cls: "assistant", role: "assistant", text: t("demo.c3.s1"), ts: iso(298) },
      { cls: "tool", tool: "Read", input: "daemon/metrics.py", result: t("demo.readResult", { n: 312 }), ts: iso(296) },
      { cls: "tool", tool: "Grep", input: "revenue|umsatz", result: t("demo.hitsResult", { n: 7, f: 3 }), ts: iso(295) },
      { cls: "assistant", role: "assistant", text: t("demo.c3.s2"), ts: iso(240) },
      { cls: "tool", tool: "Edit", input: "web/ui/charts.tsx", result: "+64 −8", ts: iso(120) },
      { cls: "assistant", role: "assistant", text: t("demo.c3.s3"), ts: iso(2) },
    ],
    d4: [
      { cls: "note", kind: "lifecycle", text: t("demo.step.startedShort"), ts: iso(180) },
      { cls: "tool", tool: "Glob", input: "exports/**", result: t("demo.filesResult", { n: 48 }), ts: iso(178) },
      { cls: "assistant", role: "assistant", text: t("demo.c4.reply"), ts: iso(6) },
    ],
    d2: [
      { cls: "note", kind: "lifecycle", text: t("demo.step.startedShort"), ts: iso(1400) },
      { cls: "assistant", role: "assistant", text: t("demo.c2.s1"), ts: iso(1380) },
      { cls: "tool", tool: "Edit", input: "daemon/auth.py", result: "+91 −4", ts: iso(900) },
      { cls: "tool", tool: "Bash", input: "pytest ops/tests/test_auth.py", result: t("demo.testsResult"), ts: iso(120) },
      { cls: "note", kind: "gate", text: t("demo.c2.gate"), ts: iso(30) },
      { cls: "assistant", role: "assistant", text: t("demo.c2.s2"), ts: iso(24) },
    ],
  };
  const extra = (extraSteps[id] ?? []).map((s) => ({
    cls: s.cls, role: s.role, ts: s.ts, text: s.textKey ? t(s.textKey) : (s.text ?? ""),
  }));
  return [...(base[id] ?? []), ...extra];
}

const ME: Me = { name: "Demo", role: "owner" };

function metrics(): Metrics {
  const done = rows.filter((r) => r.lane === "done");
  const value = rows.reduce((s, r) => s + (r.lane === "done" ? r.value : 0), 0);
  const spend = rows.reduce((s, r) => s + r.ai_cost, 0);
  return {
    settings: {
      currency: "EUR", value_per_card: 500, default_repo: "helmdeck",
      capacity: { wip_limit: 3, touch_budget_day: 20, tariff: { steer: 1, review: 1, bounce: 2 } },
    },
    cards: rows.map((r) => {
      const k = materialize(r);
      return {
        id: k.id, task: k.task, branch: k.branch, lane: k.lane, ai_cost: k.ai_cost,
        touches: k.turns, value: k.value, mode: k.mode ?? null, models: k.models,
        tokens_in: k.tokens_in, tokens_out: k.tokens_out, billing: k.billing,
        rate: k.rate ?? null, billed: k.value, margin: k.value - k.ai_cost,
      };
    }),
    sows: [{
      id: "s1", name: t("demo.project"), client: t("demo.client"), due: "",
      cards: rows.length, done: done.length, hours: 0, billed: value,
      ai_cost: spend, margin: value - spend, all_done: false,
    }],
    capacity: {
      wip: rows.filter((r) => r.lane === "working").length, wip_limit: 3,
      touches_today: 7, touch_budget_day: 20, headroom: 13,
    },
    yield_first_pass: [2, 2],
    automation: [4, 6],
    gate_failures: [],
    ai_by_model: {
      "claude-opus-4-8": {
        turns: rows.reduce((s, r) => s + r.turns, 0), cost: Number(spend.toFixed(2)),
        tok_in: rows.reduce((s, r) => s + r.tokens_in, 0),
        tok_out: rows.reduce((s, r) => s + r.tokens_out, 0),
        avg_cost_per_turn: 0.24,
      },
    },
    totals: {
      value_delivered: value, ai_spend: Number(spend.toFixed(2)),
      margin: Number((value - spend).toFixed(2)), leverage_per_touch: 38,
    },
  };
}

/** The sample PM plan behind the triage-first dashboard: goal, the three
 *  corners green, milestones and next actions wired to the sample cards, so
 *  the triangle + follow-up panels have something honest to show. */
function pmPlan() {
  const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);
  return {
    goal: t("demo.pm.goal"),
    economics: {},
    plan: {
      goal: t("demo.pm.goal"),
      done_pct: 40,
      plan_status: "ready",
      triage: { budget: "ok", timeline: "ok", scope: "ok" },
      feasibility: { earliest_done: inDays(12), note: t("demo.pm.feasNote") },
      budget: { plan: "max", fixed_monthly_eur: 90, spent_to_date_eur: 34.5,
        est_turns_to_goal: 120, velocity_turns_per_day: 18, eta_days: 7 },
      milestones: [
        { name: t("demo.pm.m1"), target_date: inDays(2), card: "d2" },
        { name: t("demo.pm.m2"), target_date: inDays(7), card: "d3" },
        { name: t("demo.pm.m3"), target_date: inDays(12) },
      ],
      next: [
        { title: t("demo.pm.n1"), card: "d2" },
        { title: t("demo.pm.n2"), card: "d4" },
        { title: t("demo.pm.n3") },
      ],
    },
    config: { loop_enabled: true, autonomy: "act" },
  };
}

// ------------------------------------------------------------- responder ---

const find = (id: string) => rows.find((r) => r.id === id);
const bump = () => { version += 1; };
const now = () => new Date().toISOString();

/** Answer a daemon call from the fixture. `undefined` = endpoint not modelled;
 *  the caller then falls back to an empty value rather than a fake success. */
export function demoRespond(method: string, rawPath: string, body?: unknown): unknown | undefined {
  const path = rawPath.split("?")[0];
  const q = rawPath.includes("?") ? rawPath.slice(rawPath.indexOf("?") + 1) : "";
  const b = (body ?? {}) as Record<string, any>;

  if (path === "/stream/wait") {
    // Long-poll: hand back the CURRENT version. client.ts paces this so the
    // board refreshes on demo mutations without spinning the loop hot.
    const seen = Number(new URLSearchParams(q).get("v") ?? 0);
    return { v: version > seen ? version : seen };
  }
  if (path === "/tracks" && method === "GET") return rows.map(materialize);
  if (path === "/me") return ME;
  if (path === "/dashboard/data") return metrics();
  if (path === "/models") return [{ id: "claude-opus-4-8", label: "Opus 4.8" }];
  if (path === "/escalations") return [
    { id: "aborted-by-restart-1", ts: "2026-08-21T04:19:07", kind: "aborted-by-restart",
      card: "20260816-193639-proc-20260816-s3", detail: "apk build (npm ci + gradle)",
      attempts: 1, closed: true, action: "rerun_deploy", why: t("esc.demoWhy") },
    { id: "conflict-unresolved-2", ts: "2026-08-21T04:05:05", kind: "conflict-unresolved",
      card: "20260816-193639-proc-20260816-s3", detail: "ops/tests/test_driver_session.py",
      attempts: 1, closed: false },
  ];
  if (path === "/chat/history") {
    return { messages: chatLog.map((c) => {
      // the daemon stamps "%H:%M" (copilot._append_log); the fixture keeps full
      // ISO for ordering, so serve the same HH:MM shape here - the transcript
      // renders ts verbatim, and a raw ISO string under every bubble is what
      // the first screenshot judge actually caught
      const hm = (c.ts ?? "").length > 5 ? (c.ts ?? "").slice(11, 16) : (c.ts ?? "");
      const base = { cls: c.cls, ts: hm, text: c.textKey ? t(c.textKey) : (c.text ?? "") };
      if (!c.mirror) return base;
      // the mirrored card question, expanded at response time (strings follow
      // the language switch) - same shape card_mirror.say_card persists
      return { ...base, card: "d2", cardName: t("demo.chat.mirrorName"), kind: "question",
        question: { id: "demo-q-1", kind: "question", asked: c.ts ?? "",
          questions: [{ question: t("demo.chat.mirrorQ"), header: t("demo.chat.mirrorHeader"),
            options: [
              { label: t("demo.chat.mirrorOptA"), description: t("demo.chat.mirrorOptADesc") },
              { label: t("demo.chat.mirrorOptB"), description: t("demo.chat.mirrorOptBDesc") },
            ] }] } };
    }),
             session_id: "demo",
             // card-parity PM-session stats so the demo shows the meter + usage line
             stats: { turns: 4, cost: 0.31, tokens_in: 58200, tokens_out: 4400,
                      ctx_tokens: 62000, ctx_window: 200000, plan_pct: 0.35 } };
  }

  if (path === "/chat" && method === "POST") {
    chatLog = [...chatLog, { cls: "user", text: String(b.text ?? ""), ts: now() },
               { cls: "assistant", textKey: "demo.chat.reply", ts: now() }];
    return { reply: t("demo.chat.reply"), cost: 0 };
  }
  if (path === "/chat/cancel") return {};

  const m = /^\/tracks\/([^/]+)(\/.*)?$/.exec(path);
  if (m) {
    const [, id, sub] = m;
    const k = find(id);
    if (sub === "/transcript") return transcript(id);
    if (sub === "/transcript/live") return { v: String(version), steps: transcript(id) };
    if (sub === "/history" || sub === "/attachments" || sub === "/turns") return [];
    if (!k) return undefined;
    if (sub === "/lane" && method === "POST") {
      k.lane = String(b.lane ?? k.lane);
      k.status = k.lane === "done" ? "done" : k.lane === "review" ? "review" : "running";
      k.updated = now(); bump();
      return materialize(k);
    }
    if (sub === "/update" && method === "POST") {
      Object.assign(k, b); k.updated = now(); bump(); return materialize(k);
    }
    if (sub === "/steer" && method === "POST") {
      k.turns += 1; k.status = "running"; k.updated = now();
      k.replyKey = "demo.steer.reply";
      (extraSteps[id] ||= []).push(
        { cls: "user", role: "user", text: String(b.text ?? ""), ts: now() },
        { cls: "assistant", role: "assistant", textKey: "demo.steer.step", ts: now() },
      );
      bump();
      return {};
    }
    if (sub === "/answer" && method === "POST") {
      // Answering the mirrored question (tracks_answer_post's shape). The pick
      // becomes the next steer like the daemon does, the owner's choice lands
      // in the chat as his own message, and the mirror row is dropped - the
      // inbox must stop offering a question that is settled.
      k.turns += 1; k.status = "running"; k.updated = now();
      k.replyKey = "demo.steer.reply";
      const pick = String(Object.values((b.answers ?? {}) as Record<string, unknown>)[0] ?? "");
      (extraSteps[id] ||= []).push(
        { cls: "user", role: "user", text: pick, ts: now() },
        { cls: "assistant", role: "assistant", textKey: "demo.steer.step", ts: now() },
      );
      chatLog = [...chatLog.filter((c) => !c.mirror),
                 { cls: "you", text: pick, ts: now() }];
      bump();
      return { started: id, answered: true };
    }
    // Archive is a reversible FLAG on the daemon (cardadmin.archive_track,
    // on=true/false), not a delete - the card stays, hidden everywhere except
    // the board's Archive scope. Answering it with a delete made the sample
    // board disagree with the product on the one thing a tester would check
    // ("where did my card go?"), and left the Archive scope unreachable in
    // demo. Restore is the same call with on:false.
    if (sub === "/archive") {
      k.archived = b.on === undefined ? true : Boolean(b.on);
      k.updated = now(); bump(); return materialize(k);
    }
    if (sub === "/delete") {
      rows = rows.filter((r) => r.id !== id); bump(); return {};
    }
    if (sub === "/cancel") { k.status = "idle"; bump(); return {}; }
  }

  if (path === "/tracks/new" && method === "POST") {
    const task = String(b.task ?? b.request ?? "").trim();
    const k = row({
      id: `d${Date.now().toString(36)}`, lane: "backlog",
      value: Number(b.value ?? 300), priority: String(b.priority ?? "normal"),
      created: now(), updated: now(),
    });
    if (task) k.task = task; else k.taskKey = "demo.newCard";
    rows = [k, ...rows]; bump();
    return materialize(k);
  }
  if (path === "/tracks/reorder" && method === "POST") {
    const ids: string[] = Array.isArray(b.ids) ? b.ids : [];
    rows = [...ids.map(find).filter(Boolean) as Row[], ...rows.filter((r) => !ids.includes(r.id))];
    bump();
    return {};
  }

  // Two sample devices so the settings Devices panel shows populated (Phase
  // G). One is the offline laptop the stale d7 card is stuck on.
  if (path === "/devices/mine" && method === "GET") return [
    { id: "demo-laptop", owner: "owner", label: "Alice's laptop",
      billing_scope: "external", created: iso(4000), last_seen: iso(3600) },
    { id: "demo-buildbox", owner: "owner", label: "Build box (shared)",
      billing_scope: "shared", created: iso(2000), last_seen: iso(30) },
  ];
  // Sections that need a real installation stay honestly empty in the demo.
  if (["/processes", "/runs", "/sessions/claude", "/history", "/connectors", "/users"].includes(path)) return [];
  if (path === "/settings") return metrics().settings ?? {};
  if (path === "/automation") return {};
  if (path === "/pm/plan") return pmPlan();
  return undefined;
}
