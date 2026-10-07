// Streaming dictation - the phone half. Daemon half: spine/media/dictation_stream.py.
//
// The owner holds the mic and TALKS; PCM chunks (~0.5 s each) leave for the
// daemon while he does, over the same sealed relay as every other request, so
// stopping costs the last chunk plus one short decode instead of an upload and
// a decode of the whole utterance. Shape copied from Paseo
// (packages/app/src/dictation/dictation-stream-sender.ts), cut to our transport.
//
// What this class guarantees, and why each is here:
//  - EVERY chunk stays in memory until the final text is back. A frame that
//    fails, a socket that drops, a daemon restart: the stream is disposable,
//    the recording is not. Recovery = new stream id + replay from chunk 0
//    (Paseo #3159 "recordings lost during connection interruptions").
//  - Chunks are numbered and sent with a small window in flight. The daemon
//    serves relay frames on a pool thread, so they can arrive swapped; it
//    reorders by `seq`, the ack says how far the in-order prefix reaches.
//  - A daemon without the route (404 on start) is not an error: the recording
//    is handed whole to the batch route via `legacy`, so a new app against an
//    old daemon dictates exactly like before instead of failing.
//  - finish() never returns a half-sentence: it waits for the full prefix to be
//    acked, and a retryable failure replays instead of giving up.
//
// No react-native import here on purpose: the whole state machine runs under
// plain node (data/__dictation_selftest__.ts) against a fake transport.

export type DictationState = "idle" | "recording" | "processing" | "failed";

/** The four daemon calls. Implemented over the relay in data/client.ts; faked
 *  in the selftest. Throw anything: classify() decides what is retryable. */
export interface DictationApi {
  start(id: string): Promise<unknown>;
  chunk(id: string, seq: number, audioB64: string): Promise<{ ack: number; partial?: string }>;
  finish(id: string, finalSeq: number): Promise<{ text: string }>;
  cancel(id: string): Promise<unknown>;
}

export class DictationError extends Error {
  retryable: boolean;
  constructor(message: string, retryable: boolean) { super(message); this.retryable = retryable; }
}

/** 400/401/403/501 = asking again changes nothing. A thrown error with no
 *  status (transport) or 404/409/5xx = the stream, not the audio, was the
 *  problem: replaying can win. */
export function isRetryable(e: unknown): boolean {
  const s = (e as { status?: number })?.status;
  if (typeof s !== "number") return true;
  return !(s === 400 || s === 401 || s === 403 || s === 501);
}

/** Route missing on this daemon (older than streaming dictation). */
function routeMissing(e: unknown): boolean {
  const s = (e as { status?: number })?.status;
  return s === 404 || s === 405 || s === 501;
}

export interface DictationOpts {
  onPartial?: (text: string) => void;
  onState?: (s: DictationState) => void;
  /** Whole recording -> text through the batch route. Only used when the daemon
   *  has no streaming route. */
  legacy?: (chunksB64: string[]) => Promise<string>;
  genId?: () => string;
  /** Chunks allowed in flight at once. */
  window?: number;
  /** Give up waiting for acks after this long without progress. */
  idleMs?: number;
}

