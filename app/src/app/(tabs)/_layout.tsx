import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { type ColorValue, Image, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/data/client";
import { useBoardFilter } from "@/data/boardfilter";
import { useT } from "@/i18n";
import { tokens } from "@/theme/tokens";
import { useSurfaces } from "@/kernel/react";

const t = tokens.dark;
const isWeb = Platform.OS === "web";
const LOGO = require("../../../assets/images/icon.png");

type IconName = keyof typeof Ionicons.glyphMap;
// labelKey / sectionKey are i18n keys, not prose - the nav renders them through
// the translator so the shell speaks the workspace language.
type NavItem = { name: string; labelKey: string; icon: IconName; sectionKey?: string; teamOnly?: boolean };

// Desktop left-sidebar nav (the old web shell): every view is first-class, in
// sections. On phone only the first four are bottom-bar tabs; the rest live
// under "More".
const NAV: NavItem[] = [
  { name: "index", labelKey: "nav.board", icon: "grid-outline" },
  { name: "needs", labelKey: "nav.needsYou", icon: "notifications-outline" },
  { name: "dashboard", labelKey: "nav.dashboard", icon: "stats-chart-outline", teamOnly: true },
  { name: "processes", labelKey: "nav.processes", icon: "git-network-outline", sectionKey: "nav.sectionWorkflow" },
  { name: "recordings", labelKey: "nav.recordings", icon: "videocam-outline" },
  { name: "sessions", labelKey: "nav.sessions", icon: "chatbubbles-outline", teamOnly: true },
  { name: "history", labelKey: "nav.history", icon: "time-outline" },
  { name: "connectors", labelKey: "nav.connectors", icon: "sync-outline", sectionKey: "nav.sectionSetup", teamOnly: true },
  { name: "automation", labelKey: "nav.automation", icon: "git-branch-outline", teamOnly: true },
  { name: "settings", labelKey: "nav.settings", icon: "settings-outline", teamOnly: true },
];
/** Frosted glass bar for the mobile bottom tabs (real backdrop blur). */
function GlassTabBar() {
  return (
    <View style={StyleSheet.absoluteFill}>
      <BlurView intensity={40} tint="dark" style={StyleSheet.absoluteFill} />
      <View style={[StyleSheet.absoluteFill, { backgroundColor: t.canvas + "66", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.glassBorder }]} />
    </View>
  );
}

/** Desktop left sidebar — the old web app's nav shell: the HelmDeck monogram +
 *  wordmark, then sectioned nav items with a left accent bar on the active one.
 *  Real glass (blur 34 / saturate 1.8) so the aurora backdrop refracts through. */
function Sidebar({ state, navigation }: any) {
  const tr = useT();
  const activeName = state.routes[state.index]?.name;
  const filter = useBoardFilter((s) => s.filter);
  const setFilter = useBoardFilter((s) => s.setFilter);
  const { data: tracks } = useQuery({ queryKey: ["tracks"], queryFn: api.tracks, staleTime: 5000 });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const clients = Object.entries(
    (tracks ?? []).reduce((acc: Record<string, number>, k) => {
      if (k.client && !k.archived) acc[k.client] = (acc[k.client] ?? 0) + 1;
      return acc;
    }, {}),
  ).sort((a, b) => a[0].localeCompare(b[0]));

  const FilterRow = ({ label, value, count }: { label: string; value: string; count?: number }) => {
    const active = activeName === "index" && filter === value;
    const color = active ? t.txtPrimary : t.txtSecondary;
    return (
      <Pressable
        onPress={() => { setFilter(value); navigation.navigate("index"); }}
        style={[styles.navitem, { backgroundColor: active ? t.accent + "1F" : "transparent" }]}
      >
        {active ? <View style={[styles.accentBar, { backgroundColor: t.accent }]} /> : null}
        <Text numberOfLines={1} style={{ color, fontSize: 13, flex: 1 }}>{label}</Text>
        {count != null ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{count}</Text> : null}
      </Pressable>
    );
  };

  return (
    <View style={[styles.side, { backgroundColor: t.glass, borderRightColor: t.glassBorder },
      ({ backdropFilter: "blur(34px) saturate(1.8)", WebkitBackdropFilter: "blur(34px) saturate(1.8)" } as any)]}>
      <View style={styles.logo}>
        <Image source={LOGO} style={styles.logoImg} />
        <Text style={{ color: t.txtPrimary, fontWeight: "700", fontSize: 14.5 }}>HelmDeck</Text>
      </View>
      <ScrollView showsVerticalScrollIndicator={false} style={{ flex: 1 }}>
        {NAV.filter((item) => !(item.teamOnly && me?.role === "client")).map((item) => {
          const active = activeName === item.name;
          const color = active ? t.txtPrimary : t.txtSecondary;
          return (
            <View key={item.name}>
              {item.sectionKey ? <Text style={styles.sect}>{tr(item.sectionKey)}</Text> : null}
              <Pressable
                onPress={() => { if (!active) navigation.navigate(item.name); }}
                style={[styles.navitem, { backgroundColor: active ? t.accent + "1F" : "transparent" }]}
              >
                {active ? <View style={[styles.accentBar, { backgroundColor: t.accent }]} /> : null}
                <Ionicons name={item.icon} size={17} color={color} />
                <Text style={{ color, fontSize: 13.5, fontWeight: active ? "600" : "500" }}>{tr(item.labelKey)}</Text>
              </Pressable>
            </View>
          );
        })}
        <Text style={styles.sect}>{tr("nav.filter")}</Text>
        <FilterRow label={tr("nav.filterAll")} value="all" />
        <FilterRow label={tr("nav.filterArchived")} value="archived" />
        {clients.length > 0 ? <Text style={styles.sect}>{tr("nav.clients")}</Text> : null}
        {clients.map(([name, count]) => (
          <FilterRow key={name} label={name} value={`client:${name}`} count={count} />
        ))}
      </ScrollView>
      <View style={{ paddingVertical: 10, paddingHorizontal: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.glassBorder }}>
        {me ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: t.accent, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ color: "#fff", fontSize: 11, fontWeight: "700" }}>{(me.name || "?").charAt(0).toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12, fontWeight: "600" }}>{me.name}</Text>
              <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>{me.role}</Text>
            </View>
          </View>
        ) : (
          <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("nav.commands")}</Text>
        )}
      </View>
    </View>
  );
}

