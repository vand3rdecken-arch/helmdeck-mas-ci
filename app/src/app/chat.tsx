import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type ChatMsg } from "@/data/client";
import { useTheme } from "@/theme";
import { Markdown } from "@/ui/card_markdown";
import { Empty } from "@/ui/kit";

// thinking levels — each maps to a real Claude Code budget keyword server-side
// (mirrors app/src/ui/card_composer.tsx).
const THINK: { id: string; short: string }[] = [
  { id: "", short: "off" }, { id: "think", short: "think" },
  { id: "think-hard", short: "hard" }, { id: "ultrathink", short: "ultra" },
];

export default function ChatScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [model, setModel] = useState("auto");
  const [thinking, setThinking] = useState("");
  const [picker, setPicker] = useState(false);
  const qc = useQueryClient();
  const scroll = useRef<ScrollView>(null);
  // turn token: each send captures the current id; Stop bumps it so a late
  // reply that arrives after cancel is discarded instead of appended.
  const turn = useRef(0);

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  // poll the transcript so the PM's proactive messages appear LIVE (the chat
  // moves on its own); don't clobber optimistic messages mid-turn (busy).
  const { data } = useQuery({ queryKey: ["chatHistory"], queryFn: api.chatHistory, enabled: me?.role !== "client", refetchInterval: 8000 });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models, enabled: me?.role !== "client" });

  useEffect(() => { if (data?.messages && !busy) setMsgs(data.messages); }, [data, busy]);

  async function send() {
    const q = text.trim();
    if (!q) return;
    setText("");
    setMsgs((m) => [...m, { cls: "user", text: q }]);
    setBusy(true);
    const id = ++turn.current;
    try {
      const r = await api.chat(q, { model, thinking });
      if (turn.current !== id) return;   // cancelled/superseded — drop this reply
      const actions = (r.actions ?? []).map((a) => a.detail || a.tool).filter(Boolean).join("\n");
      setMsgs((m) => [...m, { cls: r.error ? "error" : "bot",
        text: [actions && "⚙ " + actions.replace(/\n/g, "\n⚙ "), r.reply || r.error || "(keine Antwort)"].filter(Boolean).join("\n\n") }]);
      qc.invalidateQueries({ queryKey: ["tracks"] });
      qc.invalidateQueries({ queryKey: ["chatHistory"] });   // pull the persisted turn (+ any PM msgs)
    } catch (e) {
      if (turn.current !== id) return;
      setMsgs((m) => [...m, { cls: "error", text: String((e as Error).message) }]);
    } finally {
      if (turn.current === id) { setBusy(false); setTimeout(() => scroll.current?.scrollToEnd(), 50); }
    }
  }

  function stop() {
    turn.current++;              // invalidate the in-flight turn client-side
    api.chatCancel().catch(() => {});   // kill the copilot subprocess server-side
    setBusy(false);
  }

  const thinkShort = THINK.find((x) => x.id === thinking)?.short ?? "off";
  const modelLabel = model === "auto" ? "Auto" : model.replace("claude-", "").replace(/-\d{8}$/, "");
  const toolBtn = (active: boolean) => ({
    flexDirection: "row" as const, alignItems: "center" as const, gap: 4,
    backgroundColor: active ? t.accent + "26" : t.surface2,
    borderColor: active ? t.accent + "80" : t.borderSubtle, borderWidth: 1,
    borderRadius: 7, paddingHorizontal: 8, paddingVertical: 5,
  });

  const header = (
    <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
      <Pressable onPress={() => router.back()} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
      <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>Board copilot</Text>
    </View>
  );

  // role gate — the copilot is a team tool; clients get a notice, not the chat
  // (mirrors archive/web/components/chat.tsx returning null for clients).
  if (me?.role === "client") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        {header}
        <Empty text="Der Copilot ist nur für das Team." />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      {header}
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView ref={scroll} contentContainerStyle={{ padding: 12, gap: 8 }}>
          {msgs.length === 0 ? <Empty text="Frag den Copilot über die Arbeit." /> :
            msgs.map((m, i) => {
              const mine = m.cls === "user" || m.cls === "you";
              const isPm = m.cls === "pm";
              return (
                <View key={i} style={{ alignSelf: mine ? "flex-end" : "stretch", maxWidth: mine ? "85%" : "100%",
                  backgroundColor: mine ? t.accent + "22" : t.surface1, borderRadius: 10, padding: 10,
                  borderLeftWidth: isPm ? 3 : 0, borderLeftColor: t.accent2 }}>
                  {isPm ? (
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 4 }}>
                      <Ionicons name="compass" size={13} color={t.accent2} />
                      <Text style={{ color: t.accent2, fontSize: 11, fontWeight: "800" }}>PM</Text>
                      {m.ts ? <Text style={{ color: t.txtTertiary, fontSize: 10 }}>· {m.ts}</Text> : null}
                    </View>
                  ) : null}
                  {m.cls === "bot" || isPm
                    ? <Markdown>{m.text}</Markdown>
                    : <Text selectable style={{ color: m.cls === "error" ? t.danger : t.txtPrimary, fontSize: 14 }}>{m.text}</Text>}
                </View>
              );
            })}
          {busy ? <ActivityIndicator color={t.accent} /> : null}
        </ScrollView>

        {/* model + thinking-level pills (pattern from card_composer.tsx) */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 6, paddingHorizontal: 8, paddingTop: 8, alignItems: "center" }}>
          <Pressable onPress={() => setPicker(true)} style={toolBtn(model !== "auto")}>
            <Ionicons name="sparkles-outline" size={13} color={model !== "auto" ? t.accent : t.txtSecondary} />
            <Text style={{ color: model !== "auto" ? t.accent : t.txtSecondary, fontSize: 12 }}>{modelLabel}</Text>
          </Pressable>
          <Pressable onPress={() => { const i = THINK.findIndex((x) => x.id === thinking); setThinking(THINK[(i + 1) % THINK.length].id); }}
            style={toolBtn(thinking !== "")}>
            <Ionicons name="bulb-outline" size={13} color={thinking !== "" ? t.accent : t.txtSecondary} />
            <Text style={{ color: thinking !== "" ? t.accent : t.txtSecondary, fontSize: 12 }}>{thinkShort}</Text>
          </Pressable>
        </ScrollView>

        <View style={{ flexDirection: "row", padding: 8, gap: 8, borderTopWidth: 1, borderTopColor: t.glassBorder,
          paddingBottom: insets.bottom + 8, alignItems: "flex-end" }}>
          <TextInput value={text} onChangeText={setText} multiline placeholder="Frage…" placeholderTextColor={t.txtPlaceholder}
            style={{ flex: 1, color: t.txtPrimary, backgroundColor: t.surface2, borderRadius: 10, padding: 10, maxHeight: 120 }} />
          {busy ? (
            <Pressable onPress={stop}
              style={{ backgroundColor: t.danger, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
              <Ionicons name="stop" size={20} color="#fff" />
            </Pressable>
          ) : (
            <Pressable onPress={send} disabled={!text.trim()}
              style={{ backgroundColor: t.accent, borderRadius: 10, width: 44, height: 44, alignItems: "center", justifyContent: "center", opacity: !text.trim() ? 0.5 : 1 }}>
              <Ionicons name="arrow-up" size={22} color="#fff" />
            </Pressable>
          )}
        </View>
      </KeyboardAvoidingView>

      {/* model picker modal (pattern from card_composer.tsx) */}
      <Modal visible={picker} transparent animationType="fade" onRequestClose={() => setPicker(false)}>
        <Pressable onPress={() => setPicker(false)} style={{ flex: 1, backgroundColor: t.backdrop, justifyContent: "center", padding: 24 }}>
          <View style={{ backgroundColor: t.surface1, borderRadius: 14, borderWidth: 1, borderColor: t.glassBorder, maxHeight: "70%", overflow: "hidden" }}>
            <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "700", padding: 12 }}>MODEL</Text>
            <ScrollView>
              {["auto", ...(models ?? [])].map((raw) => {
                // /models returns objects {id,label,desc}; normalise (also plain
                // strings) so we never render an object as a child -> app crash.
                const id = typeof raw === "string" ? raw : raw.id;
                const label = id === "auto" ? "Auto (route by task)"
                  : typeof raw === "string" ? raw : (raw.label || raw.id);
                const desc = typeof raw === "string" ? "" : (raw.desc || "");
                return (
                  <Pressable key={id} onPress={() => { setModel(id); setPicker(false); }}
                    style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 11, borderTopWidth: 1, borderTopColor: t.borderSubtle }}>
                    <Ionicons name={id === model ? "radio-button-on" : "radio-button-off"} size={16} color={id === model ? t.accent : t.txtTertiary} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 14 }}>{label}</Text>
                      {desc ? <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{desc}</Text> : null}
                    </View>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}
