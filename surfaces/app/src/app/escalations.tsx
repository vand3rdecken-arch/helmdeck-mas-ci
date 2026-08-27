import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

// Henry's escalation log (dual architecture): what the harness reported,
// what Henry decided, what still waits. Read-only - decisions happen in the
// copilot cell; this screen exists so a 4am decision is READABLE at 9am.
export default function EscalationsScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { data } = useQuery({ queryKey: ["escalations"], queryFn: api.escalations,
    refetchInterval: 30000 });
  // The demo seam answers {} for unmodelled endpoints and older daemons 404
  // into odd shapes - never trust the wire to be an array (the models-picker
  // crash class: rendering a non-array took the whole app black).
  const rows = Array.isArray(data) ? data : [];
  const { wide } = useResponsive();

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <ScreenHeader title={tr("nav.escalations")} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: 14, gap: 10, paddingBottom: insets.bottom + 24,
        width: "100%", maxWidth: wide ? 720 : undefined, alignSelf: "center" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("esc.sub")}</Text>
        {rows.length === 0 ? (
          <Empty text={tr("esc.empty")} />
        ) : rows.map((e) => (
          <View key={e.id} style={{ backgroundColor: t.surface1, borderWidth: 1,
            borderColor: t.glassBorder, borderRadius: 12, padding: 12, gap: 4 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name={e.closed ? "checkmark-circle-outline" : "alert-circle-outline"}
                size={16} color={e.closed ? t.ok : t.warn} />
              <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "700", flex: 1 }}>
                {e.kind}
              </Text>
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{(e.ts ?? "").replace("T", " ")}</Text>
            </View>
            {e.card ? (
              <Text style={{ color: t.txtSecondary, fontSize: 11.5 }}>{e.card}</Text>
            ) : null}
            {e.detail ? (
              <Text selectable style={{ color: t.txtTertiary, fontSize: 11.5 }} numberOfLines={3}>
                {e.detail}
              </Text>
            ) : null}
            <Text style={{ color: e.closed ? t.ok : t.warn, fontSize: 11.5, fontWeight: "600" }}>
              {e.closed
                ? tr("esc.decided", { action: e.action ?? "?" }) + (e.why ? " — " + e.why : "")
                : tr("esc.open", { n: e.attempts })}
            </Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