// The bottom-bar / tab set, matching the hard-coded list 1:1. Used as the
// FALLBACK when the kernel registry is empty (no KernelProvider / boot failed),
// so the shell renders identically with or without the plugin kernel.
type TabItem = { name: string; labelKey: string; icon: IconName; desktopOnly?: boolean; phoneOnly?: boolean };
const TAB_FALLBACK: TabItem[] = [
  { name: "index", labelKey: "nav.dashboard", icon: "stats-chart-outline" },
  { name: "board", labelKey: "nav.board", icon: "grid-outline" },
  { name: "needs", labelKey: "nav.needsYou", icon: "notifications-outline" },
  { name: "processes", labelKey: "nav.processes", icon: "git-network-outline", desktopOnly: true },
  { name: "recordings", labelKey: "nav.recordings", icon: "videocam-outline", desktopOnly: true },
  { name: "sessions", labelKey: "nav.sessions", icon: "chatbubbles-outline", desktopOnly: true },
  { name: "history", labelKey: "nav.history", icon: "time-outline", desktopOnly: true },
  { name: "connectors", labelKey: "nav.connectors", icon: "sync-outline", desktopOnly: true },
  { name: "automation", labelKey: "nav.automation", icon: "git-branch-outline", desktopOnly: true },
  { name: "settings", labelKey: "nav.settings", icon: "settings-outline", desktopOnly: true },
  { name: "more", labelKey: "nav.more", icon: "ellipsis-horizontal", phoneOnly: true },
];

export default function TabsLayout() {
  const tr = useT();
  const { width } = useWindowDimensions();
  const sidebar = isWeb && width >= 900;   // desktop nav shell vs phone bottom bar
  // The tab set now comes from the kernel surface registry (nav.tabs plugin),
  // falling back to TAB_FALLBACK when no kernel is provided — identical output.
  const surfaces = useSurfaces();
  const fromRegistry = surfaces
    .filter((s) => s.route && s.nav)
    .map((s) => ({ name: s.route as string, labelKey: s.nav!.labelKey ?? "", icon: (s.nav!.icon ?? "ellipse-outline") as IconName, desktopOnly: s.nav!.desktopOnly, phoneOnly: s.nav!.phoneOnly }));
  const tabItems: TabItem[] = fromRegistry.length ? fromRegistry : TAB_FALLBACK;
  // Hiding a screen from the phone bottom bar uses href:null (see TAB_FALLBACK /
  // the map below). A null tabBarButton still reserves a flex slot, so the real
  // tabs would be sized to 1/11 of the width and clip to "Bo…", "Da…".
  const icon = (n: IconName) => ({ color, size }: { color: ColorValue; size: number }) =>
    <Ionicons name={n} color={color as string} size={size} />;
  return (
    <Tabs
      tabBar={sidebar ? (props) => <Sidebar {...props} /> : undefined}
      screenOptions={{
        headerShown: false,
        tabBarPosition: sidebar ? "left" : "bottom",
        tabBarStyle: sidebar
          ? { width: 220, backgroundColor: "transparent", borderRightWidth: 0 }
          : { position: "absolute", backgroundColor: "transparent", borderTopWidth: 0, elevation: 0 },
        tabBarBackground: sidebar ? undefined : () => <GlassTabBar />,
        tabBarLabelStyle: sidebar ? undefined : { fontSize: 11 },
        tabBarActiveTintColor: t.accent,
        tabBarInactiveTintColor: t.txtTertiary,
        sceneStyle: { backgroundColor: t.canvas },
      }}
    >
      {/* The DASHBOARD is `index`, not merely first in this list. Expo Router's
          documented rule is "the tab file named index.tsx is the default tab
          when the app loads", so reordering alone would have put Dashboard
          first in the bar while the app still OPENED on the board - worse than
          either arrangement on its own. The two files were therefore swapped
          (git mv) and the board now has its own named route, /(tabs)/board.
          The set below is registry-driven (nav.tabs) with a 1:1 fallback. */}
      {tabItems.map((item) => {
        const hide =
          (!sidebar && item.desktopOnly) || (sidebar && item.phoneOnly) ? { href: null } : {};
        return (
          <Tabs.Screen
            key={item.name}
            name={item.name}
            options={{ title: tr(item.labelKey), tabBarIcon: icon(item.icon), ...hide }}
          />
        );
      })}
    </Tabs>
  );
}

const styles = StyleSheet.create({
  side: { width: 220, height: "100%", paddingHorizontal: 10, paddingTop: 14, borderRightWidth: StyleSheet.hairlineWidth },
  logo: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 8, paddingBottom: 12 },
  logoImg: { width: 26, height: 26, borderRadius: 7 },
  sect: { color: t.txtTertiary, fontSize: 10.5, fontWeight: "600", letterSpacing: 0.6, textTransform: "uppercase", paddingHorizontal: 10, paddingTop: 12, paddingBottom: 4 },
  navitem: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, marginBottom: 2 },
  accentBar: { position: "absolute", left: -2, top: "22%", bottom: "22%", width: 2.5, borderRadius: 2 },
});
