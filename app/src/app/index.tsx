import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { Track } from "@/data/types";
import { executorLabel, laneColor, statusColor, useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

const LANES = ["backlog", "working", "review", "done"] as const;
const LANE_LABEL: Record<string, string> = { backlog: "Backlog", working: "Working", review: "Review", done: "Done" };

/** The desktop chip: a 5px rounded rectangle on surface-2 with a subtle border,
 *  neutral secondary text and an optional coloured status dot. */
function Chip({ text, dot, t }: { text: string; dot?: string; t: ThemeTokens }) {
  return (
    <View style={[s.chip, { backgroundColor: t.surface2, borderColor: t.borderSubtle }]}>
      {dot ? <View style={[s.dot, { backgroundColor: dot }]} /> : null}
      <Text style={[s.chipText, { color: t.txtSecondary }]}>{text}</Text>
    </View>
  );
}

function Card({ track: k, t }: { track: Track; t: ThemeTokens }) {
  return (
    <View style={[s.card, { backgroundColor: t.surface1, borderColor: t.glassBorder }]}>
      <View style={s.row}>
        <Chip text={executorLabel(k.mode)} dot={t.ai} t={t} />
        <Text style={[s.branch, { color: t.txtTertiary }]} numberOfLines={1}>{k.branch || "(no git)"}</Text>
        {k.turns > 0 ? <Text style={[s.branch, { color: t.txtTertiary }]}>{k.turns}t</Text> : null}
      </View>
      <Text style={[s.task, { color: t.txtPrimary }]} numberOfLines={3}>{k.task}</Text>
      <View style={[s.row, { flexWrap: "wrap", gap: 6 }]}>
        {k.priority && k.priority !== "medium" ? <Chip text={k.priority} dot={k.priority === "urgent" ? t.danger : t.warn} t={t} /> : null}
        {k.status ? <Chip text={k.status.replace(/_/g, " ")} dot={statusColor(t, k.status)} t={t} /> : null}
        {k.due ? <Chip text={`due ${k.due}`} t={t} /> : null}
        {k.ai_cost > 0 ? <Chip text={`AI $${k.ai_cost.toFixed(2)}`} t={t} /> : null}
        {k.client ? <Chip text={k.client} t={t} /> : null}
      </View>
    </View>
  );
}

export default function Board() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const { data, isLoading, error } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <ScrollView contentContainerStyle={{ padding: 12, paddingTop: insets.top + 12, paddingBottom: 40, gap: 8 }}>
        <Text style={[s.h1, { color: t.txtPrimary }]}>Board</Text>
        {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
        {error ? <Text style={{ color: t.danger }}>Could not load: {String((error as Error).message)}</Text> : null}
        {data
          ? LANES.map((lane) => {
              const inLane = data.filter((k) => (k.lane || "working") === lane);
              return (
                <View key={lane} style={{ gap: 8 }}>
                  <View style={[s.row, { marginTop: 8 }]}>
                    <View style={[s.dot, { backgroundColor: laneColor(t, lane) }]} />
                    <Text style={[s.lane, { color: t.txtSecondary }]}>{LANE_LABEL[lane]}</Text>
                    <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{inLane.length}</Text>
                  </View>
                  {inLane.map((k) => <Card key={k.id} track={k} t={t} />)}
                </View>
              );
            })
          : null}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  h1: { fontSize: 22, fontWeight: "700" },
  lane: { fontSize: 13, fontWeight: "600" },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 8 },
  task: { fontSize: 15, fontWeight: "500" },
  branch: { fontSize: 11, flexShrink: 1 },
  chip: { flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderRadius: 5, paddingHorizontal: 7, paddingVertical: 2 },
  chipText: { fontSize: 11, fontWeight: "500" },
  dot: { width: 7, height: 7, borderRadius: 4 },
});
