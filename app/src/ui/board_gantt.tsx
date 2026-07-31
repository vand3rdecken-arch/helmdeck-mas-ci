import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";

import type { Track } from "@/data/types";
import { laneColor, useTheme } from "@/theme";
import { Empty } from "./kit";

const DAY = 86400e3;
const parseTs = (s?: string) => (s ? new Date(s.replace(" ", "T")).getTime() : null);

/** A real Gantt (ported from archive/web views.tsx): a left label column + one
 *  horizontal column per day, a bar per card from created -> last activity
 *  (done cards freeze at acceptance), a due-date diamond, and a "today" marker.
 *  Desktop-first; on mobile the whole grid scrolls horizontally. */
export function GanttView({ tracks, onOpen, wide }: { tracks: Track[]; onOpen: (id: string) => void; wide?: boolean }) {
  const t = useTheme();
  const now = Date.now();

  const rows = tracks
    .filter((k) => !k.archived)
    .map((k) => ({
      k,
      a: parseTs(k.created) ?? now,
      b: (k.lane === "done" ? parseTs(k.updated) : now) ?? now,
      due: k.due ? parseTs(k.due + " 23:59:59") : null,
    }));
  if (rows.length === 0) return <Empty text="Noch keine Arbeit." />;

  let min = Math.min(...rows.map((x) => x.a));
  const max = Math.max(now, ...rows.map((x) => Math.max(x.b, x.due ?? 0)));
  const d0 = new Date(min); d0.setHours(0, 0, 0, 0); min = d0.getTime();
  const days = Math.max(1, Math.ceil((max - min) / DAY));
  const pxday = wide ? Math.max(64, Math.floor(900 / days)) : 56;
  const W = days * pxday;
  const xOf = (ms: number) => Math.round((ms - min) / DAY * pxday);
  const side = wide ? 210 : 130;
  const rowH = 32;

  // group by process (like the web Gantt) so chained cards read together
  const sorted = [...rows].sort((p, q) => {
    const pp = p.k.process ?? "~", pq = q.k.process ?? "~";
    return pp < pq ? -1 : pp > pq ? 1 : p.a - q.a;
  });

  return (
    <View style={{ gap: 8 }}>
      <ScrollView horizontal showsHorizontalScrollIndicator
        style={{ borderWidth: 1, borderColor: t.glassBorder, borderRadius: 12, backgroundColor: t.surface1 + "59" }}>
        <View>
          {/* header: day columns */}
          <View style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
            <View style={{ width: side, paddingHorizontal: 10, justifyContent: "center" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", letterSpacing: 0.6 }}>CARD</Text>
            </View>
            <View style={{ flexDirection: "row", width: W }}>
              {Array.from({ length: days }, (_, i) => {
                const d = new Date(min + i * DAY);
                return (
                  <View key={i} style={{ width: pxday, paddingVertical: 6, borderLeftWidth: 1, borderLeftColor: t.borderSubtle }}>
                    <Text style={{ color: t.txtTertiary, fontSize: 10, textAlign: "center" }}>{d.getMonth() + 1}/{d.getDate()}</Text>
                  </View>
                );
              })}
            </View>
          </View>

          {/* one row per card */}
          {sorted.map((r) => {
            const l = xOf(r.a), w = Math.max(14, xOf(r.b) - l);
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
                    <Text numberOfLines={1} style={{ color: "#fff", fontSize: 9.5, fontWeight: "600" }}>
                      {(r.k.branch || r.k.lane) + (late ? " · overdue" : "")}
                    </Text>
                  </View>
                </View>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
      <Text style={{ color: t.txtTertiary, fontSize: 11 }}>
        Balken = angelegt → letzte Aktivität (Done friert bei Abnahme ein) · blaue Linie = jetzt · ◆ = fällig
      </Text>
    </View>
  );
}
