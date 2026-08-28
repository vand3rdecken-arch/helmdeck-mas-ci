import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { discard, pending, subscribe, type Outbound } from "@/data/outbox";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

// The unsent queue, shown directly above the composer. ONE component rendered by
// both chats (board + card) - same law as the shared Transcript/Composer: there
// is one chat UI, not two.
//
// It exists because a failed send used to be invisible. The text was gone from
// the composer, gone from the draft store, and the optimistic bubble died with
// the screen - so "keine Nachricht, kein Fehler" was the whole experience. Now a
// send that never reached the daemon stays here, on disk, until the owner sends
// it or throws it away.
export function UnsentStrip({ scope, onRetry }: {
  scope: string;
  onRetry: (m: Outbound) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const [rows, setRows] = useState<Outbound[]>([]);

  const refresh = useCallback(() => { pending(scope).then(setRows); }, [scope]);

  // Re-read on mount, then on every change the store announces. The store is the
  // single owner of what is unsent; this component keeps no copy of its own, so
  // a park/settle from the send path can never leave a stale row here - and no
  // timer is scanning for something only this app can change.
  useEffect(() => {
    refresh();
    return subscribe(refresh);
  }, [refresh]);

  if (!rows.length) return null;
  return (
    <View style={{ gap: 6, paddingHorizontal: 12, paddingBottom: 6 }}>
      {rows.map((m) => (
        <View key={m.id} style={{
          flexDirection: "row", alignItems: "center", gap: 8, borderRadius: 10,
          borderWidth: 1, borderColor: t.warn + "66", backgroundColor: t.warn + "12",
          paddingHorizontal: 10, paddingVertical: 8,
        }}>
          <Ionicons name="cloud-offline-outline" size={14} color={t.warn} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text numberOfLines={2} style={{ color: t.txtPrimary, fontSize: 12.5 }}>{m.text}</Text>
            <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
              {tr("outbox.notSent")}{m.tries > 1 ? ` · ${tr("outbox.tries", { n: m.tries })}` : ""}
              {m.error ? ` · ${m.error}` : ""}
            </Text>
          </View>
          <Pressable hitSlop={6} onPress={() => onRetry(m)} accessibilityLabel={tr("outbox.retry")}>
            <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: "700" }}>{tr("outbox.retry")}</Text>
          </Pressable>
          <Pressable hitSlop={6} onPress={() => discard(m.id).then(refresh)}
                     accessibilityLabel={tr("outbox.discard")}>
            <Ionicons name="close" size={14} color={t.txtTertiary} />
          </Pressable>
        </View>
      ))}
    </View>
  );
}
