import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import type { Track } from "@/data/types";
import { t as tt, useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";
import { Empty } from "./kit";

const DAY = 86400e3;
const parseTs = (s?: string) => (s ? new Date(s.replace(" ", "T")).getTime() : null);
const MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
  .map((m) => `gantt.mon.${m}`);
const LANE_KEY: Record<string, string> = {
  backlog: "lane.backlog", working: "lane.working", review: "lane.review", done: "lane.done",
};

type Zoom = "weeks" | "months" | "quarters";
// pixels-per-day per zoom — like Jira, zooming out packs more time into view so
// you rescale instead of scrolling. A tick (header column) spans one unit.
const PXDAY: Record<Zoom, number> = { weeks: 18, months: 5, quarters: 1.7 };
const ZOOMS: Zoom[] = ["weeks", "months", "quarters"];

/** Header ticks (unit columns) for a zoom level: week-starts, month-starts, or
 *  quarter-starts between `min` and `max`. Each carries its pixel left/width. */
function ticks(min: number, max: number, zoom: Zoom, pxday: number) {
  const out: { label: string; left: number; width: number }[] = [];
  const d = new Date(min);
  d.setHours(0, 0, 0, 0);
  if (zoom === "weeks") {
    const dow = (d.getDay() + 6) % 7; // back to Monday
    d.setDate(d.getDate() - dow);
  } else if (zoom === "months") {
    d.setDate(1);
  } else {
    d.setMonth(Math.floor(d.getMonth() / 3) * 3, 1);
  }
  let guard = 0;
  while (d.getTime() < max && guard++ < 400) {
    const start = d.getTime();
    const next = new Date(d);
    if (zoom === "weeks") next.setDate(next.getDate() + 7);
    else if (zoom === "months") next.setMonth(next.getMonth() + 1);
    else next.setMonth(next.getMonth() + 3);
    const yy = String(d.getFullYear()).slice(2);
    const label =
      zoom === "weeks" ? `${d.getMonth() + 1}/${d.getDate()}` :
      zoom === "months" ? (d.getMonth() === 0 ? `${tt(MON[0])} '${yy}` : tt(MON[d.getMonth()])) :
      `Q${Math.floor(d.getMonth() / 3) + 1} '${yy}`;
    out.push({ label, left: ((start - min) / DAY) * pxday, width: ((next.getTime() - start) / DAY) * pxday });
    d.setTime(next.getTime());
  }
  return out;
}

/** Jira-style timeline (ported/extended from archive/web views.tsx): a left
 *  label column + a time axis you can zoom (weeks / months / quarters), a bar
 *  per card from created -> last activity (done cards freeze at acceptance), a
 *  due-date diamond, and a "today" marker. */
export function GanttView({ tracks, onOpen, wide }: { tracks: Track[]; onOpen: (id: string) => void; wide?: boolean }) {
  const t = useTheme();
  const tr = useT();
  const [zoom, setZoom] = React.useState<Zoom>("weeks");
  const now = Date.now();

  const rows = tracks
    .map((k) => ({
      k,
      a: parseTs(k.created) ?? now,
      b: (k.lane === "done" ? parseTs(k.updated) : now) ?? now,
      due: k.due ? parseTs(k.due + " 23:59:59") : null,
    }));
  if (rows.length === 0) return <Empty text={tr("gantt.empty")} />;

  let min = Math.min(...rows.map((x) => x.a));
  const max = Math.max(now, ...rows.map((x) => Math.max(x.b, x.due ?? 0))) + DAY;
  const d0 = new Date(min); d0.setHours(0, 0, 0, 0); min = d0.getTime();
  const pxday = PXDAY[zoom];
  const cols = ticks(min, max, zoom, pxday);
  const W = Math.max(1, ...cols.map((c) => c.left + c.width));
  const xOf = (ms: number) => Math.round(((ms - min) / DAY) * pxday);
  const side = wide ? 210 : 130;
  const rowH = 32;

  // group by process (like the web Gantt) so chained cards read together
  const sorted = [...rows].sort((p, q) => {
    const pp = p.k.process ?? "~", pq = q.k.process ?? "~";
    return pp < pq ? -1 : pp > pq ? 1 : p.a - q.a;
  });

  return (
    <View style={{ gap: 8 }}>
      {/* zoom control (Jira-style) */}
      <View style={{ flexDirection: "row", gap: 6, alignSelf: "flex-start" }}>
        {ZOOMS.map((key) => {
          const on = zoom === key;
          return (
            <Pressable key={key} onPress={() => setZoom(key)}
              style={{ backgroundColor: on ? t.accent + "29" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
                borderWidth: 1, borderRadius: 6, paddingHorizontal: 11, paddingVertical: 4 }}>
              <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 11.5, fontWeight: "500" }}>{tr(`gantt.zoom.${key}`)}</Text>
            </Pressable>
          );
        })}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator
        style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 12, backgroundColor: t.surface1 }}>
        <View>
          {/* header: unit columns */}
          <View style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.borderSubtle }}>
            <View style={{ width: side, paddingHorizontal: 10, justifyContent: "center" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.6 }}>{tr("gantt.card")}</Text>
            </View>
            <View style={{ width: W, height: 28 }}>
              {cols.map((c, i) => (
                <View key={i} style={{ position: "absolute", left: c.left, width: c.width, top: 0, bottom: 0,
                  borderLeftWidth: 1, borderLeftColor: t.borderSubtle, justifyContent: "center" }}>
                  <Text style={{ color: t.txtTertiary, fontSize: 10, textAlign: "center" }} numberOfLines={1}>{c.label}</Text>
                </View>
              ))}
            </View>
          </View>

          {/* one row per card */}
          {sorted.map((r) => {
            const l = xOf(r.a), w = Math.max(8, xOf(r.b) - l);
            const late = r.due != null && r.k.lane !== "done" && now > r.due;
            return (
              <Pressable key={r.k.id} onPress={() => onOpen(r.k.id)}
                style={{ flexDirection: "row", alignItems: "center", height: rowH, borderBottomWidth: 1, borderBottomColor: t.borderSubtle }}>
                <View style={{ width: side, paddingHorizontal: 10 }}>
                  <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 12 }}>{r.k.task}</Text>
                </View>
                <View style={{ width: W, height: rowH, justifyContent: "center" }}>
                  {/* today marker */}
                  <View style={{ position: "absolute", left: xOf(now), top: 0, bottom: 0, width: 1.5, backgroundColor: t.accent }} />
                  {/* due-date diamond */}
                  {r.due != null ? (
                    <View style={{
                      position: "absolute", left: xOf(r.due) - 5, top: rowH / 2 - 5, width: 10, height: 10,
                      transform: [{ rotate: "45deg" }], backgroundColor: late ? t.danger : t.txtTertiary,
                    }} />
                  ) : null}
                  {/* the bar */}
                  <View style={{
                    position: "absolute", left: l, width: w, height: 16, borderRadius: 5,
                    backgroundColor: laneColor(t, r.k.lane), justifyContent: "center", paddingHorizontal: 6, overflow: "hidden",
                  }}>
                    {w > 44 ? (
                      <Text numberOfLines={1} style={{ color: "#fff", fontSize: 9.5, fontWeight: "600" }}>
                        {(r.k.branch || (LANE_KEY[r.k.lane] ? tr(LANE_KEY[r.k.lane]) : r.k.lane))
                          + (late ? " · " + tr("gantt.overdue") : "")}
                      </Text>
                    ) : null}
                  </View>
                </View>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("gantt.legend")}</Text>
    </View>
  );
}
