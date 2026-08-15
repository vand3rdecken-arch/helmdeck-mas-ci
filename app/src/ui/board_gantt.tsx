import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import type { Track } from "@/data/types";
import { t as tt, useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";
import { Empty } from "./kit";

type Theme = ReturnType<typeof useTheme>;
type Tr = ReturnType<typeof useT>;

const DAY = 86400e3;
const parseTs = (s?: string) => (s ? new Date(s.replace(" ", "T")).getTime() : null);
const MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
  .map((m) => `gantt.mon.${m}`);
const LANE_KEY: Record<string, string> = {
  backlog: "lane.backlog", working: "lane.working", review: "lane.review", done: "lane.done",
};
// "pm.weekdays" is the existing Sun..Sat short-name list used by the PM day
// picker (dash_panels.tsx) - reuse it instead of adding a parallel key set.
const dowNames = () => tt("pm.weekdays").split(",");
const fmtDay = (ms: number) => {
  const d = new Date(ms);
  return `${dowNames()[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`;
};

type Zoom = "weeks" | "months" | "quarters";
// pixels-per-day per zoom — like Jira, zooming out packs more time into view so
// you rescale instead of scrolling. A tick (header column) spans one unit.
// "weeks" needs enough width per day to fit a weekday label ("Mon 17")
// without it bleeding into the neighbouring column.
const PXDAY: Record<Zoom, number> = { weeks: 34, months: 5, quarters: 1.7 };
const ZOOMS: Zoom[] = ["weeks", "months", "quarters"];

/** Header ticks (unit columns) for a zoom level. "weeks" ticks one column per
 *  DAY (weekday name + day-of-month, weekend tinted) so the near-term axis
 *  reads like a calendar; "months"/"quarters" still tick per unit. Each tick
 *  carries its pixel left/width. */
function ticks(min: number, max: number, zoom: Zoom, pxday: number) {
  const out: { label: string; sub?: string; weekend?: boolean; left: number; width: number }[] = [];
  const d = new Date(min);
  d.setHours(0, 0, 0, 0);
  if (zoom === "months") d.setDate(1);
  else if (zoom === "quarters") d.setMonth(Math.floor(d.getMonth() / 3) * 3, 1);
  const dn = dowNames();
  let guard = 0;
  while (d.getTime() < max && guard++ < 800) {
    const start = d.getTime();
    const next = new Date(d);
    if (zoom === "weeks") next.setDate(next.getDate() + 1);
    else if (zoom === "months") next.setMonth(next.getMonth() + 1);
    else next.setMonth(next.getMonth() + 3);
    const yy = String(d.getFullYear()).slice(2);
    const dow = d.getDay();
    const label =
      zoom === "weeks" ? dn[dow] :
      zoom === "months" ? (d.getMonth() === 0 ? `${tt(MON[0])} '${yy}` : tt(MON[d.getMonth()])) :
      `Q${Math.floor(d.getMonth() / 3) + 1} '${yy}`;
    out.push({
      label, sub: zoom === "weeks" ? String(d.getDate()) : undefined,
      weekend: zoom === "weeks" && (dow === 0 || dow === 6),
      left: ((start - min) / DAY) * pxday, width: ((next.getTime() - start) / DAY) * pxday,
    });
    d.setTime(next.getTime());
  }
  return out;
}

type Row = { k: Track; a: number; b: number; due: number | null };
type Group = { key: string; title: string; rows: Row[]; min: number; max: number };

/** Cluster consecutive same-process rows (`rows` must already be sorted by
 *  process) so chained cards read together, and compute each group's date
 *  span (earliest start -> latest due/activity) for the aggregate bar and
 *  the vertical view's chronological order. A card with no process (or the
 *  only step of one) gets a group of its own - renders with no header. */
function groupRows(rows: Row[]): Group[] {
  const groups: Group[] = [];
  for (const r of rows) {
    const key = r.k.process ?? `~${r.k.id}`;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.rows.push(r);
    else groups.push({ key, title: r.k.process_title || r.k.process || "", rows: [r], min: 0, max: 0 });
  }
  for (const g of groups) {
    g.min = Math.min(...g.rows.map((r) => r.a));
    g.max = Math.max(...g.rows.map((r) => r.due ?? r.b));
  }
  return groups;
}

function groupProgress(g: Group) {
  const done = g.rows.filter((r) => r.k.lane === "done");
  return { done: done.length, total: g.rows.length };
}

function Pill({ on, label, onPress, t }: { on: boolean; label: string; onPress: () => void; t: Theme }) {
  return (
    <Pressable onPress={onPress}
      style={{ backgroundColor: on ? t.accent + "29" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
        borderWidth: 1, borderRadius: 6, paddingHorizontal: 11, paddingVertical: 4 }}>
      <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 11.5, fontWeight: "500" }}>{label}</Text>
    </Pressable>
  );
}

