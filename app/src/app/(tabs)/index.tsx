import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Platform, Pressable, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { BoardList } from "@/ui/board";
import { GlowBackdrop } from "@/ui/glow";
import { useTheme } from "@/theme";

/** Capacity meter (old web header): WIP running / limit · attention touches ·
 *  headroom. Owner-facing at-a-glance load. */
function CapacityMeter() {
  const t = useTheme();
  const { data } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, staleTime: 8000 });
  const c = data?.capacity;
  if (!c) return null;
  const Item = ({ label, value }: { label: string; value: string }) => (
    <Text style={{ color: t.txtTertiary, fontSize: 12 }}>
      <Text style={{ color: t.txtSecondary, fontWeight: "600" }}>{value}</Text> {label}
    </Text>
  );
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
      <Item label="WIP" value={`${c.wip}/${c.wip_limit}`} />
      <Item label="Touches" value={`${c.touches_today}/${c.touch_budget_day}`} />
      <Item label="Headroom" value={`${c.headroom}`} />
    </View>
  );
}

export default function BoardTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const wide = Platform.OS === "web" && width >= 900;
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <GlowBackdrop />
      {/* desktop header: title · capacity meter · + Neu */}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 16, paddingTop: insets.top + 10,
        paddingHorizontal: wide ? 20 : 16, paddingBottom: 6 }}>
        <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700" }}>Board</Text>
        {wide ? <CapacityMeter /> : null}
        <View style={{ flex: 1 }} />
      </View>
      <BoardList />
      {/* floating board chat + new-request, bottom-right (works on desktop too) */}
      <View style={{ position: "absolute", right: 18, bottom: wide ? 24 : 84, alignItems: "center", gap: 12 }}>
        <Pressable onPress={() => router.push("/chat")}
          style={{ width: 48, height: 48, borderRadius: 15, backgroundColor: t.surface1, borderWidth: 1, borderColor: t.borderSubtle,
            alignItems: "center", justifyContent: "center",
            ...(Platform.OS === "web" ? { boxShadow: "0 4px 14px rgba(0,0,0,0.3)" } as any : { elevation: 4 }) }}>
          <Ionicons name="chatbubble-ellipses-outline" size={20} color={t.accent} />
        </Pressable>
        <Pressable onPress={() => router.push("/new")}
          style={{ width: 56, height: 56, borderRadius: 18, backgroundColor: t.accent, alignItems: "center", justifyContent: "center",
            ...(Platform.OS === "web" ? { boxShadow: "0 6px 18px rgba(0,0,0,0.35)" } as any : { elevation: 6 }) }}>
          <Ionicons name="add" size={26} color="#fff" />
        </Pressable>
      </View>
    </View>
  );
}
