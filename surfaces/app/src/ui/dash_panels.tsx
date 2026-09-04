import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React from "react";
import { Alert, Platform, Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { api, type PmBrief, type PmData } from "@/data/client";
import type { EconCard, Metrics, Sow, Usage, UsageTone, UsageWindow } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { fmtPlanPct, fmtTok, useAiFlat } from "./billing";
import { Empty } from "./kit";

const isWeb = Platform.OS === "web";

// ---- dashboard composition (settings.dashboard) ----
// The owner picks which of the 6 tiles / 5 panels show. Missing config = NONE:
// the dashboard concentrates on the triage triangle and its three corners; the
// econ tiles/tables are opt-in via the customizer (or chat). Operators still get
// everything - dashboard.tsx passes ALL_* for them explicitly (their payload has
// no settings and no triage). Keys match the archived web dash.tsx so settings
// interop.
export const ALL_TILES = ["value_delivered", "ai_spend", "margin", "yield", "automation", "leverage"] as const;
export const ALL_PANELS = ["sows", "capacity", "gates", "models", "work"] as const;
// The customizer names each tile/panel by dict key, so the chip list speaks the
// workspace language too.
export const TILE_LABEL_KEYS: Record<string, string> = {
  value_delivered: "dash.tileName.valueDelivered", ai_spend: "dash.tileName.aiSpend",
  margin: "dash.tileName.margin", yield: "dash.tileName.yield",
  automation: "dash.tileName.automation", leverage: "dash.tileName.leverage",
};
export const PANEL_LABEL_KEYS: Record<string, string> = {
  sows: "dash.panelName.sows", capacity: "dash.panelName.capacity", gates: "dash.panelName.gates",
  models: "dash.panelName.models", work: "dash.panelName.work",
};
const LANE_KEY: Record<string, string> = {
  backlog: "lane.backlog", working: "lane.working", review: "lane.review", done: "lane.done",
};
export function dashTiles(m?: Metrics): string[] {
  return m?.settings?.dashboard?.tiles ?? [];
}
export function dashPanels(m?: Metrics): string[] {
  return m?.settings?.dashboard?.panels ?? [];
}

/** Real frosted glass on the web (CSS backdrop-filter over the glow backdrop);
 *  native RN can't blur what's behind, so it uses a crisp translucent surface. */
export function glassStyle(t: ThemeTokens): ViewStyle {
  return isWeb
    ? ({ backgroundColor: t.glass, backdropFilter: "blur(16px) saturate(1.3)", WebkitBackdropFilter: "blur(16px) saturate(1.3)" } as ViewStyle)
    : { backgroundColor: t.surface1 };
}

export function cur(m?: Metrics): string {
  return m?.settings?.currency === "USD" ? "$" : "€";
}

/** A glass panel with a title + optional caption, the desktop card container. */
export function GlassPanel({ title, note, children, style }: {
  title: string; note?: string; children: React.ReactNode; style?: ViewStyle;
}) {
  const t = useTheme();
  return (
    <View style={[s.panel, glassStyle(t), { borderColor: t.glassBorder }, style]}>
      <Text style={[s.h3, { color: t.txtPrimary }]}>{title}</Text>
      {children}
      {note ? <Text style={[s.note, { color: t.txtTertiary }]}>{note}</Text> : null}
    </View>
  );
}

/** The big-number KPI tile (value + label), matches the web #tiles grid. */
export function Tile({ value, label }: { value: string; label: string }) {
  const t = useTheme();
  return (
    <View style={[s.tile, glassStyle(t), { borderColor: t.glassBorder }]}>
      <Text style={[s.tileV, { color: t.txtPrimary }]} numberOfLines={1}>{value}</Text>
      <Text style={[s.tileL, { color: t.txtTertiary }]}>{label}</Text>
    </View>
  );
}

/** Board-wide token consumption - the flat plan's cost figure ($ would lie). */
function totalTokens(m: Metrics): number {
  return (m.cards ?? []).reduce((a, x) => a + (x.tokens_in ?? 0) + (x.tokens_out ?? 0), 0);
}

export function Tiles({ m, wide, tiles }: { m: Metrics; wide: boolean; tiles?: string[] }) {
  const tr = useT();
  const flat = useAiFlat();
  const T = m.totals;
  const [y0, y1] = m.yield_first_pass ?? [0, 0];
  const [a0, a1] = m.automation ?? [0, 0];
  const c = cur(m);
  const byKey: Record<string, { value: string; label: string }> = {
    value_delivered: { value: c + T.value_delivered, label: tr("dash.tile.valueDelivered") },
    // flat: the SHARE OF THE SUBSCRIPTION is the cost. Tokens are the fallback
    // for when the daemon cannot calibrate (no Claude login, freshly reset week).
    ai_spend: flat
      ? (T.plan_pct != null && T.plan_pct > 0
        ? { value: fmtPlanPct(T.plan_pct), label: tr("dash.tile.aiPlanShare") }
        : { value: fmtTok(totalTokens(m)) + " Tok", label: tr("dash.tile.aiSpendFlat") })
      : { value: "$" + T.ai_spend.toFixed(2), label: tr("dash.tile.aiSpend") },
    margin: { value: c + T.margin, label: tr(flat ? "dash.tile.marginFlat" : "dash.tile.margin") },
    yield: { value: y1 ? Math.round((100 * y0) / y1) + "%" : "-", label: tr("dash.tile.yield", { a: y0, b: y1 }) },
    automation: { value: a1 ? Math.round((100 * a0) / a1) + "%" : "-", label: tr("dash.tile.automation", { a: a0, b: a1 }) },
    leverage: { value: c + T.leverage_per_touch, label: tr("dash.tile.leverage") },
  };
  // Enabled keys drive both which tiles show and their order (missing = all).
  const keys = (tiles ?? [...ALL_TILES]).filter((k) => byKey[k]);
  if (keys.length === 0) return null;
  return (
    <View style={s.tileGrid}>
      {keys.map((k) => (
        <View key={k} style={{ width: wide ? "32%" : "48%" }}>
          <Tile value={byKey[k].value} label={byKey[k].label} />
        </View>
      ))}
    </View>
  );
}

/** Owner-only dashboard customizer: a gear that reveals toggle chips to
 *  enable/disable each tile + panel, persisted to settings.dashboard. */
export function DashCustomize({ m }: { m: Metrics }) {
  const t = useTheme();
  const tr = useT();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const tiles = dashTiles(m);
  const panels = dashPanels(m);

  async function toggle(kind: "tiles" | "panels", key: string) {
    if (busy) return;
    setBusy(true);
    try {
      const curKeys = kind === "tiles" ? tiles : panels;
      const next = curKeys.includes(key) ? curKeys.filter((k) => k !== key) : [...curKeys, key];
      await api.saveSettings({ dashboard: { tiles: kind === "tiles" ? next : tiles, panels: kind === "panels" ? next : panels } });
      await qc.invalidateQueries({ queryKey: ["metrics"] });
    } finally {
      setBusy(false);
    }
  }

  const chip = (on: boolean, label: string, onPress: () => void) => (
    <Pressable key={label} onPress={onPress}
      style={[s.tchip, { backgroundColor: on ? t.accent + "22" : t.surface2, borderColor: on ? t.accent : t.borderSubtle }]}>
      <Text style={{ color: on ? t.accent : t.txtTertiary, fontSize: 12, fontWeight: on ? "600" : "400" }}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={{ gap: 10 }}>
      <View style={{ flexDirection: "row", justifyContent: "flex-end" }}>
        <Pressable onPress={() => setEditing((v) => !v)}
          style={[s.gearBtn, { borderColor: t.glassBorder, backgroundColor: t.surface2 }]}>
          <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{tr(editing ? "dash.customizeDone" : "dash.customize")}</Text>
        </Pressable>
      </View>
      {editing ? (
        <GlassPanel title={tr("dash.customizeTitle")} note={tr("dash.customizeNote")}>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {Object.entries(TILE_LABEL_KEYS).map(([k, key]) => chip(tiles.includes(k), tr(key), () => toggle("tiles", k)))}
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: t.glassBorder }}>
            {Object.entries(PANEL_LABEL_KEYS).map(([k, key]) => chip(panels.includes(k), tr(key), () => toggle("panels", k)))}
          </View>
        </GlassPanel>
      ) : null}
    </View>
  );
}

