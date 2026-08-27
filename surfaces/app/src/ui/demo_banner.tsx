import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { Platform, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useDemo } from "@/data/demo";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// Always-visible reminder that the board is sample data, with the way out.
// Bottom-LEFT on purpose: the board's chat/new-request FAB stack owns the
// bottom-right, so the two never collide on a phone.
export function DemoBanner() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const active = useDemo((s) => s.active);
  const disable = useDemo((s) => s.disable);
  const qc = useQueryClient();
  if (!active) return null;
  return (
    <View pointerEvents="box-none"
      style={{ position: "absolute", left: 12, right: 90, bottom: insets.bottom + 74, zIndex: 50 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, alignSelf: "flex-start", maxWidth: "100%",
        backgroundColor: t.surface2, borderColor: t.accent + "66", borderWidth: 1, borderRadius: 999,
        paddingLeft: 12, paddingRight: 6, paddingVertical: 6,
        ...(Platform.OS === "web"
          ? { boxShadow: "0 4px 14px rgba(0,0,0,0.3)" } as any
          : { shadowColor: "#000", shadowOpacity: 0.3, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 5 }) }}>
        <Ionicons name="flask-outline" size={14} color={t.accent} />
        <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 12, flexShrink: 1 }}>
          {tr("demo.banner")}
        </Text>
        <Pressable
          onPress={() => { disable(); qc.invalidateQueries(); }}
          hitSlop={8}
          style={{ backgroundColor: t.surface1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 }}>
          <Text style={{ color: t.txtPrimary, fontSize: 12, fontWeight: "600" }}>{tr("demo.exit")}</Text>
        </Pressable>
      </View>
    </View>
  );
}