/** Jira-style timeline (ported/extended from archive/web views.tsx): a left
 *  label column + a time axis you can zoom (weeks / months / quarters), a bar
 *  per card from created -> last activity (done cards freeze at acceptance), a
 *  due-date diamond, and a "today" marker. A "Vertikal" toggle swaps the whole
 *  axis for a plain chronological scroll (VerticalTimeline) - no zoom level
 *  hides part of the roadmap, so the whole thing is visible at once. */
export function GanttView({ tracks, onOpen, wide }: { tracks: Track[]; onOpen: (id: string) => void; wide?: boolean }) {
  const t = useTheme();
  const tr = useT();
  const [zoom, setZoom] = React.useState<Zoom>("weeks");
  const [collapsed, setCollapsed] = React.useState<Record<string, boolean>>({});
  const [hideDone, setHideDone] = React.useState(false);
  const [vertical, setVertical] = React.useState(false);
  const now = Date.now();

  const rows: Row[] = (hideDone ? tracks.filter((k) => k.lane !== "done") : tracks)
    .map((k) => ({
      k,
      a: parseTs(k.created) ?? now,
      b: (k.lane === "done" ? parseTs(k.updated) : now) ?? now,
      due: k.due ? parseTs(k.due + " 23:59:59") : null,
    }));
  if (rows.length === 0) return <Empty text={tr(hideDone ? "gantt.emptyHideDone" : "gantt.empty")} />;

  // group by process (like the web Gantt) so chained cards read together
  const sorted = [...rows].sort((p, q) => {
    const pp = p.k.process ?? "~", pq = q.k.process ?? "~";
    return pp < pq ? -1 : pp > pq ? 1 : p.a - q.a;
  });
  const groups = groupRows(sorted);

  const controls = (
    <View style={{ flexDirection: "row", gap: 6, alignSelf: "flex-start", flexWrap: "wrap" }}>
      {!vertical ? ZOOMS.map((key) => (
        <Pill key={key} on={zoom === key} label={tr(`gantt.zoom.${key}`)} onPress={() => setZoom(key)} t={t} />
      )) : null}
      <Pill on={vertical} label={tr("gantt.vertical")} onPress={() => setVertical((v) => !v)} t={t} />
      <Pill on={hideDone} label={tr("gantt.hideDone")} onPress={() => setHideDone((v) => !v)} t={t} />
    </View>
  );

  if (vertical) {
    return (
      <View style={{ gap: 8 }}>
        {controls}
        <VerticalTimeline groups={groups} collapsed={collapsed} setCollapsed={setCollapsed} onOpen={onOpen} now={now} t={t} tr={tr} />
        <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("gantt.legend")}</Text>
      </View>
    );
  }

  let min = Math.min(...rows.map((x) => x.a));
  const max = Math.max(now, ...rows.map((x) => Math.max(x.b, x.due ?? 0))) + DAY;
  const d0 = new Date(min); d0.setHours(0, 0, 0, 0); min = d0.getTime();
  const pxday = PXDAY[zoom];
  const cols = ticks(min, max, zoom, pxday);
  const W = Math.max(1, ...cols.map((c) => c.left + c.width));
  const xOf = (ms: number) => Math.round(((ms - min) / DAY) * pxday);
  const side = wide ? 210 : 130;
  const rowH = 32;
  const headH = zoom === "weeks" ? 34 : 28;

  return (
    <View style={{ gap: 8 }}>
      {controls}

      <ScrollView horizontal showsHorizontalScrollIndicator
        style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 12, backgroundColor: t.surface1 }}>
        <View>
          {/* header: unit columns */}
          <View style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.borderSubtle }}>
            <View style={{ width: side, paddingHorizontal: 10, justifyContent: "center" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.6 }}>{tr("gantt.card")}</Text>
            </View>
            <View style={{ width: W, height: headH }}>
              {cols.map((c, i) => (
                <View key={i} style={{ position: "absolute", left: c.left, width: c.width, top: 0, bottom: 0,
                  borderLeftWidth: 1, borderLeftColor: t.borderSubtle, justifyContent: "center", alignItems: "center",
                  overflow: "hidden", backgroundColor: c.weekend ? t.surface2 : "transparent" }}>
                  <Text style={{ color: t.txtTertiary, fontSize: 9, textAlign: "center" }} numberOfLines={1}>{c.label}</Text>
                  {c.sub ? <Text style={{ color: t.txtSecondary, fontSize: 10.5, fontWeight: "600", textAlign: "center" }} numberOfLines={1}>{c.sub}</Text> : null}
                </View>
              ))}
            </View>
          </View>

          {/* one row per card, clustered into collapsible process groups. Rows
              have no fixed height: the task title wraps in full (no "..." -
              a truncated card name is exactly what reads as unreadable), so
              the row grows to fit it and the bar/diamond re-center via the
              timeline box's own justifyContent instead of a pixel offset. */}
          {groups.map((g) => {
            const multi = g.rows.length > 1;
            const isCollapsed = multi && (collapsed[g.key] ?? true);
            const prog = groupProgress(g);
            const gl = xOf(g.min);
            const gw = Math.max(8, xOf(g.max) - gl);
            return (
              <React.Fragment key={g.key}>
                {multi ? (
                  <Pressable onPress={() => setCollapsed((c) => ({ ...c, [g.key]: !isCollapsed }))}
                    style={{ flexDirection: "row", alignItems: "stretch", minHeight: rowH, borderBottomWidth: 1,
                      borderBottomColor: t.borderSubtle, backgroundColor: t.surface2 }}>
                    <View style={{ width: side, paddingHorizontal: 10, paddingVertical: 6, flexDirection: "row", alignItems: "flex-start", gap: 6 }}>
                      <Text style={{ color: t.txtSecondary, fontSize: 10 }}>{isCollapsed ? "▸" : "▾"}</Text>
                      <Text style={{ color: t.txtPrimary, fontSize: 12, fontWeight: "600", flexShrink: 1 }}>
                        {g.title || tr("gantt.process")}
                      </Text>
                    </View>
                    <View style={{ width: W, minHeight: rowH, justifyContent: "center" }}>
                      <View style={{ position: "absolute", left: xOf(now), top: 0, bottom: 0, width: 1.5, backgroundColor: t.accent }} />
                      <View style={{
                        position: "absolute", left: gl, width: gw, height: 10, borderRadius: 5,
                        backgroundColor: t.txtTertiary + "40",
                      }} />
                      <Text numberOfLines={1} style={{ position: "absolute", left: gl + 6, right: 6, color: t.txtSecondary, fontSize: 9.5, fontWeight: "600" }}>
                        {prog.done}/{prog.total} {tr("gantt.steps")}
                      </Text>
                    </View>
                  </Pressable>
                ) : null}
                {(!multi || !isCollapsed) ? g.rows.map((r) => {
                  const l = xOf(r.a);
                  const w = Math.max(8, xOf(r.b) - l);
                  const late = r.due != null && r.k.lane !== "done" && now > r.due;
                  return (
                    <Pressable key={r.k.id} onPress={() => onOpen(r.k.id)}
                      style={{ flexDirection: "row", alignItems: "stretch", minHeight: rowH, borderBottomWidth: 1,
                        borderBottomColor: t.borderSubtle }}>
                      <View style={{ width: side, paddingHorizontal: 10, paddingLeft: multi ? 22 : 10, paddingVertical: 6, justifyContent: "center" }}>
                        <Text style={{ color: t.txtPrimary, fontSize: 12 }}>{r.k.task}</Text>
                      </View>
                      <View style={{ width: W, minHeight: rowH, justifyContent: "center" }}>
                        {/* today marker */}
                        <View style={{ position: "absolute", left: xOf(now), top: 0, bottom: 0, width: 1.5, backgroundColor: t.accent }} />
                        {/* due-date diamond */}
                        {r.due != null ? (
                          <View style={{
                            position: "absolute", left: xOf(r.due) - 5, width: 10, height: 10,
                            transform: [{ rotate: "45deg" }],
                            backgroundColor: late ? t.danger : t.txtTertiary,
                          }} />
                        ) : null}
                        {/* the bar */}
                        <View style={{
                          position: "absolute", left: l, width: w, height: 16, borderRadius: 5,
                          backgroundColor: laneColor(t, r.k.lane),
                          justifyContent: "center", paddingHorizontal: 6, overflow: "hidden",
                        }}>
                          {w > 44 ? (
                            <Text numberOfLines={1} style={{ color: "#fff", fontSize: 9.5, fontWeight: "600" }}>
                              {(r.k.branch || (LANE_KEY[r.k.lane] ? tr(LANE_KEY[r.k.lane]) : r.k.lane)) + (late ? " · " + tr("gantt.overdue") : "")}
                            </Text>
                          ) : null}
                        </View>
                      </View>
                    </Pressable>
                  );
                }) : null}
              </React.Fragment>
            );
          })}
        </View>
      </ScrollView>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("gantt.legend")}</Text>
    </View>
  );
}