// ---- a minimal table primitive that reflows well on phone + desktop ----

type Col = { key: string; label: string; num?: boolean; flex?: number; color?: (row: any) => string | undefined; render?: (row: any) => string };

function Table({ cols, rows, foot }: { cols: Col[]; rows: any[]; foot?: React.ReactNode }) {
  const t = useTheme();
  return (
    <View style={{ gap: 0 }}>
      <View style={[s.tr, { borderBottomColor: t.glassBorder, borderBottomWidth: 1, paddingBottom: 6 }]}>
        {cols.map((c) => (
          <Text key={c.key} style={[s.th, { color: t.txtTertiary, flex: c.flex ?? 1, textAlign: c.num ? "right" : "left" }]}>
            {c.label}
          </Text>
        ))}
      </View>
      {rows.map((row, i) => (
        <View key={i} style={[s.tr, { borderBottomColor: t.borderSubtle, borderBottomWidth: i === rows.length - 1 ? 0 : 1 }]}>
          {cols.map((c) => (
            <Text key={c.key} numberOfLines={1}
              style={[s.td, { color: c.color?.(row) ?? t.txtSecondary, flex: c.flex ?? 1, textAlign: c.num ? "right" : "left", fontWeight: c.color ? "600" : "400" }]}>
              {c.render ? c.render(row) : String(row[c.key] ?? "")}
            </Text>
          ))}
        </View>
      ))}
      {foot}
    </View>
  );
}

// ---- SoW margin table ----

