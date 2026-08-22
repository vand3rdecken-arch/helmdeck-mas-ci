import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Animated, Keyboard, Platform, Pressable, ScrollView, Text, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { create } from "zustand";

import { api, type ChatMsg, type SteerOpts } from "@/data/client";
import type { VoiceClip } from "@/data/voice";
import { useModels } from "@/data/use_models";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { planLabel, useAiFlat } from "@/ui/billing";
import { Composer } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { ContextMeter } from "@/ui/context_meter";
import { Empty } from "@/ui/kit";
import { VoiceMode, voiceUsable } from "@/ui/voice_mode";

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

// A live "thinking" row while the board agent works: pulsing dots + an elapsed
// clock (like Claude), so the wait reads as active reasoning, not a frozen
// "denkt". The copilot runs blocking (no token stream yet), so this is the
// honest signal we can give until the run returns / its actions stream in.
function ThinkingIndicator({ preview }: { preview?: string }) {
  const t = useTheme();
  const tr = useT();
  const d0 = useRef(new Animated.Value(0.25)).current;
  const d1 = useRef(new Animated.Value(0.25)).current;
  const d2 = useRef(new Animated.Value(0.25)).current;
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const pulse = (v: Animated.Value, delay: number) =>
      Animated.loop(Animated.sequence([
        Animated.delay(delay),
        Animated.timing(v, { toValue: 1, duration: 300, useNativeDriver: true }),
        Animated.timing(v, { toValue: 0.25, duration: 300, useNativeDriver: true }),
        Animated.delay(360 - delay),
      ]));
    const anims = [pulse(d0, 0), pulse(d1, 160), pulse(d2, 320)];
    anims.forEach((a) => a.start());
    const iv = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => { anims.forEach((a) => a.stop()); clearInterval(iv); };
  }, [d0, d1, d2]);
  // the live reasoning tail (last ~2 lines) - a real Zwischenmeldung instead of a
  // dead wait; the model streams thinking ~9s before the prose.
  const tail = (preview || "").replace(/\s+/g, " ").trim().slice(-180);
  return (
    <View style={{ paddingTop: 10, paddingLeft: 2, gap: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Ionicons name="sparkles" size={13} color={t.accent2} />
        <Text style={{ color: t.txtSecondary, fontSize: 12.5 }}>{tr("chat.thinking")}</Text>
        <View style={{ flexDirection: "row", gap: 3, marginLeft: 1 }}>
          {[d0, d1, d2].map((d, i) => (
            <Animated.View key={i} style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: t.accent2, opacity: d }} />
          ))}
        </View>
        {secs >= 2 ? <Text style={{ color: t.txtTertiary, fontSize: 11 }}>· {secs}s</Text> : null}
      </View>
      {tail ? (
        <Text numberOfLines={2} style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15, fontStyle: "italic", paddingLeft: 21 }}>
          {tail}
        </Text>
      ) : null}
    </View>
  );
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
  // Optimistic turns layered OVER the server transcript, never merged into one
  // mutable list. The old shape (setMsgs(data.messages) whenever !busy) raced
  // the busy->false edge: a refetch that hadn't persisted the just-sent turn
  // yet would clobber the echo and the reply until the next 8s poll - the
  // "my message vanished" bug. Same reconcile discipline as the card chat
  // (card/[id].tsx pending+baseline): a turn is only dropped once the server
  // transcript actually carries its user text PAST the baseline count, so a
  // repeated message ("continue" twice) can't be stripped by its older twin.
  const [pending, setPending] = useState<{ id: number; key: string; baseline: number; msgs: ChatMsg[] }[]>([]);
  // the board agent's live streaming prose while a turn runs - polled from
  // /chat/live so the board chat STREAMS like a card (one shared surface).
  const [stream, setStream] = useState("");
  const [think, setThink] = useState("");
  // Voice mode rides THIS poll rather than opening its own. /chat/live is the one
  // place a running turn is observable, and a second poller would mean a second
  // cursor over the same chunks — two owners of one truth — plus double the relay
  // round trips. So voice mode registers a sink and this loop hands clips over as
  // they land; the cursor lives here, beside the poll that moves it.
  const voiceSink = useRef<((c: VoiceClip) => void) | null>(null);
  const voiceSeq = useRef(0);
  const takeClips = useCallback((r: { voice?: (VoiceClip & { seq: number })[] } | null) => {
    const sink = voiceSink.current;
    if (!sink || !r?.voice) return;
    for (const c of r.voice) {
      // Monotonic guard, not an assumption: the drain in ask() can overlap one
      // poll, and delivering a chunk twice would say the same sentence twice.
      if (c.seq <= voiceSeq.current) continue;
      voiceSeq.current = c.seq;
      sink(c);
    }
  }, []);
  useEffect(() => {
    if (!busy) { setStream(""); setThink(""); return; }
    let alive = true, to: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api.chatLive(voiceSink.current ? voiceSeq.current : undefined);
        if (alive && r) { setStream(r.text || ""); setThink(r.thinking || ""); takeClips(r); }
      } catch { /* keep polling */ }
      if (alive) to = setTimeout(poll, 500);
    };
    poll();
    return () => { alive = false; clearTimeout(to); };
  }, [busy, takeClips]);
  const qc = useQueryClient();
  const scroll = useRef<ScrollView>(null);
  const [atBottom, setAtBottom] = useState(true);
  // Edge-to-edge (Expo SDK 57) makes Android ignore adjustResize, so the composer
  // hides behind the keyboard. Measure the keyboard height and lift the content
  // manually (a height:kb spacer) - works on both platforms without a native lib.
  const [kb, setKb] = useState(0);
  const [voiceOpen, setVoiceOpen] = useState(false);
  // Asked once per mount, not per render: capability is resolved by actually
  // probing the runtime (data/voice.ts caps()), which must not run on every
  // keystroke. A build with no audio module simply has no microphone button.
  const canVoice = useRef(voiceUsable()).current;
  // A DONE-push tap arrives as ?vq=<question>: open voice mode and have Henry
  // SPEAK the result (owner 2026-08-22) instead of parking the news as text.
  // Consumed once per value so a re-render doesn't re-fire the turn.
  const { vq } = useLocalSearchParams<{ vq?: string }>();
  const [voiceAsk, setVoiceAsk] = useState<string | undefined>(undefined);
  const vqDone = useRef<string | undefined>(undefined);
  useEffect(() => {
    const q = typeof vq === "string" ? vq : undefined;
    if (!q || !canVoice || vqDone.current === q) return;
    vqDone.current = q;
    setVoiceAsk(q);
    setVoiceOpen(true);
  }, [vq, canVoice]);
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
  // moves on its own); optimistic turns live in `pending`, layered on top.
  const { data } = useQuery({ queryKey: ["chatHistory"], queryFn: api.chatHistory, enabled: me?.role !== "client", refetchInterval: 8000 });
  const { data: models } = useModels(me?.role !== "client");
  // PM-session economics (card parity): context fill + spend, folded by the
  // daemon per finished turn (copilot._fold_stats) and served with the history.
  const stats = data?.stats;
  const flat = useAiFlat();

  // A pending turn dies only when the server history has caught up with it:
  // the daemon persists a turn as a unit (user msg + reply folded together),
  // so once the user text's occurrence count exceeds this turn's baseline the
  // whole optimistic pair is redundant and the persisted version takes over.
  const server = data?.messages;
  useEffect(() => {
    if (!server || !pending.length) return;
    const counts = new Map<string, number>();
    for (const m of server) {
      if (m.cls !== "user" && m.cls !== "you") continue;
      const key = (m.text ?? "").trim();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    setPending((p) => p.filter((tn) => (counts.get(tn.key) ?? 0) <= tn.baseline));
  }, [server]);   // eslint-disable-line react-hooks/exhaustive-deps
  const msgs = useMemo<ChatMsg[]>(
    () => [...(server ?? []), ...pending.flatMap((tn) => tn.msgs)],
    [server, pending]);

  // auto-pin to newest (incl. the PM's proactive messages) when already near the
  // bottom - same pattern as the card chat, so opening lands you at the latest.
  useEffect(() => {
    if (atBottom) setTimeout(() => scroll.current?.scrollToEnd({ animated: false }), 30);
  }, [msgs.length, atBottom]);
  const onScroll = (e: { nativeEvent: { contentOffset: { y: number }; contentSize: { height: number }; layoutMeasurement: { height: number } } }) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    setAtBottom(contentSize.height - contentOffset.y - layoutMeasurement.height < 60);
  };

  // baseline = this occurrence's rank among same-text user messages already
  // visible (server + pending) at queue time - see the reconcile effect above.
  function queueTurn(id: number, q: string) {
    const baseline = (server ?? []).filter((m) => (m.cls === "user" || m.cls === "you") && (m.text ?? "").trim() === q).length
      + pending.filter((tn) => tn.key === q).length;
    setPending((p) => [...p, { id, key: q, baseline, msgs: [{ cls: "user", text: q }] }]);
  }
  const appendReply = (id: number, msg: ChatMsg) =>
    setPending((p) => p.map((tn) => tn.id === id ? { ...tn, msgs: [...tn.msgs, msg] } : tn));

  async function send(raw: string, opts: SteerOpts) {
    const q = raw.trim();
    if (!q) return;
    setBusy(true);
    const id = ++turn.current;
    queueTurn(id, q);
    try {
      const r = await api.chat(q, opts);
      if (turn.current !== id) return;   // cancelled/superseded — drop this reply
      const actions = (r.actions ?? []).map((a) => a.detail || a.tool).filter(Boolean).join("\n");
      appendReply(id, { cls: r.error ? "error" : "bot",
        text: [actions && "⚙ " + actions.replace(/\n/g, "\n⚙ "), r.reply || r.error || tr("chat.noReply")].filter(Boolean).join("\n\n") });
      qc.invalidateQueries({ queryKey: ["tracks"] });
      qc.invalidateQueries({ queryKey: ["chatHistory"] });   // pull the persisted turn (+ any PM msgs)
    } catch (e) {
      if (turn.current !== id) return;
      appendReply(id, { cls: "error", text: String((e as Error).message) });
    } finally {
      if (turn.current === id) { setBusy(false); setTimeout(() => scroll.current?.scrollToEnd(), 50); }
    }
  }

  function stop() {
    turn.current++;              // invalidate the in-flight turn client-side
    api.chatCancel().catch(() => {});   // kill the copilot subprocess server-side
    setBusy(false);
  }

  // VOICE MODE runs the SAME turn as the composer — api.chat, same session, same
  // history — with one flag added: `voice: true` makes the daemon also render
  // Henry's prose to speech and inline it (routes_copilot.chat_post). So a
  // spoken turn lands in the text transcript too, and switching between talking
  // and typing mid-conversation loses nothing. Two send paths would have been
  // two chats one refresh apart.
  async function ask(text: string, onClip?: (c: VoiceClip) => void) {
    setBusy(true);
    const id = ++turn.current;
    queueTurn(id, text.trim());
    // Registering the sink is what switches the daemon from "one clip at the
    // end" to "a sentence at a time" — the two must be decided together, or the
    // owner gets a turn that renders speech nobody collects.
    voiceSink.current = onClip ?? null;
    voiceSeq.current = 0;
    try {
      const r = await api.chat(text, { voice: onClip ? "stream" : undefined });
      if (turn.current !== id) return { reply: "", clip: null };   // cancelled/superseded
      const said = r.reply || r.error || tr("chat.noReply");
      appendReply(id, { cls: r.error ? "error" : "bot", text: said });
      qc.invalidateQueries({ queryKey: ["tracks"] });
      qc.invalidateQueries({ queryKey: ["chatHistory"] });
      // DRAIN. The POST returns when the MODEL is done, which is not when the
      // SPEECH is: the last sentence is usually still rendering. The live poller
      // stops with `busy` a moment from now, so the tail has to be collected
      // here — without this the answer reliably loses its final sentence, and
      // only on slow renders, which is the worst way to find a bug.
      if (onClip) {
        for (let i = 0; i < 40; i++) {
          const live = await api.chatLive(voiceSeq.current).catch(() => null);
          takeClips(live);
          if (!live?.voice_pending) break;
          await new Promise((res) => setTimeout(res, 250));
        }
      }
      // Speak the PROSE only. The daemon already strips the ```actions block and
      // any <helmdeck-ask> markup before rendering, so what is heard and what is
      // read are the same sentence — never machine syntax read aloud.
      return { reply: said, clip: r.voice ?? null };
    } finally {
      if (turn.current === id) { setBusy(false); voiceSink.current = null; }
    }
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
          {msgs.length === 0 && !(busy && stream.trim())
            ? <Empty text={tr("chat.empty")} />
            : <Transcript steps={(() => {
                const s = msgs.map(toStep);
                // while streaming, append the board agent's live typing as a
                // streaming bot step - the SAME row a card worker streams into.
                if (busy && stream.trim()) s.push({ role: "assistant", kind: "text", text: stream, streaming: true });
                return s;
              })()} />}
          {busy && !stream.trim() ? <ThinkingIndicator preview={think} /> : null}
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
          {/* Context meter — the SAME component the card chat renders (see
              ui/context_meter.tsx), fed by the PM session's own evidence: the
              daemon keeps the last call's context fill + a window derived from
              the model id (never a blind 200k). Like the card it updates per
              finished turn, because that is when the runtime reports usage. */}
          <ContextMeter tokens={stats?.ctx_tokens} window={stats?.ctx_window}
            style={{ paddingHorizontal: 14, paddingTop: 6 }} />
          {/* Usage line for the running PM session: turns + consumption. On the
              flat plan the honest unit is share-of-subscription (tokens as the
              fallback), on a metered plan the measured $ (owner decree). */}
          {stats && stats.turns > 0 ? (
            <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 10, paddingHorizontal: 14, paddingTop: 3 }}>
              {tr("chat.usage", {
                turns: stats.turns,
                cost: flat ? planLabel(tr, stats.plan_pct, (stats.tokens_in ?? 0) + (stats.tokens_out ?? 0))
                  : `AI $${(stats.cost ?? 0).toFixed(2)}`,
              })}
            </Text>
          ) : null}
          <Composer onSend={send} busy={busy} onStop={stop} models={models ?? ["auto"]}
            placeholder={tr("chat.placeholder")} draftKey="board-copilot"
            onVoice={canVoice ? () => setVoiceOpen(true) : undefined}
            bottomInset={kb > 0 ? insets.bottom + 10 : insets.bottom + 8} />
        </View>
        {kb > 0 ? <View style={{ height: kb }} /> : null}
      </View>
      <VoiceMode visible={voiceOpen} onClose={() => { setVoiceOpen(false); setVoiceAsk(undefined); }}
        onAsk={ask} onCancel={stop} busy={busy} initialAsk={voiceAsk} />
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
