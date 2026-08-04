import React, { useState } from "react";
import { Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

// The git audit trail, drawn with plain Views: the accepted HEAD line on top,
// then every card branch as a lane forking below it, commits as dots on a
// shared day axis. Tap a branch row -> its card; tap a dot -> its commit
// detail (shown below the graph); fork a branch -> a new card. 1:1 with
// archive/web history.

const isWeb = Platform.OS === "web";

export interface Commit { h: string; msg: string; author: string; date: string }
export interface Branch {
  name: string; commits: Commit[]; track: string | null; task: string; lane: string | null; client: string;
}
export interface Hist { head: string; main: Commit[]; branches: Branch[] }

// a dot that was tapped: the commit plus which branch/color it lives on
interface Selected { commit: Commit; branch: string; color: string }

const DAY = 86400e3;
const ROW_H = 40;
const DOT = 10;

function withAlpha(hex: string, a: string) {
  // tokens are #rrggbb; append an 8-bit alpha so we don't need color-mix
  return hex.length === 7 ? hex + a : hex;
}

export function HistoryGraph({ h, onOpenCard, onFork }: {
  h: Hist; onOpenCard: (id: string) => void; onFork?: (track: string, branch: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [selected, setSelected] = useState<Selected | null>(null);
  const shownBranches = h.branches.filter((b) => b.commits.length);
  const all = [...h.main, ...shownBranches.flatMap((b) => b.commits)];
  if (!all.length) {
    return <Text style={{ color: t.txtTertiary, fontSize: 12.5, paddingVertical: 8 }}>{tr("history.noCommits")}</Text>;
  }
  const ts = (c: Commit) => new Date(c.date).getTime();
  const times = all.map(ts);
  let min = Math.min(...times) - DAY / 2;
  const max = Math.max(...times) + DAY;
  const days = Math.max(1, Math.ceil((max - min) / DAY));
  const pxday = Math.max(56, Math.floor(950 / days));
  const W = days * pxday;
  const x = (time: number) => Math.round(((time - min) / DAY) * pxday + pxday / 2);
  const pick = (commit: Commit, branch: string, color: string) => setSelected({ commit, branch, color });

  return (
    <View style={{ gap: 8 }}>
      <View style={{ borderWidth: 1, borderColor: t.glassBorder, borderRadius: 12, overflow: "hidden", backgroundColor: t.surface1 }}>
        <ScrollView horizontal showsHorizontalScrollIndicator style={{ maxWidth: "100%" }}>
          <View>
            {/* day axis header */}
            <View style={{ flexDirection: "row", height: 22, borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
              <View style={{ width: LABEL_W, paddingLeft: 8, justifyContent: "center" }}>
                <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{tr("history.branch")}</Text>
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

            <GraphRow t={t} label={h.head} sub={tr("history.acceptedTruth")} color={t.accent} commits={h.main} x={x} W={W} ts={ts}
              selectedHash={selected?.commit.h} onPickCommit={(c) => pick(c, h.head, t.accent)} />
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
                  selectedHash={selected?.commit.h}
                  onPickCommit={(c) => pick(c, b.name, color)}
                  onPress={b.track ? () => onOpenCard(b.track as string) : undefined}
                  onFork={b.track && onFork ? () => onFork(b.track as string, b.name) : undefined}
                />
              );
            })}
          </View>
        </ScrollView>
      </View>
      {selected ? <CommitDetail t={t} sel={selected} onClose={() => setSelected(null)} /> : null}
    </View>
  );
}

const LABEL_W = 150;

// the tapped commit's metadata, shown inline below the graph
function CommitDetail({ t, sel, onClose }: { t: ThemeTokens; sel: Selected; onClose: () => void }) {
  const tr = useT();
  const { commit: c } = sel;
  return (
    <View style={{ borderWidth: 1, borderColor: t.glassBorder, borderRadius: 12, backgroundColor: t.surface1, padding: 12, gap: 6 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: sel.color }} />
        <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 11, flex: 1 }}>{sel.branch}</Text>
        <Pressable onPress={onClose} hitSlop={8} style={{ paddingHorizontal: 6, paddingVertical: 2 }}>
          <Text style={{ color: t.txtSecondary, fontSize: 13 }}>✕</Text>
        </Pressable>
      </View>
      <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600" }}>{c.msg}</Text>
      <KVRow t={t} k="hash" v={c.h} mono />
      <KVRow t={t} k="author" v={c.author} />
      <KVRow t={t} k="date" v={c.date} />
    </View>
  );
}

function KVRow({ t, k, v, mono }: { t: ThemeTokens; k: string; v: string; mono?: boolean }) {
  return (
    <View style={{ flexDirection: "row", gap: 8 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 11.5, width: 52 }}>{k}</Text>
      <Text selectable style={{
        color: t.txtSecondary, fontSize: 12, flex: 1,
        fontFamily: mono ? (isWeb ? "ui-monospace, monospace" : "monospace") : undefined,
      }}>{v}</Text>
    </View>
  );
}

function GraphRow({
  t, label, sub, color, commits, x, W, ts, onPress, onFork, onPickCommit, selectedHash,
}: {
  t: ThemeTokens; label: string; sub?: string; color: string; commits: Commit[];
  x: (time: number) => number; W: number; ts: (c: Commit) => number;
  onPress?: () => void; onFork?: () => void;
  onPickCommit: (c: Commit) => void; selectedHash?: string;
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
        {onFork ? (
          <Pressable
            onPress={(ev) => { ev.stopPropagation(); onFork(); }}
            hitSlop={6}
            style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 5, paddingHorizontal: 6, paddingVertical: 2 }}
          >
            <Text style={{ color: t.txtSecondary, fontSize: 10 }}>⑂ fork</Text>
          </Pressable>
        ) : null}
      </View>
      <View style={{ width: W, height: ROW_H }}>
        {commits.length > 1 ? (
          <View style={{
            position: "absolute", top: ROW_H / 2 - 1, height: 2,
            backgroundColor: withAlpha(color, "73"),
            left: x(lo), width: Math.max(2, x(hi) - x(lo)),
          }} />
        ) : null}
        {commits.map((c, i) => {
          const on = selectedHash === c.h;
          return (
            <Pressable
              key={c.h + i}
              onPress={(ev) => { ev.stopPropagation(); onPickCommit(c); }}
              hitSlop={6}
              // web: native title tooltip mirrors archive/web history dots
              {...(isWeb ? { title: `${c.h} · ${c.msg}\n${c.author} · ${c.date}` } as any : {})}
              style={{
                position: "absolute", left: x(ts(c)) - DOT / 2, top: ROW_H / 2 - DOT / 2,
                width: DOT, height: DOT, borderRadius: DOT / 2, backgroundColor: color,
                borderWidth: 2, borderColor: on ? t.txtPrimary : t.surface1,
              }}
            />
          );
        })}
      </View>
    </Pressable>
  );
}
