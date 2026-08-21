import { Platform } from "react-native";

/** Voice I/O for the ChatGPT-style voice mode — ONE seam, two platform bodies.
 *
 *  WHY A SEAM AND NOT A LIBRARY CALL. The two halves of a voice turn have very
 *  different provenance in HelmDeck:
 *
 *  - SPEAKING is SERVER work and is already settled. `daemon/spine/media/voice.py`
 *    renders Henry's prose to mp3 (edge-tts) and `POST /chat {voice:true}` returns
 *    it inline as base64, because the phone reaches the daemon through the E2EE
 *    relay, which seals ONE request/response and has no second channel for a
 *    binary. So this module never synthesises anything - it PLAYS what the daemon
 *    already rendered. That keeps one voice and one register across the lens, the
 *    phone and WhatsApp (docs/voice-interaction-design.md SS3).
 *  - HEARING is PLATFORM work and cannot be centralised: recognition happens on
 *    the device, in the OS, and every OS exposes it differently.
 *
 *  CAPABILITY IS DERIVED, NEVER ASSUMED (the Paseo principle, CLAUDE.md). Nothing
 *  here trusts a build flag or a stored boolean to decide what this binary can do.
 *  `caps()` answers by actually resolving the module and asking the runtime - so a
 *  JS bundle that lands via OTA on an APK built BEFORE expo-audio was added
 *  reports `speak:false` and degrades to text, instead of white-screening on a
 *  missing native module. That is the whole reason the requires below are lazy and
 *  wrapped: an OTA bundle always runs against whatever native binary is on the
 *  phone, which is not necessarily the one it was compiled against.
 *
 *  MEASURED PLATFORM STATE (2026-08-21, against the SDK 57 sources, not memory):
 *  - `expo-audio` ~57.0.4 is real and ships a WEB body too. Its base64 `data:`
 *    URI path is implemented on all three platforms, but iOS matches the prefix
 *    literally as `data:audio/` - so the mime must stay `audio/mpeg`, which is
 *    exactly what voice.render_b64 emits.
 *  - `expo-speech-recognition` publishes no SDK 57 release (npm `latest` is
 *    56.0.1, and upstream's own repo still pins expo ~56.0.12). That is a
 *    STATEMENT ABOUT TESTING, not about compatibility, and the difference was
 *    settled by measuring rather than by reading: expo autolinking builds
 *    community modules FROM SOURCE against the app's own expo-modules-core, so
 *    there is no prebuilt ABI to mismatch. `:expo-speech-recognition:
 *    compileReleaseKotlin` against this app's SDK 57 / RN 0.86 / Kotlin 2.1.20
 *    tree is BUILD SUCCESSFUL with zero warnings, so it is a dependency, pinned
 *    EXACTLY to the version that was compiled (see app/package.json).
 *  - The Android half of that package needs a `<queries>` entry to see the
 *    recogniser at all (API 30+ package visibility). That is native config, so
 *    it belongs to app/plugins/withGlassVoice.js, which owns both the prebuild
 *    and the hand-managed-android paths. Without it everything below still runs
 *    and the microphone is simply deaf - which is why `caps()` asks
 *    `isRecognitionAvailable()` rather than settling for "the module loaded".
 *  - Web needs no package for either half: `HTMLAudioElement` plays the clip and
 *    `webkitSpeechRecognition` hears. Both are used directly here.
 */

const isWeb = Platform.OS === "web";

/** The daemon's inline clip (daemon/spine/media/voice.py render_b64). */
export interface VoiceClip { id: string; mime: string; b64: string }

