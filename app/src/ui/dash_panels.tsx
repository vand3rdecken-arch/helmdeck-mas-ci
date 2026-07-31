import { useQueryClient } from "@tanstack/react-query";
import React from "react";
import { Platform, Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { api } from "@/data/client";
import type { EconCard, Metrics, Sow } from "@/data/types";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { Empty } from "./kit";

const isWeb = Platform.OS === "web";

// ---- dashboard composition (settings.dashboard) ----
// The owner picks which of the 6 tiles / 5 panels show; missing config = all on
// (back-compat). Keys match the archived web dash.tsx so settings interop.
export const ALL_TILES = ["value_delivered", "ai_spend", "margin", "yield", "automation", "leverage"] as const;
export const ALL_PANELS = ["sows", "capacity", "gates", "models", "work"] as const;
export const TILE_LABELS: Record<string, string> = {
  value_delivered: "Value delivered", ai_spend: "AI spend", margin: "Margin",
  yield: "First-pass yield", automation: "Automation rate", leverage: "Leverage per touch",
};
export const PANEL_LABELS: Record<string, string> = {
  sows: "SoW margin", capacity: "Capacity gauge", gates: "Gate failures",
  models: "AI usage by model", work: "Work table",
};
export function dashTiles(m?: Metrics): string[] {
  return m?.settings?.dashboard?.tiles ?? [...ALL_TILES];
}
export function dashPanels(m?: Metrics): string[] {
  return m?.settings?.dashboard?.panels ?? [...ALL_PANELS];
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

export function Tiles({ m, wide, tiles }: { m: Metrics; wide: boolean; tiles?: string[] }) {
  const T = m.totals;
  const [y0, y1] = m.yield_first_pass ?? [0, 0];
  const [a0, a1] = m.automation ?? [0, 0];
  const c = cur(m);
  const byKey: Record<string, { value: string; label: string }> = {
    value_delivered: { value: c + T.value_delivered, label: "value delivered" },
    ai_spend: { value: "$" + T.ai_spend.toFixed(2), label: "AI spend" },
    margin: { value: c + T.margin, label: "margin (value − AI)" },
    yield: { value: y1 ? Math.round((100 * y0) / y1) + "%" : "-", label: `first-pass yield (${y0}/${y1})` },
    automation: { value: a1 ? Math.round((100 * a0) / a1) + "%" : "-", label: `automation rate (${a0}/${a1} auto)` },
    leverage: { value: c + T.leverage_per_touch, label: "value per touch unit" },
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
          <Text style={{ color: t.txtSecondary, fontSize: 12 }}>{editing ? "Fertig" : "⚙ Anpassen"}</Text>
        </Pressable>
      </View>
      {editing ? (
        <GlassPanel title="Auf diesem Dashboard anzeigen"
          note="Auch per Chat: „zeige nur Marge und Automatisierung“. Die Ökonomie bleibt immer gemessen.">
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {Object.entries(TILE_LABELS).map(([k, label]) => chip(tiles.includes(k), label, () => toggle("tiles", k)))}
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: t.glassBorder }}>
            {Object.entries(PANEL_LABELS).map(([k, label]) => chip(panels.includes(k), label, () => toggle("panels", k)))}
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
  const c = cur(m);
  const sows = m.sows ?? [];
  const cols: Col[] = [
    { key: "name", label: "statement of work", flex: 2, render: (r: Sow) => r.name },
    { key: "client", label: "client", flex: 1.2, render: (r: Sow) => r.client || "-" },
    { key: "status", label: "status", flex: 1.2, render: (r: Sow) => (r.all_done ? "delivered" : `${r.done}/${r.cards} done`) },
    { key: "cards", label: "cards", num: true, render: (r: Sow) => String(r.cards) },
    { key: "hours", label: "hours", num: true, render: (r: Sow) => r.hours.toFixed(1) },
    { key: "billed", label: "billed", num: true, render: (r: Sow) => c + r.billed.toFixed(2) },
    { key: "ai_cost", label: "AI $", num: true, render: (r: Sow) => r.ai_cost.toFixed(2) },
    { key: "margin", label: "margin", num: true, render: (r: Sow) => c + r.margin.toFixed(2), color: (r: Sow) => (r.margin >= 0 ? t.ok : t.danger) },
  ];
  const foot = sows.length ? (
    <View style={[s.tr, { borderTopColor: t.glassBorder, borderTopWidth: 1, paddingTop: 6 }]}>
      <Text style={[s.td, { color: t.txtPrimary, flex: 2, fontWeight: "700" }]}>total ({sows.length} SoW{sows.length === 1 ? "" : "s"})</Text>
      <Text style={[s.td, { flex: 1.2 }]} />
      <Text style={[s.td, { flex: 1.2 }]} />
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{sows.reduce((a, x) => a + x.cards, 0)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{sows.reduce((a, x) => a + x.hours, 0).toFixed(1)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{c}{sows.reduce((a, x) => a + x.billed, 0).toFixed(2)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{sows.reduce((a, x) => a + x.ai_cost, 0).toFixed(2)}</Text>
      <Text style={[s.td, { color: t.txtPrimary, flex: 1, textAlign: "right", fontWeight: "700" }]}>{c}{sows.reduce((a, x) => a + x.margin, 0).toFixed(2)}</Text>
    </View>
  ) : null;
  return (
    <GlassPanel title="SoW margin — one process = one statement of work"
      note={sows.length ? "billed = recognized revenue (fixed price on delivery · T&M accrues with hours · none = internal). margin = billed − AI cost." : undefined}>
      {sows.length ? <Table cols={cols} rows={sows} foot={foot} />
        : <Empty text="No process-grouped work yet. A process groups its cards into one SoW; per-card billing rolls up here." />}
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

export function CapacityPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const c = m.capacity;
  const pct = Math.min(100, Math.round((100 * c.touches_today) / (c.touch_budget_day || 1)));
  const actors = Object.entries(c.actors ?? {});
  return (
    <GlassPanel title="Capacity — take more work, or automate?"
      note="WIP = running agents you can supervise · touch units = your attention as currency vs a daily budget · headroom = WIP slots left. All thresholds are policy.">
      <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>
        today {c.touches_today}/{c.touch_budget_day} touch units ({pct}%) · WIP {c.wip}/{c.wip_limit} · headroom{" "}
        <Text style={{ color: t.ok, fontWeight: "700" }}>{c.headroom} cards</Text>
      </Text>
      <View style={{ marginVertical: 6 }}><Meter pct={pct} color={pct >= 90 ? t.warn : t.accent} /></View>
      {actors.length > 1 ? (
        <Text style={{ color: t.txtSecondary, fontSize: 12, marginBottom: 4 }}>
          {actors.map(([a, n]) => `${a}: ${n}t`).join(" · ")}
        </Text>
      ) : null}
      <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>
        {pct < 80 && c.headroom > 0
          ? "Below capacity → intake more: marginal cost of one more card is tokens only."
          : "At capacity → automate: fixing the top gate failure below frees the most headroom."}
      </Text>
    </GlassPanel>
  );
}

// ---- Gate failures bars ----

export function GatesPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const fails = m.gate_failures ?? [];
  const gmax = fails[0]?.[1] ?? 1;
  return (
    <GlassPanel title="Gate failures — what to fix in the harness next">
      {fails.length === 0 ? <Empty text="none recorded yet" /> : (
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
  const by = m.ai_by_model ?? {};
  const rows = Object.entries(by).map(([model, b]) => ({ model: model.replace("claude-", ""), ...b }));
  if (rows.length === 0) return null;
  const cols: Col[] = [
    { key: "model", label: "model", flex: 1.6 },
    { key: "turns", label: "turns", num: true },
    { key: "tok_in", label: "tok in", num: true, render: (r) => r.tok_in.toLocaleString() },
    { key: "tok_out", label: "tok out", num: true, render: (r) => r.tok_out.toLocaleString() },
    { key: "cost", label: "total $", num: true, render: (r) => r.cost.toFixed(2) },
    { key: "avg", label: "$/turn", num: true, render: (r) => r.avg_cost_per_turn.toFixed(3) },
  ];
  return (
    <GlassPanel title="AI usage by model — what a unit of agent work costs"
      note="avg $/turn is your quoting number: estimated turns × avg cost ≈ the AI price of a future card.">
      <Table cols={cols} rows={rows} />
    </GlassPanel>
  );
}

// ---- Work table with AI/human split bars ----

export function WorkPanel({ m }: { m: Metrics }) {
  const t = useTheme();
  const c = cur(m);
  const cards = m.cards ?? [];
  let maxA = 0.01, maxH = 1;
  cards.forEach((x) => { if (x.ai_cost > maxA) maxA = x.ai_cost; if (x.touches > maxH) maxH = x.touches; });
  return (
    <GlassPanel title="Work done">
      <View style={[s.row, { gap: 12, marginBottom: 8 }]}>
        <View style={[s.row, { gap: 4 }]}><View style={[s.sq, { backgroundColor: t.ai }]} /><Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>AI ($)</Text></View>
        <View style={[s.row, { gap: 4 }]}><View style={[s.sq, { backgroundColor: t.human }]} /><Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>human (touch units)</Text></View>
      </View>
      {/* wide table -> horizontal scroll keeps every column readable on phone */}
      <ScrollView horizontal showsHorizontalScrollIndicator={isWeb} contentContainerStyle={{ minWidth: 760 }}>
        <View style={{ flexGrow: 1 }}>
          {/* header */}
          <View style={[s.tr, { borderBottomColor: t.glassBorder, borderBottomWidth: 1, paddingBottom: 6 }]}>
            <Text style={[s.th, { color: t.txtTertiary, flex: 2.4 }]}>card</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1 }]}>lane</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1.3 }]}>model</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1.4, textAlign: "right" }]}>tok in/out</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1, textAlign: "right" }]}>AI $</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 0.8, textAlign: "right" }]}>touch</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1.4 }]}>split</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1, textAlign: "right" }]}>value</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 1, textAlign: "right" }]}>margin</Text>
            <Text style={[s.th, { color: t.txtTertiary, flex: 0.9 }]}>mode</Text>
          </View>
          {cards.length === 0 ? <Empty text="no cards yet" /> : cards.map((x: EconCard) => {
            const margin = x.margin ?? (x.value - x.ai_cost);
            const models = x.models?.length ? x.models.map((mm) => mm.replace("claude-", "")).join(", ") : "-";
            const tin = x.tokens_in ?? 0, tout = x.tokens_out ?? 0;
            const billedVal = x.billed ?? x.value;
            const mode = x.mode ?? "-";
            return (
              <View key={x.id} style={[s.tr, { borderBottomColor: t.borderSubtle, borderBottomWidth: 1, alignItems: "center" }]}>
                <Text numberOfLines={1} style={[s.td, { color: t.txtPrimary, flex: 2.4 }]}>{x.task}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtTertiary, flex: 1 }]}>{x.lane}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtSecondary, flex: 1.3 }]}>{models}</Text>
                <Text numberOfLines={1} style={[s.td, { color: t.txtSecondary, flex: 1.4, textAlign: "right" }]}>{tin.toLocaleString()}/{tout.toLocaleString()}</Text>
                <Text style={[s.td, { color: t.txtSecondary, flex: 1, textAlign: "right" }]}>{x.ai_cost.toFixed(2)}</Text>
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
