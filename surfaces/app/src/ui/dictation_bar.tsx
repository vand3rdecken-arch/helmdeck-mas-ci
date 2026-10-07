import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { ActivityIndicator, Linking, Pressable, Text, View } from "react-native";
import { useTheme } from "@/theme";
import { useT } from "@/i18n";
import type { useDictation } from "@/data/use_dictation";

type Dict = ReturnType<typeof useDictation>;

const BARS = [0.45, 0.75, 1, 0.8, 0.55, 0.9, 0.6];   // fixed silhouette, the level scales it

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Replaces the composer's input row while a dictation is running (Paseo's
 *  DictationOverlay shape): X discards, the meter + timer prove the mic is
 *  live, the partial transcript shows what was heard so far, pencil inserts
 *  the text for review, the arrow inserts AND sends. Failure keeps the
 *  recording and offers a retry instead of dropping it. */
export function DictationBar({ d, inline = false }: { d: Dict; inline?: boolean }) {
  const t = useTheme();
  const tr = useT();
  const { state } = d;
  const busy = state === "starting" || state === "processing";
  const failed = state === "failed";
  const errText = d.error === "mic-denied" ? tr("dictation.micDenied")
    : d.error === "mic-blocked" ? tr("dictation.micBlocked")
    : d.error === "mic-unavailable" ? tr("dictation.micUnavailable")
    : d.error || tr("dictation.failed");
  const sub = failed ? errText
    : state === "processing" ? tr("dictation.working")
    : d.partial || tr("dictation.listening");

  return (
    <View testID="dictation-bar" style={{ flexDirection: "row", alignItems: "center", gap: 8,
      ...(inline ? { flex: 1, minWidth: 0 } : { margin: 8 }), paddingHorizontal: 8, paddingVertical: 6, minHeight: 52, borderRadius: 12, borderWidth: 1,
      borderColor: failed ? t.danger : t.accent + "80", backgroundColor: failed ? t.danger + "14" : t.accent + "1A" }}>
      <Pressable testID="dictation-cancel" onPress={d.cancel} disabled={state === "processing"}
        accessibilityLabel={tr("dictation.cancel")} hitSlop={6}
        style={{ width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center",
          backgroundColor: t.surface2, opacity: state === "processing" ? 0.4 : 1 }}>
        <Ionicons name="close" size={19} color={t.txtSecondary} />
      </Pressable>

      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 2.5, height: 22 }}>
            {BARS.map((k, i) => (
              <View key={i} style={{ width: 3, borderRadius: 2, backgroundColor: failed ? t.danger : t.accent,
                height: state === "recording" ? 4 + Math.round(d.level * 18 * k) : 4 }} />
            ))}
          </View>
          <Text testID="dictation-timer" style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "700",
            fontVariant: ["tabular-nums"] }}>{mmss(d.seconds)}</Text>
        </View>
        <Text testID="dictation-sub" numberOfLines={failed ? 2 : 1} ellipsizeMode={state === "recording" ? "head" : "tail"}
          style={{ color: failed ? t.danger : t.txtSecondary, fontSize: 12, marginTop: 1 }}>{sub}</Text>
      </View>

      {busy ? (
        <ActivityIndicator size="small" color={t.accent} style={{ width: 36 }} />
      ) : failed ? (
        d.error === "mic-blocked" ? (
          // Android will not ask again: the only way back is the app's own
          // settings page, one tap away instead of a hunt through Settings > Apps.
          <Pressable testID="dictation-settings" onPress={() => { Linking.openSettings().catch(() => undefined); }}
            style={{ backgroundColor: t.accent, borderRadius: 9, paddingHorizontal: 12, paddingVertical: 9 }}>
            <Text style={{ color: "#fff", fontSize: 12.5, fontWeight: "700" }}>{tr("dictation.openSettings")}</Text>
          </Pressable>
        ) : d.error.startsWith("mic-") ? null : (
          <Pressable testID="dictation-retry" onPress={d.retry}
            style={{ backgroundColor: t.accent, borderRadius: 9, paddingHorizontal: 12, paddingVertical: 9 }}>
            <Text style={{ color: "#fff", fontSize: 12.5, fontWeight: "700" }}>{tr("dictation.retry")}</Text>
          </Pressable>
        )
      ) : (
        <>
          <Pressable testID="dictation-insert" onPress={() => d.confirm(false)}
            accessibilityLabel={tr("dictation.insert")}
            style={{ width: 40, height: 40, borderRadius: 10, alignItems: "center", justifyContent: "center",
              backgroundColor: t.surface2, borderWidth: 1, borderColor: t.borderSubtle }}>
            <Ionicons name="create-outline" size={19} color={t.accent} />
          </Pressable>
          <Pressable testID="dictation-send" onPress={() => d.confirm(true)}
            accessibilityLabel={tr("dictation.send")}
            style={{ width: 40, height: 40, borderRadius: 10, alignItems: "center", justifyContent: "center",
              backgroundColor: t.accent }}>
            <Ionicons name="arrow-up" size={21} color="#fff" />
          </Pressable>
        </>
      )}
    </View>
  );
}
