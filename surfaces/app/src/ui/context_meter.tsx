import { Ionicons } from "@expo/vector-icons";
import { useState, type ReactNode } from "react";
import { Pressable, Text, View, type ViewStyle } from "react-native";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// The ONE context-fill bar, shared by the card chat (card/[id].tsx) and the
// board/PM chat (chat.tsx) - a session's window meter is the same UI question
// on both surfaces, so it lives here once instead of as two copies that can
// drift apart (the project's standing "never two chat UIs" rule). Amber
// >=75%, red >=90%; near full, the caller's chat already warns that steering
// compacts+continues. tokens/window are the DAEMON's own evidence (never a
// hardcoded window - a [1m] model has a 1M window, not 200k).
// `details`: tap the meter to unfold them underneath - Paseo's composer shape
// (context ring, the provider's usage windows behind a tap), not a second
// always-on status line.
export function ContextMeter({ tokens, window, style, details }: {
  tokens?: number | null; window?: number | null; style?: ViewStyle; details?: ReactNode;
}) {
  const t = useTheme();
  const tr = useT();
  const [open, setOpen] = useState(false);
  if (!tokens) return null;
  const pct = Math.min(100, Math.round((tokens / (window || 200000)) * 100));
  const col = pct >= 90 ? t.danger : pct >= 75 ? t.warn : t.txtTertiary;
  const row = (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      <View style={{ flex: 1, height: 3, borderRadius: 2, backgroundColor: t.borderSubtle, overflow: "hidden" }}>
        <View style={{ width: `${pct}%`, height: 3, backgroundColor: col }} />
      </View>
      <Text style={{ color: col, fontSize: 10 }}>
        {tr("card.chat.context", { k: Math.round(tokens / 1000), pct })}
      </Text>
      {details ? <Ionicons name={open ? "chevron-up" : "chevron-down"} size={11} color={t.txtTertiary} /> : null}
    </View>
  );
  return (
    <View style={{ gap: 3, ...style }}>
      {details ? (
        <Pressable onPress={() => setOpen((v) => !v)} hitSlop={{ top: 10, bottom: 10 }}
          accessibilityRole="button" accessibilityLabel={tr("card.chat.usageDetails")}>
          {row}
        </Pressable>
      ) : row}
      {pct >= 90 ? (
        <Text style={{ color: t.danger, fontSize: 10 }}>{tr("card.chat.contextFull")}</Text>
      ) : null}
      {details && open ? <View style={{ paddingTop: 8 }}>{details}</View> : null}
    </View>
  );
}