export function SowPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const tr = useT();
  const flat = useAiFlat();
  const c = cur(m);
  const sows = m.sows ?? [];
  const cols: Col[] = [
    { key: "name", label: tr("dash.sow.col.name"), flex: 2, render: (r: Sow) => r.name },
    { key: "client", label: tr("dash.sow.col.client"), flex: 1.2, render: (r: Sow) => r.client || "-" },
    { key: "status", label: tr("dash.sow.col.status"), flex: 1.2, render: (r: Sow) => (r.all_done ? tr("dash.sow.delivered") : tr("dash.sow.progress", { done: r.done, cards: r.cards })) },
    { key: "cards", label: tr("dash.sow.col.cards"), num: true, render: (r: Sow) => String(r.cards) },
    { key: "hours", label: tr("dash.sow.col.hours"), num: true, render: (r: Sow) => r.hours.toFixed(1) },
    { key: "billed", label: tr("dash.sow.col.billed"), num: true, render: (r: Sow) => c + r.billed.toFixed(2) },
    { key: "ai_cost", label: tr(flat ? "dash.sow.col.aiPlan" : "dash.sow.col.aiCost"), num: true,
      render: (r: Sow) => (!flat ? r.ai_cost.toFixed(2)
        : r.plan_pct != null && r.plan_pct > 0 ? fmtPlanPct(r.plan_pct) : tr("dash.flatIncl")) },
    { key: "margin", label: tr("dash.sow.col.margin"), num: true, render: (r: Sow) => c + r.margin.toFixed(2), color: (r: Sow) => (r.margin >= 0 ? t.ok : t.danger) },
  ];
  const foot = sows.length ? (
    <View style={[s.tr, { borderTopColor: t.glassBorder, borderTopWidth: 1, paddingTop: 6 }]}>
      <Text style={[s.td, { color: t.txtPrimary, flex: 2, fontWeight: "700" }]}>
        {sows.length === 1 ? tr("dash.sow.totalOne") : tr("dash.sow.totalMany", { n: sows.length })}
      </Text>
      <Text style={[s.td, { flex: 1.2 }]} />
      <Text style={[s.td, { flex: 1.2 }]} />
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{sows.reduce((a, x) => a + x.cards, 0)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{sows.reduce((a, x) => a + x.hours, 0).toFixed(1)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{c}{sows.reduce((a, x) => a + x.billed, 0).toFixed(2)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{!flat
        ? sows.reduce((a, x) => a + x.ai_cost, 0).toFixed(2)
        : (() => { const p = sows.reduce((a, x) => a + (x.plan_pct ?? 0), 0);
                   return p > 0 ? fmtPlanPct(p) : tr("dash.flatIncl"); })()}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{c}{sows.reduce((a, x) => a + x.margin, 0).toFixed(2)}</Text>
    </View>
  ) : null;
  return (
    <GlassPanel title={tr("dash.sow.title")}
      note={sows.length ? tr(flat ? "dash.sow.noteFlat" : "dash.sow.note") : undefined}>
      {sows.length ? <Table cols={cols} rows={sows} foot={foot} />
        : <Empty text={tr("dash.sow.empty")} />}
    </GlassPanel>
  );
}

// ---- Capacity gauge with actors ----

function Meter({ pct, color }: { pct: number; color: string }) {
  const t = useTheme();
  return (
    <View style={[s.meter, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
      <View style={{ width: `${Math.min(100, Math.max(0, pct))}%`, height: "100%", backgroundColor: color, borderRadius: 999 }} />
    </View>
  );
}

/** The one ETA the app shows anywhere: a RANGE derived from measured pace,
 *  never a single day (pm-lean-advisor, 2026-09-04 - no surviving PM product
 *  lets an LLM commit a calendar date, and neither does this one anymore). */
function fmtEta(tr: ReturnType<typeof useT>, eta?: PmBrief["eta"]): string {
  if (!eta?.known || eta.days_min == null || eta.days_max == null) return tr("pm.etaUnknown");
  return eta.days_min === eta.days_max
    ? tr("dash.triangle.etaOne", { n: eta.days_min })
    : tr("dash.triangle.etaRange", { min: eta.days_min, max: eta.days_max });
}

// ---- the SENIOR-PM one-pager (owner directive 2026-09-04: "überlegt was ----
// ---- ein Senior-PM zeigen würde") ------------------------------------------
// A senior PM reports the CONCLUSION, never the analysis tool: verdict first,
// then the one decision he needs from you (tappable), then the roadmap as
// plain states - never effort units - then one situation sentence. The golden
// triangle (Budget/Timeline/Scope corners, raw usage bars, velocity, WIP) is
// his ANALYSIS - it lives behind "Details" (the unchanged TriageFollowUp),
// for the day the owner wants to audit the conclusion. This replaced
// TrianglePanel, which rendered the three analysis corners as the report.

/** Code-derived RAG verdict: a measured budget/timeline red is a real risk;
 *  otherwise an open owner decision means the project waits on YOU (warn,
 *  not danger - nothing is broken, it needs an answer); else on course. */
function verdictOf(plan: PmBrief | null | undefined): "risk" | "you" | "ok" {
  const tri = plan?.triage ?? {};
  if (tri.budget === "blocked" || tri.timeline === "blocked") return "risk";
  if ((plan?.open_questions ?? []).some((q) => q?.trim())) return "you";
  return "ok";
}

export function StatusPanel({ m, wide, defaultRepo }: { m: Metrics; wide: boolean; defaultRepo?: string }) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const { data } = useQuery<PmData>({ queryKey: ["pmPlan"], queryFn: api.pmPlan, staleTime: 30000 });
  const [details, setDetails] = React.useState(false);
  const goal = data?.goal || data?.plan?.goal;
  if (!goal) return null;
  const plan = data?.plan;
  const ask = (plan?.open_questions ?? []).find((q) => q?.trim());
  const verdict = verdictOf(plan);
  const vCol = verdict === "risk" ? t.danger : verdict === "you" ? t.warn : t.ok;
  const vTxt = tr(verdict === "risk" ? "dash.status.atRisk" : verdict === "you" ? "dash.status.needsYou" : "dash.status.onTrack");
  const pct = Math.max(0, Math.min(100, plan?.done_pct ?? 0));
  const checkedAt = plan?.generated_at ? plan.generated_at.slice(11, 16) : null;
  const b = plan?.budget;
  const ms = plan?.milestones ?? [];
  const risks = (plan?.risks ?? []).filter((r) => typeof r === "string" && r.trim()).slice(0, 2);
  // capacity as a CONCLUSION sentence; the blocked case gets the measured
  // note verbatim (pm_budget writes it in owner vocabulary since 794ecec).
  const capLine = !b?.state ? "" : b.state === "ok" ? tr("dash.status.capOk")
    : b.state === "warn" ? tr("dash.status.capWarn")
    : (b.note || tr("dash.status.capWarn"));
  return (
    <>
      <GlassPanel title={tr("dash.status.title")}>
        {/* goal + when the planner last actually ran */}
        <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 15.5, fontWeight: "700", lineHeight: 21, flex: 1 }}>{goal}</Text>
          {checkedAt ? (
            <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("dash.triangle.checkedAt", { when: checkedAt })}</Text>
          ) : null}
        </View>
        {/* THE verdict line - conclusion first */}
        <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 7 }}>
          <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: vCol }} />
          <Text style={{ color: vCol, fontSize: 14, fontWeight: "800" }}>{vTxt}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
            · {tr("dash.status.progress", { pct })} · {fmtEta(tr, plan?.eta)}
          </Text>
        </View>
        <Meter pct={pct} color={verdict === "risk" ? t.danger : t.ok} />
        {/* THE ask - the one decision only the owner can make, straight to chat */}
        {ask ? (
          <Pressable onPress={() => router.push("/chat" as never)}
            style={{ backgroundColor: t.warn + "14", borderColor: t.warn + "55", borderWidth: 1,
              borderRadius: 12, padding: 12, gap: 4 }}>
            <Text style={{ color: t.warn, fontSize: 11, fontWeight: "800", letterSpacing: 0.5, textTransform: "uppercase" }}>
              {tr("dash.status.needTitle")}
            </Text>
            <Text style={{ color: t.txtPrimary, fontSize: 13.5, lineHeight: 19 }}>{ask}</Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
              <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("dash.status.answerHint")}</Text>
              <Ionicons name="arrow-forward-circle" size={15} color={t.accent} />
            </View>
          </Pressable>
        ) : null}
        {/* roadmap: milestones as STATES, never effort units */}
        {ms.length ? (
          <View style={{ gap: 7 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.5, textTransform: "uppercase" }}>
              {tr("dash.status.roadmap")}
            </Text>
            {ms.map((mm, i) => {
              const done = mm.status === "done";
              const wait = !done && !!mm.calendar_wait;
              const running = !done && !wait && mm.status === "in_progress";
              const ic = done ? "checkmark-circle" : wait ? "pause-circle" : running ? "play-circle" : "ellipse-outline";
              const col = done ? t.ok : wait ? t.txtTertiary : running ? t.accent : t.txtTertiary;
              const word = done ? tr("dash.triangle.msDone") : wait ? tr("dash.triangle.msWait")
                : running ? tr("dash.status.msRunning") : tr("dash.status.msPlanned");
              return (
                <Pressable key={i} disabled={!mm.card} onPress={() => router.push(`/card/${mm.card}` as never)}
                  style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <Ionicons name={ic as keyof typeof Ionicons.glyphMap} size={16} color={col} />
                  <Text numberOfLines={1} style={{ color: done ? t.txtTertiary : t.txtSecondary, fontSize: 12.5, flex: 1,
                    textDecorationLine: done ? "line-through" : "none" }}>{mm.name}</Text>
                  <Text style={{ color: col, fontSize: 11, fontWeight: "600" }}>{word}</Text>
                  {mm.card ? <Ionicons name="chevron-forward" size={13} color={t.txtTertiary} /> : null}
                </Pressable>
              );
            })}
          </View>
        ) : null}
        {/* situation: capacity + risks as sentences, not gauges */}
        {capLine || risks.length ? (
          <View style={{ gap: 3 }}>
            {capLine ? <Text style={{ color: t.txtTertiary, fontSize: 12, lineHeight: 17 }}>{capLine}</Text> : null}
            {risks.map((r, i) => (
              <Text key={i} style={{ color: t.warn, fontSize: 12, lineHeight: 17 }}>⚠ {r}</Text>
            ))}
          </View>
        ) : null}
        {/* the analysis, on demand */}
        <Pressable onPress={() => setDetails((d) => !d)}
          style={{ flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start" }}>
          <Text style={{ color: t.txtTertiary, fontSize: 12, fontWeight: "600" }}>{tr("dash.status.details")}</Text>
          <Ionicons name={details ? "chevron-up" : "chevron-down"} size={13} color={t.txtTertiary} />
        </Pressable>
      </GlassPanel>
      {details ? <TriageFollowUp m={m} wide={wide} defaultRepo={defaultRepo} /> : null}
    </>
  );
}

