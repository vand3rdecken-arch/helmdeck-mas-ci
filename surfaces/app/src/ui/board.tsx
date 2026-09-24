import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, Animated as RNAnimated, Easing, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, { runOnJS, useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useBoardFilter } from "@/data/boardfilter";
import { cardStation, columnLabel, groupByColumn, renderColumns, useBoards,
  type RenderColumn } from "@/data/boards";
import { useDemo } from "@/data/demo";
import { useHealth } from "@/data/health";
import type { Track, LaneMove } from "@/data/types";
import { t as tt, useT } from "@/i18n";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { fmtPlanPct, fmtTok, planLabel, useAiFlat } from "./billing";
import { GanttView } from "./board_gantt";
import { LiveThumb } from "./board_live";
import { Chip, Dot, Empty } from "./kit";
import { isWeb, useResponsive } from "./responsive";
import { useActionSheet } from "./action_sheet";
import { SignOff } from "./sign_off";
import { SignOffBatch } from "./sign_off_batch";

/** Content-layer card (Apple HIG: don't put Liquid Glass in the content layer —
 *  use an opaque standard surface with a hairline + soft elevation shadow, and
 *  let the aurora show through the *chrome* instead). */
function contentCardStyle(t: ThemeTokens) {
  return isWeb
    ? ({ backgroundColor: t.surface1,
        boxShadow: "0 1px 2px rgba(0,0,0,0.28), 0 6px 18px rgba(0,0,0,0.22)" } as any)
    : { backgroundColor: t.surface1, elevation: 3 };
}

/** Translator signature (useT / t). Helpers take it so they render in the
 *  workspace language without each growing its own hook. */
type TFn = (key: string, vars?: Record<string, string | number>) => string;

// Raw daemon vocabulary -> shared chrome keys. Unknown values fall back to the
// raw string so a new lane/status/priority stays visible instead of blank.
const LANE_KEY: Record<string, string> = {
  backlog: "lane.backlog", working: "lane.working", review: "lane.review", done: "lane.done",
};
const STATUS_KEY: Record<string, string> = {
  queued: "status.queued", running: "status.running", gating: "status.gating",
  needs_you: "status.needsYou", bounced: "status.bounced",
  submitted: "status.submitted", accepted: "status.accepted",
};
const PRIO_KEY: Record<string, string> = {
  urgent: "prio.urgent", high: "prio.high", medium: "prio.medium", low: "prio.low",
};
const statusLabel = (tr: TFn, s?: string) =>
  (s ? (STATUS_KEY[s] ? tr(STATUS_KEY[s]) : s.replace(/_/g, " ")) : "");
const prioLabel = (tr: TFn, p?: string) => (p ? (PRIO_KEY[p] ? tr(PRIO_KEY[p]) : p) : "");

/** A STATION's own name - what an unlabelled column renders as (see
 *  data/boards.ts columnLabel). Boards own their column labels now; this stays
 *  the resolver underneath them, and `policy.lane_labels` stays in the chain
 *  for one release as the PRD specifies: it is what a workspace that renamed a
 *  lane before boards existed still reads on any board whose column the user
 *  never labelled. */
export function useLaneLabels() {
  const tr = useT();
  // /me first: it carries the public UI policy for EVERY role. The dashboard
  // payload strips `settings` for operators, so reading only there left them
  // with raw lane keys while the owner saw the configured labels.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const { data } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 10000 });
  const labels = me?.ui?.lane_labels ?? data?.settings?.policy?.lane_labels ?? {};
  return (lane: string) => labels[lane]
    ?? (LANE_KEY[lane] ? tr(LANE_KEY[lane]) : lane.charAt(0).toUpperCase() + lane.slice(1));
}

function prioOrd(p?: string) { return { urgent: 0, high: 1, medium: 2, low: 3 }[p ?? ""] ?? 2; }

/** Manual board order is data: the daemon's /tracks/reorder writes `rank`, so a
 *  lane sorts by rank first (unranked cards keep their incoming order). */
function laneSort(a: Track, b: Track) {
  return (a.rank ?? 1e9) - (b.rank ?? 1e9)
    || prioOrd(a.priority) - prioOrd(b.priority)
    || (a.due ?? "9999").localeCompare(b.due ?? "9999");
}
const isRunning = (k: Track) => k.status === "running" || k.lane === "working";

/** Two lines of a PM work package, worth reading. The stored body is structured
 *  (NUTZERGESCHICHTE / FERTIG, WENN / …); flattened raw, the ALL-CAPS heads run
 *  into the prose ("NUTZERGESCHICHTE Als Owner… FERTIG, WENN - Die…") and eat
 *  the preview. Drop the heads and lead with the actual user story. */
function descPreview(d?: string) {
  const body = (d ?? "").split("\n").filter((l) => {
    const s = l.trim();
    if (!s) return false;
    return !(s.length <= 40 && s === s.toUpperCase() && /[A-ZÄÖÜ]/.test(s));
  });
  return body.join(" ").replace(/\s+/g, " ").trim();
}
/** The daemon is running this card's gate/merge/deploy right now (backgrounded,
 *  can take minutes). Without a visible cue the board looked frozen. */
const isGating = (k: Track) => k.status === "gating";

/** The daemon's verdict after a lane move (ported from archive/web board.tsx
 *  drop()): Review = preview (gate + merge check), Done = land (merge+deploy).
 *
 *  Review/Done now run in the BACKGROUND (the gate alone is a subprocess with a
 *  600s ceiling), so the move answers {gating:true} and the real verdict lands
 *  on the card, in the chat and by push. Acknowledge the START here rather than
 *  reporting an outcome we don't have yet — the old inline call blocked the
 *  request for minutes and put the only copy of the reason in a 5s toast. */
