import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Animated, AppState, Keyboard, Platform, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { create } from "zustand";

import { api, neverDelivered, type ChatMsg, type SteerOpts } from "@/data/client";
import { CHAT_FOCUS, usePresence } from "@/data/presence";
import { chatFallbackInterval, ensureChatFresh, useStreamCaps } from "@/data/stream";
import type { PendingQuestion } from "@/data/types";
import type { VoiceClip } from "@/data/voice";
import { useModels } from "@/data/use_models";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { planLabel, useAiFlat } from "@/ui/billing";
import { BackgroundTasks } from "@/ui/card_background";
import { Composer, type Recipient } from "@/ui/card_composer";
import { QuestionPanel } from "@/ui/card_question";
import { Transcript, type TStep } from "@/ui/card_transcript";
import { ChatScroll, type ChatScrollHandle } from "@/ui/chat_scroll";
import { ThreadList } from "@/ui/chat_threads";
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
// `context` is what the chat was opened ABOUT (harness-config-ui 5.5): the
// harness screen's "Henry fragen" hands over the row, the chip renders it above
// the composer, and the turn carries it - so Henry never has to guess which
// setting was meant. It rides on THIS store rather than on a prop because the
// panel is opened imperatively from anywhere (useCopilotPanel.getState().show()),
// which is the same reason `open` lives here.
export interface ChatContext {
  /** What the chip reads: "Abnahme · Grüne Karten automatisch annehmen". */
  label: string;
  /** The line the turn carries, naming the setting in Henry's own terms. */
  hint: string;
}
interface CopilotPanel {
  open: boolean; context?: ChatContext;
  show: (ctx?: ChatContext) => void;
  setContext: (ctx?: ChatContext) => void;
  hide: () => void;
  clearContext: () => void;
}
export const useCopilotPanel = create<CopilotPanel>((set) => ({
  open: false,
  context: undefined,
  // Opening WITHOUT a context CLEARS the previous one. A stale chip would
  // attach the last question's subject to an unrelated message, which is worse
  // than no chip at all - the chip's whole value is that it is trustworthy.
  show: (ctx) => set({ open: true, context: ctx }),
  // Hand over the subject WITHOUT arming the desktop panel - what the phone
  // path needs, because there the chat is the /chat route and `open` governs
  // only the wide-screen overlay. Callers used to show()+push(), which left
  // `open` true behind the route; a later resize to a wide window then popped
  // the overlay on top of the chat screen. Same clearing semantics as show().
  setContext: (ctx) => set({ context: ctx }),
  hide: () => set({ open: false }),
  clearContext: () => set({ context: undefined }),
}));

// Board copilot chat = the SAME transcript + composer UI as the card chat
// (surfaces/app/src/ui/card_transcript.tsx + card_composer.tsx). Only the submit target
// differs (api.chat here vs api.steer on a card), so there is ONE chat UI to
// maintain, not two. The board's flat ChatMsg log is mapped onto the transcript
// step model below.
// The mirrored-card label: "Frage · Kartenname". Composed HERE, not on the
// daemon, because each surface lays it out differently - the watch draws it as
// a TitleCard title, this draws it as the transcript's sender line. The daemon
// therefore ships the PARTS (kind + cardName), never a rendered string.
// `tr` is threaded in (module function, no hooks) so the label follows the app
// language like every other string - the first screenshot judge caught it as
// hardcoded "Frage" inside an otherwise English UI.
const CARD_KIND_KEY: Record<string, string> = {
  question: "chat.mirror.question", result: "chat.mirror.result",
  blocker: "chat.mirror.blocker", closed: "chat.mirror.closed",
};