// ---- the three-corner follow-up ---------------------------------------------
// The rule of this dashboard: below the triangle, EVERY piece of follow-up
// information belongs to exactly one of the three corners - Budget, Timeline,
// Scope. What used to sprawl across the PM panel (launch countdown, milestones,
// budget chips, progress, next actions) lands here, under its corner.

const eur = (n?: number) => "€" + (n ?? 0).toFixed(2);

function MiniChip({ label, color }: { label: string; color?: string }) {
  const t = useTheme();
  return (
    <View style={{ backgroundColor: t.surface2, borderColor: color ? color + "66" : t.borderSubtle, borderWidth: 1,
      borderRadius: 999, paddingHorizontal: 9, paddingVertical: 4 }}>
      <Text style={{ color: color || t.txtSecondary, fontSize: 11.5, fontWeight: "600" }}>{label}</Text>
    </View>
  );
}

/** One corner's follow-up card: header repeats the corner's name + green/red
 *  state so each detail is visibly anchored to its triangle corner. */
function CornerPanel({ label, state, children, style }: {
  label: string; state?: "ok" | "blocked"; children: React.ReactNode; style?: ViewStyle;
}) {
  const t = useTheme();
  const tr = useT();
  const col = state === "blocked" ? t.danger : state === "ok" ? t.ok : t.txtTertiary;
  const word = state === "blocked" ? tr("dash.triangle.red") : state === "ok" ? tr("dash.triangle.ok") : tr("dash.triangle.unknown");
  return (
    <View style={[s.panel, glassStyle(t), { borderColor: t.glassBorder }, style]}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: col }} />
        <Text style={[s.h3, { color: t.txtPrimary, flex: 1 }]}>{label}</Text>
        <Text style={{ color: col, fontSize: 11, fontWeight: "600" }}>{word}</Text>
      </View>
      {children}
    </View>
  );
}