function laneVerdict(res: LaneMove, lane: string): string | null {
  // The onboarding example card refuses every move off Backlog (it never runs
  // an agent) - surfaced the same way GxP's refusal is, so a curious drag
  // reads as an explanation, not a silent snap-back.
  if (res.example_refused) return res.example_refused;
  // The gate/merge report itself is audit text from the daemon - it travels as
  // a variable and stays in its original wording.
  const heads = () => (res.gate_report ?? []).map((p) => p.split("\n")[0]).join(" | ");
  if (res.gating) {
    return tt(lane === "done" ? "board.verdict.gatingDone" : "board.verdict.gating");
  }
  if (lane === "review") {
    if (res.gate_failed) return tt("board.verdict.gateRed", { why: heads() });
    const k = res.merge_kind;
    const verdict = k === "mergeable" ? tt("board.merge.mergeable")
      : (k === "already_merged" || k === "redundant_uncommitted") ? tt("board.merge.redundant")
      : k === "conflict" ? tt("board.merge.conflict") : tt("board.merge.checked");
    return tt("board.verdict.review", { verdict });
  }
  if (lane === "done") {
    // The daemon can still refuse a landing (GxP: no signature, drifted, or the
    // actor is not an account). Without this the board showed "accepted" for a
    // card that never moved.
    if (res.gxp_refused) return res.gxp_refused;
    if (res.gate_failed) return tt("board.verdict.gateOpen", { why: heads() });
    if (res.merge_failed) {
      const why = (res.merge_report ?? "").split("\n")[0];
      return tt(res.merge_kind === "conflict" ? "board.verdict.mergeConflict" : "board.verdict.cannotLand", { why });
    }
    return res.merge_kind === "merged" ? tt("board.verdict.merged")
      : (res.merge_kind === "already_merged" || res.merge_kind === "redundant_uncommitted") ? tt("board.verdict.redundant")
      : tt("board.accepted");
  }
  return lane === "working" ? tt("board.verdict.dispatched") : lane === "backlog" ? tt("board.verdict.queued") : null;
}

/** A softly pulsing dot — the board's live "this card's agent is running" cue.
 *  Works everywhere (LiveThumb hides itself over the relay the phone uses).
 *  Uses RN's core Animated, NOT reanimated: the enabled React Compiler mangles
 *  reanimated's useAnimatedStyle worklet (crashed with "undefined is not a
 *  function"); the classic Animated loop has no worklet and is immune. */
function RunningPulse({ color }: { color: string }) {
  const o = useRef(new RNAnimated.Value(1)).current;
  useEffect(() => {
    const loop = RNAnimated.loop(RNAnimated.sequence([
      RNAnimated.timing(o, { toValue: 0.28, duration: 750, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      RNAnimated.timing(o, { toValue: 1, duration: 750, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [o]);
  return <RNAnimated.View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: color, opacity: o }} />;
}

function Card({ k, onMove }: { k: Track; onMove: (k: Track) => void }) {
  const t = useTheme();
  const tr = useT();
  const flat = useAiFlat();
  const router = useRouter();
  const tint = k.status === "needs_you" ? t.ok : k.status === "bounced" ? t.danger : null;
  // tap-to-expand for the last-reply/report preview (see below)
  const [subOpen, setSubOpen] = useState(false);
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000 });
  const cards = metrics?.cards ?? [];
  const e = cards.find((c) => c.id === k.id);
  const maxA = Math.max(1, ...cards.map((c) => c.ai_cost));   // cross-card scale so
  const maxH = Math.max(1, ...cards.map((c) => c.touches));   // split bars compare
  // Step number from the card's own field; the branch regex is only a fallback
  // for cards filed before process_step existed (their branches still end in
  // -sN). New branches carry a card-id tail, so the regex alone would silently
  // drop the step badge.
  const stepNo = k.process_step ?? k.branch?.match(/-s(\d+)$/)?.[1];
  const report =
    (k.gate_report && k.gate_report.length) ? "gate: " + k.gate_report.join(" | ") :
    (k.merge_report && !k.gate_report) ? k.merge_report.split("\n")[0] :
    (k.review_report && k.lane === "review") ? k.review_report.split("\n")[0] : null;
  const reportColor = k.gate_failed || k.merge_kind === "conflict" ? t.danger : k.merge_kind === "mergeable" ? t.ok : t.txtTertiary;
  const sub =
    isGating(k) ? tr("board.card.gating") :
    k.lane === "backlog" ? descPreview(k.description) :
    k.status === "running" ? null :
    (k.lane === "working" && k.last_reply) ? k.last_reply :
    (k.lane === "review" && k.last_reply) ? tr("board.card.delivered", { text: k.last_reply }) :
    k.lane === "done" ? tr("board.accepted") + (k.updated ? ` · ${k.updated}` : "") : null;

  return (
    <Pressable
      onPress={() => router.push(`/card/${k.id}`)}
      onLongPress={() => onMove(k)}
      style={[s.card, tint ? { backgroundColor: t.surface1 } : contentCardStyle(t), {
        borderColor: tint ? tint + "B3" : t.borderSubtle,
        borderWidth: tint ? 2 : 1,
        ...(tint && isWeb ? { boxShadow: "0 1px 2px rgba(0,0,0,0.28), 0 6px 18px rgba(0,0,0,0.22)" } as any : null),
      }]}
    >
      {/* Visible menu affordance. The card menu used to be LONG-PRESS only,
          which is undiscoverable and unreachable with a mouse - on desktop the
          menu was simply inaccessible. This ⋯ opens the same action sheet on a
          plain tap. A nested Pressable captures the touch, so it does not also
          open the card. */}
      <Pressable onPress={() => onMove(k)} hitSlop={8}
        accessibilityRole="button" accessibilityLabel={tr("board.card.menu")}
        style={{ position: "absolute", top: 4, right: 4, zIndex: 5,
          padding: 6, borderRadius: 8 }}>
        <Ionicons name="ellipsis-horizontal" size={16} color={t.txtTertiary} />
      </Pressable>
      {tint ? (
        <Text style={{ color: tint, fontSize: 11.5, fontWeight: "600", paddingRight: 22 }}>
          {k.status === "needs_you" ? tr("board.card.replyReady") : tr("board.card.bounced")}
        </Text>
      ) : null}
      <View style={s.row}>
        {k.status === "running" ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <RunningPulse color={t.ai} />
            <Text style={{ color: t.ai, fontSize: 11, fontWeight: "700" }}>{tr("status.running")}</Text>
          </View>
        ) : isGating(k) ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <RunningPulse color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "700" }}>{tr("status.gating")}</Text>
          </View>
        ) : null}
        <Chip text={executorLabel(k.mode)} dot={t.ai} />
        <Text style={[s.branch, { color: t.txtTertiary }]} numberOfLines={1}>{k.branch || tr("board.noGit")}</Text>
        {k.turns > 0 ? <Text style={[s.branch, { color: t.txtTertiary }]}>{k.turns}t</Text> : null}
      </View>
      <Text style={[s.task, { color: t.txtPrimary }]} numberOfLines={3}>{k.task}</Text>
      {k.status === "running" ? <LiveThumb trackId={k.id} /> : null}
      {/* Last-reply preview: clamped by default, TAP to expand in place. The
          hard 2-line clamp with flattened newlines made long worker replies
          unreadable on the board (owner report) - and the only alternative was
          opening the card. A nested Pressable (same trick as the ⋯ menu above)
          toggles the clamp without also navigating into the card. */}
      {sub ? (
        <Pressable onPress={() => setSubOpen((v) => !v)} hitSlop={4}>
          <Text style={{ color: t.txtTertiary, fontSize: 11.5 }} numberOfLines={subOpen ? undefined : 2}>
            {subOpen ? sub : sub.replace(/\n/g, " ")}
          </Text>
        </Pressable>
      ) : null}
      {report ? (
        <Pressable onPress={() => setSubOpen((v) => !v)} hitSlop={4}>
          <Text style={{ color: reportColor, fontSize: 11 }} numberOfLines={subOpen ? undefined : 1}>
            {subOpen ? report : report.slice(0, 140)}
          </Text>
        </Pressable>
      ) : null}
      <View style={[s.row, { flexWrap: "wrap", gap: 6 }]}>
        {k.process ? <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>⛓ {stepNo ? tr("board.step", { n: String(stepNo) }) : (k.process_title ?? tr("board.process"))}</Text> : null}
        {k.driver && k.driver !== "claude" ? <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>{k.driver}</Text> : null}
        {k.priority && k.priority !== "medium" ? <Chip text={prioLabel(tr, k.priority)} dot={k.priority === "urgent" ? t.danger : t.warn} /> : null}
        {k.status ? <Chip text={statusLabel(tr, k.status)} dot={statusColor(t, k.status)} /> : null}
        {/* GxP: only rendered for a card in the regulated scope - t.human is the
            "a person did this" token, so the badge reads as a human obligation
            rather than another machine status. */}
        {k.gxp_scope ? (
          <Chip text={k.gxp_signed ? tr("sign.badgeSigned") : tr("sign.badgeNeeds")}
                dot={k.gxp_signed ? t.ok : t.human} />
        ) : null}
        {/* remote device execution: a card running on a team member's own PC.
            t.ai (machine-work token) for the normal "on device" state; t.danger
            when the daemon's read-side hint says the device may be offline, so
            a stuck card is unmistakable at a glance (owner reviews the board). */}
        {k.exec_site && k.exec_site.startsWith("local:") ? (
          <Chip text={k.device_stale ? tr("board.deviceStale") : tr("board.onDevice")}
                dot={k.device_stale ? t.danger : t.ai} />
        ) : null}
        {k.due ? <Chip text={tr("board.due", { d: k.due })} /> : null}
        {k.value > 0 ? <Chip text={`€${k.value}`} /> : null}
        {k.ai_cost > 0 ? <Chip text={flat
          ? planLabel(tr, e?.plan_pct, (k.tokens_in ?? 0) + (k.tokens_out ?? 0))
          : `AI $${k.ai_cost.toFixed(2)}`} /> : null}
        {e && e.touches > 0 ? <Chip text={`${e.touches}t`} /> : null}
        {e?.mode ? <Chip text={tr(e.mode === "auto" ? "board.mode.auto" : "board.mode.assisted")} dot={e.mode === "auto" ? t.ai : t.human} /> : null}
        {k.client ? <Chip text={k.client} /> : null}
      </View>
      {e && (e.ai_cost > 0 || e.touches > 0) ? (
        <View style={{ gap: 2, marginTop: 2 }}>
          <View style={{ height: 3, borderRadius: 2, backgroundColor: t.ai, width: `${Math.max(2, Math.round((100 * e.ai_cost) / maxA))}%` }} />
          <View style={{ height: 3, borderRadius: 2, backgroundColor: t.human, width: `${Math.max(2, Math.round((100 * e.touches) / maxH))}%` }} />
        </View>
      ) : null}
    </Pressable>
  );
}

