// Selftest for data/dictation.ts - the streaming dictation state machine, run
// against a FAKE daemon that behaves like the real one where it matters:
// chunks may arrive swapped and late, a stream can die, a route can be missing.
//
// Run: npx tsc -p tsconfig.dictation.json && node .dictation-out/data/__dictation_selftest__.js
import { DictationSession, DictationApi, DictationError, chunksToWavB64, isRetryable } from "./dictation";
import { applyCleanup, undoCleanup } from "./dictation_clean";

let fails = 0;
function check(name: string, cond: unknown, detail?: unknown) {
  console.log(`${cond ? "ok  " : "FAIL"} ${name}${!cond && detail !== undefined ? " - " + JSON.stringify(detail) : ""}`);
  if (!cond) fails++;
}
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const err = (status?: number, msg = "x") => Object.assign(new Error(msg), status === undefined ? {} : { status });

interface Daemon {
  api: DictationApi;
  streams: Map<string, { chunks: Map<number, string>; ack: number }>;
  log: string[];
  maxInflight: number;
  // knobs
  delay: (seq: number) => number;
  failChunk: (id: string, seq: number) => Error | null;
  failStart: Error | null;
  failFinish: (id: string, n: number) => Error | null;
}

function fakeDaemon(): Daemon {
  const d: Daemon = {
    streams: new Map(), log: [], maxInflight: 0,
    delay: () => 1, failChunk: () => null, failStart: null, failFinish: () => null,
    api: null as unknown as DictationApi,
  };
  let finishCalls = 0;
  let inflight = 0;
  d.api = {
    async start(id) {
      d.log.push("start:" + id);
      if (d.failStart) throw d.failStart;
      d.streams.set(id, { chunks: new Map(), ack: -1 });
      return { id };
    },
    async chunk(id, seq, audio) {
      inflight++; d.maxInflight = Math.max(d.maxInflight, inflight);
      try {
        await sleep(d.delay(seq));
        const f = d.failChunk(id, seq);
        if (f) throw f;
        const s = d.streams.get(id);
        if (!s) throw err(404, "dictation stream not started");
        s.chunks.set(seq, audio);
        while (s.chunks.has(s.ack + 1)) s.ack++;
        return { ack: s.ack, partial: "p" + s.ack };
      } finally { inflight--; }
    },
    async finish(id, finalSeq) {
      const f = d.failFinish(id, ++finishCalls);
      if (f) throw f;
      const s = d.streams.get(id);
      if (!s) throw err(404, "dictation stream not started");
      if (s.ack < finalSeq) throw err(409, "chunks missing");
      d.log.push("finish:" + id);
      d.streams.delete(id);
      return { text: Array.from({ length: finalSeq + 1 }, (_, i) => s.chunks.get(i)).join(" ") };
    },
    async cancel(id) { d.log.push("cancel:" + id); d.streams.delete(id); return {}; },
  };
  return d;
}

let n = 0;
const ids = () => `id${++n}`;

async function feed(s: DictationSession, count: number, gap = 2) {
  for (let i = 0; i < count; i++) { s.push("c" + i); await sleep(gap); }
}

