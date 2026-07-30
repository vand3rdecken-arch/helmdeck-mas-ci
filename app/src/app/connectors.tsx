import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Chip, Empty, Panel, ScreenHeader } from "@/ui/kit";

export default function Connectors() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });

  async function act(name: string, fn: () => Promise<unknown>, ok: string) {
    try { await fn(); await qc.invalidateQueries({ queryKey: ["connectors"] }); Alert.alert(ok); }
    catch (e) { Alert.alert("Fehler", String((e as Error).message)); }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Connectors" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 8, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data && data.length === 0 ? <Empty text="Keine Connectors." /> : null}
        {(data ?? []).map((c: any) => (
          <Panel key={c.name}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "500", flex: 1 }}>{c.name}</Text>
              {c.schedule ? <Chip text={`${c.schedule}m`} /> : null}
            </View>
            {c.last ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{c.last}</Text> : null}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
              <Pressable onPress={() => act(c.name, () => api.runConnector(c.name), "Gestartet")}
                style={{ backgroundColor: t.accent, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 }}>
                <Text style={{ color: "#fff", fontSize: 13 }}>Run</Text>
              </Pressable>
              <Pressable onPress={() => act(c.name, () => api.rollbackConnector(c.name), "Zurückgerollt")}
                style={{ borderWidth: 1, borderColor: t.borderSubtle, borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 }}>
                <Text style={{ color: t.txtSecondary, fontSize: 13 }}>Rollback</Text>
              </Pressable>
            </View>
          </Panel>
        ))}
      </ScrollView>
    </View>
  );
}
