import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Easing, Modal, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { caps, listen, openSpeech, speak, stopSpeaking, type Listener, type SpeechQueue, type VoiceClip } from "@/data/voice";
// The OWN pipeline (speech-to-speech shape): raw mic + on-device VAD cut
// utterances, the daemon transcribes them (faster-whisper). Optional native
// module — null on builds that predate it, and live mode simply isn't offered.
import LiveMic, { type MicSegment } from "../../modules/livemic";
import { ensureLocalStt, localSttSupported, transcribeLocal } from "@/data/stt_local";
import { getLang, useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Empty } from "@/ui/kit";

/** Full-screen voice mode — the ChatGPT / Gemini Live interaction shape, built on
 *  HelmDeck's own turn-based stack.
 *
 *  WHAT IS COPIED AND WHAT IS NOT (docs/voice-interaction-design.md SS7). The UI
 *  is copyable and this copies it: a full-screen takeover, one big state-driven
 *  orb, the transcript hidden behind a toggle, one unmistakable way out. The
 *  FEEL is not: ChatGPT and Gemini run native audio-in/audio-out models over a
 *  persistent WebRTC session with server-side VAD, which is what buys sub-400ms
 *  replies and talk-over-the-model barge-in. Claude has no such API - its own
 *  voice mode is a cascaded STT -> text -> TTS pipeline, exactly the shape this
 *  already is. So the two places the illusion would break are handled honestly
 *  instead of faked:
 *
 *  - BARGE-IN is a TAP, not a shout. On a phone, opening a Bluetooth hands-free
 *    mic collapses all audio output to telephone quality (HFP and A2DP are
 *    mutually exclusive on Android and iOS alike), so "keep the mic open while
 *    speaking" would degrade the very speech it listens past. Tapping the orb
 *    cuts Henry off and starts listening - one gesture, same intent, no wrecked
 *    audio.
 *  - THE WAIT IS SHOWN, not hidden. A real turn takes seconds, not milliseconds.
 *    The thinking state gets its own animation and an elapsed clock (the same
 *    honesty the text chat's ThinkingIndicator already applies) rather than a
 *    fake instant response.
 *
 *  This owns the INTERACTION only. The transport stays with the caller via
 *  `onAsk`, so voice mode sends through the exact same path the text composer
 *  does - there is one chat, spoken or typed, never two that can drift.
 */

export type VoiceState = "idle" | "listening" | "thinking" | "speaking" | "error";

export interface VoiceTurn { role: "user" | "henry"; text: string }

/** The caller answers a spoken question.
 *
 *  `onClip` is how speech arrives NOW: the daemon renders Henry's answer
 *  sentence by sentence while he is still writing it, and the caller (which owns
 *  the transport — this component deliberately does not) hands each chunk over
 *  as it lands. The returned `clip` is the older one-shot path, kept because a
 *  daemon that predates streaming still answers that way and going silent
 *  against an older daemon would be a worse bug than speaking late. */
export type AskFn = (text: string, onClip?: (c: VoiceClip) => void)
  => Promise<{ reply: string; clip?: VoiceClip | null }>;

// -- the orb -----------------------------------------------------------------

/** Three haloes and a gradient core. Animation is the state readout: the owner
 *  should know what the machine is doing from across the room, without reading a
 *  word. RN's Animated (not Reanimated) on purpose - it is what the rest of this
 *  app animates with and it behaves identically under react-native-web, which is
 *  where this gets verified. */
