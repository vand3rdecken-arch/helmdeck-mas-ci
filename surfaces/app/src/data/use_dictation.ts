// useDictation - mic + DictationSession + the UI-facing state, for the composer.
//
// The composer owns WHAT happens to the text (insert at the end, or insert and
// send); this hook owns the recording lifecycle:
//
//   idle -> starting -> recording -> processing -> idle
//                                        \-> failed -> (retry) processing ...
//
// Guards, copied from Paseo's use-dictation.ts because each is a real race:
//  - start while already starting/recording/processing is refused (a double tap
//    must not open two microphones);
//  - confirm and cancel are mutually exclusive and idempotent (Enter and the X
//    in the same frame);
//  - an unmount mid-recording releases the mic and tells the daemon, so a
//    screen change never leaves the microphone open.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./client";
import { DictationSession, chunksToWavB64, type DictationApi } from "./dictation";
import { MicError, dictationMicUsable, openDictationMic, type MicHandle } from "./dictation_mic";

export type UiState = "idle" | "starting" | "recording" | "processing" | "failed";

const dictApi: DictationApi = {
  start: (id) => api.dictationStart(id),
  chunk: (id, seq, audio) => api.dictationChunk(id, seq, audio),
  finish: (id, finalSeq) => api.dictationFinish(id, finalSeq),
  cancel: (id) => api.dictationCancel(id),
};

const b64decode = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const b64encode = (u: Uint8Array) => {
  let s = "";
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s);
};

/** Old daemon without the streaming route: the whole recording as one WAV
 *  through the batch route, exactly what dictation-less builds always did. */
const legacy = async (chunks: string[]) =>
  (await api.transcribe(chunksToWavB64(chunks, b64decode, b64encode))).text;

export interface DictationEvents {
  /** The text is back. `send` = the owner chose "insert and send". */
  onText: (text: string, send: boolean) => void;
  /** Nothing intelligible was said (silence, a mis-tap). Not an error. */
  onEmpty?: () => void;
}

export function useDictation(ev: DictationEvents) {
  const [state, setState] = useState<UiState>("idle");
  const [level, setLevel] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState("");
  const usable = useRef(dictationMicUsable()).current;

  const evRef = useRef(ev);
  evRef.current = ev;
  const sessionRef = useRef<DictationSession | null>(null);
  const micRef = useRef<MicHandle | null>(null);
  const gate = useRef({ starting: false, confirming: false, cancelling: false });
  const sendRef = useRef(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastLevel = useRef(0);
  const alive = useRef(true);

  const stopTimer = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };

  const reset = useCallback(() => {
    stopTimer();
    sessionRef.current = null;
    micRef.current = null;
    if (!alive.current) return;
    setState("idle"); setLevel(0); setSeconds(0); setPartial(""); setError("");
  }, []);

  const start = useCallback(async () => {
    const g = gate.current;
    if (!usable || g.starting || sessionRef.current) return;
    g.starting = true;
    setError(""); setPartial(""); setSeconds(0); setState("starting");
    const session = new DictationSession(dictApi, {
      onPartial: (t) => { if (alive.current) setPartial(t); },
      legacy,
    });
    sessionRef.current = session;
    try {
      micRef.current = await openDictationMic({
        onChunk: (b64) => session.push(b64),
        onLevel: (l) => {
          if (!alive.current || Math.abs(l - lastLevel.current) < 0.05) return;
          lastLevel.current = l; setLevel(l);
        },
      });
      if (!alive.current || sessionRef.current !== session) {   // cancelled while the mic opened
        await micRef.current.stop().catch(() => undefined);
        return;
      }
      const t0 = Date.now();
      timer.current = setInterval(() => setSeconds(Math.floor((Date.now() - t0) / 1000)), 500);
      setState("recording");
    } catch (e) {
      session.cancel();
      sessionRef.current = null;
      setError(e instanceof MicError && e.reason === "denied" ? "mic-denied"
        : e instanceof MicError && e.reason === "blocked" ? "mic-blocked" : "mic-unavailable");
      setState("failed");
    } finally {
      g.starting = false;
    }
  }, [usable]);

  /** Stop talking and get the text. `send` = insert AND send. */
  const confirm = useCallback(async (send: boolean) => {
    const g = gate.current;
    const session = sessionRef.current;
    if (!session || g.confirming || g.cancelling || (state !== "recording" && state !== "failed")) return;
    g.confirming = true;
    sendRef.current = send;
    stopTimer();
    setState("processing"); setError("");
    try {
      const mic = micRef.current;
      micRef.current = null;
      if (mic) await mic.stop();                 // flushes the tail chunk into the session
      const text = (await session.finish()).trim();
      if (!alive.current) return;
      if (text) evRef.current.onText(text, send); else evRef.current.onEmpty?.();
      reset();
    } catch (e) {
      if (!alive.current) return;
      setError((e as Error)?.message || "failed");
      setState("failed");                        // chunks are kept: retry replays them
    } finally {
      g.confirming = false;
    }
  }, [state, reset]);

  const cancel = useCallback(async () => {
    const g = gate.current;
    if (g.cancelling || g.confirming) return;
    g.cancelling = true;
    try {
      const session = sessionRef.current;
      const mic = micRef.current;
      sessionRef.current = null; micRef.current = null;
      session?.cancel();
      if (mic) await mic.stop().catch(() => undefined);
      reset();
    } finally {
      g.cancelling = false;
    }
  }, [reset]);

  /** After a failed finish: replay the kept recording. Same insert/send choice. */
  const retry = useCallback(() => confirm(sendRef.current), [confirm]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      stopTimer();
      sessionRef.current?.cancel();
      micRef.current?.stop().catch(() => undefined);
    };
  }, []);

  return { usable, state, level, seconds, partial, error, start, confirm, cancel, retry };
}