/** What this runtime can actually do, answered by asking it. */
export interface VoiceCaps {
  speak: boolean;
  hear: boolean;
  /** Can this runtime listen WHILE speaking without transcribing its own voice?
   *
   *  This is the whole barge-in question and it has exactly one documented
   *  answer today. Chromium's speech recogniser opens a RAW capture device -
   *  `speech_recognizer_impl.cc` wires no `AudioProcessingSettings` and no echo
   *  reference at all - so the Web Speech API does not cancel our own playback.
   *  Two recent additions change that: Chrome 135 lets `start()` take a
   *  MediaStreamTrack, and Chrome 141 added `echoCancellationMode: "all"`,
   *  defined as removing "all sound being played by the system". Together they
   *  are the only path where full duplex is documented rather than hoped for.
   *
   *  MEASURED FALSE EVERYWHERE, 2026-08-21, and that is why there is no duplex
   *  code path behind this flag. Chromium 150 (Electron 43, the newest shell
   *  there is) does not advertise `echoCancellationMode` in
   *  `getSupportedConstraints()` AND does not return it from
   *  `track.getSettings()` when asked for explicitly - i.e. the constraint the
   *  release notes describe is not honoured in the runtime we would ship. Run
   *  `tools/probe_duplex.js` to re-check; the day it comes back true, THAT is
   *  when the listening path gets its duplex branch, tested against a browser
   *  that actually has it. Shipping the branch now would mean shipping code no
   *  test on earth could exercise.
   *
   *  Probed through the browser's own answer rather than a version sniff, so it
   *  flips on by itself. */
  duplex: boolean;
  /** Why `hear` is false, for a UI that must never be a silent dead end.
   *  - `unsupported`  the browser has no Web Speech API (Firefox, Chrome-on-iOS)
   *  - `no-module`    this native binary predates the STT module (an OTA bundle
   *                   can legitimately outrun the APK it lands on)
   *  - `unavailable`  the module is there, but the OS exposes no recogniser:
   *                   a Play-less/AOSP device, or a manifest missing the
   *                   `<queries>` entry (withGlassVoice.js) */
  hearReason?: "unsupported" | "no-module" | "unavailable";
}

export interface Listener {
  /** Finish the phrase and deliver a final result. */
  stop(): void;
  /** Drop it — no final result (used when the sheet closes mid-listen). */
  abort(): void;
}

export interface ListenOpts {
  lang: string;
  /** Words so far, for the live caption under the orb. */
  onPartial(text: string): void;
  /** The finished phrase — this is what gets sent to Henry. */
  onFinal(text: string): void;
  onError(kind: "denied" | "nospeech" | "failed", detail?: string): void;
  /** Mic loudness 0..1 where the platform reports it, for the orb's reactivity. */
  onLevel?(level: number): void;
}

// -- module resolution -------------------------------------------------------
// Wrapped and cached. A missing native module must read as "this build cannot",
// never as a crash, because an OTA bundle can legitimately outrun the binary.

/** Exactly the slice of expo-audio ~57.0.4 this module uses, declared locally
 *  rather than imported as `typeof import("expo-audio")`. That is deliberate:
 *  the type must not depend on the package being INSTALLED, because the runtime
 *  contract here is explicitly "may be absent". Importing its types would make a
 *  missing dependency a compile error, which is the opposite of the behaviour
 *  this file exists to provide. Signatures verified against the SDK 57 source
 *  (`packages/expo-audio/src/ExpoAudio.ts`). */
interface AudioPlayerLike {
  play(): void;
  pause(): void;
  /** Frees the native player. `createAudioPlayer` does NOT auto-release — only
   *  the `useAudioPlayer` hook does — so every path must call this. */
  remove(): void;
  addListener(ev: "playbackStatusUpdate", fn: (s: { didJustFinish?: boolean }) => void): { remove(): void };
}
interface AudioModule {
  createAudioPlayer(source: { uri: string }): AudioPlayerLike;
  setAudioModeAsync(mode: {
    playsInSilentMode?: boolean;
    interruptionMode?: "mixWithOthers" | "doNotMix" | "duckOthers";
  }): Promise<void>;
}

let audioMod: AudioModule | null | undefined;
function expoAudio(): AudioModule | null {
  if (audioMod !== undefined) return audioMod;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    audioMod = require("expo-audio") as AudioModule;
  } catch {
    audioMod = null;
  }
  return audioMod;
}

/** The slice of expo-speech-recognition 56.0.1 used here, declared locally for
 *  the same reason as AudioPlayerLike above: an OTA bundle may land on an APK
 *  built before this module existed, so "absent" has to be a runtime answer
 *  rather than a compile error. Verified against the package's own
 *  `build/ExpoSpeechRecognitionModule.types.d.ts`. */
interface SttModule {
  ExpoSpeechRecognitionModule: {
    start(o: Record<string, unknown>): void;
    stop(): void;
    abort(): void;
    requestPermissionsAsync(): Promise<{ granted: boolean }>;
    /** Does the OS actually expose a recogniser right now? False on a Play-less
     *  device, and false when the manifest lacks the `<queries>` entry. */
    isRecognitionAvailable(): boolean;
    addListener(ev: string, fn: (e: unknown) => void): { remove(): void };
  };
}
let sttMod: SttModule | null | undefined;
function expoStt(): SttModule | null {
  if (sttMod !== undefined) return sttMod;
  try {
    // Lazy and wrapped on purpose — see the header. Importing it at module scope
    // would turn "this APK is older than this bundle" into a white screen.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    sttMod = require("expo-speech-recognition") as SttModule;
  } catch {
    sttMod = null;
  }
  return sttMod;
}

