// THE PHONE'S SOCKET TO ITS RELAY ROOM (owner 2026-09-24: "warum gibt es noch
// in app sachen, die gepollt sind, das macht doch kein senior engineer").
//
// Paseo keeps both ends as hibernating sockets (packages/relay/src/
// cloudflare-adapter.ts) and its app polls nothing the daemon could push. Here
// the phone joins its room with ONE socket (/tunnel/client?room=&pub=) and
// gets two things over it:
//   * requests: {kind:"req", id, cipher} -> {kind:"res", id, cipher}. Same
//     NaCl-sealed inner request as the HTTP path, just without a Cloudflare
//     request per call. The room routes the reply by the phone's key (`to`),
//     so it survives the object hibernating in between.
//   * events:   {kind:"event", cipher} -> {v, c}. The daemon's board/chat
//     cursors, PUSHED the moment they move (spine/comms/relay_client
//     _EventPublisher) - the socket form of the /stream/wait long-poll.
//
// Capability is OBSERVED, never assumed: `eventsLive` turns true only when an
// event actually arrived on this connection. The room tells the daemon a phone
// joined; a new daemon answers with the current state, an old one says
// nothing - and then the app simply keeps its long-poll.
//
// Keepalive: text "ping" every 30 s. A browser/RN socket has no API for
// protocol pings; the room answers this one with setWebSocketAutoResponse,
// which the idle test (ops/tests/test_relay_client_socket.py) measured to cost
// ZERO object invocations. No message at all for 75 s = dead, reconnect.
//
// No React, no expo, no crypto import: sealing is injected, so this file runs
// under plain node in its end-to-end test.

export type RelayEvent = { v?: number; c?: number };

export interface SocketDeps {
  /** wss://…/tunnel/client?room=…&pub=… - or null when not in relay mode. */
  url: () => string | null;
  /** Seal a plaintext to the daemon / open a daemon cipher. */
  seal: (plain: string) => string;
  open: (cipher: string) => string;
  WebSocketImpl?: typeof WebSocket;
}

/** The room could not deliver this over the socket - fetch it over HTTP. */
export class SocketRetryHttp extends Error {}
/** The socket failed this request: closed, timed out, or no daemon. */
export class SocketError extends Error {
  code: "closed" | "timeout" | "offline" | "keys";
  constructor(code: "closed" | "timeout" | "offline" | "keys", msg?: string) {
    super(msg ?? code);
    this.code = code;
  }
}

const PING_EVERY_MS = 30_000;
const DEAD_AFTER_MS = 75_000;
const BACKOFF_MAX_MS = 30_000;
/** A request bigger than this goes over HTTP (the worker caps a frame at 4 MB,
 *  a socket message is meant to stay small). */
export const SOCKET_MAX_REQUEST = 900 * 1024;

type Pending = { resolve: (r: { status: number; body: string }) => void; reject: (e: Error) => void; timer?: ReturnType<typeof setTimeout> };

export class RelaySocket {
  private deps: SocketDeps | null = null;
  private ws: WebSocket | null = null;
  private pending = new Map<string, Pending>();
  private eventFns = new Set<(e: RelayEvent) => void>();
  private liveFns = new Set<(live: boolean) => void>();
  private backoff = 1000;
  private lastRx = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private seq = 0;
  state: "off" | "connecting" | "open" = "off";
  eventsLive = false;

  start(deps: SocketDeps) {
    this.stop();
    this.deps = deps;
    this.running = true;
    this.connect();
  }

  stop() {
    this.running = false;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.teardown("closed");
  }

  /** Reconnect NOW if we are not connected (the app came to the foreground). */
  kick() {
    if (!this.running || this.state !== "off") return;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.backoff = 1000;
    this.connect();
  }

  isOpen() {
    return this.state === "open";
  }

  onEvent(fn: (e: RelayEvent) => void) {
    this.eventFns.add(fn);
    return () => { this.eventFns.delete(fn); };
  }

  onLive(fn: (live: boolean) => void) {
    this.liveFns.add(fn);
    return () => { this.liveFns.delete(fn); };
  }

  /** Resolves once events stop being live (socket dropped) - or never, if
   *  `signal` aborts first, in which case it resolves then. */
  waitNotLive(signal?: { aborted: boolean }) {
    return new Promise<void>((resolve) => {
      if (!this.eventsLive || signal?.aborted) return resolve();
      const off = this.onLive((live) => { if (!live) { off(); resolve(); } });
    });
  }

