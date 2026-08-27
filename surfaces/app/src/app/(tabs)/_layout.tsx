import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { type ColorValue, Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { api, type CellInfo } from "@/data/client";
import { useBoardFilter } from "@/data/boardfilter";
import { useT } from "@/i18n";
import { tokens } from "@/theme/tokens";
import { useSurfaces } from "@/kernel/react";
import { can, type Surface } from "@/kernel";
import { useResponsive } from "@/ui/responsive";
import { NAV, TAB_FALLBACK, type NavItem as FallbackNavItem, type TabItem as FallbackTabItem } from "./_nav_fallback";

const t = tokens.dark;
const LOGO = require("../../../assets/images/icon.png");

type IconName = keyof typeof Ionicons.glyphMap;
// NAV/TAB_FALLBACK data now lives in ./_nav_fallback.ts (card 4, ops/docs/
// backlog/rbac-gxp) - split out so a plain-node self-test can import the
// SAME arrays without pulling in react-native (which this file does).
// Re-typed here with the stricter Ionicons icon type; the data file itself
// uses a plain string (see its own comment on why).
type NavItem = FallbackNavItem & { icon: IconName };
type TabItem = FallbackTabItem & { icon: IconName };
// Cell-enable nav gating (Phase 1 of the cell-registry decree, daemon/debt.py
// order 33; the 3 tab-bearing surfaces got real route+nav in the
// plugin-kernel-dual-nav cutover): a disabled cell's tab must not appear,
// even though server.py already 404s its routes. Keyed off the /cells
// manifest generically (by surface id, not a hardcoded cell name) so any
// cell with a Surface+nav entry (today: board/engineer, processes, connectors)
// is covered automatically.
function useDisabledCellSurfaces(): Set<string> {
  const { data } = useQuery({ queryKey: ["cells"], queryFn: api.cells, staleTime: 30000, retry: false });
  const disabled = new Set<string>();
  for (const c of (data?.cells ?? []) as CellInfo[]) {
    if (c.enabled || !c.surface) continue;
    disabled.add(c.surface);
    // Nav-only tab entries (nav.tabs, e.g. id "tab.connectors" route "connectors")
    // don't share the cell's "surfaces.<id>" id, so also index the bare suffix.
    disabled.add(c.surface.replace(/^surfaces\./, ""));
  }
  return disabled;
}

function isSurfaceCellDisabled(s: Surface, disabled: Set<string>): boolean {
  if (disabled.size === 0) return false;
  return disabled.has(s.id) || Boolean(s.route && disabled.has(s.route));
}

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
  // Sidebar items now come from the same kernel registry as the bottom bar
  // (nav.tabs), excluding phone-only entries (More). Falls back to the
  // hard-coded NAV when no kernel is provided.
  const surfaces = useSurfaces();
  const disabledCells = useDisabledCellSurfaces();
  const registryNav = surfaces
    .filter((s) => s.route && s.nav && !s.nav.phoneOnly && !isSurfaceCellDisabled(s, disabledCells))
    .map((s) => ({ name: s.route as string, labelKey: s.nav!.labelKey ?? "", icon: (s.nav!.icon ?? "ellipse-outline") as IconName, sectionKey: s.nav!.sectionKey, cap: s.nav!.cap }));
  const navItems: NavItem[] = registryNav.length ? registryNav : (NAV as NavItem[]);
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
        {navItems.filter((item) => can(me, item.cap)).map((item) => {
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
// `cap`: card 4 closed a real gap here - this list previously had NO role
// gating fields at all, so a kernel failure (or, before the registry path was
// fixed below, even the normal registry path) showed every tab, owner-only
// ones included, to every role on the phone bottom bar.

export default function TabsLayout() {
  const tr = useT();
  const { wide: sidebar } = useResponsive();   // desktop nav shell vs phone bottom bar
  // The tab set now comes from the kernel surface registry (nav.tabs plugin),
  // falling back to TAB_FALLBACK when no kernel is provided — identical output.
  const surfaces = useSurfaces();
  const disabledCells = useDisabledCellSurfaces();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const fromRegistry = surfaces
    .filter((s) => s.route && s.nav && !isSurfaceCellDisabled(s, disabledCells))
    .map((s) => ({ name: s.route as string, labelKey: s.nav!.labelKey ?? "", icon: (s.nav!.icon ?? "ellipse-outline") as IconName, desktopOnly: s.nav!.desktopOnly, phoneOnly: s.nav!.phoneOnly, cap: s.nav!.cap }));
  const tabItems: TabItem[] = (fromRegistry.length ? fromRegistry : (TAB_FALLBACK as TabItem[])).filter((item) => can(me, item.cap));
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
