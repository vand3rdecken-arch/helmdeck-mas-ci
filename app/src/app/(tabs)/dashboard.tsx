import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Platform, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useTheme } from "@/theme";
import { CapacityPanel, GatesPanel, ModelsPanel, SowPanel, Tiles, WorkPanel } from "@/ui/dash_panels";

const isWeb = Platform.OS === "web";

export default function DashboardTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data, isLoading, error } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, refetchInterval: 10000 });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        Dashboard
      </Text>
      <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, paddingBottom: 120, gap: 12, width: "100%", maxWidth: wide ? 1500 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
        {error ? <Text style={{ color: t.danger }}>Desktop nicht erreichbar.</Text> : null}
        {data ? (
          <>
            <Tiles m={data} wide={wide} />
            {/* On desktop the two gauges sit side by side; the wide tables stay full width. */}
            {wide ? (
              <View style={{ flexDirection: "row", gap: 12, alignItems: "flex-start" }}>
                <View style={{ flex: 1 }}><CapacityPanel m={data} /></View>
                <View style={{ flex: 1 }}><GatesPanel m={data} /></View>
              </View>
            ) : (
              <>
                <CapacityPanel m={data} />
                <GatesPanel m={data} />
              </>
            )}
            <SowPanel m={data} />
            <ModelsPanel m={data} />
            <WorkPanel m={data} />
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}