function NextUp({ items, onDone }: { items: Track[]; onDone: (k: Track) => void }) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const why = (k: Track) =>
    k.status === "bounced" ? tr("board.why.bounced") :
    k.status === "needs_you" ? tr("board.why.needsYou") :
    k.mode === "human" ? tr("board.why.human") : k.mode === "cowork" ? tr("board.why.cowork") : tr("board.why.next");
  return (
    <View style={[s.nextup, { backgroundColor: t.warn + "12", borderColor: t.warn + "66" }]}>
      <Text style={{ color: t.warn, fontSize: 11.5, fontWeight: "700" }}>▸ {tr("board.nextUp")}</Text>
      {items.slice(0, 4).map((k) => (
        <Pressable key={k.id} onPress={() => router.push(`/card/${k.id}`)} style={[s.row, { gap: 8 }]}>
          <Dot color={statusColor(t, k.status)} />
          <Text style={{ color: t.txtPrimary, fontSize: 12.5, flex: 1 }} numberOfLines={1}>{k.task}</Text>
          {k.mode === "human" && k.lane === "backlog" ? (
            <Pressable onPress={() => onDone(k)} hitSlop={6}
              style={{ flexDirection: "row", alignItems: "center", gap: 3, borderWidth: 1, borderColor: t.borderStrong, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 1 }}>
              <Ionicons name="checkmark" size={11} color={t.ok} />
              <Text style={{ color: t.txtSecondary, fontSize: 10.5 }}>{tr("board.markDone")}</Text>
            </Pressable>
          ) : (
            <Text style={{ color: t.warn, fontSize: 10.5, fontWeight: "600" }}>{why(k)}</Text>
          )}
        </Pressable>
      ))}
      {items.length > 4 ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("board.more", { n: items.length - 4 })}</Text> : null}
    </View>
  );
}

