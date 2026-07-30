import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { BoardList } from "@/ui/board";
import { GlowBackdrop } from "@/ui/glow";
import { useTheme } from "@/theme";

export default function BoardTab() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <GlowBackdrop />
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        Board
      </Text>
      <BoardList />
      <View style={{ position: "absolute", right: 18, bottom: 24, alignItems: "center", gap: 12 }}>
        <Pressable onPress={() => router.push("/chat")}
          style={{ width: 44, height: 44, borderRadius: 14, backgroundColor: t.surface2, alignItems: "center", justifyContent: "center" }}>
          <Ionicons name="chatbubble-outline" size={18} color={t.accent} />
        </Pressable>
        <Pressable onPress={() => router.push("/new")}
          style={{ width: 56, height: 56, borderRadius: 18, backgroundColor: t.accent, alignItems: "center", justifyContent: "center" }}>
          <Ionicons name="add" size={26} color="#fff" />
        </Pressable>
      </View>
    </View>
  );
}
