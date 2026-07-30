import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Chip, Empty, Panel, ScreenHeader } from "@/ui/kit";

export default function Recordings() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Recordings" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 8, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data && data.length === 0 ? <Empty text="Keine Aufnahmen." /> : null}
        {(data ?? []).map((r: any) => (
          <Panel key={r.id}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={{ color: t.txtPrimary, fontSize: 14, flex: 1 }} numberOfLines={1}>{r.title ?? r.id}</Text>
              {r.status ? <Chip text={r.status} /> : null}
            </View>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{r.kind ?? ""}{r.steps ? ` · ${r.steps} steps` : ""}</Text>
          </Panel>
        ))}
      </ScrollView>
    </View>
  );
}
