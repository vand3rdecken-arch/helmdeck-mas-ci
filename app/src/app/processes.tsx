import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Chip, Empty, Panel, ScreenHeader } from "@/ui/kit";

export default function Processes() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery({ queryKey: ["processes"], queryFn: api.processes });
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Processes" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 8, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data && data.length === 0 ? <Empty text="Keine Prozesse." /> : null}
        {(data ?? []).map((p: any) => (
          <Panel key={p.id}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "500", flex: 1 }}>{p.request ?? p.name ?? p.id}</Text>
              {p.status ? <Chip text={p.status} /> : null}
            </View>
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{(p.steps?.length ?? 0)} Schritte{p.client ? ` · ${p.client}` : ""}</Text>
          </Panel>
        ))}
      </ScrollView>
    </View>
  );
}
