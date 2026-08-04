import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { type ColorValue, Image, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/data/client";
import { useBoardFilter } from "@/data/boardfilter";
import { useT } from "@/i18n";
import { tokens } from "@/theme/tokens";

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
// screens that are NOT phone bottom-bar tabs (hidden there, shown in sidebar)
const DESKTOP_ONLY = new Set(["processes", "recordings", "sessions", "history", "connectors", "automation", "settings"]);

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

export default function TabsLayout() {
  const tr = useT();
  const { width } = useWindowDimensions();
  const sidebar = isWeb && width >= 900;   // desktop nav shell vs phone bottom bar
  // Remove a screen from the phone bottom bar entirely. Must use href:null, not
  // a null tabBarButton — a null button still reserves a flex slot, so the four
  // real tabs would be sized to 1/11 of the width and clip to "Bo…", "Da…".
  const hideOnPhone = (name: string) =>
    !sidebar && DESKTOP_ONLY.has(name) ? { href: null } : {};
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
      <Tabs.Screen name="index" options={{ title: tr("nav.board"), tabBarIcon: icon("grid-outline") }} />
      <Tabs.Screen name="needs" options={{ title: tr("nav.needsYou"), tabBarIcon: icon("notifications-outline") }} />
      <Tabs.Screen name="dashboard" options={{ title: tr("nav.dashboard"), tabBarIcon: icon("stats-chart-outline") }} />
      <Tabs.Screen name="processes" options={{ title: tr("nav.processes"), tabBarIcon: icon("git-network-outline"), ...hideOnPhone("processes") }} />
      <Tabs.Screen name="recordings" options={{ title: tr("nav.recordings"), tabBarIcon: icon("videocam-outline"), ...hideOnPhone("recordings") }} />
      <Tabs.Screen name="sessions" options={{ title: tr("nav.sessions"), tabBarIcon: icon("chatbubbles-outline"), ...hideOnPhone("sessions") }} />
      <Tabs.Screen name="history" options={{ title: tr("nav.history"), tabBarIcon: icon("time-outline"), ...hideOnPhone("history") }} />
      <Tabs.Screen name="connectors" options={{ title: tr("nav.connectors"), tabBarIcon: icon("sync-outline"), ...hideOnPhone("connectors") }} />
      <Tabs.Screen name="automation" options={{ title: tr("nav.automation"), tabBarIcon: icon("git-branch-outline"), ...hideOnPhone("automation") }} />
      <Tabs.Screen name="settings" options={{ title: tr("nav.settings"), tabBarIcon: icon("settings-outline"), ...hideOnPhone("settings") }} />
      <Tabs.Screen name="more" options={{ title: tr("nav.more"), tabBarIcon: icon("ellipsis-horizontal"), ...(sidebar ? { href: null } : {}) }} />
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