/** Basename of a card's `repo`. Machine cards carry a plain FOLDER there (a
 *  machine task's workplace is any directory, e.g. C:\Users\<name>), not a git
 *  repo, so this is a display label only - the filter value stays the full path
 *  because two projects can share a basename. */
const repoName = (p?: string) =>
  (p ?? "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "—";

function ScopeChip({ label, count, active, onPress }: {
  label: string; count: number; active: boolean; onPress: () => void;
}) {
  const t = useTheme();
  return (
    <Pressable onPress={onPress}
      accessibilityRole="button" accessibilityState={{ selected: active }}
      style={{ flexDirection: "row", alignItems: "center", gap: 6,
        backgroundColor: active ? t.accent + "29" : t.surface2,
        borderColor: active ? t.accent + "80" : t.borderSubtle,
        borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
      <Text numberOfLines={1} style={{ color: active ? t.accent : t.txtSecondary,
        fontSize: 12, fontWeight: "500", maxWidth: 170 }}>{label}</Text>
      <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "600" }}>{count}</Text>
    </Pressable>
  );
}

/** Which slice of the cards the lanes render. Lives ON THE BOARD, not only in
 *  the desktop sidebar: that sidebar mounts only when `useResponsive().wide`,
 *  which is `isWeb && width >= 900`, so on the PHONE `useBoardFilter` was
 *  permanently "all" and an archived card had no reachable view at all.
 *
 *  That is the actual reason machine cards read as "missing": the board hides
 *  archived cards (correctly), while Henry's snapshot lists every track
 *  (cells/copilot/copilot.py _snapshot) - so a card the owner had been told
 *  about showed up nowhere, and the repo shown next to it made it look like a
 *  "project" the board was filtered to. There is NO server-side repo filter
 *  (GET /tracks filters on auth.owns_card only) and this does not add one: the
 *  scopes are derived from the cards already in hand.
 *
 *  Hides itself when there is nothing to choose between - a single-repo board
 *  with no archive gets no chrome. */
function ScopeBar({ rows, filter, onSet }: { rows: Track[]; filter: string; onSet: (v: string) => void }) {
  const tr = useT();
  const live = rows.filter((k) => !k.archived);
  const archived = rows.filter((k) => !!k.archived).length;
  const byRepo = new Map<string, number>();
  for (const k of live) byRepo.set(k.repo ?? "", (byRepo.get(k.repo ?? "") ?? 0) + 1);
  // Keep the selected repo listed even after its last live card is archived,
  // otherwise the board goes empty with no chip marked and no way back.
  if (filter.startsWith("repo:") && !byRepo.has(filter.slice(5))) byRepo.set(filter.slice(5), 0);
  const repos = [...byRepo.entries()].sort((a, b) => repoName(a[0]).localeCompare(repoName(b[0])));
  // Same rule for the archive chip, and for the same reason: restoring the LAST
  // archived card while the Archive scope is selected used to make this whole
  // bar disappear - leaving an empty board, no chip marked, and nothing to tap
  // to get out of a scope that now matches nothing. Measured on the real board
  // (ops/tests/shot_archive_scope.py), not reasoned about.
  const onArchive = filter === "archived";
  if (repos.length < 2 && archived === 0 && !onArchive) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      contentContainerStyle={{ flexDirection: "row", gap: 6, paddingVertical: 1 }}>
      <ScopeChip label={tr("board.scope.all")} count={live.length}
        active={filter === "all"} onPress={() => onSet("all")} />
      {repos.length > 1 ? repos.map(([path, n]) => (
        <ScopeChip key={path} label={repoName(path)} count={n}
          active={filter === "repo:" + path} onPress={() => onSet("repo:" + path)} />
      )) : null}
      {archived > 0 || onArchive ? (
        <ScopeChip label={tr("board.scope.archived")} count={archived}
          active={onArchive} onPress={() => onSet("archived")} />
      ) : null}
    </ScrollView>
  );
}

function LayoutToggle({ layout, onSet }: { layout: string; onSet: (v: string) => void }) {
  const t = useTheme();
  const tr = useT();
  return (
    <View style={{ flexDirection: "row", gap: 6 }}>
      {["board", "timeline"].map((key) => {
        const on = layout === key;
        return (
          <Pressable key={key} onPress={() => onSet(key)}
            style={{ backgroundColor: on ? t.accent + "29" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
              borderWidth: 1, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 5 }}>
            <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 12, fontWeight: "500" }}>{tr(`board.layout.${key}`)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---- desktop drag-and-drop kanban --------------------------------------------
// A card is a Pan gesture that only activates after a short hold (so a plain tap
// still opens the card). While dragging we translate it under the finger, hit-
// test the column plates in window coordinates, and show an insertion line.
// Drop -> moveLane (the column's STATION changed) or reorder (same station,
// new position). The columns are the active board's, so their number and their
// stations are data now - nothing below may assume there are four of them.

type Frame = { x: number; w: number };
type CardCenter = { col: string; cy: number };

function DraggableCard({
  k, colId, onMoveTarget, onDropCard, onMeasure, children,
}: {
  k: Track;
  /** The column this card is RENDERED in - the reorder index is measured
   *  within it, so it must be the rendered column and not the card's station
   *  (two columns may show one station). */
  colId: string;
  onMoveTarget: (x: number, y: number, id: string) => void;
  onDropCard: (id: string, x: number, y: number) => void;
  onMeasure: (id: string, colId: string, cy: number) => void;
  children: React.ReactNode;
}) {
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const lifted = useSharedValue(0);
  const ref = useRef<View>(null);

  const pan = Gesture.Pan()
    .activateAfterLongPress(200)
    .onStart(() => { lifted.value = 1; })
    .onUpdate((e) => {
      tx.value = e.translationX; ty.value = e.translationY;
      runOnJS(onMoveTarget)(e.absoluteX, e.absoluteY, k.id);
    })
    .onEnd((e) => { runOnJS(onDropCard)(k.id, e.absoluteX, e.absoluteY); })
    .onFinalize(() => { lifted.value = 0; tx.value = withTiming(0); ty.value = withTiming(0); });

  const aStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: tx.value }, { translateY: ty.value }, { scale: lifted.value ? 1.03 : 1 }],
    zIndex: lifted.value ? 999 : 0,
    opacity: lifted.value ? 0.95 : 1,
  }));

  return (
    <GestureDetector gesture={pan}>
      <Animated.View
        ref={ref}
        onLayout={() => ref.current?.measureInWindow((_x, y, _w, h) => onMeasure(k.id, colId, y + h / 2))}
        style={aStyle}
      >
        {children}
      </Animated.View>
    </GestureDetector>
  );
}

