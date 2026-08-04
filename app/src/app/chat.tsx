import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Keyboard, Platform, Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { create } from "zustand";

import { api, type ChatMsg, type SteerOpts } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Composer } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { Empty } from "@/ui/kit";

// Desktop copilot is an IN-PAGE overlay (not a route), so the board stays mounted
// and visible-behind-dimmed — a route/transparentModal leaves a black void on web
// because expo-router doesn't keep the previous screen rendered. The FAB opens
// this store on wide screens; the phone still navigates to the /chat route.
interface CopilotPanel { open: boolean; show: () => void; hide: () => void }
export const useCopilotPanel = create<CopilotPanel>((set) => ({
  open: false,
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
}));

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

// The chat body (transcript + composer + logic). `onClose` returns to the board:
// router.back() when mounted as a route (phone), or the panel store's hide() when
// mounted as the desktop overlay. `wide` caps/centers the column for desktop.
function ChatBody({ onClose, wide }: { onClose: () => void; wide: boolean }) {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const colMax = wide ? 860 : undefined;
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
        text: [actions && "⚙ " + actions.replace(/\n/g, "\n⚙ "), r.reply || r.error || tr("chat.noReply")].filter(Boolean).join("\n\n") }]);
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
      <Pressable onPress={onClose} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
      <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{tr("chat.title")}</Text>
    </View>
  );

  // role gate — the copilot is a team tool; clients get a notice, not the chat
  // (mirrors archive/web/components/chat.tsx returning null for clients).
  if (me?.role === "client") {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top }}>
        {header}
        <Empty text={tr("chat.teamOnly")} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top,
      ...(wide ? { borderLeftWidth: 1, borderColor: t.glassBorder } : null) }}>
      {header}
      <View style={{ flex: 1 }}>
        <ScrollView ref={scroll} onScroll={onScroll} scrollEventThrottle={64} style={{ flex: 1 }}
          contentContainerStyle={{ padding: 12, paddingBottom: 24, width: "100%", maxWidth: colMax, alignSelf: "center" }}>
          {msgs.length === 0
            ? <Empty text={tr("chat.empty")} />
            : <Transcript steps={msgs.map(toStep)} />}
          {busy ? <Text style={{ color: t.txtTertiary, fontSize: 12, paddingTop: 8 }}>{tr("chat.thinking")}</Text> : null}
        </ScrollView>
        {!atBottom ? (
          <Pressable onPress={() => { scroll.current?.scrollToEnd({ animated: true }); setAtBottom(true); }}
            style={{ position: "absolute", right: 14, bottom: (kb > 0 ? kb : 0) + 96, flexDirection: "row", alignItems: "center", gap: 4,
              backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1, borderRadius: 16,
              paddingHorizontal: 12, paddingVertical: 7, ...(Platform.OS === "web" ? {} : { elevation: 6 }) }}>
            <Ionicons name="arrow-down" size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>{tr("chat.latest")}</Text>
          </Pressable>
        ) : null}

        <View style={{ width: "100%", maxWidth: colMax, alignSelf: "center" }}>
          <Composer onSend={send} busy={busy} onStop={stop} models={models ?? ["auto"]}
            placeholder={tr("chat.placeholder")} draftKey="board-copilot"
            bottomInset={kb > 0 ? insets.bottom + 10 : insets.bottom + 8} />
        </View>
        {kb > 0 ? <View style={{ height: kb }} /> : null}
      </View>
    </View>
  );
}

// Desktop overlay: a right-side panel over the DIMMED board, which STAYS mounted
// and visible because this renders inside the board screen (not as a route). The
// board tab mounts this; it no-ops on phone / when closed. Tapping the board area
// (the flex-1 backdrop) closes it.
export function CopilotOverlay() {
  const t = useTheme();
  const tr = useT();
  const { width } = useWindowDimensions();
  const wide = Platform.OS === "web" && width >= 900;
  const open = useCopilotPanel((s) => s.open);
  const hide = useCopilotPanel((s) => s.hide);
  if (!wide || !open) return null;
  return (
    <View style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, flexDirection: "row", backgroundColor: "#00000073" }}>
      <Pressable style={{ flex: 1 }} onPress={hide} accessibilityLabel={tr("chat.close")} />
      <View style={{ width: 540, maxWidth: "48%", ...(Platform.OS === "web" ? { boxShadow: "-8px 0 24px rgba(0,0,0,0.35)" } as any : {}) }}>
        <ChatBody onClose={hide} wide />
      </View>
    </View>
  );
}

export default function ChatScreen() {
  const router = useRouter();
  const tr = useT();
  const { width } = useWindowDimensions();
  const wide = Platform.OS === "web" && width >= 900;
  // Phone: the chat is a full-screen route. Desktop reaches the copilot via the
  // in-page CopilotOverlay (board FAB opens the panel store), NOT this route — but
  // if a wide window ever lands here directly (deep link / reload), still render
  // as a panel rather than a full-bleed takeover.
  if (wide) {
    return (
      <View style={{ flex: 1, flexDirection: "row", backgroundColor: "#00000073" }}>
        <Pressable style={{ flex: 1 }} onPress={() => router.back()} accessibilityLabel={tr("chat.close")} />
        <View style={{ width: 540, maxWidth: "48%" }}><ChatBody onClose={() => router.back()} wide /></View>
      </View>
    );
  }
  return <ChatBody onClose={() => router.back()} wide={false} />;
}