export function TriageFollowUp({ m, wide, defaultRepo }: { m: Metrics; wide: boolean; defaultRepo?: string }) {
  const t = useTheme();
  const tr = useT();
  const flat = useAiFlat();
  const router = useRouter();
  const qc = useQueryClient();
  const { data } = useQuery<PmData>({ queryKey: ["pmPlan"], queryFn: api.pmPlan, staleTime: 30000 });
  const makeCard = useMutation({
    mutationFn: (task: string) => api.newTrack({ repo: defaultRepo, task, lane: "backlog", priority: "medium" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tracks"] }); Alert.alert("PM", tr("pm.cardCreated")); },
    onError: (e: unknown) => Alert.alert("PM", String((e as Error).message)),
  });
  const plan = data?.plan;
  if (!plan) return null;
  const tri = plan.triage;
  const b = plan.budget;
  const feas = plan.feasibility;
  const c = cur(m);
  const ms = plan.milestones ?? [];
  const pct = Math.max(0, Math.min(100, plan.done_pct ?? 0));
  const cap = m.capacity;

  // The budget corner renders GENERICALLY by the PM's computed kind: "usage"
  // (Max plan - the real rate-limit windows the PM checked, same UsageRow the
  // Settings panel uses) or "cash" (API plan - euro spend vs cap). The PM owns
  // the verdict; the board only draws. Adding a plan = a new kind branch.
  const reasons = plan.triage_reasons;
  const GateReason = ({ text }: { text?: string }) =>
    text ? <Text style={{ color: t.danger, fontSize: 11.5, lineHeight: 16, marginBottom: 6 }}>⚠ {text}</Text> : null;
  const budget = (
    <CornerPanel key="budget" label={tr("dash.triangle.budget")} state={tri?.budget} style={wide ? { flex: 1 } : undefined}>
      <GateReason text={reasons?.budget} />
      {b?.kind === "usage" ? (
        <View>
          {b.windows?.length ? b.windows.map((w) => <UsageRow key={w.id} w={w} />)
            : <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("dash.usage.unavailable")}</Text>}
          {b.est_turns_to_goal != null ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7, marginTop: 2 }}>
              <MiniChip label={tr("pm.turns", { n: b.est_turns_to_goal })} />
            </View>
          ) : null}
        </View>
      ) : (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
          {b?.projected_eur != null ? <MiniChip label={tr("pm.cashToGoal", { v: eur(b.projected_eur) })} /> : null}
          {b?.monthly_eur != null ? <MiniChip label={tr("pm.flatMonthly", { v: eur(b.monthly_eur) })} /> : null}
          {b?.spent_to_date_eur != null ? <MiniChip label={tr("dash.corner.spentToDate", { v: eur(b.spent_to_date_eur) })} /> : null}
          {b?.est_turns_to_goal != null ? <MiniChip label={tr("pm.turns", { n: b.est_turns_to_goal })} /> : null}
          <MiniChip label={!flat ? tr("dash.corner.aiSpend", { v: m.totals.ai_spend.toFixed(2) })
            : m.totals.plan_pct != null && m.totals.plan_pct > 0
              ? tr("dash.corner.aiPlan", { v: fmtPlanPct(m.totals.plan_pct) })
              : tr("dash.corner.aiUse", { v: fmtTok(totalTokens(m)) })} />
        </View>
      )}
      {feas?.budget ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16, marginTop: 4 }}>{feas.budget}</Text> : null}
      {b?.note ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16, marginTop: 2 }}>{b.note}</Text> : null}
    </CornerPanel>
  );

  const timeline = (
    <CornerPanel key="timeline" label={tr("dash.triangle.timeline")} state={tri?.timeline} style={wide ? { flex: 1 } : undefined}>
      <GateReason text={reasons?.timeline} />
      {/* the ONE eta the app shows anywhere - a RANGE from measured pace,
          never a single invented day (pm-lean-advisor, 2026-09-04) */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
        <Ionicons name="speedometer-outline" size={13} color={t.accent} />
        <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "700", flex: 1 }}>{fmtEta(tr, plan.eta)}</Text>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
        {b?.velocity_turns_per_day != null ? <MiniChip label={tr("pm.perDay", { n: b.velocity_turns_per_day })} /> : null}
      </View>
      {ms.length ? (
        <View style={{ gap: 6 }}>
          {ms.map((mm, i) => (
            <Pressable key={i} disabled={!mm.card} onPress={() => router.push(`/card/${mm.card}` as never)}
              style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
              <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: t.accent2 }} />
              <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12, flex: 1 }}>{mm.name}</Text>
              <Text style={{ color: t.accent2, fontSize: 11, fontWeight: "700" }}>
                {mm.status === "done" ? tr("dash.triangle.msDone")
                  : mm.calendar_wait ? tr("dash.triangle.msWait")
                  : mm.est_turns != null ? tr("dash.triangle.msTurns", { n: mm.est_turns })
                  : tr("pm.etaUnknown")}
              </Text>
              {mm.card ? <Ionicons name="arrow-forward-circle" size={15} color={t.accent} /> : null}
            </Pressable>
          ))}
        </View>
      ) : null}
      {feas?.note ? <Text style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 16 }}>{feas.note}</Text> : null}
    </CornerPanel>
  );

  const scope = (
    <CornerPanel key="scope" label={tr("dash.triangle.scope")} state={tri?.scope} style={wide ? { flex: 1 } : undefined}>
      <GateReason text={reasons?.scope} />
      <View style={{ gap: 4 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("pm.progress")}</Text>
          <Text style={{ color: t.txtSecondary, fontSize: 11, fontWeight: "700" }}>{pct}%</Text>
        </View>
        <View style={{ height: 6, borderRadius: 3, backgroundColor: t.surface2, overflow: "hidden" }}>
          <View style={{ width: `${pct}%`, height: 6, backgroundColor: t.ok }} />
        </View>
      </View>
      {plan.next?.length ? (
        <View style={{ gap: 6 }}>
          <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.5 }}>{tr("pm.nextHeading")}</Text>
          {plan.next.slice(0, 3).map((n, i) => (
            <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: "800", width: 12 }}>{i + 1}</Text>
              <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 12.5, flex: 1 }}>{n.title}</Text>
              {n.card ? (
                <Pressable onPress={() => router.push(`/card/${n.card}` as never)} hitSlop={6}>
                  <Ionicons name="arrow-forward-circle" size={18} color={t.accent} />
                </Pressable>
              ) : (
                <Pressable onPress={() => Alert.alert(tr("pm.createCardTitle"), n.title, [
                  { text: tr("ui.cancel"), style: "cancel" },
                  { text: tr("ui.create"), onPress: () => makeCard.mutate(n.title) }])} hitSlop={6}>
                  <Ionicons name="add-circle" size={18} color={t.ok} />
                </Pressable>
              )}
            </View>
          ))}
        </View>
      ) : null}
      <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("dash.corner.wip", { wip: cap.wip, limit: cap.wip_limit, n: cap.headroom })}</Text>
    </CornerPanel>
  );

  return wide
    ? <View style={{ flexDirection: "row", gap: 12, alignItems: "flex-start" }}>{budget}{timeline}{scope}</View>
    : <View style={{ gap: 12 }}>{budget}{timeline}{scope}</View>;
}