function Orb({ state, level }: { state: VoiceState; level: number }) {
  const t = useTheme();
  const pulse = useRef(new Animated.Value(0)).current;
  const spin = useRef(new Animated.Value(0)).current;
  // Mic level is smoothed here rather than at the source: raw amplitude is
  // jittery enough to read as a flicker, and only some platforms report it at
  // all (see voice.ts onLevel) - so the breathing loop below is the floor and
  // level only ever adds to it.
  const react = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    // Idle/listening/speaking breathe; thinking runs faster and tighter, so the
    // wait looks like work rather than a stall.
    const dur = state === "thinking" ? 620 : state === "speaking" ? 900 : 1500;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: dur, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0, duration: dur, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    ]));
    loop.start();
    return () => { loop.stop(); };
  }, [state, pulse]);

  useEffect(() => {
    if (state !== "thinking") { spin.setValue(0); return; }
    const loop = Animated.loop(
      Animated.timing(spin, { toValue: 1, duration: 2600, easing: Easing.linear, useNativeDriver: true }));
    loop.start();
    return () => { loop.stop(); };
  }, [state, spin]);

  useEffect(() => {
    Animated.timing(react, { toValue: level, duration: 90, useNativeDriver: true }).start();
  }, [level, react]);

  const tint = state === "listening" ? t.accent
    : state === "error" ? t.danger
    : t.accent2;
  const tint2 = state === "listening" ? t.accent2
    : state === "error" ? t.danger
    : t.accent;

  // haloes: each ring scales and fades on the same clock, offset by index, so
  // the orb reads as radiating rather than merely resizing
  const ring = (i: number) => {
    const base = 1 + i * 0.16;
    const amp = state === "listening" ? 0.1 + i * 0.05 : state === "thinking" ? 0.05 : 0.07;
    return {
      transform: [{
        scale: Animated.add(
          pulse.interpolate({ inputRange: [0, 1], outputRange: [base, base + amp] }),
          react.interpolate({ inputRange: [0, 1], outputRange: [0, 0.16 + i * 0.06] }),
        ),
      }],
      opacity: pulse.interpolate({
        inputRange: [0, 1],
        outputRange: [0.26 - i * 0.07, 0.1 - i * 0.03],
      }),
    };
  };

  return (
    <View style={{ width: 260, height: 260, alignItems: "center", justifyContent: "center" }}>
      {[2, 1, 0].map((i) => (
        <Animated.View key={i} pointerEvents="none"
          style={[{ position: "absolute", width: 150, height: 150, borderRadius: 75, backgroundColor: tint }, ring(i)]} />
      ))}
      <Animated.View style={{
        width: 150, height: 150, borderRadius: 75, overflow: "hidden",
        transform: [{
          scale: Animated.add(
            pulse.interpolate({ inputRange: [0, 1], outputRange: [1, state === "thinking" ? 1.03 : 1.06] }),
            react.interpolate({ inputRange: [0, 1], outputRange: [0, 0.09] }),
          ),
        }, {
          rotate: spin.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] }),
        }],
        ...(Platform.OS === "web"
          ? { boxShadow: `0 0 46px ${tint}66` } as object
          : { shadowColor: tint, shadowOpacity: 0.55, shadowRadius: 26, shadowOffset: { width: 0, height: 0 }, elevation: 12 }),
      }}>
        <LinearGradient colors={[tint2, tint]} start={{ x: 0.1, y: 0 }} end={{ x: 0.9, y: 1 }}
          style={{ flex: 1 }} />
      </Animated.View>
    </View>
  );
}

// -- the screen --------------------------------------------------------------

// The rendered greeting clip, kept for the app session: the phrase is static,
// so one /notify/speak round trip covers every later open (instant greeting).
let greetCache: VoiceClip | null = null;