// Minimal shape of the Web Speech API — the DOM lib types it only behind
// `dom.iterable`/vendor prefixes, and RN's tsconfig does not pull those in.
interface WebSpeechEvent {
  resultIndex: number;
  results: { isFinal: boolean; 0: { transcript: string }; length: number }[] & { length: number };
}
interface WebSpeechRecognition {
  lang: string; continuous: boolean; interimResults: boolean; maxAlternatives: number;
  start(): void; stop(): void; abort(): void;
  onresult: ((e: WebSpeechEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}
function webSpeechCtor(): (new () => WebSpeechRecognition) | null {
  if (!isWeb || typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => WebSpeechRecognition;
    webkitSpeechRecognition?: new () => WebSpeechRecognition;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** What this runtime can do — asked, not assumed. Cheap and side-effect free. */
/** Does this browser expose `echoCancellationMode`? That constraint is the one
 *  documented way to cancel the page's OWN audio out of a capture stream -
 *  plain `echoCancellation: true` only "SHOULD" attempt it and in Chrome
 *  historically cancelled remote WebRTC audio only, which is useless here. */
function webDuplex(): boolean {
  if (!isWeb || typeof navigator === "undefined") return false;
  try {
    const s = navigator.mediaDevices?.getSupportedConstraints?.() as
      Record<string, boolean> | undefined;
    return !!s?.echoCancellationMode && typeof navigator.mediaDevices?.getUserMedia === "function";
  } catch {
    return false;
  }
}

export function caps(): VoiceCaps {
  if (isWeb) {
    const hear = !!webSpeechCtor();
    return {
      duplex: hear && webDuplex(),
      // Every browser that runs the app has HTMLAudioElement; there is nothing
      // to feature-detect that could plausibly be false.
      speak: typeof window !== "undefined" && typeof window.Audio === "function",
      hear,
      // Firefox / Brave / Chrome-on-iOS have no Web Speech API at all.
      hearReason: hear ? undefined : "unsupported",
    };
  }
  const stt = expoStt();
  const speak = !!expoAudio();
  // NATIVE HAS NO DUPLEX, and the reason is the library rather than the OS.
  // Android exposes both halves - `AcousticEchoCanceler` and the
  // VOICE_COMMUNICATION source, which is the one documented to apply AEC - but
  // expo-speech-recognition reaches neither: its ExpoAudioRecorder.kt builds
  // its AudioRecord on `MediaRecorder.AudioSource.VOICE_RECOGNITION` and its
  // `audioSource` option takes a FILE URI, not an input device. So the phone
  // would transcribe its own answer. Reported false until measured otherwise on
  // a real device - see debt `voice-barge-in`.
  if (!stt) return { speak, hear: false, duplex: false, hearReason: "no-module" };
  // ASK THE OS, don't infer from the import. A linked module proves the binary
  // shipped the code; it does not prove this device has a recogniser to talk to.
  // Android hands recognition to another app (normally Google's), so on an
  // AOSP/Play-less build — or with a manifest missing the <queries> entry — the
  // module loads perfectly and every start() would fail with
  // `service-not-allowed`. Reporting hear:true there would put a live microphone
  // button on a screen that can never hear, which is the exact dead end this
  // whole capability probe exists to prevent.
  let live = false;
  try { live = stt.ExpoSpeechRecognitionModule.isRecognitionAvailable(); } catch { live = false; }
  return { speak, hear: live, duplex: false, hearReason: live ? undefined : "unavailable" };
}

// -- speaking ----------------------------------------------------------------

let stopCurrent: (() => void) | null = null;

/** Cut the current clip off. Safe to call when nothing is playing.
 *
 *  This is the honest form of barge-in on a turn-based stack: the owner TAPS to
 *  interrupt rather than talking over the voice. Opening a Bluetooth hands-free
 *  mic collapses ALL output to telephone quality on both Android and iOS
 *  (HFP/A2DP are mutually exclusive), so listening WHILE speaking would wreck the
 *  audio it is listening past - see docs/voice-interaction-design.md SS4.5. */
export function stopSpeaking() {
  const s = stopCurrent;
  stopCurrent = null;
  try { s?.(); } catch { /* already gone */ }
}

/** Play a daemon-rendered clip. Resolves when it finishes, is interrupted, or
 *  fails — speech is an enhancement and must never strand the caller, so this
 *  never rejects (same contract as voice.py's render: failure means "no audio
 *  this time", and the text answer is already on screen). */
export async function speak(clip: VoiceClip): Promise<void> {
  stopSpeaking();
  const uri = `data:${clip.mime || "audio/mpeg"};base64,${clip.b64}`;
  if (isWeb) return speakWeb(uri);
  return speakNative(uri);
}

function speakWeb(uri: string): Promise<void> {
  return new Promise<void>((resolve) => {
    let done = false;
    const finish = () => { if (done) return; done = true; stopCurrent = null; resolve(); };
    let el: HTMLAudioElement;
    try { el = new window.Audio(uri); } catch { return finish(); }
    // `onended` on the raw element, deliberately NOT expo-audio's status hook:
    // its web body never emits a status update from `onended`, so `didJustFinish`
    // is only observed by a 500ms-throttled timeupdate and can be missed outright
    // — which would hang a conversation loop that waits for "finished speaking".
    el.onended = finish;
    el.onerror = finish;
    stopCurrent = () => { try { el.pause(); el.currentTime = 0; } catch { /* detached */ } finish(); };
    // Autoplay policy: a promise rejection here means no user gesture has
    // unlocked audio yet. Resolving (not throwing) keeps the turn moving in
    // silence; the UI opens on a tap, which is what unlocks it.
    el.play()?.catch(finish);
  });
}

async function speakNative(uri: string): Promise<void> {
  const A = expoAudio();
  if (!A) return;
  return new Promise<void>((resolve) => {
    let done = false;
    let player: AudioPlayerLike | null = null;
    let sub: { remove(): void } | null = null;
    const finish = () => {
      if (done) return;
      done = true;
      stopCurrent = null;
      try { sub?.remove(); } catch { /* already removed */ }
      // createAudioPlayer does NOT auto-release (only the useAudioPlayer hook
      // does) — without this every spoken turn leaks a native player.
      try { player?.remove(); } catch { /* already gone */ }
      resolve();
    };
    try {
      // playsInSilentMode so an answer is not swallowed by the iOS ring switch —
      // the owner asked to be spoken to, the hardware switch predates the ask.
      A.setAudioModeAsync({ playsInSilentMode: true, interruptionMode: "duckOthers" })
        .catch(() => { /* web/no-op or unsupported combo — playback still works */ });
      player = A.createAudioPlayer({ uri });
      sub = player.addListener("playbackStatusUpdate", (s: { didJustFinish?: boolean }) => {
        if (s?.didJustFinish) finish();
      });
      stopCurrent = () => { try { player?.pause(); } catch { /* detached */ } finish(); };
      player.play();
    } catch {
      finish();
    }
  });
}

/** A turn's speech, arriving in pieces.
 *
 *  The daemon now renders Henry's answer sentence by sentence while he is still
 *  writing it (daemon/spine/media/voice_stream.py), so the client no longer gets
 *  ONE clip at the end - it gets a series, and has to play them back to back
 *  without gaps, in order, and be able to throw the rest away mid-sentence when
 *  the owner interrupts. That is a queue, not a function call. */
export interface SpeechQueue {
  /** Another rendered chunk arrived. Plays immediately if nothing else is. */
  push(clip: VoiceClip): void;
  /** No further chunks will arrive (the turn is over and nothing is rendering). */
  close(): void;
  /** Resolves once everything pushed has been played - or the moment `stop()`
   *  is called. This is what "Henry finished speaking" means now. */
  done(): Promise<void>;
  /** Interrupt: drop what is queued and cut the clip that is playing. */
  stop(): void;
}

export function openSpeech(): SpeechQueue {
  const q: VoiceClip[] = [];
  let closed = false, stopped = false, running = false;
  let settleDone: (() => void) | null = null;
  const finished = new Promise<void>((r) => { settleDone = r; });
  const settle = () => { const r = settleDone; settleDone = null; r?.(); };

  const pump = async () => {
    if (running || stopped) return;
    running = true;
    for (;;) {
      const next = q.shift();
      if (!next) {
        running = false;
        // Empty but not closed: the model is still writing. Stop the loop and
        // let the next push() restart it, rather than spinning on a timer.
        if (closed || stopped) settle();
        return;
      }
      await speak(next);
      if (stopped) { running = false; return; }   // stop() already settled
    }
  };

  return {
    push(clip) { if (!stopped && !closed) { q.push(clip); void pump(); } },
    close() { closed = true; if (!running) { q.length ? void pump() : settle(); } },
    done: () => finished,
    stop() {
      if (stopped) return;
      stopped = true;
      q.length = 0;
      stopSpeaking();
      settle();
    },
  };
}

// -- hearing -----------------------------------------------------------------

/** Start recognition. Returns a handle, or null when this runtime cannot hear
 *  (the caller shows speak-only mode rather than a dead microphone). */
export function listen(o: ListenOpts): Listener | null {
  return isWeb ? listenWeb(o) : listenNative(o);
}

function listenWeb(o: ListenOpts): Listener | null {
  const Ctor = webSpeechCtor();
  if (!Ctor) { o.onError("failed", "no Web Speech API"); return null; }
  let rec: WebSpeechRecognition;
  try { rec = new Ctor(); } catch { o.onError("failed"); return null; }
  rec.lang = o.lang;
  // One phrase per turn: `continuous` would keep firing results while Henry is
  // still answering, which on a turn-based stack means talking over the reply.
  rec.continuous = false;
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  let settled = false;
  let best = "";
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      const txt = r[0]?.transcript ?? "";
      if (r.isFinal) best += txt; else interim += txt;
    }
    o.onPartial((best + interim).trim());
  };
  rec.onerror = (e) => {
    settled = true;
    if (e.error === "not-allowed" || e.error === "service-not-allowed") o.onError("denied");
    else if (e.error === "no-speech") o.onError("nospeech");
    else if (e.error !== "aborted") o.onError("failed", e.error);
  };
  // Chrome ends the session on its own after a pause — that end IS the phrase
  // boundary, so the final result is delivered here rather than from a timer.
  rec.onend = () => {
    if (settled) return;
    settled = true;
    const t = best.trim();
    if (t) o.onFinal(t); else o.onError("nospeech");
  };
  try { rec.start(); } catch { o.onError("failed"); return null; }
  return {
    stop: () => { try { rec.stop(); } catch { /* already stopped */ } },
    abort: () => { settled = true; try { rec.abort(); } catch { /* already stopped */ } },
  };
}

function listenNative(o: ListenOpts): Listener | null {
  const M = expoStt();
  if (!M) { o.onError("failed", "no speech module in this build"); return null; }
  const R = M.ExpoSpeechRecognitionModule;
  let settled = false;
  // Kept apart, not collapsed into one `best`. The recogniser emits a stream of
  // interim guesses and then a final one, and the final is not necessarily an
  // extension of the last interim — it is a re-decode with the whole utterance
  // in hand ("wie steht das bot" -> "wie steht das board"). Overwriting a final
  // with a later interim, or sending the newest string whatever it was, would
  // ask Henry the question the owner nearly said.
  let finalTxt = "";
  let interimTxt = "";
  const subs: { remove(): void }[] = [];
  const cleanup = () => { subs.forEach((s) => { try { s.remove(); } catch { /* gone */ } }); subs.length = 0; };
  try {
    subs.push(R.addListener("result", (e: unknown) => {
      const r = e as { results?: { transcript?: string }[]; isFinal?: boolean };
      const txt = (r.results?.[0]?.transcript ?? "").trim();
      if (!txt) return;
      if (r.isFinal) finalTxt = txt; else interimTxt = txt;
      o.onPartial(txt);
    }));
    subs.push(R.addListener("volumechange", (e: unknown) => {
      const v = (e as { value?: number }).value;
      // Android reports roughly -2..10 dB here; normalise so the orb reacts on a
      // 0..1 scale like the web analyser path.
      if (typeof v === "number" && o.onLevel) o.onLevel(Math.max(0, Math.min(1, (v + 2) / 12)));
    }));
    subs.push(R.addListener("error", (e: unknown) => {
      if (settled) return;
      settled = true;
      const code = String((e as { error?: string }).error ?? "");
      cleanup();
      if (code.includes("not-allowed") || code.includes("permission")) o.onError("denied");
      else if (code.includes("no-speech")) o.onError("nospeech");
      else o.onError("failed", code);
    }));
    subs.push(R.addListener("end", () => {
      if (settled) return;
      settled = true;
      cleanup();
      // The final if there was one; otherwise the best interim, because a
      // recogniser that ends without a final still heard something and throwing
      // it away would read as "it ignored me".
      const t = (finalTxt || interimTxt).trim();
      if (t) o.onFinal(t); else o.onError("nospeech");
    }));
  } catch {
    cleanup();
    o.onError("failed");
    return null;
  }
  R.requestPermissionsAsync()
    .then((p) => {
      if (settled) return;
      if (!p.granted) { settled = true; cleanup(); o.onError("denied"); return; }
      R.start({ lang: o.lang, interimResults: true, continuous: false, maxAlternatives: 1 });
    })
    .catch(() => { if (!settled) { settled = true; cleanup(); o.onError("failed"); } });
  return {
    stop: () => { try { R.stop(); } catch { /* not running */ } },
    abort: () => { settled = true; cleanup(); try { R.abort(); } catch { /* not running */ } },
  };
}