  /** One sealed request over the socket. `inner` is the plaintext
   *  {method, path, headers, body} JSON - the exact shape the HTTP path seals. */
  request(inner: string, timeoutMs: number): Promise<{ status: number; body: string }> {
    const ws = this.ws;
    const deps = this.deps;
    if (!ws || !deps || this.state !== "open") return Promise.reject(new SocketRetryHttp("socket not open"));
    if (inner.length > SOCKET_MAX_REQUEST) return Promise.reject(new SocketRetryHttp("too large for the socket"));
    const id = `p${Date.now().toString(36)}${(this.seq++).toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    return new Promise((resolve, reject) => {
      const p: Pending = { resolve, reject };
      p.timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new SocketError("timeout"));
      }, timeoutMs);
      this.pending.set(id, p);
      try {
        ws.send(JSON.stringify({ kind: "req", id, cipher: deps.seal(inner) }));
      } catch {
        clearTimeout(p.timer);
        this.pending.delete(id);
        reject(new SocketRetryHttp("send failed"));
      }
    });
  }

  // ---- internals ------------------------------------------------------------

  private setLive(live: boolean) {
    if (this.eventsLive === live) return;
    this.eventsLive = live;
    for (const fn of [...this.liveFns]) fn(live);
  }

  private connect() {
    const deps = this.deps;
    const url = deps?.url();
    if (!deps || !url || !this.running) { this.state = "off"; return; }
    const Impl = deps.WebSocketImpl ?? WebSocket;
    this.state = "connecting";
    let ws: WebSocket;
    try {
      ws = new Impl(url);
    } catch {
      this.state = "off";
      this.scheduleRetry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.state = "open";
      this.backoff = 1000;
      this.lastRx = Date.now();
      this.pingTimer = setInterval(() => {
        if (Date.now() - this.lastRx > DEAD_AFTER_MS) { try { ws.close(); } catch { /* */ } return; }
        try { ws.send("ping"); } catch { /* the close handler reconnects */ }
      }, PING_EVERY_MS);
    };
    ws.onmessage = (m: { data: unknown }) => {
      if (this.ws !== ws) return;
      this.lastRx = Date.now();
      if (typeof m.data !== "string" || m.data === "pong") return;
      let d: { kind?: string; id?: string; cipher?: string; retry?: string; status?: number; error?: string };
      try { d = JSON.parse(m.data); } catch { return; }
      if (d.kind === "event" && typeof d.cipher === "string") {
        let ev: RelayEvent;
        try { ev = JSON.parse(deps.open(d.cipher)); } catch { return; }
        this.setLive(true);
        for (const fn of [...this.eventFns]) fn(ev);
      } else if (d.kind === "res" && typeof d.id === "string") {
        const p = this.pending.get(d.id);
        if (!p) return;
        this.pending.delete(d.id);
        if (p.timer) clearTimeout(p.timer);
        if (d.retry === "http") return p.reject(new SocketRetryHttp("room asked for http"));
        if (d.status === 503) return p.reject(new SocketError("offline", d.error));
        if (typeof d.cipher !== "string" || !d.cipher) return p.reject(new SocketError("closed", "empty reply"));
        let resp: { status?: number; body?: string };
        try { resp = JSON.parse(deps.open(d.cipher)); } catch { return p.reject(new SocketError("keys")); }
        p.resolve({ status: resp.status ?? 200, body: resp.body ?? "" });
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.teardown("closed");
      this.scheduleRetry();
    };
    ws.onerror = () => { /* onclose follows and owns the reconnect */ };
  }

  private teardown(reason: "closed") {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
    const ws = this.ws;
    this.ws = null;
    this.state = "off";
    if (ws) { try { ws.close(); } catch { /* */ } }
    for (const [, p] of this.pending) {
      if (p.timer) clearTimeout(p.timer);
      p.reject(new SocketError(reason));
    }
    this.pending.clear();
    this.setLive(false);
  }

  private scheduleRetry() {
    if (!this.running || this.retryTimer) return;
    const wait = this.backoff;
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
    this.retryTimer = setTimeout(() => { this.retryTimer = null; this.connect(); }, wait);
  }
}

/** The one socket the app uses. */
export const relaySocket = new RelaySocket();

/** wss://…/tunnel/client?room=…&pub=… from the pairing, or null. */
export function clientSocketUrl(relayUrl: string, room: string, myPub: string): string | null {
  if (!relayUrl || !room || !myPub) return null;
  const base = relayUrl.replace(/\/+$/, "");
  const ws = base.startsWith("https://") ? "wss://" + base.slice(8)
    : base.startsWith("http://") ? "ws://" + base.slice(7) : "";
  if (!ws) return null;
  return `${ws}/tunnel/client?room=${encodeURIComponent(room)}&pub=${encodeURIComponent(myPub)}`;
}