export function VoiceMode({ visible, onClose, onAsk, onCancel, busy, initialAsk }: {
  visible: boolean;
  onClose: () => void;
  onAsk: AskFn;
  /** Abort the in-flight turn (client token bump + server-side /chat/cancel).
   *  Lets a tap interrupt Henry mid-THINKING, not only mid-speech. */
  onCancel?: () => void;
  /** True while the caller's own turn is running (the text chat and voice mode
   *  share one agent, so voice must not start a second turn on top of one). */
  busy?: boolean;
  /** Ask this the moment the sheet opens (a DONE-push tap: Henry speaks the
   *  result instead of greeting), then fall into the normal listen loop. */
  initialAsk?: string;
}) {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const [state, setState] = useState<VoiceState>("idle");
  const [caption, setCaption] = useState("");
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [showTranscript, setShowTranscript] = useState(false);
  const [level, setLevel] = useState(0);
  const [problem, setProblem] = useState("");
  const [secs, setSecs] = useState(0);
  // STICKY, unlike `problem`. When the daemon answers without a clip, speech is
  // unavailable for structural reasons (edge-tts needs the network, voice.py
  // fails soft) — so it will be missing for EVERY turn, not just this one. A
  // transient notice would be erased by the next startListening() a moment
  // later and the owner would be left with a voice mode that is silently mute
  // and never says why. Once observed, this stays up for the session.
  const [silent, setSilent] = useState(false);
  // Auto-continue: after Henry finishes speaking, listen again — the continuous
  // loop ChatGPT/Gemini default to. Turned off by the mute button, which then
  // makes the orb a push-to-talk button instead.
  const [hands, setHands] = useState(true);
  // LIVE pipeline: raw mic + own VAD instead of the platform recognizer. The
  // open mic survives across turns (no per-utterance engine restart), the
  // endpointing is ours, and STT runs on the PC (whisper) — the speech-to-
  // speech cascade on HelmDeck's transport. Off by default: the platform
  // path is the proven baseline and LIVE needs the daemon-side STT stage.
  const [live, setLive] = useState(false);
  const liveRef = useRef(live);
  liveRef.current = live;
  const liveAvail = LiveMic != null;
  // The A/B the owner asked for (2026-08-23): WHERE does the segment get
  // transcribed - "pc" = daemon faster-whisper over the relay, "device" =
  // sherpa-onnx whisper-tiny on the phone itself. A ref-mirrored state like
  // `live`, because the segment handler runs outside React's render clock.
  const [sttDev, setSttDev] = useState(false);
  const sttDevRef = useRef(sttDev);
  sttDevRef.current = sttDev;
  const [sttNote, setSttNote] = useState("");

  const listener = useRef<Listener | null>(null);
  // The turn's speech queue, so an interrupt can drop what is still QUEUED and
  // not merely cut the clip that happens to be playing — with streaming there
  // are usually two or three more sentences waiting behind it.
  const speechRef = useRef<SpeechQueue | null>(null);
  const alive = useRef(false);
  const ability = useRef(caps()).current;
  const handsRef = useRef(hands);
  handsRef.current = hands;
  // The loop is mutually recursive (a finished answer starts the next listen),
  // which two useCallbacks cannot express without one closing over a stale copy
  // of the other. The indirection is a ref on purpose: it is assigned once per
  // render below, so `run` always re-enters the CURRENT listener rather than the
  // one that happened to exist when it was memoised.
  const startRef = useRef<() => void>(() => {});
  // Same indirection for run(): the open-effect fires an initialAsk turn and
  // must reach the CURRENT run, not the one from the mount render.
  const runRef = useRef<(said: string) => void>(() => {});
  // Turn epoch: a tap during THINKING cancels the in-flight turn; the epoch
  // bump makes every continuation of the cancelled run() a no-op, so its late
  // reply/error can never overwrite the fresh listening state.
  const epoch = useRef(0);
  // Transient-failure budget for hands-free. Measured 2026-08-21: an STT
  // "aborted" and a relay restart (push_relay ships + bounces the relay mid
  // deploy) each parked the orb on a red error while "Läuft weiter" promised
  // the opposite - a hands-free loop that dead-ends on a hiccup isn't hands
  // free. Bounded (3) so a genuinely down relay ends in an honest error, not
  // an infinite silent retry; reset by any successful listen or answer.
  const retries = useRef(0);
  // Quiet-cycle budget for hands-free (owner 2026-08-22: "hört mir nicht zu" /
  // "Geräusch bricht ab"): the engine is single-shot, so its endpointing fires
  // an end after every pause - previously ONE quiet cycle (or a cough the
  // engine "recognized") dropped the loop to idle and the conversation was
  // over. Now silence and noise re-open the mic for up to 5 cycles (~half a
  // minute of open conversation) before resting; any real phrase resets it.
  const silences = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retrySoon = useCallback((ms: number) => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    retryTimer.current = setTimeout(() => {
      retryTimer.current = null;
      if (alive.current) startRef.current();
    }, ms);
  }, []);

  const scroll = useRef<ScrollView>(null);

  // elapsed clock while a turn runs — the wait is real, so it is shown
  useEffect(() => {
    if (state !== "thinking") { setSecs(0); return; }
    const iv = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(iv);
  }, [state]);

  const stopListening = useCallback(() => {
    const l = listener.current;
    listener.current = null;
    try { l?.abort(); } catch { /* already gone */ }
    setLevel(0);
  }, []);

  // -- the loop: listen -> ask -> speak -> listen ----------------------------

  const run = useCallback(async (said: string) => {
    if (!alive.current) return;
    const my = ++epoch.current;
    const gone = () => !alive.current || epoch.current !== my;
    setTurns((v) => [...v, { role: "user", text: said }]);
    setCaption("");
    setState("thinking");
    // Opened BEFORE the turn starts, because the first chunk can arrive while
    // the model is still writing — that is the whole point of streaming, and a
    // queue created after the await would miss it.
    const speech = openSpeech();
    speechRef.current = speech;
    let heard = false;
    let reply = "";
    let clip: VoiceClip | null | undefined;
    try {
      const r = await onAsk(said, (c) => {
        if (gone() || !c?.b64) return;
        heard = true;
        setSilent(false);
        // The first chunk is the moment the wait visibly ends.
        setState((s) => (s === "thinking" ? "speaking" : s));
        speech.push(c);
      });
      reply = r.reply || "";
      clip = r.clip;
    } catch (e) {
      speech.stop();
      if (gone()) return;   // cancelled by a tap - listening already took over
      speechRef.current = null;
      setProblem(String((e as Error).message || tr("voice.failed")));
      setState("error");
      // hands-free: a failed ASK (relay restart, network blip) goes back to
      // LISTENING after a beat - never re-sends the question on its own, the
      // owner just says it again. Push-to-talk keeps the tap-to-retry.
      if (handsRef.current && retries.current < 3) { retries.current += 1; retrySoon(2500); }
      return;
    }
    retries.current = 0;
    if (gone()) { speech.stop(); return; }
    setTurns((v) => [...v, { role: "henry", text: reply || tr("chat.noReply") }]);
    setCaption(reply);
    if (!heard && clip?.b64) {
      // Older daemon: no chunks, one clip at the end. Same queue, one item.
      setState("speaking");
      setSilent(false);
      speech.push(clip);
    } else if (!heard) {
      // Nothing at all: the daemon renders through edge-tts, which fails soft
      // when it is offline or unavailable (voice.py). The answer is not lost —
      // it is on screen and in the transcript — so say so and keep going rather
      // than pretending the turn failed.
      setSilent(true);
    }
    speech.close();
    await speech.done();
    if (gone()) return;
    speechRef.current = null;
    if (handsRef.current) startRef.current();
    else setState("idle");
  }, [onAsk, tr]);

  const startListening = useCallback(() => {
    if (!alive.current) return;
    // LIVE branch: the mic is already open (the module holds it for the whole
    // session) — "listen" is just the should_listen gate opening. Everything
    // that must die when listening takes over (queued speech, the current
    // clip) dies exactly like the platform branch.
    if (liveRef.current && LiveMic) {
      speechRef.current?.stop();
      speechRef.current = null;
      stopSpeaking();
      stopListening();
      setProblem("");
      setCaption("");
      setState("listening");
      LiveMic.start(true);
      LiveMic.setMuted(false);
      return;
    }
    if (!ability.hear) { setState("idle"); return; }
    speechRef.current?.stop();      // drops the queue, not just the current clip
    speechRef.current = null;
    stopSpeaking();
    stopListening();
    setProblem("");
    setCaption("");
    setState("listening");
    listener.current = listen({
      lang: getLang() === "de" ? "de-DE" : "en-US",
      onPartial: (txt) => { if (alive.current) setCaption(txt); },
      onLevel: (v) => { if (alive.current) setLevel(v); },
      onFinal: (txt) => {
        listener.current = null;
        setLevel(0);
        if (!alive.current) return;
        const said = (txt || "").trim();
        // NOISE GUARD: an engine "final" without linguistic content (a cough,
        // a door, a hum transcribed as punctuation) must never become a turn
        // to Henry - treat it exactly like silence and keep listening.
        if (!/[a-zA-ZÀ-ſ]{2,}/.test(said)) {
          if (handsRef.current && silences.current < 5) {
            silences.current += 1; retrySoon(250); return;
          }
          silences.current = 0;
          setState("idle");
          return;
        }
        silences.current = 0;
        run(said);
      },
      onError: (kind, detail) => {
        listener.current = null;
        setLevel(0);
        if (!alive.current) return;
        if (kind === "nospeech") {
          // Silence is the owner thinking, not a failure. Hands-free keeps
          // the conversation OPEN: re-listen for up to 5 quiet cycles before
          // resting; push-to-talk drops straight back to the orb button.
          if (handsRef.current && silences.current < 5) {
            silences.current += 1; retrySoon(250); return;
          }
          silences.current = 0;
          setState("idle");
          return;
        }
        setProblem(kind === "denied" ? tr("voice.denied") : (detail || tr("voice.failed")));
        setState("error");
        // recognizer hiccup ("aborted", service restart): in hands-free mode
        // reopen the mic after a beat instead of parking red. Permission
        // denial is NOT transient - never retried.
        if (kind !== "denied" && handsRef.current && retries.current < 3) {
          retries.current += 1; retrySoon(1500);
        }
      },
    });
    if (!listener.current) setState("idle");
  }, [ability.hear, run, stopListening, tr]);
  startRef.current = startListening;
  runRef.current = run;

  // open / close lifecycle
  useEffect(() => {
    if (!visible) return;
    alive.current = true;
    setProblem(""); setCaption(""); setState("idle"); setLevel(0); setSilent(false);
    // The opening tap IS the user gesture browsers require before audio may
    // play, so starting here is what unlocks playback for the whole session.
    // GREET FIRST (owner ask 2026-08-21: "so know he's hearing"): a short
    // spoken "Ja?" is the audible proof the session is live - the visual orb
    // is useless in a pocket or on glasses. Spoken BEFORE the mic opens (no
    // duplex - his own ear must not transcribe his own greeting), cached
    // after the first open so later opens greet instantly. Best-effort: if
    // the render fails, the mic still starts - listening beats greeting.
    // A DONE-push tap skips the greeting: the first thing Henry says IS the
    // result. run() then falls into the normal hands-free loop.
    if (initialAsk) {
      runRef.current(initialAsk);
    } else if (ability.hear) {
      (async () => {
        try {
          // ALWAYS fire the request - the daemon uses it as the "voice mode
          // is opening" signal to prewarm the chat process (spawn + cache
          // prefill), which is what makes the FIRST question fast. The
          // cached clip still plays instantly; the response just refreshes it.
          const req = api.speak(tr("voice.greeting"));
          if (greetCache) {
            req.then((r) => { if (r.clip) greetCache = r.clip; }).catch(() => {});
          } else {
            greetCache = (await req).clip;
          }
          if (greetCache && alive.current) await speak(greetCache);
        } catch { /* greeting is decor, never a blocker */ }
        if (alive.current) startListening();
      })();
    }
    return () => {
      alive.current = false;
      if (retryTimer.current) { clearTimeout(retryTimer.current); retryTimer.current = null; }
      retries.current = 0;
      stopListening();
      speechRef.current?.stop();
      speechRef.current = null;
      stopSpeaking();
      try { LiveMic?.stop(); } catch { /* absent on old builds */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  // LIVE pipeline: segments arrive from the native VAD; each one becomes a
  // turn. The mic is MUTED the moment a segment is accepted (should_listen:
  // Henry must never transcribe his own speaker) and re-opens via the normal
  // startListening() when his answer finishes — one loop, both branches.
  useEffect(() => {
    const mic = LiveMic;
    if (!visible || !live || !mic) return;
    mic.start(true);
    const seg = mic.addListener("onSegment", async (e: MicSegment) => {
      if (!alive.current || !liveRef.current) return;
      mic.setMuted(true);
      setState("thinking");
      try {
        // the A/B fork: same segment, two ears - phone (sherpa) or PC (whisper)
        const t0 = Date.now();
        const raw = sttDevRef.current
          ? await transcribeLocal(e.b64)
          : (await api.transcribe(e.b64, getLang() === "de" ? "de" : "en")).text;
        setSttNote(`${sttDevRef.current ? "Gerät" : "PC"} ${((Date.now() - t0) / 1000).toFixed(1)}s`);
        const said = (raw || "").trim();
        // same noise guard as the platform branch: no linguistic content ->
        // back to listening, never a turn to Henry
        if (!/[a-zA-ZÀ-ſ]{2,}/.test(said)) {
          if (alive.current) startRef.current();
          return;
        }
        setCaption(said);
        runRef.current(said);
      } catch (err) {
        // 501 = daemon lacks faster-whisper: a structural reason, tell it once
        if (alive.current) {
          setProblem(String((err as Error).message || tr("voice.failed")));
          setState("error");
          startRef.current();
        }
      }
    });
    const st = mic.addListener("onState", (e: { state: string }) => {
      if (alive.current) setLevel(e.state === "speech" ? 0.8 : 0);
    });
    return () => { seg.remove(); st.remove(); try { mic.stop(); } catch { /* gone */ } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, live]);

  useEffect(() => {
    if (showTranscript) setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 40);
  }, [turns.length, showTranscript]);

  /** The orb is one button whose meaning follows the state — interrupt while
   *  speaking, submit while listening, start while idle. Never a dead tap. */
  function tapOrb() {
    if (state === "speaking") { startListening(); return; }   // startListening drops the queue
    if (state === "listening") { listener.current?.stop(); return; }   // finish the phrase
    if (state === "thinking") {
      // Interrupt mid-THINKING (owner 2026-08-22: "lässt sich nicht
      // unterbrechen wenn er denkt"): invalidate the in-flight run() via the
      // epoch, cancel server-side, open the mic. The bottom hint has promised
      // "Tippen unterbricht Henry" all along - now it is true here too.
      epoch.current++;
      onCancel?.();
      startListening();
      return;
    }
    if (busy) return;
    startListening();
  }

  const label = problem ? problem
    : state === "listening" ? tr("voice.listening")
    : state === "thinking" ? (secs >= 2 ? tr("voice.thinkingSecs", { s: secs }) : tr("voice.thinking"))
    : state === "speaking" ? tr("voice.speaking")
    : ability.hear ? tr("voice.tapToTalk")
    : tr("voice.speakOnly");

  const ctl = (on: boolean) => ({
    width: 56, height: 56, borderRadius: 28, alignItems: "center" as const, justifyContent: "center" as const,
    backgroundColor: on ? t.accent + "26" : t.surface2,
    borderWidth: 1, borderColor: on ? t.accent + "80" : t.borderSubtle,
  });

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}
      presentationStyle={Platform.OS === "web" ? undefined : "fullScreen"} transparent={false}>
      <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top, paddingBottom: insets.bottom }}>
        {/* header: leave, and the transcript toggle (hidden by default, like both
            references — the point of voice mode is not reading) */}
        <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingVertical: 10 }}>
          <Pressable onPress={onClose} hitSlop={12} accessibilityLabel={tr("voice.close")}>
            <Ionicons name="chevron-down" size={26} color={t.txtSecondary} />
          </Pressable>
          <Text style={{ flex: 1, textAlign: "center", color: t.txtSecondary, fontSize: 13, fontWeight: "600" }}>
            {tr("voice.title")}
          </Text>
          <Pressable onPress={() => setShowTranscript((v) => !v)} hitSlop={12}
            accessibilityLabel={tr("voice.transcript")}>
            <Ionicons name={showTranscript ? "chatbubble" : "chatbubble-outline"} size={20}
              color={showTranscript ? t.accent : t.txtSecondary} />
          </Pressable>
        </View>

        {showTranscript ? (
          <>
          {/* Reading the transcript must not cost the state readout: without
              this the orb is gone and nothing says whether Henry is listening,
              thinking or talking — a voice surface that has stopped telling you
              what it is doing. A dot + the same label carries it in one line. */}
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7, paddingBottom: 8 }}>
            <View style={{ width: 7, height: 7, borderRadius: 4,
              backgroundColor: problem ? t.danger : state === "listening" ? t.accent : t.accent2 }} />
            <Text style={{ color: problem ? t.danger : t.txtSecondary, fontSize: 12 }}>{label}</Text>
          </View>
          <ScrollView ref={scroll} style={{ flex: 1 }}
            contentContainerStyle={{ padding: 16, paddingBottom: 28, gap: 12, maxWidth: 720,
              width: "100%", alignSelf: "center", flexGrow: 1 }}>
            {turns.map((v, i) => (
              <View key={i} style={{ alignSelf: v.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%" }}>
                <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", marginBottom: 3,
                  textAlign: v.role === "user" ? "right" : "left" }}>
                  {v.role === "user" ? tr("voice.you") : tr("chat.title")}
                </Text>
                <View style={{ backgroundColor: v.role === "user" ? t.accent + "1F" : t.surface1,
                  borderColor: v.role === "user" ? t.accent + "4D" : t.borderSubtle, borderWidth: 1,
                  borderRadius: 14, paddingHorizontal: 13, paddingVertical: 9 }}>
                  <Text style={{ color: t.txtPrimary, fontSize: 14.5, lineHeight: 20 }}>{v.text}</Text>
                </View>
              </View>
            ))}
            {/* The shared Empty (same component the text chat uses, so the
                wording and type scale match) — but centred in the void rather
                than stranded top-left, because here it is the ONLY thing on a
                full screen instead of a note above a populated list. */}
            {turns.length === 0
              ? <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
                  <Empty text={tr("voice.transcriptEmpty")} />
                </View>
              : null}
          </ScrollView>
          </>
        ) : (
          /* The WHOLE free surface taps like the orb (owner 2026-08-22: had to
             aim for the button repeatedly to cut Henry off - interrupting must
             be a slap, not a target). Same semantics as tapOrb: interrupt while
             speaking, submit while listening, start while idle. */
          <Pressable onPress={tapOrb} accessibilityLabel={tr("voice.orb")}
            accessibilityRole="button" accessibilityState={{ busy: state === "thinking" }}
            style={{ flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 28, gap: 26 }}>
            <Orb state={problem ? "error" : state} level={level} />
            <View style={{ alignItems: "center", gap: 10, minHeight: 96 }}>
              <Text style={{ color: problem ? t.danger : t.txtSecondary, fontSize: 14, fontWeight: "600" }}>
                {label}
              </Text>
              {/* The live caption: what was heard while listening, what is being
                  said while speaking. Capped so a long answer scrolls the eye
                  rather than the screen — the transcript toggle is the place to
                  read a full reply. */}
              {caption ? (
                <Text numberOfLines={4} style={{ color: t.txtPrimary, fontSize: 17, lineHeight: 24,
                  textAlign: "center", maxWidth: 560 }}>
                  {caption}
                </Text>
              ) : null}
            </View>
          </Pressable>
        )}

        {/* controls: hands-free toggle · end · re-listen. Three, because a voice
            surface the owner cannot silence instantly is worse than no voice. */}
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 22, paddingVertical: 18 }}>
          <Pressable onPress={() => setHands((v) => !v)} style={ctl(hands)}
            accessibilityLabel={tr(hands ? "voice.handsOn" : "voice.handsOff")}>
            <Ionicons name={hands ? "infinite" : "hand-left-outline"} size={22} color={hands ? t.accent : t.txtSecondary} />
          </Pressable>
          <Pressable onPress={onClose}
            style={{ width: 66, height: 66, borderRadius: 33, alignItems: "center", justifyContent: "center", backgroundColor: t.danger }}
            accessibilityLabel={tr("voice.close")}>
            <Ionicons name="close" size={28} color="#fff" />
          </Pressable>
          <Pressable onPress={tapOrb} style={ctl(state === "listening")}
            accessibilityLabel={tr("voice.orb")}>
            <Ionicons name={state === "speaking" ? "stop" : "mic"} size={22}
              color={state === "listening" ? t.accent : t.txtSecondary} />
          </Pressable>
          {liveAvail ? (
            <Pressable onPress={() => { const v = !live; setLive(v); liveRef.current = v; startRef.current(); }}
              style={ctl(live)} accessibilityLabel={tr(live ? "voice.liveOn" : "voice.liveOff")}>
              <Ionicons name="pulse" size={22} color={live ? t.accent : t.txtSecondary} />
            </Pressable>
          ) : null}
          {live && localSttSupported() ? (
            <Pressable
              onPress={async () => {
                if (sttDev) { setSttDev(false); sttDevRef.current = false; setSttNote(""); return; }
                // first enable downloads ~104 MB from Hugging Face - say so
                setSttNote(tr("voice.sttLoading"));
                try {
                  await ensureLocalStt(getLang() === "de" ? "de" : "en");
                  setSttDev(true); sttDevRef.current = true;
                  setSttNote(tr("voice.sttDevice"));
                } catch (e) {
                  setSttNote(String((e as Error).message));
                }
              }}
              style={ctl(sttDev)} accessibilityLabel={tr(sttDev ? "voice.sttDevice" : "voice.sttPc")}>
              <Ionicons name="hardware-chip-outline" size={22} color={sttDev ? t.accent : t.txtSecondary} />
            </Pressable>
          ) : null}
        </View>
        {live && sttNote ? (
          <Text style={{ color: t.txtTertiary, fontSize: 11, textAlign: "center" }}>{sttNote}</Text>
        ) : null}
        <Text style={{ color: silent ? t.warn : t.txtTertiary, fontSize: 11, textAlign: "center", paddingBottom: 10, paddingHorizontal: 24 }}>
          {silent ? tr("voice.noAudio") : hands ? tr("voice.hintHands") : tr("voice.hintPush")}
        </Text>
      </View>
    </Modal>
  );
}

/** Whether this runtime can do voice at all — the composer hides its microphone
 *  rather than offering a button that cannot work.
 *
 *  HEARING is the requirement, not speaking. A voice mode that can only speak is
 *  a screen with no way IN: the orb's every state routes through startListening,
 *  so without a recogniser the tap does nothing and the owner is left poking a
 *  pretty circle. Speaking without hearing already has a home — it is what the
 *  text chat does when it plays back an answer. So: no ear, no microphone button,
 *  and the composer is unchanged rather than lying. */
export function voiceUsable() {
  return caps().hear;
}