// ---- Claude usage (rate-limit windows + weekly pacing) ----
const _DOW = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
function fmtWhen(iso: string | null): string {
  if (!iso) return "?";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "?";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${_DOW[d.getDay()]} ${p(d.getDate())}.${p(d.getMonth() + 1)}. ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function toneColor(t: ThemeTokens, tone: UsageTone, accent: string): string {
  return tone === "danger" ? t.danger : tone === "warning" ? t.warn : accent;
}

function UsageRow({ w }: { w: UsageWindow }) {
  const t = useTheme();
  const tr = useT();
  const pct = typeof w.usedPct === "number" ? w.usedPct : 0;
  const col = toneColor(t, w.tone, t.accent);
  const pacing = w.pacing;
  const warn = pacing?.flag;
  return (
    <View style={{ marginBottom: 10 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" }}>
        <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600" }}>{w.label}</Text>
        <Text style={{ color: col, fontSize: 12.5, fontWeight: "700" }}>{tr("dash.usage.used", { pct: Math.round(pct) })}</Text>
      </View>
      <View style={{ marginVertical: 5 }}><Meter pct={pct} color={col} /></View>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("dash.usage.reset", { when: fmtWhen(w.resetsAt) })}</Text>
      {warn ? (
        <Text style={{ color: t.warn, fontSize: 11.5, marginTop: 3 }}>
          {tr("dash.usage.pace", { proj: Math.round(pacing?.projected_pct ?? 0), when: fmtWhen(pacing?.exhaust_at ?? null) })}
        </Text>
      ) : null}
    </View>
  );
}

/** The usage element: Claude subscription rate-limit windows (5h + weekly) with
 *  pacing. Owner-only; polls /usage every 5 min (the daemon caches it). Renders
 *  nothing until it has an answer, and only a small note if usage is unavailable. */
export function UsagePanel() {
  const t = useTheme();
  const tr = useT();
  const { data } = useQuery<Usage>({
    queryKey: ["usage"], queryFn: api.usage,
    refetchInterval: 5 * 60 * 1000, staleTime: 4 * 60 * 1000,
  });
  if (!data) return null;
  if (data.status !== "ok" || data.windows.length === 0) {
    return (
      <GlassPanel title={tr("dash.usage.title")}>
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("dash.usage.unavailable")}</Text>
      </GlassPanel>
    );
  }
  return (
    <GlassPanel title={tr("dash.usage.title")} note={data.plan ?? undefined}>
      {data.windows.map((w) => <UsageRow key={w.id} w={w} />)}
    </GlassPanel>
  );
}

export function CapacityPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const tr = useT();
  const c = m.capacity;
  const pct = Math.min(100, Math.round((100 * c.touches_today) / (c.touch_budget_day || 1)));
  const actors = Object.entries(c.actors ?? {});
  return (
    <GlassPanel title={tr("dash.capacity.title")} note={tr("dash.capacity.note")}>
      <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
        {tr("dash.capacity.line", { a: c.touches_today, b: c.touch_budget_day, pct, wip: c.wip, limit: c.wip_limit })}{" "}
        <Text style={{ color: t.ok, fontWeight: "700" }}>{tr("dash.capacity.headroom", { n: c.headroom })}</Text>
      </Text>
      <View style={{ marginVertical: 6 }}><Meter pct={pct} color={pct >= 90 ? t.warn : t.accent} /></View>
      {actors.length > 1 ? (
        <Text style={{ color: t.txtSecondary, fontSize: 12, marginBottom: 4 }}>
          {actors.map(([a, n]) => `${a}: ${n}t`).join(" · ")}
        </Text>
      ) : null}
      <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>
        {tr(pct < 80 && c.headroom > 0 ? "dash.capacity.below" : "dash.capacity.at")}
      </Text>
    </GlassPanel>
  );
}

