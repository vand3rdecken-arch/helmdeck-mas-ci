import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Keyboard, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type ChatMsg, type SteerOpts } from "@/data/client";
import { useTheme } from "@/theme";
import { Composer } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { Empty } from "@/ui/kit";

// Board copilot chat = the SAME transcript + composer UI as the card chat
// (app/src/ui/card_transcript.tsx + card_composer.tsx). Only the submit target
// differs (api.chat here vs api.steer on a card), so there is ONE chat UI to
// maintain, not two. The board's flat ChatMsg log is mapped onto the transcript
// step model below.
function toStep(m: ChatMsg): TStep {
  const mine = m.cls === "user" || m.cls === "you";
  return {
    role: mine ? "user" : "assistant",
    kind: "text",
    cls: m.cls,
    text: m.cls === "error" ? "⚠ " + m.text : m.text,
    ts: m.ts,
    agent: m.cls === "pm",   // the PM's proactive messages get the board-agent tag
  };
}

export default function ChatScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const qc = useQueryClient();
  const scroll = useRef<ScrollView>(null);
  const [atBottom, setAtBottom] = useState(true);
  // Edge-to-edge (Expo SDK 57) makes Android ignore adjustResize, so the composer
  // hides behind the keyboard. Measure the keyboard height and lift the content
  // manually (a height:kb spacer) - works on both platforms without a native lib.
  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);
  // turn token: each send captures the current id; Stop bumps it so a late reply
  // that arrives after cancel is discarded instead of appended.
  const turn = useRef(0);

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  // poll the transcript so the PM's proactive messages appear LIVE (the chat
  // moves on its own); don't clobber optimistic messages mid-turn (busy).
  const { data } = useQuery({ queryKey: ["chatHistory"], queryFn: api.chatHistory, enabled: me?.role !== "client", refetchInterval: 8000 });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models, enabled: me?.role !== "client" });

  useEffect(() => { if (data?.messages && !busy) setMsgs(data.messages); }, [data, busy]);

  // auto-pin to newest (incl. the PM's proactive messages) when already near the
  // bottom - same pattern as the card chat, so opening lands you at the latest.
  useEffect(() => {
    if (atBottom) setTimeout(() => scroll.current?.scrollToEnd({ animated: false }), 30);
  }, [msgs.length, atBottom]);
  const onScroll = (e: { nativeEvent: { contentOffset: { y: number }; contentSize: { height: number }; layoutMeasurement: { height: number } } }) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    setAtBottom(contentSize.height - contentOffset.y - layoutMeasurement.height < 60);
  };

  async function send(raw: string, opts: SteerOpts) {
    const q = raw.trim();
    if (!q) return;
    setMsgs((m) => [...m, { cls: "user", text: q }]);
    setBusy(true);
    const id = ++turn.current;
    try {
      const r = await api.chat(q, opts);
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
      <View style={{ flex: 1 }}>
        <ScrollView ref={scroll} onScroll={onScroll} scrollEventThrottle={64} style={{ flex: 1 }}
          contentContainerStyle={{ padding: 12, paddingBottom: 24 }}>
          {msgs.length === 0
            ? <Empty text="Frag den Copilot über die Arbeit." />
            : <Transcript steps={msgs.map(toStep)} />}
          {busy ? <Text style={{ color: t.txtTertiary, fontSize: 12, paddingTop: 8 }}>… denkt</Text> : null}
        </ScrollView>
        {!atBottom ? (
          <Pressable onPress={() => { scroll.current?.scrollToEnd({ animated: true }); setAtBottom(true); }}
            style={{ position: "absolute", right: 14, bottom: (kb > 0 ? kb : 0) + 96, flexDirection: "row", alignItems: "center", gap: 4,
              backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16,
              paddingHorizontal: 12, paddingVertical: 7, ...(Platform.OS === "web" ? {} : { elevation: 6 }) }}>
            <Ionicons name="arrow-down" size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Neueste</Text>
          </Pressable>
        ) : null}

        <Composer onSend={send} busy={busy} onStop={stop} models={models ?? ["auto"]}
          placeholder="Frage…" draftKey="board-copilot"
          bottomInset={kb > 0 ? insets.bottom + 10 : insets.bottom + 8} />
        {kb > 0 ? <View style={{ height: kb }} /> : null}
      </View>
    </View>
  );
}