/** The "this column is not on your board" cue. An overflow column is derived
 *  (data/boards.ts renderColumns) and disappears when its last card leaves, so
 *  it has to SAY that - otherwise it reads as a column the user forgot they
 *  made, and they go looking for it in the editor. */
function OverflowMark({ color }: { color: string }) {
  const tr = useT();
  return (
    <View accessibilityLabel={tr("board.overflowHint")}
      style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
      <Ionicons name="eye-off-outline" size={11} color={color} />
    </View>
  );
}

function WideKanban({
  tracks, columns, label, qc, onError, onInfo, onMove, gateDone,
}: {
  tracks: Track[];
  /** The active board's columns PLUS any derived overflow ones. Never
   *  `board.columns` raw - see renderColumns for why that would hide cards. */
  columns: RenderColumn[];
  label: (station: string) => string;
  qc: QueryClient;
  onError: (m: string) => void;
  onInfo: (m: string | null) => void;
  onMove: (k: Track) => void;
  /** GxP: true when the drop was intercepted for a signature instead. */
  gateDone: (k: Track, lane: string) => boolean;
}) {
  const t = useTheme();
  const tr = useT();
  const colFrames = useRef<Record<string, Frame>>({});
  const colRefs = useRef<Record<string, View | null>>({});
  const cardPos = useRef<Record<string, CardCenter>>({});
  const [indicator, setIndicator] = useState<{ col: string; index: number } | null>(null);

  const grouped = useMemo(() => {
    const g = groupByColumn(columns, tracks);
    for (const id of Object.keys(g)) g[id] = g[id].slice().sort(laneSort);
    return g;
  }, [columns, tracks]);

  // A board can hold more columns than fit, so the row scrolls horizontally -
  // which makes every measured frame stale the moment it does. Re-measure on
  // scroll or the drag hit-test silently drops cards into the wrong column.
  const measureAll = useCallback(() => {
    for (const c of columns) {
      colRefs.current[c.id]?.measureInWindow((x, _y, w) => { colFrames.current[c.id] = { x, w }; });
    }
  }, [columns]);

  /** The column a drop at `x` lands in. Resolves to the column that actually
   *  RENDERS that station's cards (groupByColumn's first-match), so a pointer
   *  over a second column of the same station still promises the truth. */
  const targetAt = useCallback((x: number): RenderColumn | null => {
    for (const c of columns) {
      const f = colFrames.current[c.id];
      if (f && x >= f.x && x <= f.x + f.w) {
        return columns.find((h) => h.station === c.station) ?? c;
      }
    }
    return null;
  }, [columns]);

  const indexAt = useCallback((colId: string, y: number, dragged: string): number => {
    const arr = Object.entries(cardPos.current)
      .filter(([id, v]) => v.col === colId && id !== dragged)
      .sort((a, b) => a[1].cy - b[1].cy);
    let i = 0;
    for (const [, v] of arr) { if (y > v.cy) i++; else break; }
    return i;
  }, []);

  const onMeasure = useCallback((id: string, colId: string, cy: number) => { cardPos.current[id] = { col: colId, cy }; }, []);

  const onMoveTarget = useCallback((x: number, y: number, id: string) => {
    const col = targetAt(x);
    if (!col) { setIndicator(null); return; }
    setIndicator({ col: col.id, index: indexAt(col.id, y, id) });
  }, [targetAt, indexAt]);

  const onDropCard = useCallback(async (id: string, x: number, y: number) => {
    setIndicator(null);
    const col = targetAt(x);
    const card = tracks.find((k) => k.id === id);
    if (!col || !card) return;
    // The drag gesture is REDIRECTED, not forbidden. Taking away a gesture that
    // worked yesterday is worse UX than translating it - the drop opens the
    // sign-off dialog instead of moving the card.
    if (gateDone(card, col.station)) return;
    try {
      if (cardStation(card) !== col.station) {
        // THE COLUMN IS A VIEW, THE STATION IS THE WORKFLOW. A drop translates
        // to move_lane(station) and to nothing else, so a card dragged through
        // somebody's custom column runs the exact same rails as always -
        // including the gate on review entry, the merge classification and the
        // GxP refusals. A board can never buy its way around them, because a
        // board never gets to name the destination.
        const res = await api.moveLane(id, col.station);
        onInfo(laneVerdict(res, col.station));
      } else {
        const ordered = (grouped[col.id] ?? []).map((k) => k.id).filter((cid) => cid !== id);
        ordered.splice(indexAt(col.id, y, id), 0, id);
        await api.reorder(ordered);
      }
      await qc.invalidateQueries({ queryKey: ["tracks"] });
    } catch (e) { onError(String((e as Error).message)); }
  }, [tracks, grouped, indexAt, targetAt, qc, onError, onInfo, gateDone]);

  const Ins = () => <View style={{ height: 2, borderRadius: 2, backgroundColor: t.accent, marginVertical: 2 }} />;

  return (
    // contentContainerStyle flexGrow:1 keeps a four-column board filling the
    // width exactly as it did before boards existed; a wider board scrolls
    // instead of squeezing its columns below the readable minimum.
    <ScrollView horizontal showsHorizontalScrollIndicator={false}
      onScroll={measureAll} scrollEventThrottle={16}
      contentContainerStyle={{ flexGrow: 1, flexDirection: "row", gap: 14, alignItems: "flex-start" }}>
      {columns.map((col) => {
        const inCol = grouped[col.id] ?? [];
        return (
          <View
            key={col.id}
            ref={(r) => { colRefs.current[col.id] = r; }}
            onLayout={() => colRefs.current[col.id]?.measureInWindow((x, _y, w) => { colFrames.current[col.id] = { x, w }; })}
            style={s.column}
          >
            {/* web-app lanes are transparent: just a sticky header + floating glass cards */}
            <View style={[s.row, { paddingBottom: 10, paddingHorizontal: 6 }]}>
              <Dot color={laneColor(t, col.station)} size={9} />
              <Text numberOfLines={1}
                style={{ color: col.overflow ? t.txtTertiary : t.txtSecondary,
                  fontSize: 12.5, fontWeight: "600", flex: 1 }}>
                {columnLabel(col, label)}
              </Text>
              {col.overflow ? <OverflowMark color={t.txtTertiary} /> : null}
              <View style={{ backgroundColor: t.layer1, borderRadius: 9, paddingHorizontal: 7, paddingVertical: 0.5 }}>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5, fontWeight: "600" }}>{inCol.length}</Text>
              </View>
            </View>
            {inCol.length === 0 ? (
              <>
                {indicator?.col === col.id && indicator.index === 0 ? <Ins /> : null}
                <Empty text={tr("ui.empty")} />
              </>
            ) : (
              inCol.map((k, i) => (
                <React.Fragment key={k.id}>
                  {indicator?.col === col.id && indicator.index === i ? <Ins /> : null}
                  <DraggableCard k={k} colId={col.id} onMoveTarget={onMoveTarget} onDropCard={onDropCard} onMeasure={onMeasure}>
                    {/* real onMove, not a no-op: the ⋯ menu button inside the
                        card needs it, and long-press is unreachable with a mouse
                        on desktop (the card menu was inaccessible there). */}
                    <Card k={k} onMove={onMove} />
                  </DraggableCard>
                </React.Fragment>
              ))
            )}
            {indicator?.col === col.id && indicator.index === inCol.length && inCol.length > 0 ? <Ins /> : null}
          </View>
        );
      })}
    </ScrollView>
  );
}

