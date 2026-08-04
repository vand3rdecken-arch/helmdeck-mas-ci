import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Animated as RNAnimated, Easing, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, { runOnJS, useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";

import { api } from "@/data/client";
import { useBoardFilter } from "@/data/boardfilter";
import type { Track, LaneMove } from "@/data/types";
import { t as tt, useT } from "@/i18n";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { GanttView } from "./board_gantt";
import { LiveThumb } from "./board_live";
import { Chip, Dot, Empty } from "./kit";
import { useActionSheet } from "./action_sheet";

const LANES = ["backlog", "working", "review", "done"] as const;
const isWeb = Platform.OS === "web";

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

function useLaneLabels() {
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
  const router = useRouter();
  const tint = k.status === "needs_you" ? t.ok : k.status === "bounced" ? t.danger : null;
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000 });
  const cards = metrics?.cards ?? [];
  const e = cards.find((c) => c.id === k.id);
  const maxA = Math.max(1, ...cards.map((c) => c.ai_cost));   // cross-card scale so
  const maxH = Math.max(1, ...cards.map((c) => c.touches));   // split bars compare
  const stepM = k.branch?.match(/-s(\d+)$/);
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
      {tint ? (
        <Text style={{ color: tint, fontSize: 11.5, fontWeight: "600" }}>
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
      {sub ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }} numberOfLines={2}>{sub.replace(/\n/g, " ")}</Text> : null}
      {report ? <Text style={{ color: reportColor, fontSize: 11 }} numberOfLines={1}>{report.slice(0, 140)}</Text> : null}
      <View style={[s.row, { flexWrap: "wrap", gap: 6 }]}>
        {k.process ? <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>⛓ {stepM ? tr("board.step", { n: stepM[1] }) : (k.process_title ?? tr("board.process"))}</Text> : null}
        {k.driver && k.driver !== "claude" ? <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>{k.driver}</Text> : null}
        {k.priority && k.priority !== "medium" ? <Chip text={prioLabel(tr, k.priority)} dot={k.priority === "urgent" ? t.danger : t.warn} /> : null}
        {k.status ? <Chip text={statusLabel(tr, k.status)} dot={statusColor(t, k.status)} /> : null}
        {k.due ? <Chip text={tr("board.due", { d: k.due })} /> : null}
        {k.value > 0 ? <Chip text={`€${k.value}`} /> : null}
        {k.ai_cost > 0 ? <Chip text={`AI $${k.ai_cost.toFixed(2)}`} /> : null}
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

function LRow({ k, onOpen, onMove }: { k: Track; onOpen: () => void; onMove: () => void }) {
  const t = useTheme();
  const tr = useT();
  return (
    <Pressable onPress={onOpen} onLongPress={onMove} style={[s.row, { paddingVertical: 7, gap: 8 }]}>
      <Dot color={statusColor(t, k.status)} />
      <Text style={{ color: t.txtTertiary, fontSize: 10.5, width: 96 }} numberOfLines={1}>{k.branch || tr("board.noGit")}</Text>
      <Text style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }} numberOfLines={1}>{k.task}</Text>
      {k.status ? <Text style={{ color: statusColor(t, k.status), fontSize: 10.5 }}>{statusLabel(tr, k.status)}</Text> : null}
      {k.priority && k.priority !== "medium" ? <Text style={{ color: k.priority === "urgent" ? t.danger : t.warn, fontSize: 10.5 }}>{prioLabel(tr, k.priority)}</Text> : null}
      {k.due ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{k.due}</Text> : null}
      {k.value > 0 ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>€{k.value}</Text> : null}
      {k.ai_cost > 0 ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>${k.ai_cost.toFixed(2)}</Text> : null}
      {k.updated ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{k.updated}</Text> : null}
    </Pressable>
  );
}

