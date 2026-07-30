import { Ionicons } from "@expo/vector-icons";
import { Tabs } from "expo-router";
import { tokens } from "@/theme/tokens";

const t = tokens.dark;

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: { backgroundColor: t.surface1, borderTopColor: t.glassBorder },
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
