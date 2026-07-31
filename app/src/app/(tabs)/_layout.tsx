import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { Platform, StyleSheet, useWindowDimensions, View } from "react-native";
import { tokens } from "@/theme/tokens";

const t = tokens.dark;
const isWeb = Platform.OS === "web";

/** Frosted glass nav — real backdrop blur (expo-blur), the cross-platform
 *  version of this session's Haze work. On desktop it's a left sidebar (edge on
 *  the right); on mobile a bottom bar (edge on top). */
function GlassTabBar({ side }: { side?: boolean }) {
  return (
    <View style={StyleSheet.absoluteFill}>
      <BlurView intensity={40} tint="dark" style={StyleSheet.absoluteFill} />
      <View style={[StyleSheet.absoluteFill, { backgroundColor: t.canvas + "66" },
        side
          ? { borderRightWidth: StyleSheet.hairlineWidth, borderRightColor: t.glassBorder }
          : { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: t.glassBorder }]} />
    </View>
  );
}

export default function TabsLayout() {
  const { width } = useWindowDimensions();
  // desktop → left sidebar with labels (a real desktop nav, not a phone bar)
  const sidebar = isWeb && width >= 900;
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarPosition: sidebar ? "left" : "bottom",
        tabBarVariant: sidebar ? "material" : "uikit",
        tabBarStyle: sidebar
          ? { width: 208, backgroundColor: "transparent", borderRightWidth: 0, elevation: 0 }  // reserves layout space so no card hides behind it
          : { position: "absolute", backgroundColor: "transparent", borderTopWidth: 0, elevation: 0 },  // floats over content (glass)
        tabBarLabelPosition: sidebar ? "beside-icon" : undefined,
        tabBarBackground: () => <GlassTabBar side={sidebar} />,
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
