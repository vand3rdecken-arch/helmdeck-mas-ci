// The microphone half of dictation: raw 16 kHz mono PCM16 in ~0.5 s chunks
// (base64), plus a 0..1 level for the meter. The session that numbers, sends
// and replays them is data/dictation.ts - this file only produces audio.
//
//  web     getUserMedia + a ScriptProcessor, linearly resampled down to 16 kHz.
//          (Paseo's use-dictation-audio-source.web.ts does exactly this; the
//          deprecated node still works everywhere and is seek-free, an
//          AudioWorklet would need a separately served module file.)
//  native  modules/livemic startStream - AudioRecord on the PHONE mic in
//          MODE_NORMAL, so the glasses' A2DP route is never touched
//          (ops/docs/glasses-reference.md:209). ABSENT on an APK built before
//          the module grew it. THEN the older `start` + onSegment path is used
//          (VAD-cut WAV per phrase, re-cut here into the same 0.5 s chunks): the
//          text arrives phrase by phrase instead of word by word, but the
//          button never disappears from a phone whose APK is older than the OTA
//          (measured 2026-10-07: 1.0.51 + the dictation bundle = no mic at all).

import { Platform, PermissionsAndroid } from "react-native";
import LiveMic from "../../modules/livemic";

import { CHUNK_SAMPLES, feedWav } from "./dictation_wav";
export { CHUNK_SAMPLES };

export class MicError extends Error {
  constructor(public reason: "denied" | "blocked" | "unavailable", message: string) { super(message); }
}

export interface MicHandle {
  /** Stops capture and resolves AFTER the last (partial) chunk went to onChunk. */
  stop(): Promise<void>;
}

export interface MicOpts {
  onChunk: (b64: string) => void;
  onLevel?: (level: number) => void;
}

export function dictationMicUsable(): boolean {
  if (Platform.OS === "web") {
    const w = globalThis as any;
    return !!w.navigator?.mediaDevices?.getUserMedia && !!(w.AudioContext || w.webkitAudioContext);
  }
  return LiveMic != null && (typeof LiveMic.startStream === "function" || typeof LiveMic.start === "function");
}

export async function openDictationMic(o: MicOpts): Promise<MicHandle> {
  return Platform.OS === "web" ? openWeb(o) : openNative(o);
}

// ---- native -------------------------------------------------------------

async function openNative(o: MicOpts): Promise<MicHandle> {
  const mic = LiveMic;
  if (!mic || (typeof mic.startStream !== "function" && typeof mic.start !== "function")) {
    throw new MicError("unavailable", "this build has no microphone module");
  }
  if (Platform.OS === "android") {
    const r = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO);
    // never_ask_again: Android will not show the prompt again, so asking is
    // pointless - the only way out is the app's settings page (the bar offers it).
    if (r === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN) throw new MicError("blocked", "microphone permission blocked");
    if (r !== PermissionsAndroid.RESULTS.GRANTED) throw new MicError("denied", "microphone permission denied");
  }
  const legacy = typeof mic.startStream !== "function";
  const chunks = legacy
    ? mic.addListener("onSegment", (e: { b64?: string }) => { if (e?.b64) feedWav(e.b64, o.onChunk); })
    : mic.addListener("onChunk", (e: { b64?: string }) => { if (e?.b64) o.onChunk(e.b64); });
  const levels = legacy
    ? mic.addListener("onState", (e: { state?: string }) => o.onLevel?.(e?.state === "speech" ? 0.5 : 0.08))
    : mic.addListener("onLevel", (e: { level?: number }) => o.onLevel?.(e?.level ?? 0));
  let ok = false;
  try { ok = legacy ? await mic.start(true) : await mic.startStream!(true); } catch { ok = false; }
  if (!ok) {
    chunks.remove(); levels.remove();
    throw new MicError("unavailable", "microphone unavailable");
  }
  return {
    async stop() {
      try { await mic.stop(); } catch { /* already idle */ }
      // the tail chunk is an event on the same thread as this promise; one
      // beat lets it land before the listener goes (voice_mode.tsx does the same)
      await new Promise((r) => setTimeout(r, 60));
      chunks.remove(); levels.remove();
    },
  };
}

// ---- web ----------------------------------------------------------------

function toB64(pcm: Int16Array): string {
  const u8 = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode(...u8.subarray(i, i + 0x8000));
  return btoa(s);
}

async function openWeb(o: MicOpts): Promise<MicHandle> {
  const w = globalThis as any;
  let stream: MediaStream;
  try {
    stream = await w.navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (e) {
    const name = (e as Error)?.name;
    throw new MicError(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "unavailable",
      (e as Error)?.message || "microphone unavailable");
  }
  const Ctx = w.AudioContext || w.webkitAudioContext;
  const ctx: AudioContext = new Ctx();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const mute = ctx.createGain();            // the processor must be wired to run; silence it
  mute.gain.value = 0;
  const ratio = ctx.sampleRate / 16000;
  let pos = 0;                              // fractional read position carried across blocks
  let out = new Int16Array(CHUNK_SAMPLES);
  let filled = 0;

  proc.onaudioprocess = (ev: AudioProcessingEvent) => {
    const inp = ev.inputBuffer.getChannelData(0);
    let sum = 0;
    for (let i = 0; i < inp.length; i++) sum += inp[i] * inp[i];
    o.onLevel?.(Math.min(1, Math.sqrt(sum / inp.length) * 4));
    while (pos < inp.length) {
      const i = Math.floor(pos);
      const a = inp[i];
      const b = inp[Math.min(i + 1, inp.length - 1)];
      const v = a + (b - a) * (pos - i);
      out[filled++] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
      if (filled === CHUNK_SAMPLES) { o.onChunk(toB64(out)); out = new Int16Array(CHUNK_SAMPLES); filled = 0; }
      pos += ratio;
    }
    pos -= inp.length;
  };
  src.connect(proc); proc.connect(mute); mute.connect(ctx.destination);

  return {
    async stop() {
      try { proc.onaudioprocess = null; src.disconnect(); proc.disconnect(); mute.disconnect(); } catch { /* gone */ }
      stream.getTracks().forEach((t) => t.stop());
      if (filled > 0) o.onChunk(toB64(out.slice(0, filled)));   // the tail the owner just said
      filled = 0;
      try { await ctx.close(); } catch { /* already closed */ }
    },
  };
}