/** "Vertikal" mode: the same process-grouped rows as GanttView, but as a
 *  plain chronological scroll (soonest due date first) instead of a
 *  day-scaled axis - nothing is off-screen behind a zoom level or a
 *  horizontal scroll, so the whole roadmap reads in one vertical pass. */
function VerticalTimeline({ groups, collapsed, setCollapsed, onOpen, now, t, tr }: {
  groups: Group[]; collapsed: Record<string, boolean>;
  setCollapsed: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  onOpen: (id: string) => void; now: number; t: Theme; tr: Tr;
}) {
  const chrono = [...groups].sort((a, b) => a.min - b.min);
  return (
    <View style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 12, backgroundColor: t.surface1, overflow: "hidden" }}>
      {chrono.map((g) => {
        const multi = g.rows.length > 1;
        const isCollapsed = multi && (collapsed[g.key] ?? true);
        const prog = groupProgress(g);
        return (
          <React.Fragment key={g.key}>
            {multi ? (
              <Pressable onPress={() => setCollapsed((c) => ({ ...c, [g.key]: !isCollapsed }))}
                style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10, paddingHorizontal: 12,
                  borderBottomWidth: 1, borderBottomColor: t.borderSubtle, backgroundColor: t.surface2 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 10 }}>{isCollapsed ? "▸" : "▾"}</Text>
                <Text style={{ color: t.txtPrimary, fontSize: 12.5, fontWeight: "600", flex: 1 }}>
                  {g.title || tr("gantt.process")}
                </Text>
                <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{prog.done}/{prog.total} {tr("gantt.steps")}</Text>
              </Pressable>
            ) : null}
            {(!multi || !isCollapsed) ? g.rows.map((r) => {
              const late = r.due != null && r.k.lane !== "done" && now > r.due;
              return (
                <Pressable key={r.k.id} onPress={() => onOpen(r.k.id)}
                  style={{ flexDirection: "row", gap: 10, paddingVertical: 9, paddingHorizontal: 12,
                    paddingLeft: multi ? 26 : 12, borderBottomWidth: 1, borderBottomColor: t.borderSubtle }}>
                  <View style={{ width: 60 }}>
                    <Text style={{ color: late ? t.danger : t.txtTertiary, fontSize: 10.5, fontWeight: "600" }} numberOfLines={1}>
                      {fmtDay(r.due ?? r.a)}
                    </Text>
                  </View>
                  <View style={{ width: 8, alignItems: "center", paddingTop: 3 }}>
                    <View style={{ width: 8, height: 8, borderRadius: 4,
                      backgroundColor: late ? t.danger : laneColor(t, r.k.lane) }} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: t.txtPrimary, fontSize: 12.5 }}>{r.k.task}</Text>
                    <Text style={{ color: t.txtTertiary, fontSize: 10.5, marginTop: 1 }}>
                      {(r.k.branch || (LANE_KEY[r.k.lane] ? tr(LANE_KEY[r.k.lane]) : r.k.lane)) + (late ? " · " + tr("gantt.overdue") : "")}
                    </Text>
                  </View>
                </Pressable>
              );
            }) : null}
          </React.Fragment>
        );
      })}
    </View>
  );
}