/** Shown when the board can't reach a daemon. HelmDeck is a companion app, so
 *  "offline" is also what every first-time visitor sees before pairing — the
 *  one place where offering the demo actually helps instead of nagging. */
function DemoInvite() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const enable = useDemo((s) => s.enable);
  return (
    <View style={{ backgroundColor: t.surface1, borderWidth: 1, borderColor: t.borderSubtle,
      borderRadius: 14, padding: 16, gap: 10, marginTop: 6 }}>
      <Text style={{ color: t.txtSecondary, fontSize: 13, lineHeight: 19 }}>{tr("demo.ctaHint")}</Text>
      <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
        <Pressable
          onPress={() => { enable(); qc.invalidateQueries(); }}
          style={{ backgroundColor: t.accent, borderRadius: 11, paddingHorizontal: 16, paddingVertical: 10 }}>
          <Text style={{ color: "#fff", fontSize: 13.5, fontWeight: "600" }}>{tr("demo.cta")}</Text>
        </Pressable>
        <Pressable
          onPress={() => router.push("/scan" as never)}
          style={{ backgroundColor: t.surface2, borderWidth: 1, borderColor: t.borderSubtle,
            borderRadius: 11, paddingHorizontal: 16, paddingVertical: 10 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "600" }}>{tr("demo.pairInstead")}</Text>
        </Pressable>
      </View>
    </View>
  );
}

