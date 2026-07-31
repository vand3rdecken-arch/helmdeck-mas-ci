import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useCallback, useRef, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, { runOnJS, useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";

import { api } from "@/data/client";
import { useBoardFilter } from "@/data/boardfilter";
import type { Track } from "@/data/types";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";
import { GanttView } from "./board_gantt";
import { LiveThumb } from "./board_live";
import { Chip, Dot, Empty } from "./kit";

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

function useLaneLabels() {
  const { data } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 10000 });
  const labels = data?.settings?.policy?.lane_labels ?? {};
  return (lane: string) => labels[lane] ?? lane.charAt(0).toUpperCase() + lane.slice(1);
}

function prioOrd(p?: string) { return { urgent: 0, high: 1, medium: 2, low: 3 }[p ?? ""] ?? 2; }

/** Manual board order is data: the daemon's /tracks/reorder writes `rank`, so a
 *  lane sorts by rank first (unranked cards keep their incoming order). */
function laneSort(a: Track, b: Track) { return (a.rank ?? 1e9) - (b.rank ?? 1e9); }
const isRunning = (k: Track) => k.status === "running" || k.lane === "working";

function Card({ k, onMove }: { k: Track; onMove: (k: Track) => void }) {
  const t = useTheme();
  const router = useRouter();
  const tint = k.status === "needs_you" ? t.ok : k.status === "bounced" ? t.danger : null;
  const sub =
    k.lane === "backlog" ? k.description :
    k.status === "running" ? null :
    (k.lane === "working" && k.last_reply) ? k.last_reply :
    (k.lane === "review" && k.last_reply) ? "Geliefert: " + k.last_reply :
    k.lane === "done" ? "Abgenommen" + (k.updated ? ` · ${k.updated}` : "") : null;

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
          {k.status === "needs_you" ? "● Antwort da – tippen" : "● abgelehnt – ansehen"}
        </Text>
      ) : null}
      <View style={s.row}>
        <Chip text={executorLabel(k.mode)} dot={t.ai} />
        <Text style={[s.branch, { color: t.txtTertiary }]} numberOfLines={1}>{k.branch || "(no git)"}</Text>
        {k.turns > 0 ? <Text style={[s.branch, { color: t.txtTertiary }]}>{k.turns}t</Text> : null}
      </View>
      <Text style={[s.task, { color: t.txtPrimary }]} numberOfLines={3}>{k.task}</Text>
      {k.status === "running" ? <LiveThumb trackId={k.id} /> : null}
      {sub ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }} numberOfLines={2}>{sub.replace(/\n/g, " ")}</Text> : null}
      <View style={[s.row, { flexWrap: "wrap", gap: 6 }]}>
        {k.priority && k.priority !== "medium" ? <Chip text={k.priority} dot={k.priority === "urgent" ? t.danger : t.warn} /> : null}
        {k.status ? <Chip text={k.status.replace(/_/g, " ")} dot={statusColor(t, k.status)} /> : null}
        {k.due ? <Chip text={`due ${k.due}`} /> : null}
        {k.ai_cost > 0 ? <Chip text={`AI $${k.ai_cost.toFixed(2)}`} /> : null}
        {k.client ? <Chip text={k.client} /> : null}
      </View>
    </Pressable>
  );
}

function NextUp({ items }: { items: Track[] }) {
  const t = useTheme();
  const router = useRouter();
  const why = (k: Track) =>
    k.status === "bounced" ? "gate abgelehnt - fixen" :
    k.status === "needs_you" ? "Agent braucht dich" :
    k.mode === "human" ? "dein Schritt" : k.mode === "cowork" ? "cowork" : "als Nächstes";
  return (
    <View style={[s.nextup, { backgroundColor: t.warn + "12", borderColor: t.warn + "66" }]}>
      <Text style={{ color: t.warn, fontSize: 11.5, fontWeight: "700" }}>▸ NEXT UP</Text>
      {items.slice(0, 4).map((k) => (
        <Pressable key={k.id} onPress={() => router.push(`/card/${k.id}`)} style={[s.row, { gap: 8 }]}>
          <Dot color={statusColor(t, k.status)} />
          <Text style={{ color: t.txtPrimary, fontSize: 12.5, flex: 1 }} numberOfLines={1}>{k.task}</Text>
          <Text style={{ color: t.warn, fontSize: 10.5, fontWeight: "600" }}>{why(k)}</Text>
        </Pressable>
      ))}
      {items.length > 4 ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>+{items.length - 4} weitere</Text> : null}
    </View>
  );
}

function LRow({ k, onOpen, onMove }: { k: Track; onOpen: () => void; onMove: () => void }) {
  const t = useTheme();
  return (
    <Pressable onPress={onOpen} onLongPress={onMove} style={[s.row, { paddingVertical: 7, gap: 8 }]}>
      <Dot color={statusColor(t, k.status)} />
      <Text style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }} numberOfLines={1}>{k.task}</Text>
      {k.priority && k.priority !== "medium" ? <Text style={{ color: k.priority === "urgent" ? t.danger : t.warn, fontSize: 10.5 }}>{k.priority}</Text> : null}
      {k.ai_cost > 0 ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>${k.ai_cost.toFixed(2)}</Text> : null}
      {k.updated ? <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{k.updated}</Text> : null}
    </Pressable>
  );
}