function toStep(m: ChatMsg, me?: string, tr?: (k: string) => string): TStep {
  const mine = m.cls === "user" || m.cls === "you";
  // A mirrored card event is the WORKER speaking, not Henry. Attributing it to
  // Henry would be a lie the owner acts on: he would read a card waiting on a
  // decision as Henry's advice, and keeping those two apart is the entire job
  // of the transcript's sender model.
  // Henry filed/steered a card: the topic continues in that card's thread -
  // draw the hand-over as a tile, not as a sentence about plumbing.
  if (m.cls === "act" && m.card) {
    return { role: "assistant", kind: "card", cls: m.cls, card: m.card, label: m.cardName || m.card,
             text: m.text, ts: m.ts, by: "Henry", byKind: "henry" };
  }
  if (m.cls === "card") {
    const label = tr?.(CARD_KIND_KEY[m.kind ?? ""] ?? "chat.mirror.card") ?? "";
    return {
      role: "assistant", kind: "text", cls: m.cls, text: m.text, ts: m.ts,
      by: `${label} · ${m.cardName || m.card || "?"}`, byKind: "worker",
    };
  }
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

/** The question this chat is currently offering to answer, or null.
 *
 *  TWO kinds arrive here and both are answerable, which is the whole point of
 *  one inbox:
 *    * `cls:"card"` — a WORKER's question, mirrored in (card_mirror.py). Bound
 *      to a card, settled through POST /tracks/<id>/answer.
 *    * `cls:"bot"`  — HENRY's own, parsed off his reply at event time
 *      (cells/copilot/copilot.chat). Settled by POST /chat with `answer_to`,
 *      i.e. the choice becomes the owner's next message.
 *  Only the door differs; the panel and this selector are shared. Henry's used
 *  to be invisible here — his reply still carried the block as TEXT, so the
 *  transcript printed raw `<helmdeck-ask>` JSON at the owner (screenshot
 *  2026-08-29 17:56) and there was nothing to tap.
 *
 *  The NEWEST question that nothing later has settled. "Later" is positional,
 *  not temporal: the log is append-ordered. For a card that means any entry
 *  bound to the SAME card (the owner replied, or the card moved on); for Henry
 *  it means anyone speaking at all, since his questions live in the one
 *  conversation rather than beside it. Answering a superseded request_id is
 *  exactly the 409 both daemon doors raise, so not offering it is the honest UI
 *  for a state the server would reject anyway.
 *
 *  Deliberately ONE at a time. Several can wait at once, and a panel per
 *  question would turn the composer into a form; the owner answers the newest,
 *  and the next surfaces as soon as that one is settled. */
function openChatQuestion(msgs: ChatMsg[]): ChatMsg | null {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (!m.question) continue;
    const later = msgs.slice(i + 1);
    if (m.cls === "card" && m.kind === "question" && m.card) {
      return later.some((x) => x.card === m.card) ? null : m;
    }
    if (m.cls === "bot") {
      return later.some((x) => x.cls === "you" || x.cls === "user" || x.cls === "bot")
        ? null : m;
    }
  }
  return null;
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
  // What this conversation was opened ABOUT (harness-config-ui 5.5). Subscribed
  // here rather than passed down, because BOTH doors render this body - the
  // phone's /chat route and the desktop CopilotOverlay - and only the store is
  // reachable from both.
  const chatCtx = useCopilotPanel((s) => s.context);
  // Presence: while this body is mounted the owner is LOOKING at the Henry
  // transcript, so his own answer must not also buzz his pocket. It hangs on
  // ChatBody rather than on ChatScreen because BOTH doors render this - the
  // phone's full-screen route and the desktop CopilotOverlay - and a hook on
  // the route would have left the desktop reporting no focus at all.
  // The inverse is the point of the fix: leaving the chat resumes the push, so
  // an answer that lands while he is on the board or away reaches him.
  useEffect(() => {
    usePresence.getState().setFocusedCard(CHAT_FOCUS);
    return () => usePresence.getState().setFocusedCard(null);
  }, []);
  const [busy, setBusy] = useState(false);
  // phone: the conversation list is a full-screen sheet over the chat; on
  // desktop it is a permanent sidebar (CopilotOverlay/ChatScreen), so the
  // header button only exists on the narrow layout.
  const [threadsOpen, setThreadsOpen] = useState(false);
  const nav = useRouter();
  const busyRef = useRef(false);
  busyRef.current = busy;
  // The server transcript length when the CURRENT turn began - the anchor the
  // held stream is released against (see `held`). Captured at send/observe
  // time, NOT at hand-over: the daemon appends the bot row and bumps the
  // cursor BEFORE it answers the POST, so by the time busy flips the refetch
  // has often already landed the answer - a hand-over snapshot then already
  // contains it and the held copy never releases, i.e. the answer shows twice
  // (owner 2026-09-13, "Nachricht kam zwei mal an").
  const turnStartLen = useRef(0);
  const serverLenRef = useRef(0);
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
  // THE LAST STREAMED PROSE, kept on screen AFTER the turn ends until the
  // persisted bot line has actually arrived. `busy=false` used to wipe the
  // streaming bubble synchronously while the history refetch was still 1-3s
  // out over the relay - and if that refetch failed, the answer the owner had
  // just watched Henry type was simply gone (2026-09-12 22:06). `len` is the
  // server transcript length at hand-over: the hold is released the moment
  // the transcript grows past it with something that is not the owner's own
  // echo, i.e. the daemon's copy of this very answer (or its error).
  const [held, setHeld] = useState<{ text: string; len: number } | null>(null);   // len = turnStartLen at hand-over
  // A turn OBSERVED rather than sent: the daemon reports `running` on
  // /chat/live, so a screen that (re)mounts or resumes while Henry is still
  // working - or whose POST /chat died on the relay's 115s leg while the turn
  // went on - shows the thinking row and the stream instead of a dead
  // transcript. Derived from the daemon's own signal, never from a stored
  // flag (CLAUDE.md). While true, the live poll (not a POST) ends the turn.
  const derived = useRef(false);
  const [think, setThink] = useState("");
  // the tool action currently executing ("Bash: py ..."): tool rounds used to
  // go DARK in the live feed - since Henry actually checks (2026-09-02), the
  // silence sat exactly where his rigor lives. Paseo renders tool calls as
  // visible chips the moment they happen; this is that signal for the wait row.
  const [liveStatus, setLiveStatus] = useState("");
  // Transient tool steps (owner 2026-09-13): visible while Henry works, so a
  // 40s Bash round reads as work and not as a frozen spinner - rendered with
  // the SAME tool row a worker card uses, and gone the moment the turn ends
  // (they are never part of the persisted transcript).
  const [liveSteps, setLiveSteps] = useState<NonNullable<Awaited<ReturnType<typeof api.chatLive>>["steps"]>>([]);
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
    if (!busy) {
      // hand the stream over to `held` instead of dropping it (see `held`)
      setStream((cur) => {
        if (cur.trim()) setHeld({ text: cur, len: turnStartLen.current });
        return "";
      });
      setThink(""); setLiveStatus(""); setLiveSteps([]);
      derived.current = false;
      return;
    }
    let alive = true, to: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api.chatLive(voiceSink.current ? voiceCur.current.seq : undefined,
          voiceSink.current ? voiceCur.current.turn : undefined);
        if (alive && r) {
          setStream(r.text || ""); setThink(r.thinking || "");
          setLiveStatus(r.status || ""); takeClips(r);
          if (Array.isArray(r.steps)) setLiveSteps(r.steps);
          // An observed turn has no POST to end it: the daemon saying
          // "not running" IS the end. Strictly `false` - an old daemon omits
          // the field, and undefined must not end anything.
          if (derived.current && r.running === false) {
            derived.current = false;
            setBusy(false);
            void ensureChatFresh(qc);
            return;
          }
        }
      } catch { /* keep polling */ }
      if (alive) to = setTimeout(poll, 500);
    };
    poll();
    return () => { alive = false; clearTimeout(to); };
  }, [busy, takeClips]);
  const qc = useQueryClient();
  // The scroller (and its "↓ Neueste" pill) is ui/chat_scroll.tsx - the SAME
  // component the card chat uses. The hand-rolled copy that used to live here
  // positioned the pill against a wrapper that also held the composer stack, so
  // the composer swallowed every tap on it (owner report 2026-08-31).
  const scroll = useRef<ChatScrollHandle>(null);
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
  // The transcript moves on its own (Henry's answer, the PM's proactive
  // messages, a mirrored card event) and this query is how that reaches the
  // screen; optimistic turns live in `pending`, layered on top.
  //
  // The 8s poll that used to be hardcoded here was the only reason a Henry
  // answer ever appeared: the transcript is a JSON file, not a table, so
  // db._version never moved for it and the global stream never fired.
  // copilot._append_log now bumps a chat cursor and useGlobalStream
  // (_layout.tsx) waits on it over the same sealed hanging GET as the board,
  // invalidating exactly this query - event-driven, with the stream's own
  // reconnect as the catch-up path.
  //
  // The interval is therefore FALSE against any daemon that pushes chat events,
  // and only falls back to the old 8s against one that provably cannot (an OTA
  // and a daemon restart are independent events, so this bundle can meet an
  // older daemon - see data/stream.ts). Not a hedge: a fixed timer left in
  // "just in case" would keep the defect alive on every current daemon.
  const chatEvents = useStreamCaps((s) => s.chatEvents);
  const { data } = useQuery({
    queryKey: ["chatHistory"],
    queryFn: api.chatHistory,
    enabled: me?.role !== "client",
    refetchInterval: chatFallbackInterval(chatEvents),
  });
  const { data: models } = useModels(me?.role !== "client");
  // PM-session economics (card parity): context fill + spend, folded by the
  // daemon per finished turn (copilot._fold_stats) and served with the history.
  const stats = data?.stats;
  const flat = useAiFlat();
  const modeBase = [{ id: "auto", label: tr("card.perm.auto") }, { id: "bypassPermissions", label: tr("card.perm.full") },
    { id: "acceptEdits", label: tr("card.perm.edit") }, { id: "plan", label: tr("card.perm.plan") }]
    .filter((m) => m.id !== "bypassPermissions" || me?.role === "owner");
  const cur = data?.hands_mode;
  const henryModes = me?.role === "client" ? undefined
    : [...modeBase.filter((m) => m.id === cur), ...modeBase.filter((m) => m.id !== cur)];

  // A pending turn dies only when the server history has caught up with it:
  // the daemon persists a turn as a unit (user msg + reply folded together),
  // so once the user text's occurrence count exceeds this turn's baseline the
  // whole optimistic pair is redundant and the persisted version takes over.
  const server = data?.messages;
  serverLenRef.current = (server ?? []).length;
  // Release the held stream once the daemon's own copy is on screen: any
  // non-owner line that landed after the turn began IS that copy (or the
  // turn's error line) - regardless of whether it arrived before or after
  // busy flipped.
  useEffect(() => {
    if (!held || !server) return;
    if (server.slice(held.len).some((m) => m.cls !== "user" && m.cls !== "you")) setHeld(null);
  }, [server, held]);
  // OBSERVE a turn already running on the daemon (mount + every foreground
  // resume): /chat/live `running` is the one place that state is owned.
  useEffect(() => {
    let alive = true;
    const probe = async () => {
      try {
        const r = await api.chatLive();
        if (!alive || !r || r.running !== true || busyRef.current) return;
        derived.current = true;
        turnStartLen.current = serverLenRef.current;
        turn.current++;            // a late POST result of a dead screen cannot end this one
        setBusy(true);
      } catch { /* offline - the stream loop's reconnect is the catch-up */ }
    };
    void probe();
    const sub = AppState.addEventListener("change", (st) => { if (st === "active") void probe(); });
    return () => { alive = false; sub.remove(); };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps
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

  // THE INBOX'S OPEN CARD QUESTION, and therefore the composer's routing
  // target. Derived from the transcript on every render rather than stored:
  // the answer can arrive from another device, from the watch, or from the
  // notification's own buttons, and a remembered target would keep offering to
  // answer a question that is already settled - the stale-flag class this repo
  // keeps out (CLAUDE.md: derived, not stored).
  const openQ = useMemo(() => openChatQuestion(msgs), [msgs]);
  const cardRecipients = useMemo<Recipient[]>(() => openQ?.card ? [
    { id: "henry", label: tr("transcript.boardAgent"), color: t.accent2,
      icon: "sparkles-outline", hint: tr("card.chat.mentionHenry") },
    { id: `card:${openQ.card}`, label: openQ.cardName || openQ.card, color: t.accent,
      icon: "construct-outline", hint: tr("card.chat.mentionWorker") },
  ] : [], [openQ, tr, t]);
  // undefined, not "henry", when nothing is waiting: the Composer hides the
  // whole recipient affordance on a single-target surface, which is what the
  // board chat has always been and must stay when no card is asking.
  const replyTarget = openQ?.card ? `card:${openQ.card}` : undefined;

  // Auto-pin to newest lives in ChatScroll now, driven by the scroll view's own
  // content-size/layout signals rather than by `msgs.length` - the count does
  // not move while Henry STREAMS into the last bubble, which is exactly when
  // following the conversation matters most.

  // baseline = this occurrence's rank among same-text user messages already
  // visible (server + pending) at queue time - see the reconcile effect above.
  function queueTurn(id: number, q: string, mid: string) {
    const baseline = (server ?? []).filter((m) => (m.cls === "user" || m.cls === "you") && (m.text ?? "").trim() === q).length
      + pending.filter((tn) => tn.key === q).length;
    setHeld(null);
    turnStartLen.current = (server ?? []).length;
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
  // `opts.answer_to`/`opts.answers` mark a TAPPED answer to one of Henry's own
  // questions: they ride through to POST /chat, where the daemon validates the
  // choice and writes the message text itself. `raw` is then only the optimistic
  // preview (see sendAnswer) - the daemon's wording replaces it on the next
  // history poll. Should the send fail and land in the outbox, retrying it drops
  // back to sending that preview as an ordinary message, which still reads as
  // the owner's answer and still settles the question.
  async function send(raw: string, opts: SteerOpts & {
    answer_to?: string; answers?: Record<string, string | string[]>;
  }, retryOf?: string) {
    const q = raw.trim();
    if (!q) return;
    setBusy(true);
    const id = ++turn.current;
    // Minted HERE, before the request, so the optimistic bubble already carries
    // the identity the daemon will echo back. Same token client.ts would have
    // minted itself; passing it in only moves the minting one step earlier.
    const mid = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    queueTurn(id, q, mid);
    // Routed to a CARD when the composer's target is one (`card:<id>`), so the
    // words reach that worker instead of starting a Henry turn. The id comes
    // from the chip the owner can see, which in turn comes from the `card` the
    // mirror stamped on the message - at no point is it inferred from the text.
    const to = opts.to ?? replyTarget;
    const replyCard = to?.startsWith("card:") ? to.slice("card:".length) : "";
    // THE CONTEXT TRAVELS WITH THE TURN (harness-config-ui 5.5), but NOT into
    // the owner's own bubble: queueTurn above already rendered what he typed,
    // and echoing a machine-written "es geht um ..." line back at him as his
    // words would be the screen putting sentences in his mouth. Henry gets the
    // subject, the transcript stays his.
    const ctx = useCopilotPanel.getState().context;
    const wire = ctx?.hint ? ctx.hint + "\n\n" + q : q;
    try {
      const r = await api.chat(wire, {
        ...opts, mid, ...(replyCard ? { reply_to_card: replyCard } : {}) });
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
      if (r.routed) {
        // The message went to a card, not to Henry. There is no reply to
        // render: the worker answers in its own turn, and that turn's END is
        // what comes back here as a mirrored `result`. Appending
        // "chat.noReply" would put a phantom empty Henry turn under the
        // owner's own message - the same cosmetic defect the `duplicate`
        // branch above exists to avoid.
        qc.invalidateQueries({ queryKey: ["tracks"] });
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
      // The POST leg over the relay is bounded (daemon _local 115s, relay
      // 120s) while a Henry turn is not - so a transport error here usually
      // means "the answer is still being written", not "it failed". Ask the
      // daemon: if the turn is running, keep observing it via /chat/live and
      // let the history deliver the answer; only a turn that is NOT running
      // gets the error bubble.
      try {
        const live = await api.chatLive();
        if (turn.current === id && live?.running === true) { derived.current = true; return; }
      } catch { /* daemon unreachable - fall through to the error bubble */ }
      appendReply(id, { cls: "error", text: msg });
    } finally {
      if (turn.current === id && !derived.current) { setBusy(false); setTimeout(() => scroll.current?.toBottom(), 50); }
    }
  }

  /** The owner TAPPED an option on one of Henry's own questions.
   *
   *  It runs the ORDINARY send path - same turn, same session, same optimistic
   *  bubble, same outbox - because the decree is that the choice becomes the
   *  owner's next message, not that it gets a private channel. Two consequences
   *  fall out of that for free: the panel disappears the instant the optimistic
   *  `you` bubble lands (openChatQuestion sees someone spoke after the question),
   *  and answering is undoable in exactly the way any other message is.
   *
   *  Not awaited: `send` resolves only when the whole turn is DONE, and the
   *  panel spins while its submit promise is pending. Waiting here would pin a
   *  dead panel over the transcript for the length of Henry's answer. */
  function sendAnswer(q: PendingQuestion,
                      answers: Record<string, string | string[]>, rid: string) {
    // The optimistic bubble's text only. The daemon renders the authoritative
    // wording from the SAME answers (spine/ops/ask.chat_answer_text) and its
    // version replaces this one on the next history poll - retired by
    // client_msg_id, so the two never have to agree character for character.
    // The shape is mirrored here purely so the bubble does not visibly reword
    // itself a second later.
    const one = (h: string) => {
      const v = answers[h];
      return (Array.isArray(v) ? v : [v]).filter(Boolean).join(", ");
    };
    const qs = q.questions ?? [];
    const preview = qs.length === 1
      ? one(qs[0].header)
      : qs.map((x) => `${x.header}: ${one(x.header)}`).join("; ");
    void send(preview, { answer_to: rid, answers });
    return Promise.resolve();
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
      // ARM, not listen. `listen` opens the mic from HERE, which is exactly what
      // made the phone the starting point of a hands-free surface (owner,
      // 2026-09-04: "das muss in Brille aktiviert werden"). Arming parks the
      // service on the lens's wake counter instead: the owner then taps Speak on
      // the GLASSES, as often as he likes, without taking the phone out again.
      // Falls back to the old behaviour on a binary predating arm(), so an OTA
      // bundle landing on an older APK still works instead of doing nothing.
      if (glassVoice.arm() || glassVoice.listen(true)) setGlassOn(true);
    } finally {
      setGlassBusy(false);
    }
  }
  const header = (
    <View style={{ flexDirection: "row", alignItems: "center", padding: 10, gap: 8 }}>
      <Pressable onPress={onClose} hitSlop={10}><Ionicons name="chevron-back" size={24} color={t.txtSecondary} /></Pressable>
      <Text style={{ color: t.txtPrimary, fontSize: 16, fontWeight: "600" }}>{tr("chat.title")}</Text>
      {!wide ? (
        <Pressable onPress={() => setThreadsOpen(true)} hitSlop={10} accessibilityLabel={tr("chat.threads")}
                   style={{ marginLeft: 6 }}>
          <Ionicons name="albums-outline" size={22} color={t.txtSecondary} />
        </Pressable>
      ) : null}
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

  if (threadsOpen && !wide) {
    return (
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
        <ThreadList current="inbox" onClose={() => setThreadsOpen(false)}
          onPick={(id) => { setThreadsOpen(false); if (id !== "inbox") nav.push(`/card/${id}?tab=chat`); }} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top,
      ...(wide ? { borderLeftWidth: 1, borderColor: t.glassBorder } : null) }}>
      {header}
      <View style={{ flex: 1 }}>
        <ChatScroll ref={scroll} label={tr("chat.latest")}
          contentContainerStyle={{ padding: 12, paddingBottom: 24, width: "100%", maxWidth: colMax, alignSelf: "center" }}>
          {msgs.length === 0 && !(busy && stream.trim())
            ? <Empty text={tr("chat.empty")} />
            : <Transcript me={me?.name} ctxWindow={stats?.ctx_window} steps={(() => {
                const s = msgs.map((m) => toStep(m, me?.name, tr));
                // while streaming, append the board agent's live typing as a
                // streaming bot step - the SAME row a card worker streams into.
                if (busy) for (const st of liveSteps) s.push({ role: "assistant", kind: "tool", tool: st.tool, label: st.label, status: st.status, running: st.status === "running", by: "Henry", byKind: "henry" });
                if (busy && stream.trim()) s.push({ role: "assistant", kind: "text", text: stream, streaming: true, by: "Henry", byKind: "henry" });
                else if (!busy && held) s.push({ role: "assistant", kind: "text", text: held.text, by: "Henry", byKind: "henry" });
                return s;
              })()} />}
          {busy && !stream.trim() ? <ThinkingIndicator preview={think.trim() || (liveSteps.length ? "" : liveStatus)} /> : null}
        </ChatScroll>

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
          {/* The SAME QuestionPanel the card screen pins above its composer -
              not a second one built for this surface. Both kinds of question
              render through it (see openChatQuestion); only the DOOR differs, so
              the board chat gets real option buttons either way and there is no
              second answer path - or second chat UI - to keep in sync. */}
          {openQ?.question ? (
            <QuestionPanel question={openQ.question}
              onSubmit={openQ.card
                // a WORKER's question: settle it on the card, which resumes the
                // session it parked - the owner's words belong to that worker.
                ? (answers, rid) => api.answer(openQ.card as string, answers, rid)
                // HENRY's own: the choice becomes the owner's next message.
                : (answers, rid) => sendAnswer(openQ.question as PendingQuestion, answers, rid)}
              // ...and the promise made to the owner has to match the door.
              hint={openQ.card ? undefined : tr("card.q.hintChat")}
              onAnswered={() => qc.invalidateQueries({ queryKey: ["chatHistory"] })} />
          ) : null}
          {/* Henry's follow-ups in flight (owner report 2026-09-12: "er sagt er
              macht was, aber ich sehe nichts") - the SAME line a card shows for
              its background tasks, fed by /chat/history's derived descriptors. */}
          <BackgroundTasks tasks={data?.followups ?? {}} variant="henry" />
          <UnsentStrip scope="board" onRetry={(m) => send(m.text, m.opts, m.id)} />
          <Composer onSend={send} busy={busy} onStop={stop} models={models ?? ["auto"]}
            // Mode row (owner request 2026-09-12, screenshot of Claude Code's
            // picker: Model / Thinking / Mode): Henry's permission mode, same
            // three options and labels as a card's composer, current mode
            // first. The pick rides in the send body (`mode`) and copilot.chat
            // writes it to the one knob before spawning - card parity.
            modeOptions={henryModes}
            placeholder={tr("chat.placeholder")} draftKey="board-copilot"
            onVoice={canVoice ? () => setVoiceOpen(true) : undefined}
            // The routing target, made VISIBLE and switchable rather than
            // inferred. The decree allows "the next message, when it clearly
            // answers the card question" - a chip the owner can see and change
            // is what makes that "clearly": he is never guessing where his
            // words went, and a remark meant for Henry is one tap away.
            recipients={cardRecipients} defaultTo={replyTarget}
            // WHAT this message is about, when the chat was opened from a
            // settings row. Stays attached across messages (the VS Code
            // "Attach Context" behaviour the design cites) and is dropped with
            // the chip's own x - never silently, because a chip that vanishes
            // on its own is a chip the owner stops trusting.
            contextChip={chatCtx?.label}
            onClearContext={chatCtx ? () => useCopilotPanel.getState().clearContext() : undefined}
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
  const router = useRouter();
  const { wide } = useResponsive();
  const open = useCopilotPanel((s) => s.open);
  const hide = useCopilotPanel((s) => s.hide);
  if (!wide || !open) return null;
  // Sidebar + chat, the desktop chat-app shape: the conversation list on the
  // left is permanent, the inbox on the right; picking a thread leaves the
  // panel for that card's chat tab.
  return (
    <View style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, flexDirection: "row", backgroundColor: "#00000073" }}>
      <Pressable style={{ flex: 1 }} onPress={hide} accessibilityLabel={tr("chat.close")} />
      <View style={{ width: 820, maxWidth: "72%", flexDirection: "row", ...(Platform.OS === "web" ? { boxShadow: "-8px 0 24px rgba(0,0,0,0.35)" } as any : {}) }}>
        <View style={{ width: 280, borderLeftWidth: 1, borderColor: t.glassBorder }}>
          <ThreadList current="inbox" embedded
            onPick={(id) => { if (id !== "inbox") { hide(); router.push(`/card/${id}?tab=chat`); } }} />
        </View>
        <View style={{ flex: 1 }}><ChatBody onClose={hide} wide /></View>
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
        <View style={{ width: 820, maxWidth: "72%", flexDirection: "row" }}>
          <View style={{ width: 280 }}>
            <ThreadList current="inbox" embedded onPick={(id) => { if (id !== "inbox") router.push(`/card/${id}?tab=chat`); }} />
          </View>
          <View style={{ flex: 1 }}><ChatBody onClose={() => router.back()} wide /></View>
        </View>
      </View>
    );
  }
  return <ChatBody onClose={() => router.back()} wide={false} />;
}
