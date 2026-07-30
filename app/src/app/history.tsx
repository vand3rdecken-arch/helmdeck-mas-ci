import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Empty, ScreenHeader } from "@/ui/kit";

export default function History() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery({ queryKey: ["history"], queryFn: api.gitHistory });
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="History" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 6, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data && data.length === 0 ? <Empty text="Keine Einträge." /> : null}
        {(data ?? []).map((h: any, i: number) => (
          <View key={i} style={{ flexDirection: "row", gap: 8, paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11, width: 70 }}>{h.ts ?? ""}</Text>
            <Text style={{ color: t.txtPrimary, fontSize: 12.5, flex: 1 }}>{h.detail ?? h.kind ?? JSON.stringify(h).slice(0, 80)}</Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
