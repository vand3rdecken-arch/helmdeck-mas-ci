import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { Empty, Panel, ScreenHeader } from "@/ui/kit";

export default function Sessions() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { data, isLoading, error } = useQuery({ queryKey: ["sessions"], queryFn: api.claudeSessions });
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title="Sessions" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 12, gap: 8, paddingBottom: 40 }}>
        {isLoading ? <ActivityIndicator color={t.accent} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data && data.length === 0 ? <Empty text="Keine Sessions." /> : null}
        {(data ?? []).map((sv: any, i: number) => (
          <Panel key={sv.id ?? i}>
            <Text style={{ color: t.txtPrimary, fontSize: 13.5 }} numberOfLines={2}>{sv.summary ?? sv.title ?? sv.id}</Text>
            {sv.updated ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{sv.updated}</Text> : null}
          </Panel>
        ))}
      </ScrollView>
    </View>
  );
}