function LayoutToggle({ layout, onSet }: { layout: string; onSet: (v: string) => void }) {
  const t = useTheme();
  const tr = useT();
  return (
    <View style={{ flexDirection: "row", gap: 6 }}>
      {["board", "list", "timeline"].map((key) => {
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
// test the four column plates in window coordinates, and show an insertion line.
// Drop -> moveLane (lane changed) or reorder (same lane, new position).

type Frame = { x: number; w: number };
type CardCenter = { lane: string; cy: number };

function DraggableCard({
  k, onMoveTarget, onDropCard, onMeasure, children,
}: {
  k: Track;
  onMoveTarget: (x: number, y: number, id: string) => void;
  onDropCard: (id: string, x: number, y: number) => void;
  onMeasure: (id: string, lane: string, cy: number) => void;
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
        onLayout={() => ref.current?.measureInWindow((_x, y, _w, h) => onMeasure(k.id, k.lane || "working", y + h / 2))}
        style={aStyle}
      >
        {children}
      </Animated.View>
    </GestureDetector>
  );
}

function WideKanban({
  tracks, label, qc, onError, onInfo,
}: {
  tracks: Track[];
  label: (l: string) => string;
  qc: QueryClient;
  onError: (m: string) => void;
  onInfo: (m: string | null) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const colFrames = useRef<Record<string, Frame>>({});
  const colRefs = useRef<Record<string, View | null>>({});
  const cardPos = useRef<Record<string, CardCenter>>({});
  const [indicator, setIndicator] = useState<{ lane: string; index: number } | null>(null);

  const byLane = useCallback(
    (lane: string) => tracks.filter((k) => (k.lane || "working") === lane).slice().sort(laneSort),
    [tracks],
  );

  const laneAt = useCallback((x: number): string | null => {
    for (const lane of LANES) {
      const f = colFrames.current[lane];
      if (f && x >= f.x && x <= f.x + f.w) return lane;
    }
    return null;
  }, []);

  const indexAt = useCallback((lane: string, y: number, dragged: string): number => {
    const arr = Object.entries(cardPos.current)
      .filter(([id, v]) => v.lane === lane && id !== dragged)
      .sort((a, b) => a[1].cy - b[1].cy);
    let i = 0;
    for (const [, v] of arr) { if (y > v.cy) i++; else break; }
    return i;
  }, []);

  const onMeasure = useCallback((id: string, lane: string, cy: number) => { cardPos.current[id] = { lane, cy }; }, []);

  const onMoveTarget = useCallback((x: number, y: number, id: string) => {
    const lane = laneAt(x);
    if (!lane) { setIndicator(null); return; }
    setIndicator({ lane, index: indexAt(lane, y, id) });
  }, [laneAt, indexAt]);

  const onDropCard = useCallback(async (id: string, x: number, y: number) => {
    setIndicator(null);
    const lane = laneAt(x);
    const card = tracks.find((k) => k.id === id);
    if (!lane || !card) return;
    try {
      if ((card.lane || "working") !== lane) {
        const res = await api.moveLane(id, lane);
        onInfo(laneVerdict(res, lane));
      } else {
        const ordered = byLane(lane).map((k) => k.id).filter((cid) => cid !== id);
        ordered.splice(indexAt(lane, y, id), 0, id);
        await api.reorder(ordered);
      }
      await qc.invalidateQueries({ queryKey: ["tracks"] });
    } catch (e) { onError(String((e as Error).message)); }
  }, [tracks, byLane, indexAt, laneAt, qc, onError, onInfo]);

  const Ins = () => <View style={{ height: 2, borderRadius: 2, backgroundColor: t.accent, marginVertical: 2 }} />;

  return (
    <View style={{ flexDirection: "row", gap: 14, alignItems: "flex-start" }}>
      {LANES.map((lane) => {
        const inLane = byLane(lane);
        return (
          <View
            key={lane}
            ref={(r) => { colRefs.current[lane] = r; }}
            onLayout={() => colRefs.current[lane]?.measureInWindow((x, _y, w) => { colFrames.current[lane] = { x, w }; })}
            style={s.column}
          >
            {/* web-app lanes are transparent: just a sticky header + floating glass cards */}
            <View style={[s.row, { paddingBottom: 10, paddingHorizontal: 6 }]}>
              <Dot color={laneColor(t, lane)} size={9} />
              <Text style={{ color: t.txtSecondary, fontSize: 12.5, fontWeight: "600", flex: 1 }}>{label(lane)}</Text>
              <View style={{ backgroundColor: t.layer1, borderRadius: 9, paddingHorizontal: 7, paddingVertical: 0.5 }}>
                <Text style={{ color: t.txtTertiary, fontSize: 11.5, fontWeight: "600" }}>{inLane.length}</Text>
              </View>
            </View>
            {inLane.length === 0 ? (
              <>
                {indicator?.lane === lane && indicator.index === 0 ? <Ins /> : null}
                <Empty text={tr("ui.empty")} />
              </>
            ) : (
              inLane.map((k, i) => (
                <React.Fragment key={k.id}>
                  {indicator?.lane === lane && indicator.index === i ? <Ins /> : null}
                  <DraggableCard k={k} onMoveTarget={onMoveTarget} onDropCard={onDropCard} onMeasure={onMeasure}>
                    <Card k={k} onMove={() => {}} />
                  </DraggableCard>
                </React.Fragment>
              ))
            )}
            {indicator?.lane === lane && indicator.index === inLane.length && inLane.length > 0 ? <Ins /> : null}
          </View>
        );
      })}
    </View>
  );
}

export function BoardList({ filter, topInset = 0 }: { filter?: "needs_you"; topInset?: number }) {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const label = useLaneLabels();
  const qc = useQueryClient();
  // Freshness is driven by the global version long-poll (useGlobalStream); this
  // interval is just a slow safety net if that loop errors.
  // While the daemon is gating/merging a card, 20s is far too coarse to feel
  // like feedback — poll hard until the verdict lands, then back off.
  const { data, isLoading, error } = useQuery({
    queryKey: ["tracks"], queryFn: api.tracks,
    refetchInterval: (q) => (Array.isArray(q.state.data)
      && (q.state.data as Track[]).some(isGating) ? 2500 : 20000),
  });
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useState("board");
  const [toast, setToast] = useState<string | null>(null);
  const showToast = useCallback((m: string | null) => {
    if (!m) return;
    setToast(m);
    setTimeout(() => setToast(null), 5200);
  }, []);
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;   // desktop kanban vs phone single-scroll
  const sheet = useActionSheet();

  // Needs tab passes filter="needs_you" (flat list). The Board tab (no prop)
  // takes its filter from the sidebar store: all / archived / client:<name>.
  const storeFilter = useBoardFilter((s) => s.filter);
  const eff = filter ?? storeFilter;
  // Normally Track[]. Over the relay a hiccup or a pairing/pin mismatch
  // (the daemon's 409 "another phone is paired…") comes back as an {error}
  // OBJECT, not an array — `?? []` doesn't catch that, and calling .filter on
  // it white-screened the whole board. Guard the shape and surface the message.
  const rows: Track[] = Array.isArray(data) ? data : [];
  const dataErr = !Array.isArray(data) && data && typeof data === "object"
    ? String((data as { error?: unknown }).error ?? "") : "";
  const shown = rows.filter((k) => {
    if (eff === "needs_you") return (k.status === "needs_you" || k.status === "bounced") && !k.archived;
    if (eff === "archived") return !!k.archived;
    if (eff.startsWith("client:")) return k.client === eff.slice(7) && !k.archived;
    return !k.archived; // "all"
  });

  function onMove(k: Track) {
    sheet.show({
      title: k.task,
      message: tr("board.moveTo"),
      options: LANES.filter((l) => l !== k.lane).map((l) => ({
        label: "→ " + label(l),
        onPress: async () => {
          setBusy(true);
          try { const res = await api.moveLane(k.id, l); showToast(laneVerdict(res, l)); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
          catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
          finally { setBusy(false); }
        },
      })),
    });
  }

  const nextUp = (data ?? [])
    .filter((k) => k.lane !== "done" && !k.archived && (k.status === "needs_you" || k.status === "bounced" || (k.up_next && k.lane === "backlog")))
    .sort((a, b) => prioOrd(a.priority) - prioOrd(b.priority) || (a.due ?? "9999").localeCompare(b.due ?? "9999"));

  return (
    <>
    <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, paddingTop: topInset + (wide ? 8 : 8),
      paddingBottom: 120, gap: 10, width: "100%", maxWidth: wide ? 1500 : undefined, alignSelf: "center" }}
      refreshControl={undefined}>
      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
      {error || dataErr ? <Text style={{ color: t.danger }}>{dataErr || tr("ui.offline")}</Text> : null}
      {busy ? <ActivityIndicator color={t.accent} /> : null}
      {!filter ? <LayoutToggle layout={layout} onSet={setLayout} /> : null}
      {!filter && nextUp.length > 0 ? (
        <NextUp items={nextUp} onDone={async (k) => {
          try { const res = await api.moveLane(k.id, "done"); showToast(laneVerdict(res, "done") ?? tr("board.stepDone")); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
          catch (e) { Alert.alert(tr("ui.error"), String((e as Error).message)); }
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
        // desktop kanban: four column plates side by side, drag to move/reorder
        <WideKanban tracks={shown} label={label} qc={qc} onError={(m) => Alert.alert(tr("ui.error"), m)} onInfo={showToast} />
      ) : (
        LANES.map((lane) => {
          const inLane = shown.filter((k) => (k.lane || "working") === lane).slice().sort(laneSort);
          if (layout === "list" && inLane.length === 0) return null;   // list hides empty lanes
          return (
            <View key={lane} style={{ gap: 8 }}>
              <View style={[s.row, { marginTop: 8 }]}>
                <Dot color={laneColor(t, lane)} size={8} />
                <Text style={{ color: t.txtSecondary, fontSize: 13, fontWeight: "600" }}>{label(lane)}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{inLane.length}</Text>
              </View>
              {inLane.length === 0 ? <Empty text={tr("ui.empty")} /> :
                inLane.map((k) => layout === "list"
                  ? <LRow key={k.id} k={k} onOpen={() => router.push(`/card/${k.id}`)} onMove={() => onMove(k)} />
                  : <Card key={k.id} k={k} onMove={onMove} />)}
            </View>
          );
        })
      )}
    </ScrollView>
    {toast ? (
      <View pointerEvents="none" style={{ position: "absolute", left: 0, right: 0, bottom: 24, alignItems: "center" }}>
        <View style={{ maxWidth: 560, backgroundColor: t.surface1, borderColor: t.borderStrong, borderWidth: 1,
          borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10,
          ...(isWeb ? { boxShadow: "0 6px 20px rgba(0,0,0,0.35)" } as any : { elevation: 6 }) }}>
          <Text style={{ color: t.txtPrimary, fontSize: 12.5 }}>{toast}</Text>
        </View>
      </View>
    ) : null}
    {sheet.node}
    </>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  card: { borderRadius: 16, paddingVertical: 11, paddingHorizontal: 12, gap: 7 },
  column: { flex: 1, minWidth: 250, maxWidth: 340, gap: 8, minHeight: 120 },
  task: { fontSize: 13.5, fontWeight: "500", lineHeight: 19 },
  branch: { fontSize: 11, flexShrink: 1 },
  nextup: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 6 },
});
