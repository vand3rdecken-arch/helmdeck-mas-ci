import { Text, View, type ViewStyle } from "react-native";

import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// The ONE context-fill bar, shared by the card chat (card/[id].tsx) and the
// board/PM chat (chat.tsx) - a session's window meter is the same UI question
// on both surfaces, so it lives here once instead of as two copies that can
// drift apart (the project's standing "never two chat UIs" rule). Amber
// >=75%, red >=90%; near full, the caller's chat already warns that steering
// compacts+continues. tokens/window are the DAEMON's own evidence (never a
// hardcoded window - a [1m] model has a 1M window, not 200k).
export function ContextMeter({ tokens, window, style }: {
  tokens?: number | null; window?: number | null; style?: ViewStyle;
}) {
  const t = useTheme();
  const tr = useT();
  if (!tokens) return null;
  const pct = Math.min(100, Math.round((tokens / (window || 200000)) * 100));
  const col = pct >= 90 ? t.danger : pct >= 75 ? t.warn : t.txtTertiary;
  return (
    <View style={{ gap: 3, ...style }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <View style={{ flex: 1, height: 3, borderRadius: 2, backgroundColor: t.borderSubtle, overflow: "hidden" }}>
          <View style={{ width: `${pct}%`, height: 3, backgroundColor: col }} />
        </View>
        <Text style={{ color: col, fontSize: 10 }}>
          {tr("card.chat.context", { k: Math.round(tokens / 1000), pct })}
        </Text>
      </View>
      {pct >= 90 ? (
        <Text style={{ color: t.danger, fontSize: 10 }}>{tr("card.chat.contextFull")}</Text>
      ) : null}
    </View>
  );
}