function LayoutToggle({ layout, onSet }: { layout: string; onSet: (v: string) => void }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", gap: 6 }}>
      {[["board", "Board"], ["list", "Liste"], ["timeline", "Timeline"]].map(([key, lbl]) => {
        const on = layout === key;
        return (
          <Pressable key={key} onPress={() => onSet(key)}
            style={{ backgroundColor: on ? t.accent + "29" : t.surface2, borderColor: on ? t.accent + "80" : t.borderSubtle,
              borderWidth: 1, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 5 }}>
            <Text style={{ color: on ? t.accent : t.txtSecondary, fontSize: 12, fontWeight: "500" }}>{lbl}</Text>
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
  tracks, label, qc, onError,
}: {
  tracks: Track[];
  label: (l: string) => string;
  qc: QueryClient;
  onError: (m: string) => void;
}) {
  const t = useTheme();
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
        await api.moveLane(id, lane);
      } else {
        const ordered = byLane(lane).map((k) => k.id).filter((cid) => cid !== id);
        ordered.splice(indexAt(lane, y, id), 0, id);
        await api.reorder(ordered);
      }
      await qc.invalidateQueries({ queryKey: ["tracks"] });
    } catch (e) { onError(String((e as Error).message)); }
  }, [tracks, byLane, indexAt, laneAt, qc, onError]);

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
                <Empty text="leer" />
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
  const router = useRouter();
  const label = useLaneLabels();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, refetchInterval: 5000 });
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useState("board");
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;   // desktop kanban vs phone single-scroll

  // Needs tab passes filter="needs_you" (flat list). The Board tab (no prop)
  // takes its filter from the sidebar store: all / archived / client:<name>.
  const storeFilter = useBoardFilter((s) => s.filter);
  const eff = filter ?? storeFilter;
  const shown = (data ?? []).filter((k) => {
    if (eff === "needs_you") return k.status === "needs_you" && !k.archived;
    if (eff === "archived") return !!k.archived;
    if (eff.startsWith("client:")) return k.client === eff.slice(7) && !k.archived;
    return !k.archived; // "all"
  });

  function onMove(k: Track) {
    Alert.alert(k.task, "Verschieben nach…", [
      ...LANES.filter((l) => l !== k.lane).map((l) => ({
        text: "→ " + label(l),
        onPress: async () => {
          setBusy(true);
          try { await api.moveLane(k.id, l); await qc.invalidateQueries({ queryKey: ["tracks"] }); }
          catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
          finally { setBusy(false); }
        },
      })),
      { text: "Abbrechen", style: "cancel" as const },
    ]);
  }

  const nextUp = (data ?? [])
    .filter((k) => k.lane !== "done" && (k.status === "needs_you" || k.status === "bounced"))
    .sort((a, b) => prioOrd(a.priority) - prioOrd(b.priority) || (a.due ?? "9999").localeCompare(b.due ?? "9999"));

  return (
    <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, paddingTop: topInset + (wide ? 8 : 8),
      paddingBottom: 120, gap: 10, width: "100%", maxWidth: wide ? 1500 : undefined, alignSelf: "center" }}
      refreshControl={undefined}>
      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
      {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar – läuft HelmDeck?</Text> : null}
      {busy ? <ActivityIndicator color={t.accent} /> : null}
      {!filter ? <LayoutToggle layout={layout} onSet={setLayout} /> : null}
      {!filter && nextUp.length > 0 ? <NextUp items={nextUp} /> : null}
      {filter === "needs_you" ? (
        shown.length === 0 ? <Empty text="Nichts wartet gerade auf dich." /> :
          shown.map((k) => <Card key={k.id} k={k} onMove={onMove} />)
      ) : layout === "timeline" ? (
        // Timeline = the old web's day-scaled bar view (created→last activity,
        // today line, due diamonds). No separate "Gantt" tab anymore.
        <GanttView tracks={shown} onOpen={(id) => router.push(`/card/${id}`)} wide={wide} />
      ) : wide && layout === "board" ? (
        // desktop kanban: four column plates side by side, drag to move/reorder
        <WideKanban tracks={shown} label={label} qc={qc} onError={(m) => Alert.alert("Fehler", m)} />
      ) : (
        LANES.map((lane) => {
          const inLane = shown.filter((k) => (k.lane || "working") === lane).slice().sort(laneSort);
          return (
            <View key={lane} style={{ gap: 8 }}>
              <View style={[s.row, { marginTop: 8 }]}>
                <Dot color={laneColor(t, lane)} size={8} />
                <Text style={{ color: t.txtSecondary, fontSize: 13, fontWeight: "600" }}>{label(lane)}</Text>
                <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{inLane.length}</Text>
              </View>
              {inLane.length === 0 ? <Empty text="leer" /> :
                inLane.map((k) => layout === "list"
                  ? <LRow key={k.id} k={k} onOpen={() => router.push(`/card/${k.id}`)} onMove={() => onMove(k)} />
                  : <Card key={k.id} k={k} onMove={onMove} />)}
            </View>
          );
        })
      )}
    </ScrollView>
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