const defaultId = () => `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export class DictationSession {
  state: DictationState = "recording";
  private chunks: string[] = [];
  private id: string;
  private gen = 0;                    // bumped on resync: stale replies are ignored
  private started = false;
  private startP: Promise<void> | null = null;
  private mode: "undecided" | "stream" | "legacy" = "undecided";
  private broken = false;
  private startErr: unknown = null;   // why the last start failed (status decides retryable)
  private next = 0;                   // next seq to send
  private acked = -1;
  private inflight = 0;
  private dead = false;
  private waiters: Array<() => void> = [];
  private readonly window: number;
  private readonly idleMs: number;

  constructor(private api: DictationApi, private opts: DictationOpts = {}) {
    this.id = (opts.genId ?? defaultId)();
    this.window = opts.window ?? 3;
    this.idleMs = opts.idleMs ?? 30_000;
    this.opts.onState?.("recording");
    // Start the stream NOW, while the owner is still finding his first word:
    // by the time chunk 0 is ready the round trip is already paid.
    void this.ensureStarted().then(() => this.kick());
  }

  /** The audio source calls this with each PCM16 chunk (base64). */
  push(chunkB64: string): void {
    if (this.dead || this.state !== "recording") return;
    this.chunks.push(chunkB64);
    this.kick();
  }

  get chunkCount(): number { return this.chunks.length; }

  /** Stop talking: flush, wait for the daemon, return the text. Safe to call
   *  again after a failure - it replays from chunk 0 (the "retry" button). */
  async finish(): Promise<string> {
    if (this.dead) throw new DictationError("dictation cancelled", false);
    this.setState("processing");
    if (!this.chunks.length) {
      // nothing was said: free the daemon's stream now instead of at its idle sweep
      const id = this.id;
      void Promise.resolve().then(() => this.api.cancel(id)).catch(() => undefined);
      this.end();
      return "";
    }
    let last: unknown = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await this.ensureStarted();
        if (this.mode === "legacy") {
          if (!this.opts.legacy) throw new DictationError("daemon has no streaming dictation", false);
          const text = await this.opts.legacy(this.chunks);
          this.end();
          return text;
        }
        if (this.broken) await this.resync();
        await this.drain();
        if (this.broken) throw new DictationError("stream broke while sending", true);
        const r = await this.api.finish(this.id, this.chunks.length - 1);
        this.end();
        return (r.text || "").trim();
      } catch (e) {
        last = e;
        if (this.dead) throw new DictationError("dictation cancelled", false);
        if (!isRetryable(e)) break;
        this.broken = true;           // the next attempt replays under a fresh id
      }
    }
    this.setState("failed");
    const msg = (last as Error)?.message || "dictation failed";
    throw new DictationError(msg, isRetryable(last));
  }

  /** Throw the recording away. Tells the daemon, never waits for it. */
  cancel(): void {
    if (this.dead) return;
    this.dead = true;
    this.chunks = [];
    const id = this.id;
    void Promise.resolve().then(() => this.api.cancel(id)).catch(() => undefined);
    this.setState("idle");
    this.wake();
  }

  // ---- sending ----------------------------------------------------------

  private ensureStarted(): Promise<void> {
    if (this.started || this.mode === "legacy") return Promise.resolve();
    if (this.startP) return this.startP;
    const gen = this.gen;
    this.startP = this.api.start(this.id).then(() => {
      if (gen !== this.gen) return;
      this.started = true;
      this.mode = "stream";
    }).catch((e) => {
      if (gen !== this.gen) return;
      if (routeMissing(e)) this.mode = "legacy";
      else { this.broken = true; this.startErr = e; }
    }).finally(() => { if (gen === this.gen) this.startP = null; });
    return this.startP;
  }

  private kick(): void {
    if (this.dead || this.broken || this.mode === "legacy") return;
    if (!this.started) { void this.ensureStarted().then(() => this.kick()); return; }
    while (this.inflight < this.window && this.next < this.chunks.length) {
      const seq = this.next++;
      const gen = this.gen;
      this.inflight++;
      this.api.chunk(this.id, seq, this.chunks[seq]).then((r) => {
        if (gen !== this.gen) return;
        if (typeof r?.ack === "number") this.acked = Math.max(this.acked, r.ack);
        if (typeof r?.partial === "string") this.opts.onPartial?.(r.partial);
      }).catch(() => {
        if (gen !== this.gen) return;
        this.broken = true;           // keep recording; finish() / retry replays
      }).finally(() => {
        if (gen !== this.gen) return;
        this.inflight--;
        this.kick();
        this.wake();
      });
    }
  }

  /** New id, everything from chunk 0 again. The daemon kept nothing worth
   *  resuming; the phone kept every chunk. */
  private async resync(): Promise<void> {
    this.gen++;
    this.id = (this.opts.genId ?? defaultId)();
    this.started = false;
    this.startP = null;
    this.acked = -1;
    this.next = 0;
    this.inflight = 0;
    this.broken = false;
    this.startErr = null;
    await this.ensureStarted();
    if (this.broken) throw this.startErr ?? new DictationError("could not restart the dictation stream", true);
    this.kick();
  }

  /** Resolves when the whole prefix is acked, the stream broke, or nothing
   *  moved for idleMs (then it marks the stream broken). */
  private drain(): Promise<void> {
    return new Promise((resolve) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const arm = () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => { this.broken = true; done(); }, this.idleMs);
      };
      const done = () => { if (timer) clearTimeout(timer); resolve(); };
      const check = () => {
        if (this.dead || this.broken || this.acked >= this.chunks.length - 1) { done(); return; }
        arm();
        this.waiters.push(check);
      };
      check();
    });
  }

  private wake(): void {
    const w = this.waiters;
    this.waiters = [];
    for (const f of w) f();
  }

  private end(): void { this.dead = true; this.setState("idle"); this.wake(); }

  private setState(s: DictationState): void {
    if (this.state === s) return;
    this.state = s;
    this.opts.onState?.(s);
  }
}

/** PCM16 chunks (base64) -> one WAV (base64) for the batch route. Only the
 *  legacy fallback needs it; pure so it can be tested. */
export function chunksToWavB64(chunksB64: string[], b64decode: (s: string) => Uint8Array,
                               b64encode: (u: Uint8Array) => string): string {
  const parts = chunksB64.map(b64decode);
  const n = parts.reduce((a, p) => a + p.length, 0);
  const out = new Uint8Array(44 + n);
  const dv = new DataView(out.buffer);
  const tag = (o: number, s: string) => { for (let i = 0; i < s.length; i++) out[o + i] = s.charCodeAt(i); };
  tag(0, "RIFF"); dv.setUint32(4, 36 + n, true); tag(8, "WAVE"); tag(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true); tag(36, "data"); dv.setUint32(40, n, true);
  let o = 44;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return b64encode(out);
}
