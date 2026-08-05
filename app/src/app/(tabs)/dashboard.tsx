import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Platform, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { Me } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { CapacityPanel, dashPanels, dashTiles, DashCustomize, GatesPanel, ModelsPanel, SowPanel, Tiles, TrianglePanel, WorkPanel } from "@/ui/dash_panels";
import { PMPanel } from "@/ui/pm_panel";

const isWeb = Platform.OS === "web";

export default function DashboardTab() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const wide = isWeb && width >= 900;
  const { data, isLoading, error } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, refetchInterval: 10000 });
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const isOwner = me?.role === "owner";

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        {tr("nav.dashboard")}
      </Text>
      <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, paddingBottom: 120, gap: 12, width: "100%", maxWidth: wide ? 1500 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("ui.offline")}</Text> : null}
        {data ? (
          (() => {
            const panels = dashPanels(data);
            const showCap = panels.includes("capacity");
            const showGates = panels.includes("gates");
            return (
              <>
                {/* triage is the dashboard's FOCUS - first and loud */}
                {isOwner ? <TrianglePanel /> : null}
                {isOwner ? <PMPanel defaultRepo={(data as { settings?: { default_repo?: string } })?.settings?.default_repo} /> : null}
                {isOwner ? <DashCustomize m={data} /> : null}
                <Tiles m={data} wide={wide} tiles={dashTiles(data)} />
                {/* On desktop the two gauges sit side by side; the wide tables stay full width. */}
                {wide && showCap && showGates ? (
                  <View style={{ flexDirection: "row", gap: 12, alignItems: "flex-start" }}>
                    <View style={{ flex: 1 }}><CapacityPanel m={data} /></View>
                    <View style={{ flex: 1 }}><GatesPanel m={data} /></View>
                  </View>
                ) : (
                  <>
                    {showCap ? <CapacityPanel m={data} /> : null}
                    {showGates ? <GatesPanel m={data} /> : null}
                  </>
                )}
                {panels.includes("sows") ? <SowPanel m={data} /> : null}
                {panels.includes("models") ? <ModelsPanel m={data} /> : null}
                {panels.includes("work") ? <WorkPanel m={data} /> : null}
              </>
            );
          })()
        ) : null}
      </ScrollView>
    </View>
  );
}
