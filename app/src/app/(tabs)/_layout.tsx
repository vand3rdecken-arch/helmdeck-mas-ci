import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { Platform, Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { tokens } from "@/theme/tokens";

const t = tokens.dark;
const isWeb = Platform.OS === "web";

/** Frosted glass bar for the mobile bottom tabs (real backdrop blur). */
function GlassTabBar() {
  return (
    <View style={StyleSheet.absoluteFill}>
      <BlurView intensity={40} tint="dark" style={StyleSheet.absoluteFill} />
      <View style={[StyleSheet.absoluteFill, { backgroundColor: t.canvas + "66", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.glassBorder }]} />
    </View>
  );
}

/** Desktop left sidebar — the old web app's nav shell: a gradient logo mark +
 *  "SwarmDeck", then the nav items with a left accent bar on the active one.
 *  Real glass (blur 34 / saturate 1.8) so the aurora backdrop refracts through. */
function Sidebar({ state, descriptors, navigation }: any) {
  return (
    <View style={[styles.side, { backgroundColor: t.glass, borderRightColor: t.glassBorder },
      ({ backdropFilter: "blur(34px) saturate(1.8)", WebkitBackdropFilter: "blur(34px) saturate(1.8)" } as any)]}>
      <View style={styles.logo}>
        <View style={[styles.logoDot, { backgroundColor: t.accent }]}>
          <Ionicons name="albums" size={13} color="#fff" />
        </View>
        <Text style={{ color: t.txtPrimary, fontWeight: "700", fontSize: 14.5 }}>SwarmDeck</Text>
      </View>
      {state.routes.map((route: any, i: number) => {
        const { options } = descriptors[route.key];
        const active = state.index === i;
        const color = active ? t.txtPrimary : t.txtSecondary;
        const label = (options.title ?? route.name) as string;
        return (
          <Pressable
            key={route.key}
            onPress={() => {
              const e = navigation.emit({ type: "tabPress", target: route.key, canPreventDefault: true });
              if (!active && !e.defaultPrevented) navigation.navigate(route.name);
            }}
            style={[styles.navitem, { backgroundColor: active ? t.accent + "1F" : "transparent" }]}
          >
            {active ? <View style={[styles.accentBar, { backgroundColor: t.accent }]} /> : null}
            {options.tabBarIcon?.({ focused: active, color, size: 17 })}
            <Text style={{ color, fontSize: 13.5, fontWeight: active ? "600" : "500" }}>{label}</Text>
          </Pressable>
        );
      })}
      <View style={{ marginTop: "auto", padding: 8 }}>
        <Text style={{ color: t.txtTertiary, fontSize: 11 }}>⌘K · Befehle</Text>
      </View>
    </View>
  );
}

export default function TabsLayout() {
  const { width } = useWindowDimensions();
  const sidebar = isWeb && width >= 900;   // desktop nav shell vs phone bottom bar
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
        tabBarActiveTintColor: t.accent,
        tabBarInactiveTintColor: t.txtTertiary,
        sceneStyle: { backgroundColor: t.canvas },
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Board", tabBarIcon: ({ color, size }) => <Ionicons name="grid-outline" color={color} size={size} /> }} />
      <Tabs.Screen name="needs" options={{ title: "Needs you", tabBarIcon: ({ color, size }) => <Ionicons name="notifications-outline" color={color} size={size} /> }} />
      <Tabs.Screen name="dashboard" options={{ title: "Dashboard", tabBarIcon: ({ color, size }) => <Ionicons name="stats-chart-outline" color={color} size={size} /> }} />
      <Tabs.Screen name="more" options={{ title: "More", tabBarIcon: ({ color, size }) => <Ionicons name="ellipsis-horizontal" color={color} size={size} /> }} />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  side: { width: 220, height: "100%", paddingHorizontal: 10, paddingTop: 14, borderRightWidth: StyleSheet.hairlineWidth },
  logo: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 8, paddingBottom: 16 },
  logoDot: { width: 24, height: 24, borderRadius: 7, alignItems: "center", justifyContent: "center" },
  navitem: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, marginBottom: 2 },
  accentBar: { position: "absolute", left: -2, top: "22%", bottom: "22%", width: 2.5, borderRadius: 2 },
});
