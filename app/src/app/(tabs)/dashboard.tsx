import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { KVRow, Panel, SectionLabel } from "@/ui/kit";

export default function DashboardTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const { data, isLoading, error } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const cap = data?.capacity;
  const tot = data?.totals;
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        Dashboard
      </Text>
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 120, gap: 10 }}>
        {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {cap ? (
          <Panel>
            <SectionLabel text="capacity" />
            <KVRow k="WIP" v={`${cap.wip} / ${cap.wip_limit}`} />
            <KVRow k="Touches heute" v={`${cap.touches_today} / ${cap.touch_budget_day}`} />
            <KVRow k="Headroom" v={`${cap.headroom}`} />
          </Panel>
        ) : null}
        {tot ? (
          <Panel>
            <SectionLabel text="economics" />
            <KVRow k="Value delivered" v={`€${tot.value_delivered.toFixed(2)}`} />
            <KVRow k="AI spend" v={`$${tot.ai_spend.toFixed(2)}`} />
            <KVRow k="Margin" v={`€${tot.margin.toFixed(2)}`} color={tot.margin < 0 ? t.danger : t.ok} />
          </Panel>
        ) : null}
      </ScrollView>
    </View>
  );
}
