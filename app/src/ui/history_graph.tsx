import React from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { laneColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

// The git audit trail, drawn with plain Views: the accepted HEAD line on top,
// then every card branch as a lane forking below it, commits as dots on a
// shared day axis. Tap a branch row -> its card. 1:1 with archive/web history.

export interface Commit { h: string; msg: string; author: string; date: string }
export interface Branch {
  name: string; commits: Commit[]; track: string | null; task: string; lane: string | null; client: string;
}
export interface Hist { head: string; main: Commit[]; branches: Branch[] }

const DAY = 86400e3;
const ROW_H = 40;
const DOT = 10;

function withAlpha(hex: string, a: string) {
  // tokens are #rrggbb; append an 8-bit alpha so we don't need color-mix
  return hex.length === 7 ? hex + a : hex;
}

export function HistoryGraph({ h, onOpenCard }: { h: Hist; onOpenCard: (id: string) => void }) {
  const t = useTheme();
  const shownBranches = h.branches.filter((b) => b.commits.length);
  const all = [...h.main, ...shownBranches.flatMap((b) => b.commits)];
  if (!all.length) {
    return <Text style={{ color: t.txtTertiary, fontSize: 12.5, paddingVertical: 8 }}>Noch keine Commits.</Text>;
  }
  const ts = (c: Commit) => new Date(c.date).getTime();
  const times = all.map(ts);
  let min = Math.min(...times) - DAY / 2;
  const max = Math.max(...times) + DAY;
  const days = Math.max(1, Math.ceil((max - min) / DAY));
  const pxday = Math.max(56, Math.floor(950 / days));
  const W = days * pxday;
  const x = (time: number) => Math.round(((time - min) / DAY) * pxday + pxday / 2);

  return (
    <View style={{ borderWidth: 1, borderColor: t.glassBorder, borderRadius: 12, overflow: "hidden", backgroundColor: t.surface1 }}>
      <ScrollView horizontal showsHorizontalScrollIndicator style={{ maxWidth: "100%" }}>
        <View>
          {/* day axis header */}
          <View style={{ flexDirection: "row", height: 22, borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
            <View style={{ width: LABEL_W, paddingLeft: 8, justifyContent: "center" }}>
              <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>branch</Text>
            </View>
            <View style={{ flexDirection: "row", width: W }}>
              {Array.from({ length: days }, (_, i) => {
                const d = new Date(min + i * DAY + DAY / 2);
                return (
                  <Text key={i} style={{ width: pxday, textAlign: "center", color: t.txtTertiary, fontSize: 10 }}>
                    {d.getMonth() + 1}/{d.getDate()}
                  </Text>
                );
              })}
            </View>
          </View>

          <GraphRow t={t} label={h.head} sub="the accepted truth" color={t.accent} commits={h.main} x={x} W={W} ts={ts} />
          {shownBranches.map((b) => {
            const color = laneColor(t, b.lane ?? undefined);
            return (
              <GraphRow
                key={b.name}
                t={t}
                label={b.name}
                sub={b.task || undefined}
                color={color}
                commits={b.commits}
                x={x}
                W={W}
                ts={ts}
                onPress={b.track ? () => onOpenCard(b.track as string) : undefined}
              />
            );
          })}
        </View>
      </ScrollView>
    </View>
  );
}

const LABEL_W = 150;

function GraphRow({
  t, label, sub, color, commits, x, W, ts, onPress,
}: {
  t: ThemeTokens; label: string; sub?: string; color: string; commits: Commit[];
  x: (time: number) => number; W: number; ts: (c: Commit) => number; onPress?: () => void;
}) {
  const times = commits.map(ts);
  const lo = times.length ? Math.min(...times) : 0;
  const hi = times.length ? Math.max(...times) : 0;
  return (
    <Pressable
      onPress={onPress}
      style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: t.glassBorder }}
    >
      <View style={{ width: LABEL_W, paddingHorizontal: 8, paddingVertical: 6, flexDirection: "row", alignItems: "center", gap: 6 }}>
        <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: color }} />
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text numberOfLines={1} style={{ color: t.txtPrimary, fontSize: 12 }}>{label}</Text>
          {sub ? <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 10 }}>{sub}</Text> : null}
        </View>
      </View>
      <View style={{ width: W, height: ROW_H }}>
        {commits.length > 1 ? (
          <View style={{
            position: "absolute", top: ROW_H / 2 - 1, height: 2,
            backgroundColor: withAlpha(color, "73"),
            left: x(lo), width: Math.max(2, x(hi) - x(lo)),
          }} />
        ) : null}
        {commits.map((c, i) => (
          <View
            key={c.h + i}
            style={{
              position: "absolute", left: x(ts(c)) - DOT / 2, top: ROW_H / 2 - DOT / 2,
              width: DOT, height: DOT, borderRadius: DOT / 2, backgroundColor: color,
              borderWidth: 2, borderColor: t.surface1,
            }}
          />
        ))}
      </View>
    </Pressable>
  );
}
