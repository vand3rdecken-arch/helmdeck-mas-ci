import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useCellEnabled } from "@/data/cells";
import type { Me } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { CopilotOverlay, useCopilotPanel } from "@/app/chat";
import { ALL_PANELS, ALL_TILES, CapacityPanel, GatesPanel, ModelsPanel, SowPanel, Tiles, TriageFollowUp, TrianglePanel, WorkPanel } from "@/ui/dash_panels";
import { PMStatusPanel } from "@/ui/pm_panel";
import { useResponsive } from "@/ui/responsive";

export default function DashboardTab() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { wide } = useResponsive();
  const { data, isLoading, error } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, refetchInterval: 10000 });
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const isOwner = me?.role === "owner";
  const pmEnabled = useCellEnabled("pm");
  const copilotEnabled = useCellEnabled("copilot");

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        {tr("nav.dashboard")}
      </Text>
      {/* phone: the chat FAB floats at bottom 84-132px, so the last element (the
          customize gear) needs more clearance than desktop to stay tappable */}
      <ScrollView contentContainerStyle={{ padding: wide ? 20 : 12, paddingBottom: wide ? 120 : 170, gap: 12, width: "100%", maxWidth: wide ? 1500 : undefined, alignSelf: "center" }}>
        {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} /> : null}
        {error ? <Text style={{ color: t.danger }}>{tr("ui.offline")}</Text> : null}
        {data ? (
          (() => {
            // OWNER: a very clean overview - only the single planning loop's
            // three-corner triangle (the measured Budget/Timeline/Scope
            // assessment), its follow-ups, and the loop's status + deltas.
            // Every metric panel + the PM controls moved off here (controls ->
            // Settings). OPERATOR keeps the classic all-on metrics view (no
            // triage/settings surface on their payload).
            const defaultRepo = (data as { settings?: { default_repo?: string } })?.settings?.default_repo;
            if (isOwner) {
              return (
                <>
                  <TrianglePanel />
                  <TriageFollowUp m={data} wide={wide} defaultRepo={defaultRepo} />
                  {pmEnabled ? <PMStatusPanel /> : null}
                </>
              );
            }
            const panels = [...ALL_PANELS];
            const tiles = [...ALL_TILES];
            const showCap = panels.includes("capacity");
            const showGates = panels.includes("gates");
            return (
              <>
                <Tiles m={data} wide={wide} tiles={tiles} />
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
      {/* same agent chat as the board: floating button (desktop opens the in-page
          panel over the dimmed dashboard, phone routes to /chat) + the overlay.
          Copilot has no nav.tabs entry to hide (it's a FAB, not a tab), so it
          gates itself directly off the copilot cell flag. */}
      {copilotEnabled ? (
        <>
          <View style={{ position: "absolute", right: 18, bottom: wide ? 24 : 84 }}>
            <Pressable onPress={() => wide ? useCopilotPanel.getState().show() : router.push("/chat")}
              style={{ width: 48, height: 48, borderRadius: 15, backgroundColor: t.surface1, borderWidth: 1, borderColor: t.borderSubtle,
                alignItems: "center", justifyContent: "center",
                ...(Platform.OS === "web" ? { boxShadow: "0 4px 14px rgba(0,0,0,0.3)" } as any : { elevation: 4 }) }}>
              <Ionicons name="chatbubble-ellipses-outline" size={20} color={t.accent} />
            </Pressable>
          </View>
          <CopilotOverlay />
        </>
      ) : null}
    </View>
  );
}
