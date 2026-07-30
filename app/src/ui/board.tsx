import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import React, { useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { api } from "@/data/client";
import type { Track } from "@/data/types";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import { Chip, Dot, Empty } from "./kit";

const LANES = ["backlog", "working", "review", "done"] as const;

function useLaneLabels() {
  const { data } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 10000 });
  const labels = data?.settings?.policy?.lane_labels ?? {};
  return (lane: string) => labels[lane] ?? lane.charAt(0).toUpperCase() + lane.slice(1);
}

function prioOrd(p?: string) { return { urgent: 0, high: 1, medium: 2, low: 3 }[p ?? ""] ?? 2; }

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
      style={[s.card, {
        backgroundColor: tint ? tint + "1A" : t.surface1,
        borderColor: tint ? tint + "B3" : t.glassBorder,
        borderWidth: tint ? 2 : 1,
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

function TimelineRows({ tracks, onOpen }: { tracks: Track[]; onOpen: (id: string) => void }) {
  const t = useTheme();
  const items = tracks
    .filter((k) => k.lane !== "done")
    .sort((a, b) => (a.due ?? "9999").localeCompare(b.due ?? "9999") || (a.created ?? "").localeCompare(b.created ?? ""));
  if (items.length === 0) return <Empty text="Nichts terminiert." />;
  return (
    <View style={{ gap: 4 }}>
      {items.map((k) => (
        <Pressable key={k.id} onPress={() => onOpen(k.id)} style={[s.row, { paddingVertical: 7, gap: 8 }]}>
          <Text style={{ color: k.due ? t.human : t.txtTertiary, fontSize: 11, width: 84 }}>{k.due ?? "—"}</Text>
          <Dot color={statusColor(t, k.status)} />
          <Text style={{ color: t.txtPrimary, fontSize: 13, flex: 1 }} numberOfLines={1}>{k.task}</Text>
        </Pressable>
      ))}
    </View>
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

export function BoardList({ filter, topInset = 0 }: { filter?: "needs_you"; topInset?: number }) {
  const t = useTheme();
  const router = useRouter();
  const label = useLaneLabels();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, refetchInterval: 5000 });
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useState("board");

  const shown = (data ?? []).filter((k) => (filter === "needs_you" ? k.status === "needs_you" : true));

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
    <ScrollView contentContainerStyle={{ padding: 12, paddingTop: topInset + 8, paddingBottom: 120, gap: 8 }}
      refreshControl={undefined}>
      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
      {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar – läuft SwarmDeck?</Text> : null}
      {busy ? <ActivityIndicator color={t.accent} /> : null}
      {!filter ? <LayoutToggle layout={layout} onSet={setLayout} /> : null}
      {!filter && nextUp.length > 0 ? <NextUp items={nextUp} /> : null}
      {filter === "needs_you" ? (
        shown.length === 0 ? <Empty text="Nichts wartet gerade auf dich." /> :
          shown.map((k) => <Card key={k.id} k={k} onMove={onMove} />)
      ) : layout === "timeline" ? (
        <TimelineRows tracks={shown} onOpen={(id) => router.push(`/card/${id}`)} />
      ) : (
        LANES.map((lane) => {
          const inLane = shown.filter((k) => (k.lane || "working") === lane);
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
  card: { borderRadius: 12, padding: 12, gap: 8 },
  task: { fontSize: 15, fontWeight: "500" },
  branch: { fontSize: 11, flexShrink: 1 },
  nextup: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 6 },
});
