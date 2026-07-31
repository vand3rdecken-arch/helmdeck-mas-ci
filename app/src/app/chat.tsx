import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type ChatMsg } from "@/data/client";
import { useTheme } from "@/theme";
import { Empty } from "@/ui/kit";

export default function ChatScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const qc = useQueryClient();
  const scroll = useRef<ScrollView>(null);
  const { data } = useQuery({ queryKey: ["chatHistory"], queryFn: api.chatHistory });

  useEffect(() => { if (data?.messages) setMsgs(data.messages); }, [data]);

  async function send() {
    const q = text.trim();
    if (!q) return;
    setText("");
    setMsgs((m) => [...m, { cls: "user", text: q }]);
    setBusy(true);
    try {
      const r = await api.chat(q);
      const actions = (r.actions ?? []).map((a) => a.detail || a.tool).filter(Boolean).join("\n");
      setMsgs((m) => [...m, { cls: r.error ? "error" : "bot",
        text: [actions && "⚙ " + actions.replace(/\n/g, "\n⚙ "), r.reply || r.error || "(keine Antwort)"].filter(Boolean).join("\n\n") }]);
      qc.invalidateQueries({ queryKey: ["tracks"] });
    } catch (e) {
      setMsgs((m) => [...m, { cls: "error", text: String((e as Error).message) }]);
    } finally { setBusy(false); setTimeout(() => scroll.current?.scrollToEnd(), 50); }
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>Board copilot</Text>
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView ref={scroll} contentContainerStyle={{ padding: 12, gap: 8 }}>
          {msgs.length === 0 ? <Empty text="Frag den Copilot über die Arbeit." /> :
            msgs.map((m, i) => {
              const mine = m.cls === "user";
              return (
                <View key={i} style={{ alignSelf: mine ? "flex-end" : "stretch", maxWidth: mine ? "85%" : "100%",
                  backgroundColor: mine ? t.accent + "22" : t.surface1, borderRadius: 10, padding: 10 }}>
                  <Text selectable style={{ color: m.cls === "error" ? t.danger : t.txtPrimary, fontSize: 14 }}>{m.text}</Text>
                </View>
              );
            })}
          {busy ? <ActivityIndicator color={t.accent} /> : null}
        </ScrollView>
        <View style={{ flexDirection: "row", padding: 8, gap: 8, borderTopWidth: 1, borderTopColor: t.glassBorder,
          paddingBottom: insets.bottom + 8, alignItems: "flex-end" }}>
          <TextInput value={text} onChangeText={setText} multiline placeholder="Frage…" placeholderTextColor={t.txtPlaceholder}
            style={{ flex: 1, color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 10, padding: 10, maxHeight: 120 }} />
          <Pressable onPress={send} disabled={busy || !text.trim()}
            style={{ backgroundColor: t.accent, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center", opacity: busy || !text.trim() ? 0.5 : 1 }}>
            <Ionicons name="arrow-up" size={22} color="#fff" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}