// ---- Gate failures bars ----

export function GatesPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const tr = useT();
  const fails = m.gate_failures ?? [];
  const gmax = fails[0]?.[1] ?? 1;
  return (
    <GlassPanel title={tr("dash.gates.title")}>
      {fails.length === 0 ? <Empty text={tr("dash.gates.empty")} /> : (
        <View style={{ gap: 6 }}>
          {fails.map(([k, n]) => (
            <View key={k} style={s.hbar}>
              <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12, width: "40%" }}>{k}</Text>
              <View style={[s.trk, { backgroundColor: t.surface2 }]}>
                <View style={{ width: `${Math.max(3, Math.round((100 * n) / gmax))}%`, height: "100%", backgroundColor: t.danger, borderRadius: 999 }} />
              </View>
              <Text style={{ color: t.txtPrimary, fontSize: 12, width: 28, textAlign: "right", fontWeight: "600" }}>{n}</Text>
            </View>
          ))}
        </View>
      )}
    </GlassPanel>
  );
}

// ---- AI usage by model ----

export function ModelsPanel({ m }: { m: Metrics }) {
  const tr = useT();
  const flat = useAiFlat();
  const by = m.ai_by_model ?? {};
  const rows = Object.entries(by).map(([model, b]) => ({ model: model.replace("claude-", ""), ...b }));
  if (rows.length === 0) return null;
  const calibrated = m.plan_calibration != null;
  const cols: Col[] = [
    { key: "model", label: tr("dash.models.col.model"), flex: 1.6 },
    { key: "turns", label: tr("dash.models.col.turns"), num: true },
    { key: "tok_in", label: tr("dash.models.col.tokIn"), num: true, render: (r) => r.tok_in.toLocaleString() },
    { key: "tok_out", label: tr("dash.models.col.tokOut"), num: true, render: (r) => r.tok_out.toLocaleString() },
    // flat plan: a $ column would present subscription work as pay-per-token
    // spend. ONE quoting column replaces the two money ones - share of the plan
    // per turn when the quota could be calibrated, tokens per turn when not.
    ...(flat
      ? [calibrated
        ? { key: "planturn", label: tr("dash.models.col.planPerTurn"), num: true,
            render: (r: any) => (r.plan_pct_per_turn != null && r.plan_pct_per_turn > 0
              ? fmtPlanPct(r.plan_pct_per_turn) : "-") } as Col
        : { key: "tokturn", label: tr("dash.models.col.tokPerTurn"), num: true,
            render: (r: any) => (r.turns ? fmtTok((r.tok_in + r.tok_out) / r.turns) : "-") } as Col]
      : [{ key: "cost", label: tr("dash.models.col.cost"), num: true, render: (r: any) => r.cost.toFixed(2) } as Col,
         { key: "avg", label: tr("dash.models.col.avg"), num: true, render: (r: any) => r.avg_cost_per_turn.toFixed(3) } as Col]),
  ];
  return (
    <GlassPanel title={tr("dash.models.title")} note={tr(flat ? "dash.models.noteFlat" : "dash.models.note")}>
      <Table cols={cols} rows={rows} />
    </GlassPanel>
  );
}

// ---- Work table with AI/human split bars ----

