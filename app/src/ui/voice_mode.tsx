import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Easing, Modal, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { caps, listen, speak, stopSpeaking, type Listener, type VoiceClip } from "@/data/voice";
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

/** The caller answers a spoken question: run the turn, return prose + the clip
 *  the daemon rendered (`POST /chat {voice:true}` -> `out.voice`). */
export type AskFn = (text: string) => Promise<{ reply: string; clip?: VoiceClip | null }>;

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

export function VoiceMode({ visible, onClose, onAsk, busy }: {
  visible: boolean;
  onClose: () => void;
  onAsk: AskFn;
  /** True while the caller's own turn is running (the text chat and voice mode
   *  share one agent, so voice must not start a second turn on top of one). */
  busy?: boolean;
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

  const listener = useRef<Listener | null>(null);
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
    setTurns((v) => [...v, { role: "user", text: said }]);
    setCaption("");
    setState("thinking");
    let reply = "";
    let clip: VoiceClip | null | undefined;
    try {
      const r = await onAsk(said);
      reply = r.reply || "";
      clip = r.clip;
    } catch (e) {
      if (!alive.current) return;
      setProblem(String((e as Error).message || tr("voice.failed")));
      setState("error");
      return;
    }
    if (!alive.current) return;
    setTurns((v) => [...v, { role: "henry", text: reply || tr("chat.noReply") }]);
    setCaption(reply);
    if (clip?.b64) {
      setState("speaking");
      setSilent(false);      // speech came back — drop the notice
      await speak(clip);
    } else {
      // No clip: the daemon renders speech through edge-tts, which fails soft
      // when it is offline or unavailable (voice.py). The answer is not lost —
      // it is on screen and in the transcript — so say so and keep going rather
      // than pretending the turn failed.
      setSilent(true);
    }
    if (!alive.current) return;
    if (handsRef.current) startRef.current();
    else setState("idle");
  }, [onAsk, tr]);

  const startListening = useCallback(() => {
    if (!alive.current) return;
    if (!ability.hear) { setState("idle"); return; }
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
        if (alive.current) run(txt);
      },
      onError: (kind, detail) => {
        listener.current = null;
        setLevel(0);
        if (!alive.current) return;
        if (kind === "nospeech") {
          // Silence is not a failure — it is the owner not talking yet. Drop
          // back to idle so the orb is a button again, never an error wall.
          setState("idle");
          return;
        }
        setProblem(kind === "denied" ? tr("voice.denied") : (detail || tr("voice.failed")));
        setState("error");
      },
    });
    if (!listener.current) setState("idle");
  }, [ability.hear, run, stopListening, tr]);
  startRef.current = startListening;

  // open / close lifecycle
  useEffect(() => {
    if (!visible) return;
    alive.current = true;
    setProblem(""); setCaption(""); setState("idle"); setLevel(0); setSilent(false);
    // The opening tap IS the user gesture browsers require before audio may
    // play, so starting here is what unlocks playback for the whole session.
    if (ability.hear) startListening();
    return () => {
      alive.current = false;
      stopListening();
      stopSpeaking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  useEffect(() => {
    if (showTranscript) setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 40);
  }, [turns.length, showTranscript]);

  /** The orb is one button whose meaning follows the state — interrupt while
   *  speaking, submit while listening, start while idle. Never a dead tap. */
  function tapOrb() {
    if (busy) return;
    if (state === "speaking") { stopSpeaking(); startListening(); return; }
    if (state === "listening") { listener.current?.stop(); return; }   // finish the phrase
    if (state === "thinking") return;
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
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 28, gap: 26 }}>
            <Pressable onPress={tapOrb} accessibilityLabel={tr("voice.orb")}
              accessibilityRole="button" accessibilityState={{ busy: state === "thinking" }}>
              <Orb state={problem ? "error" : state} level={level} />
            </Pressable>
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
          </View>
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
        </View>
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
