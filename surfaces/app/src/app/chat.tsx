import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Animated, Keyboard, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { create } from "zustand";

import { api, neverDelivered, type ChatMsg, type SteerOpts } from "@/data/client";
import type { VoiceClip } from "@/data/voice";
import { useModels } from "@/data/use_models";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { planLabel, useAiFlat } from "@/ui/billing";
import { Composer } from "@/ui/card_composer";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { UnsentStrip } from "@/ui/outbox_strip";
import * as outbox from "@/data/outbox";
import { ContextMeter } from "@/ui/context_meter";
import { Empty } from "@/ui/kit";
import { VoiceMode, voiceUsable } from "@/ui/voice_mode";
import { useResponsive } from "@/ui/responsive";
import * as glassVoice from "@/data/glasses";

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
// (surfaces/app/src/ui/card_transcript.tsx + card_composer.tsx). Only the submit target
// differs (api.chat here vs api.steer on a card), so there is ONE chat UI to
// maintain, not two. The board's flat ChatMsg log is mapped onto the transcript
// step model below.
function toStep(m: ChatMsg, me?: string): TStep {
  const mine = m.cls === "user" || m.cls === "you";
  return {
    role: mine ? "user" : "assistant",
    kind: "text",
    cls: m.cls,
    text: m.cls === "error" ? "⚠ " + m.text : m.text,
    ts: m.ts,
    // Henry's identity on EVERY reply here (not just proactive `pm` pushes) -
    // this surface is Henry-only, so every non-user message is him.
    by: mine ? me : (m.cls !== "error" ? "Henry" : undefined),
    byKind: mine ? "human" : (m.cls !== "error" ? "henry" : undefined),
    agent: m.cls === "pm",   // legacy flag, superseded by byKind above
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
  // `mid`    — the id this turn was SENT with (client.ts's replay token, which
  //            is also the identity the daemon echoes back on the persisted
  //            entry). Retiring by this instead of by text is the whole fix.
  // `anchor` — how long the server list was when this turn was queued, so the
  //            optimistic bubble is INSERTED where it belongs instead of pinned
  //            to the very end. Without it a PM message that lands mid-turn
  //            renders before a message that was sent earlier.
  const [pending, setPending] = useState<{ id: number; key: string; mid: string; baseline: number; anchor: number; msgs: ChatMsg[] }[]>([]);
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
  // The cursor is (turn, seq), never seq alone: the daemon restarts seq at 1
  // every turn, so after a steer the old turn's high seq would make every clip
  // of the NEW answer look like a duplicate — text on screen, speech silently
  // dropped (measured 2026-08-23). Same addressing the Realtime APIs use:
  // audio belongs to a response id, and a chunk from another turn is judged by
  // its turn, not by a shared counter.
  const voiceCur = useRef({ turn: 0, seq: 0 });
  const takeClips = useCallback((r: { voice?: (VoiceClip & { turn?: number; seq: number })[] } | null) => {
    const sink = voiceSink.current;
    if (!sink || !r?.voice) return;
    const cur = voiceCur.current;
    for (const c of r.voice) {
      const ct = c.turn ?? 0;            // old daemon: no turn ids, one shared line
      if (ct < cur.turn) continue;       // an interrupted answer's leftovers
      if (ct > cur.turn) { cur.turn = ct; cur.seq = 0; }
      // Monotonic guard, not an assumption: the drain in ask() can overlap one
      // poll, and delivering a chunk twice would say the same sentence twice.
      if (c.seq <= cur.seq) continue;
      cur.seq = c.seq;
      sink(c);
    }
  }, []);
  useEffect(() => {
    if (!busy) { setStream(""); setThink(""); return; }
    let alive = true, to: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api.chatLive(voiceSink.current ? voiceCur.current.seq : undefined,
          voiceSink.current ? voiceCur.current.turn : undefined);
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
    // IDENTITY FIRST. The daemon echoes the `mid` this turn was sent with back
    // on the persisted entry (copilot.chat -> client_msg_id), so an exact match
    // retires exactly this copy — even when the same sentence was sent twice,
    // and even when the stored text differs by a character.
    const seenIds = new Set<string>();
    const counts = new Map<string, number>();
    for (const m of server) {
      if (m.cls !== "user" && m.cls !== "you") continue;
      if (m.client_msg_id) seenIds.add(m.client_msg_id);
      const key = (m.text ?? "").trim();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    setPending((p) => p.filter((tn) => {
      if (tn.mid && seenIds.has(tn.mid)) return false;
      // COMPAT(chatClientMsgId): added 2026-08-29, remove once every daemon in
      // use echoes client_msg_id. Counting same-TEXT occurrences is what this
      // used to do exclusively, and it is why a copy could stick forever: if the
      // stored text never matched, the count never rose and the bubble stayed
      // pinned to the bottom of the chat. Kept only so a turn sent to an older
      // daemon still clears. Same shim, same reasoning, same dated-cleanup rule
      // Paseo applies to its own text fallback.
      return (counts.get(tn.key) ?? 0) <= tn.baseline;
    }));
  }, [server]);   // eslint-disable-line react-hooks/exhaustive-deps
  // INSERTED AT ITS ANCHOR, not appended. `[...server, ...pending]` put every
  // optimistic bubble after the entire server list, so anything that arrived
  // while a turn was running — a PM watchdog message, another device's turn —
  // rendered BEFORE a message that had been sent earlier.
  const msgs = useMemo<ChatMsg[]>(() => {
    const base = server ?? [];
    if (!pending.length) return base;
    const out: ChatMsg[] = [];
    let cursor = 0;
    // by anchor, so two turns queued in order stay in order
    for (const tn of [...pending].sort((a, b) => a.anchor - b.anchor)) {
      // clamped: the history can be compacted between queue and render, and an
      // anchor past the end must degrade to "at the end", never throw away rows.
      const at = Math.min(Math.max(tn.anchor, cursor), base.length);
      out.push(...base.slice(cursor, at), ...tn.msgs);
      cursor = at;
    }
    out.push(...base.slice(cursor));
    return out;
  }, [server, pending]);

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
  function queueTurn(id: number, q: string, mid: string) {
    const baseline = (server ?? []).filter((m) => (m.cls === "user" || m.cls === "you") && (m.text ?? "").trim() === q).length
      + pending.filter((tn) => tn.key === q).length;
    setPending((p) => [...p, {
      id, key: q, mid, baseline,
      // Where this bubble belongs: after everything the server had shown at the
      // moment it was sent, and BEFORE anything that arrives afterwards.
      anchor: (server ?? []).length,
      msgs: [{ cls: "user", text: q, client_msg_id: mid }],
    }]);
  }
  const appendReply = (id: number, msg: ChatMsg) =>
    setPending((p) => p.map((tn) => tn.id === id ? { ...tn, msgs: [...tn.msgs, msg] } : tn));

  // `retryOf` = the outbox row this send is re-attempting, so a success settles
  // THAT row instead of leaving a duplicate parked, and a second failure counts
  // the attempt instead of parking the same text twice.
  async function send(raw: string, opts: SteerOpts, retryOf?: string) {
    const q = raw.trim();
    if (!q) return;
    setBusy(true);
    const id = ++turn.current;
    // Minted HERE, before the request, so the optimistic bubble already carries
    // the identity the daemon will echo back. Same token client.ts would have
    // minted itself; passing it in only moves the minting one step earlier.
    const mid = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    queueTurn(id, q, mid);
    try {
      const r = await api.chat(q, { ...opts, mid });
      // Past the await = the daemon answered. THAT is the proof a retried
      // message is delivered; nothing earlier is (a dispatched request is not
      // a received one).
      if (retryOf) await outbox.settle(retryOf);
      if (turn.current !== id) return;   // cancelled/superseded — drop this reply
      if (r.duplicate && !r.reply) {
        // A transport layer replayed this POST and the daemon refused to run a
        // second turn (cells/copilot/chat_dedupe.py) while the original was
        // still going. There is no answer to render HERE — appending
        // "chat.noReply" would put a phantom empty turn in the chat, which is
        // the cosmetic half of the very bug this path exists to stop. The
        // history poll below delivers the real turn when it lands.
        qc.invalidateQueries({ queryKey: ["chatHistory"] });
        return;
      }
      const actions = (r.actions ?? []).map((a) => a.detail || a.tool).filter(Boolean).join("\n");
      appendReply(id, { cls: r.error ? "error" : "bot",
        text: [actions && "⚙ " + actions.replace(/\n/g, "\n⚙ "), r.reply || r.error || tr("chat.noReply")].filter(Boolean).join("\n\n") });
      qc.invalidateQueries({ queryKey: ["tracks"] });
      qc.invalidateQueries({ queryKey: ["chatHistory"] });   // pull the persisted turn (+ any PM msgs)
    } catch (e) {
      const msg = String((e as Error).message);
      // Park BEFORE any UI work and REGARDLESS of supersession: the optimistic
      // bubble is component state and dies with the screen, so the outbox is the
      // only thing standing between a failed send and a lost message.
      if (neverDelivered(e)) {
        if (retryOf) await outbox.retried(retryOf, msg);
        else await outbox.park("board", q, opts, msg, Date.now());
      }
      if (turn.current !== id) return;
      appendReply(id, { cls: "error", text: msg });
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
    // Same identity discipline as the typed path: a SPOKEN turn is an ordinary
    // /chat turn (see the note above), so it must carry a mid too - otherwise
    // exactly the messages dictated in voice mode fall back to text matching.
    const mid = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    queueTurn(id, text.trim(), mid);
    // Registering the sink is what switches the daemon from "one clip at the
    // end" to "a sentence at a time" — the two must be decided together, or the
    // owner gets a turn that renders speech nobody collects.
    voiceSink.current = onClip ?? null;
    // Reset only the seq half: the turn half may only move FORWARD (takeClips),
    // or a superseded drain could re-adopt the interrupted turn's clips.
    //
    // And the seq half only resets while we have never seen a turn id (a
    // LEGACY daemon, where seq is the whole cursor). On a turn-id daemon the
    // previous turn's stream stays current until the daemon begins the new
    // one - a zeroed seq in that window makes the poller re-collect EVERY
    // clip of the finished answer, and Henry audibly says the whole previous
    // message again (owner report 2026-08-23 evening, "viele Nachrichten
    // doppelt"). With turn ids the correct reset happens in takeClips the
    // moment the new turn's first clip arrives (ct > turn -> seq = 0).
    if (voiceCur.current.turn === 0) voiceCur.current.seq = 0;
    try {
      const r = await api.chat(text, { voice: onClip ? "stream" : undefined, mid });
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
          // A superseded turn's drain must DIE, not keep collecting: it shares
          // the cursor with the turn that replaced it, and measured 2026-08-23
          // it re-raised the seq the new ask() had just reset — every clip of
          // the new answer then judged "already played" and dropped.
          if (turn.current !== id) break;
          const live = await api.chatLive(voiceCur.current.seq, voiceCur.current.turn).catch(() => null);
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

  // GLASSES CONVERSATION — hands-free loop through GlassVoiceService (native,
  // Android only, owner only). The button is an AFFORDANCE, not a status: the
  // service's own foreground notification is the truth surface for "listening/
  // speaking" (its state lives outside React and survives this screen). Config
  // is fetched lazily at start — glance_origin + glance_token come from daemon
  // settings, and passing the RELAY url instead would fail silently off-LAN
  // (data/glasses.ts explains which URL is the right one).
  const glassAvail = useMemo(() => glassVoice.caps().available, []);
  const [glassOn, setGlassOn] = useState(false);
  const [glassBusy, setGlassBusy] = useState(false);
  async function toggleGlasses() {
    if (glassBusy) return;
    if (glassOn) { glassVoice.stopListening(); setGlassOn(false); return; }
    setGlassBusy(true);
    try {
      const s = await api.settings().catch(() => null);
      const origin = (s?.glance_origin || "").trim();
      const token = (s?.glance_token || "").trim();
      if (!origin || !token || !glassVoice.configure(origin, token)) {
        appendReply(++turn.current, {
          cls: "error",
          text: tr("chat.glassesUnconfigured"),
        });
        return;
      }
      if (glassVoice.listen(true)) setGlassOn(true);
    } finally {
      setGlassBusy(false);
    }
  }
  const header = (
    <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
      <Pressable onPress={onClose} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
      <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{tr("chat.title")}</Text>
      {glassAvail && me?.role === "owner" ? (
        <Pressable onPress={toggleGlasses} hitSlop={10} style={{ marginLeft: "auto" }}
                   accessibilityLabel={tr("chat.glassesTalk")}>
          <Ionicons name="glasses-outline" size={24}
                    color={glassOn ? t.accent : t.txtSecondary} />
        </Pressable>
      ) : null}
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
            : <Transcript me={me?.name} steps={(() => {
                const s = msgs.map((m) => toStep(m, me?.name));
                // while streaming, append the board agent's live typing as a
                // streaming bot step - the SAME row a card worker streams into.
                if (busy && stream.trim()) s.push({ role: "assistant", kind: "text", text: stream, streaming: true, by: "Henry", byKind: "henry" });
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
          <UnsentStrip scope="board" onRetry={(m) => send(m.text, m.opts, m.id)} />
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
  const { wide } = useResponsive();
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
  const { wide } = useResponsive();
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