export function WorkPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const tr = useT();
  const flat = useAiFlat();
  const c = cur(m);
  const cards = m.cards ?? [];
  let maxA = 0.01, maxH = 1;
  cards.forEach((x) => { if (x.ai_cost > maxA) maxA = x.ai_cost; if (x.touches > maxH) maxH = x.touches; });
  return (
    <GlassPanel title={tr("dash.work.title")}>
      <View style={[s.row, { gap: 12, marginBottom: 8 }]}>
        <View style={[s.row, { gap: 4 }]}><View style={[s.sq, { backgroundColor: t.ai }]} /><Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr(flat ? "dash.work.legendAiFlat" : "dash.work.legendAi")}</Text></View>
        <View style={[s.row, { gap: 4 }]}><View style={[s.sq, { backgroundColor: t.human }]} /><Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("dash.work.legendHuman")}</Text></View>
      </View>
      {/* wide table -> horizontal scroll keeps every column readable on phone */}
      <ScrollView horizontal showsHorizontalScrollIndicator={isWeb} contentContainerStyle={{ minWidth: 760 }}>
        <View style={{ flexGrow: 1 }}>
          {/* header */}
          <View style={[s.tr, { borderBottomColor: t.glassBorder, borderBottomWidth: 1, paddingBottom: 6 }]}>
            <Text style={[s.th, { color: t.txtTertiary, flex: 2.4 }]}>{tr("dash.work.col.card")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1 }]}>{tr("dash.work.col.lane")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1.3 }]}>{tr("dash.work.col.model")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1.4, textAlign: "right" }]}>{tr("dash.work.col.tok")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1, textAlign: "right" }]}>{tr(flat ? "dash.work.col.aiFlat" : "dash.work.col.aiCost")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 0.8, textAlign: "right" }]}>{tr("dash.work.col.touch")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1.4 }]}>{tr("dash.work.col.split")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1, textAlign: "right" }]}>{tr("dash.work.col.value")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1, textAlign: "right" }]}>{tr("dash.work.col.margin")}</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 0.9 }]}>{tr("dash.work.col.mode")}</Text>
          </View>
          {cards.length === 0 ? <Empty text={tr("dash.work.empty")} /> : cards.map((x: EconCard) => {
            const margin = x.margin ?? (x.value - (flat ? 0 : x.ai_cost));
            const models = x.models?.length ? x.models.map((mm) => mm.replace("claude-", "")).join(", ") : "-";
            const tin = x.tokens_in ?? 0, tout = x.tokens_out ?? 0;
            const billedVal = x.billed ?? x.value;
            const mode = x.mode ?? "-";
            return (
              <View key={x.id} style={[s.tr, { borderBottomColor: t.borderSubtle, borderBottomWidth: 1, alignItems: "center" }]}>
                <Text numberOfLines={1} style={[s.td, { color: t.txtPrimary, flex: 2.4 }]}>{x.task}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtTertiary, flex: 1 }]}>{LANE_KEY[x.lane] ? tr(LANE_KEY[x.lane]) : x.lane}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtSecondary, flex: 1.3 }]}>{models}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtSecondary, flex: 1.4, textAlign: "right" }]}>{tin.toLocaleString()}/{tout.toLocaleString()}</Text>
                <Text style={[s.td, { color: t.txtSecondary, flex: 1, textAlign: "right" }]}>{!flat
                  ? x.ai_cost.toFixed(2)
                  : x.plan_pct != null && x.plan_pct > 0 ? fmtPlanPct(x.plan_pct) : tr("dash.flatIncl")}</Text>
                <Text style={[s.td, { color: t.txtSecondary, flex: 0.8, textAlign: "right" }]}>{x.touches}</Text>
                <View style={{ flex: 1.4, gap: 2, justifyContent: "center", paddingRight: 6 }}>
                  <View style={{ height: 4, borderRadius: 999, backgroundColor: t.ai, width: `${Math.max(2, Math.round((100 * x.ai_cost) / maxA))}%` }} />
                  <View style={{ height: 4, borderRadius: 999, backgroundColor: t.human, width: `${Math.max(2, Math.round((100 * x.touches) / maxH))}%` }} />
                </View>
                <Text numberOfLines={1} style={[s.td, { color: t.txtSecondary, flex: 1, textAlign: "right" }]}>{c}{billedVal.toFixed(2)}{x.billing === "tm" ? " ~" : ""}</Text>
                <Text style={[s.td, { color: margin >= 0 ? t.ok : t.danger, flex: 1, textAlign: "right", fontWeight: "600" }]}>{c}{margin.toFixed(2)}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtTertiary, flex: 0.9 }]}>{mode}</Text>
              </View>
            );
          })}
        </View>
      </ScrollView>
    </GlassPanel>
  );
}

const s = StyleSheet.create({
  panel: { borderWidth: 1, borderRadius: 14, padding: 14, gap: 8 },
  h3: { fontSize: 14, fontWeight: "700" },
  note: { fontSize: 11, lineHeight: 16, marginTop: 4 },
  tile: { borderWidth: 1, borderRadius: 12, padding: 14, gap: 4, minHeight: 74, justifyContent: "center" },
  tileV: { fontSize: 22, fontWeight: "700" },
  tileL: { fontSize: 11.5 },
  tileGrid: { flexDirection: "row", flexWrap: "wrap", gap: "2%" as any, rowGap: 10 as any },
  row: { flexDirection: "row", alignItems: "center" },
  sq: { width: 9, height: 9, borderRadius: 2 },
  tr: { flexDirection: "row", alignItems: "center", paddingVertical: 6, gap: 6 },
  th: { fontSize: 10.5, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.4 },
  td: { fontSize: 12.5 },
  tchip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  gearBtn: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  meter: { height: 8, borderRadius: 999, borderWidth: 1, overflow: "hidden" },
  hbar: { flexDirection: "row", alignItems: "center", gap: 8 },
  trk: { flex: 1, height: 8, borderRadius: 999, overflow: "hidden" },
});