async function main() {
  // 1. swapped, late chunks still come back in order; window respected
  {
    const d = fakeDaemon();
    d.delay = (seq) => (seq % 2 ? 1 : 12);                 // odd chunks overtake even ones
    const partials: string[] = [];
    const s = new DictationSession(d.api, { genId: ids, onPartial: (p) => partials.push(p), window: 3 });
    await feed(s, 8);
    const text = await s.finish();
    check("swapped chunks reassemble in order", text === "c0 c1 c2 c3 c4 c5 c6 c7", text);
    check("window of 3 respected", d.maxInflight <= 3, d.maxInflight);
    check("partials flowed while recording", partials.length > 0, partials);
    check("state back to idle after finish", s.state === "idle", s.state);
  }

  // 2. connection drops mid-recording: keep recording, replay under a NEW id
  {
    const d = fakeDaemon();
    let outage = false;
    d.failChunk = (_id, seq) => {                           // transport error, no status
      if (seq === 3) outage = true;                         // the network drops at chunk 3 ...
      return outage ? err() : null;                         // ... and stays down until the test says
    };
    const s = new DictationSession(d.api, { genId: ids });
    await feed(s, 8);
    check("recording kept all 8 chunks through the outage", s.chunkCount === 8, s.chunkCount);
    outage = false;                                         // network is back
    d.failChunk = () => null;
    const text = await s.finish();
    check("replay under a fresh id recovers the whole text", text === "c0 c1 c2 c3 c4 c5 c6 c7", text);
    const starts = d.log.filter((l) => l.startsWith("start:"));
    check("a second stream was started for the replay", starts.length === 2, d.log);
  }

  // 3. daemon forgot the stream (restart): finish gets 404 -> replay
  {
    const d = fakeDaemon();
    const s = new DictationSession(d.api, { genId: ids });
    await feed(s, 4);
    await sleep(20);
    d.streams.clear();                                      // daemon restarted
    const text = await s.finish();
    check("daemon restart mid-recording: text still complete", text === "c0 c1 c2 c3", text);
  }

  // 4. old daemon without the route -> legacy batch path, no chunk calls
  {
    const d = fakeDaemon();
    d.failStart = err(404, "?");
    let chunkCalls = 0;
    const orig = d.api.chunk; d.api.chunk = (...a) => { chunkCalls++; return orig(...a); };
    let got: string[] = [];
    const s = new DictationSession(d.api, { genId: ids, legacy: async (c) => { got = c.slice(); return "legacy text"; } });
    await feed(s, 5);
    const text = await s.finish();
    check("old daemon: falls back to the batch route", text === "legacy text", text);
    check("old daemon: batch got EVERY chunk", got.length === 5, got);
    check("old daemon: no streaming chunk calls", chunkCalls === 0, chunkCalls);
  }

  // 5. refusal that replay cannot fix is not retried forever
  {
    const d = fakeDaemon();
    const s = new DictationSession(d.api, { genId: ids });
    await feed(s, 3);
    d.failStart = err(403, "no cap");
    d.failChunk = () => err();                              // force a resync, whose start is refused
    d.streams.clear();
    let thrown: DictationError | null = null;
    try { await s.finish(); } catch (e) { thrown = e as DictationError; }
    check("403 on restart fails finish", thrown !== null);
    check("403 is reported as not retryable", thrown?.retryable === false, thrown?.retryable);
    check("state is failed (chunks kept for a retry)", s.state === "failed", s.state);
    // owner taps retry after fixing the cause
    d.failStart = null; d.failChunk = () => null;
    const text = await s.finish();
    check("retry after failure replays and succeeds", text === "c0 c1 c2", text);
  }

  // 6. nothing said: "" and the daemon's stream is freed
  {
    const d = fakeDaemon();
    const s = new DictationSession(d.api, { genId: ids });
    await sleep(5);
    const text = await s.finish();
    await sleep(5);
    check("empty recording returns empty text", text === "", text);
    check("empty recording cancels the daemon stream", d.log.some((l) => l.startsWith("cancel:")), d.log);
  }

  // 7. cancel: tells the daemon, finish after cancel refuses
  {
    const d = fakeDaemon();
    const s = new DictationSession(d.api, { genId: ids });
    await feed(s, 3);
    s.cancel();
    await sleep(5);
    check("cancel reaches the daemon", d.log.some((l) => l.startsWith("cancel:")), d.log);
    let refused = false;
    try { await s.finish(); } catch { refused = true; }
    check("finish after cancel is refused", refused);
    s.push("late");
    check("audio pushed after cancel is ignored", s.chunkCount === 0, s.chunkCount);
  }

  // 8. a LATE ack from the abandoned stream must not count for the new one
  {
    const d = fakeDaemon();
    let first = true;
    d.delay = (seq) => (first && seq === 0 ? 60 : 1);
    d.failChunk = (_id, seq) => (first && seq === 2 ? err() : null);
    const s = new DictationSession(d.api, { genId: ids });
    await feed(s, 4);
    first = false;
    d.delay = () => 1; d.failChunk = () => null;
    const text = await s.finish();
    check("stale reply after resync is ignored", text === "c0 c1 c2 c3", text);
  }

  // 9. never finishes with a gap: drain times out -> replay, not a half text
  {
    const d = fakeDaemon();
    let swallow = true;
    const orig = d.api.chunk;
    d.api.chunk = async (id, seq, a) => {                   // chunk 1 is accepted but never answered
      if (swallow && seq === 1) await new Promise(() => undefined);
      return orig(id, seq, a);
    };
    const s = new DictationSession(d.api, { genId: ids, idleMs: 40 });
    await feed(s, 3);
    swallow = false;
    const text = await s.finish();
    check("a lost reply times out and replays instead of returning a half-text",
      text === "c0 c1 c2", text);
  }

  // 10. helpers
  check("transport error is retryable", isRetryable(err()));
  check("403 not retryable / 409 retryable", !isRetryable(err(403)) && isRetryable(err(409)));
  {
    const b64d = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
    const b64e = (u: Uint8Array) => btoa(Array.from(u, (b) => String.fromCharCode(b)).join(""));
    const pcm = new Uint8Array(100).fill(7);
    const wav = b64d(chunksToWavB64([b64e(pcm.slice(0, 60)), b64e(pcm.slice(60))], b64d, b64e));
    const dv = new DataView(wav.buffer);
    const tag = (o: number) => String.fromCharCode(wav[o], wav[o + 1], wav[o + 2], wav[o + 3]);
    check("wav header: RIFF/WAVE, 16 kHz mono, data length", tag(0) === "RIFF" && tag(8) === "WAVE"
      && dv.getUint32(24, true) === 16000 && dv.getUint16(22, true) === 1
      && dv.getUint32(40, true) === 100 && wav.length === 144, wav.length);
  }

  // 11. cleanup swap: only where the raw dictation still sits verbatim
  {
    const raw = "starte den Bild jetzt", cleaned = "Starte den Build jetzt";
    check("swap works when the field is just the dictation", applyCleanup(raw, raw, cleaned) === cleaned);
    check("swap keeps what was typed before and after",
      applyCleanup("Hallo Henry. " + raw + " und danke", raw, cleaned) === "Hallo Henry. " + cleaned + " und danke");
    check("swap is refused once the owner edited the dictation", applyCleanup("starte den Bild später", raw, cleaned) === null);
    check("swap is refused after the field was cleared or sent", applyCleanup("", raw, cleaned) === null);
    check("swap is refused when the cleaned text is empty or identical",
      applyCleanup(raw, raw, "") === null && applyCleanup(raw, raw, raw) === null);
    check("two identical dictations: only the LAST one is swapped",
      applyCleanup(raw + " " + raw, raw, cleaned) === raw + " " + cleaned);
    check("undo restores the raw text", undoCleanup("x " + cleaned, cleaned, raw) === "x " + raw);
    check("undo is refused once the cleaned text was changed", undoCleanup("x Starte den Build", cleaned, raw) === null);
  }

  console.log(fails ? `\n${fails} failure(s)` : "\nall passed");
  process.exit(fails ? 1 : 0);
}

main();