export function BoardList({ filter, topInset = 0 }: { filter?: "needs_you"; topInset?: number }) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const label = useLaneLabels();
  // WHICH board is drawn (accounts-boards-prd phase 2). Falls back to the four
  // stations when /me carries no boards - an older daemon or the demo fixture -
  // so this screen never depends on the feature being there.
  const { active } = useBoards();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  // Freshness is driven by the global version long-poll (useGlobalStream); this
  // interval is just a slow safety net if that loop errors.
  // While the daemon is gating/merging a card, 20s is far too coarse to feel
  // like feedback — poll hard until the verdict lands, then back off.
  // No timer (2026-09-24): every writer of this data moves the daemon's `v`,
  // and a moved `v` reaches the phone as a pushed event (or the long-poll)
  // that invalidates every query - app/_layout.tsx useGlobalStream. A timer
  // here only re-asked what the daemon would have said anyway, and every
  // ask was a Cloudflare request (the 2026-09-23 rate limit).
  // The gate verdict is a track write too, so it arrives as an event the moment
  // it lands - sooner than the 2.5 s poll that used to wait for it.
  const { data, isLoading, error } = useQuery({
    queryKey: ["tracks"], queryFn: api.tracks,
  });
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useState("board");
  const [toast, setToast] = useState<string | null>(null);
  const showToast = useCallback((m: string | null) => {
    if (!m) return;
    setToast(m);
    setTimeout(() => setToast(null), 5200);
  }, []);
  const { wide } = useResponsive();   // desktop kanban vs phone single-scroll
  const sheet = useActionSheet();
  // GxP: a card in the regulated scope cannot just be moved to done - it needs
  // a signature first. ONE gate for all four entry points below (pill, move
  // sheet, drag, card detail has its own), so no path can forget it.
  const [signing, setSigning] = useState<Track | null>(null);
  // Batch sign-off: a selection mode over the cards that are IN SCOPE and
  // still unsigned. Only offered when there is more than one - a "select" chip
  // above a single card is noise.
  const [picking, setPicking] = useState<Set<string> | null>(null);
  const [batch, setBatch] = useState<Track[] | null>(null);
  /** Returns true when the move was intercepted and a signature is being taken
   *  instead. Callers do nothing further in that case. */
  const gateDone = useCallback((k: Track, lane: string) => {
    if (lane !== "done" || !k.gxp_scope) return false;
    setSigning(k);
    return true;
  }, []);

  // Needs tab passes filter="needs_you" (flat list). The Board tab (no prop)
  // takes its filter from the shared store: all / archived / client:<name> /
  // repo:<path> - written by the desktop sidebar AND by ScopeBar, which is the
  // only writer the phone has (the sidebar is web-and-wide-only).
  const storeFilter = useBoardFilter((s) => s.filter);
  const setStoreFilter = useBoardFilter((s) => s.setFilter);
  const eff = filter ?? storeFilter;
  // Normally Track[]. Over the relay a hiccup or a pairing/pin mismatch
  // (the daemon's 409 "another phone is paired…") comes back as an {error}
  // OBJECT, not an array — `?? []` doesn't catch that, and calling .filter on
  // it white-screened the whole board. Guard the shape and surface the message.
  const rows: Track[] = Array.isArray(data) ? data : [];
  const dataErr = !Array.isArray(data) && data && typeof data === "object"
    ? String((data as { error?: unknown }).error ?? "") : "";
  // Offer the sample board wherever the board is UNUSABLE with nothing to show:
  // hard-offline (health store) OR any query error OR an error payload. The
  // health store alone is too narrow — a reachable-but-unauthenticated daemon
  // (401, e.g. an emulator hitting 10.0.2.2) round-trips fine so health stays
  // "ok", yet the board is just as empty and unpaired as a first-launch tester's.
  const offline = useHealth((s) => s.status === "offline");
  const demoActive = useDemo((s) => s.active);
  const showDemoInvite = !filter && !demoActive && rows.length === 0 && !isLoading
    && (offline || !!error || !!dataErr);
  const shown = rows.filter((k) => {
    if (eff === "needs_you") return (k.status === "needs_you" || k.status === "bounced") && !k.archived;
    if (eff === "archived") return !!k.archived;
    if (eff.startsWith("client:")) return k.client === eff.slice(7) && !k.archived;
    // repo scope: the card's own workplace path (machine cards carry a plain
    // folder here). Client-side only - /tracks never filtered by repo.
    if (eff.startsWith("repo:")) return (k.repo ?? "") === eff.slice(5) && !k.archived;
    return !k.archived; // "all"
  });
  // The columns actually drawn: the active board's, plus a derived overflow
  // column for any station that holds cards this board does not show. Computed
  // over `shown` (the filtered set) rather than every row, so the invariant is
  // about what this screen claims to display - a card hidden by the Archive
  // filter is not "invisible", it is filtered.
  const columns = useMemo(() => renderColumns(active, shown), [active, shown]);
  // Moving from the ⋯ sheet targets a STATION, offered under the board's own
  // wording. Deduped by station: two columns showing one station are one
  // destination, and listing it twice would read as two different places.
  const moveTargets = useMemo(() => {
    const seen = new Set<string>();
    return columns.filter((c) => !seen.has(c.station) && seen.add(c.station));
  }, [columns]);

  function onMove(k: Track) {
    sheet.show({
      title: k.task,
      message: tr("board.moveTo"),
      options: moveTargets.filter((c) => c.station !== cardStation(k)).map((c) => ({
        label: "→ " + columnLabel(c, label),
        onPress: async () => {
          const l = c.station;
          if (gateDone(k, l)) return;
          setBusy(true);
          try { const res = await api.moveLane(k.id, l); showToast(laneVerdict(res, l)); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
          catch (e) { showToast(String((e as Error).message)); }
          finally { setBusy(false); }
        },
      })),
    });
  }

  // The Archive chip is not a scope like the repo chips - it is the OTHER
  // half of the board (the slice every other view hides). So it is the one
  // filter under which the board-wide live sections must go quiet: NextUp and
  // the sign-off bar both read `rows` directly and both exclude archived
  // cards, so under "Archiv" they rendered ACTIVE cards (a needs_you machine
  // card sat in the NextUp strip right above the archived lanes) - which reads
  // as "my live card is in the archive", and no lane move could clear it
  // because neither section ever looked at the lane. Owner report 2026-08-27,
  // card 20260827-224828-machine. Repo scopes keep their old behaviour on
  // purpose: "what needs you" IS board-wide across projects.
  const archiveView = !filter && eff === "archived";

  // `rows`, not `data`: over the relay a hiccup answers with an {error} OBJECT,
  // and `data ?? []` does not catch that - .filter on it white-screened the
  // board, the very crash the `rows` guard above was added for. This list
  // deliberately ignores the repo/client scope chips (see above).
  const nextUp = rows
    .filter((k) => k.lane !== "done" && !k.archived && (k.status === "needs_you" || k.status === "bounced" || (k.up_next && k.lane === "backlog")))
    .sort((a, b) => prioOrd(a.priority) - prioOrd(b.priority) || (a.due ?? "9999").localeCompare(b.due ?? "9999"));

  // Cards a batch sign-off could cover: in the regulated scope, resting on
  // review, not signed yet.
  const signable = rows.filter((k) => !archiveView && k.gxp_scope && !k.gxp_signed
    && k.lane === "review" && !k.archived);
  const picked = signable.filter((k) => picking?.has(k.id));

  return (
    <>
    <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, paddingTop: topInset + (wide ? 8 : 8),
      paddingBottom: 120 + insets.bottom, gap: 10, width: "100%", maxWidth: wide ? 1500 : undefined, alignSelf: "center" }}
      refreshControl={undefined}>
      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
      {error || dataErr ? <Text style={{ color: t.danger }}>{dataErr || tr("ui.offline")}</Text> : null}
      {showDemoInvite ? <DemoInvite /> : null}
      {busy ? <ActivityIndicator color={t.accent} /> : null}
      {/* Batch sign-off bar. Only when there is more than one card to sign -
          a "select" affordance above a single card is noise. */}
      {signable.length > 1 ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10,
          borderWidth: 1, borderColor: t.human + "55", backgroundColor: t.human + "12",
          borderRadius: 12, paddingVertical: 8, paddingHorizontal: 12 }}>
          <Ionicons name="shield-checkmark" size={15} color={t.human} />
          <Text style={{ color: t.txtSecondary, fontSize: 12.5, flex: 1 }}>
            {tr("sign.badgeNeeds")} · {signable.length}
          </Text>
          {picking ? (
            <>
              <Pressable onPress={() => setPicking(null)} hitSlop={6}>
                <Text style={{ color: t.txtTertiary, fontSize: 12.5 }}>{tr("sign.batchCancel")}</Text>
              </Pressable>
              <Pressable
                onPress={() => { if (picked.length) setBatch(picked); }}
                disabled={!picked.length} hitSlop={6}
                style={{ backgroundColor: t.human, borderRadius: 8,
                  paddingVertical: 6, paddingHorizontal: 12, opacity: picked.length ? 1 : 0.45 }}>
                <Text style={{ color: "#fff", fontSize: 12.5, fontWeight: "700" }}>
                  {tr("sign.ctaN", { n: String(picked.length) })}
                </Text>
              </Pressable>
            </>
          ) : (
            <Pressable onPress={() => setPicking(new Set())} hitSlop={6}>
              <Text style={{ color: t.human, fontSize: 12.5, fontWeight: "600" }}>
                {tr("sign.batchSelect")}
              </Text>
            </Pressable>
          )}
        </View>
      ) : null}
      {/* While picking, the cards to choose from are listed flat - the kanban
          columns would hide most of them behind a scroll. */}
      {picking ? (
        <View style={{ gap: 6 }}>
          {signable.map((k) => {
            const on = picking.has(k.id);
            return (
              <Pressable key={k.id}
                onPress={() => setPicking((p) => {
                  const n = new Set(p); if (on) n.delete(k.id); else n.add(k.id); return n;
                })}
                accessibilityRole="checkbox" accessibilityState={{ checked: on }}
                style={{ flexDirection: "row", alignItems: "center", gap: 10,
                  borderWidth: 1, borderColor: on ? t.human : t.borderSubtle,
                  backgroundColor: on ? t.human + "14" : t.surface1,
                  borderRadius: 10, padding: 10 }}>
                <Ionicons name={on ? "checkbox" : "square-outline"} size={18}
                          color={on ? t.human : t.txtPlaceholder} />
                <Text style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }} numberOfLines={1}>
                  {k.id} · {k.task}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
      {!filter ? <ScopeBar rows={rows} filter={eff} onSet={setStoreFilter} /> : null}
      {!filter ? <LayoutToggle layout={layout} onSet={setLayout} /> : null}
      {!filter && !archiveView && nextUp.length > 0 ? (
        <NextUp items={nextUp} onDone={async (k) => {
          if (gateDone(k, "done")) return;
          try { const res = await api.moveLane(k.id, "done"); showToast(laneVerdict(res, "done") ?? tr("board.stepDone")); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
          catch (e) { showToast(String((e as Error).message)); }
        }} />
      ) : null}
      {filter === "needs_you" ? (
        shown.length === 0 ? <Empty text={tr("board.emptyNeedsYou")} /> :
          shown.map((k) => <Card key={k.id} k={k} onMove={onMove} />)
      ) : layout === "timeline" ? (
        // Timeline = the old web's day-scaled bar view (created→last activity,
        // today line, due diamonds). No separate "Gantt" tab anymore.
        <GanttView tracks={shown} onOpen={(id) => router.push(`/card/${id}`)} wide={wide} />
      ) : wide && layout === "board" ? (
        // desktop kanban: the board's column plates side by side, drag to move/reorder
        <WideKanban tracks={shown} columns={columns} label={label} qc={qc} onError={showToast} onInfo={showToast} onMove={onMove} gateDone={gateDone} />
      ) : (
        // phone: the same columns, stacked. One grouping function for both
        // layouts, so a card can never be in one column on the desktop and
        // another on the phone.
        (() => {
          const grouped = groupByColumn(columns, shown);
          return columns.map((col) => {
            const inCol = (grouped[col.id] ?? []).slice().sort(laneSort);
            return (
              <View key={col.id} style={{ gap: 8 }}>
                <View style={[s.row, { marginTop: 8 }]}>
                  <Dot color={laneColor(t, col.station)} size={8} />
                  <Text style={{ color: col.overflow ? t.txtTertiary : t.txtSecondary, fontSize: 13, fontWeight: "600" }}>
                    {columnLabel(col, label)}
                  </Text>
                  {col.overflow ? <OverflowMark color={t.txtTertiary} /> : null}
                  <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{inCol.length}</Text>
                </View>
                {inCol.length === 0 ? <Empty text={tr("ui.empty")} /> :
                  inCol.map((k) => <Card key={k.id} k={k} onMove={onMove} />)}
              </View>
            );
          });
        })()
      )}
    </ScrollView>
    {toast ? (
      <View pointerEvents="none" style={{ position: "absolute", left: 0, right: 0, bottom: 24 + insets.bottom, alignItems: "center" }}>
        <View style={{ maxWidth: 560, backgroundColor: t.surface1, borderColor: t.borderStrong, borderWidth: 1,
          borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10,
          ...(isWeb ? { boxShadow: "0 6px 20px rgba(0,0,0,0.35)" } as any : { elevation: 6 }) }}>
          <Text style={{ color: t.txtPrimary, fontSize: 12.5 }}>{toast}</Text>
        </View>
      </View>
    ) : null}
    {sheet.node}
    {batch ? (
      <SignOffBatch
        cards={batch}
        onClose={() => { setBatch(null); setPicking(null); }}
        onSigned={async (msg, landed) => {
          showToast(msg);
          // Signing authorises; the lane machine still verifies each card
          // independently before merging. Sequential, not parallel: each of
          // these runs a gate and a merge into the SAME main, and firing them
          // at once would have them race for it.
          for (const id of landed) {
            try {
              const res = await api.moveLane(id, "done");
              if (res.gxp_refused) showToast(res.gxp_refused);
            } catch (e) { showToast(String((e as Error).message)); }
          }
          await qc.invalidateQueries({ queryKey: ["tracks"] });
        }}
      />
    ) : null}
    {signing ? (
      <SignOff
        card={signing}
        onClose={() => setSigning(null)}
        onSigned={async (msg) => {
          showToast(msg);
          // The signature does NOT accept the card - it authorises the accept.
          // Two steps on purpose (ops/docs/gxp-mode-design.md 2.3): the human
          // decides, the lane machine independently verifies before merging.
          try {
            const res = await api.moveLane(signing.id, "done");
            showToast(laneVerdict(res, "done") ?? tr("board.stepDone"));
          } catch (e) { showToast(String((e as Error).message)); }
          await qc.invalidateQueries({ queryKey: ["tracks"] });
        }}
      />
    ) : null}
    </>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  card: { borderRadius: 16, paddingVertical: 11, paddingHorizontal: 12, gap: 7 },
  // flexGrow (not flex:1) + flexShrink:0: with the pre-boards four columns this
  // still divides the width evenly, but a board with more columns than fit must
  // SCROLL rather than squeeze every column below the readable minimum.
  column: { flexGrow: 1, flexShrink: 0, flexBasis: 250, minWidth: 250, maxWidth: 340, gap: 8, minHeight: 120 },
  task: { fontSize: 13.5, fontWeight: "500", lineHeight: 19 },
  branch: { fontSize: 11, flexShrink: 1 },
  nextup: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 6 },
});
