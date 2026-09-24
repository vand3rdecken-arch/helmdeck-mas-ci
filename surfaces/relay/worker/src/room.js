// One Durable Object per relay room. Holds ONLY transient state in memory:
// the queue of sealed frames the phone posted, and the callers waiting for a
// reply. Nothing is persisted - a frame that is not pulled within its timeout
// is gone, exactly like relay.py. The DO sees ciphertext only (NaCl box,
// sealed end-to-end between phone and daemon - see spine/comms/e2ee.py).
//
// TWO WAYS FOR THE DAEMON TO BE HERE (2026-09-24). The daemon used to
// long-poll /pull every 25 s: 3,456 requests a day per PC while NOTHING
// happened, each one holding this object awake for its whole wait. That is
// what tripped Cloudflare's free-plan limit on 2026-09-23 with a single user
// ("This website has been temporarily rate limited", 429 even on /health).
// The daemon now keeps ONE WebSocket open instead (tag "daemon"), accepted
// through the Hibernation API: while it idles this object sleeps and bills
// nothing, and the keepalive text "ping" is answered "pong" by the runtime
// WITHOUT waking it. A phone frame goes down the socket; the reply comes back
// up it - or over /push, both resolve the same waiting id. /pull stays for
// daemons that have not upgraded yet and for relays without WebSocket.

const PULL_TIMEOUT_MS = 25_000;   // daemon long-poll (relay.py PULL_TIMEOUT)
const REPLY_TIMEOUT_MS = 120_000; // phone waits for the daemon's reply (REPLY_TIMEOUT)
const DAEMON_STALE_MS = (25 + 15) * 1000; // no pull for this long = "no daemon connected"
const MAX_QUEUE = 64;             // frames queued but not yet pulled
const MAX_WAITING = 64;           // phone requests awaiting a reply

function json(code, obj) {
  return new Response(JSON.stringify(obj), {
    status: code, headers: { "content-type": "application/json" },
  });
}

export class Room {
  constructor(state, env) {
    this.state = state;
    this.q = [];                 // [{id, pub, cipher, t}]
    this.waiting = new Map();    // id -> resolve(replyObj)
    this.pullers = [];           // resolve(frame|null) for parked /pull calls
    this.lastPull = 0;
    // The daemon's keepalive is answered by the RUNTIME, not by this code: the
    // object is not woken, so an idle PC costs no duration and no request. The
    // constructor runs again after every wake; setting the same pair again is
    // idempotent.
    this.state.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request) {
    const url = new URL(request.url);
    switch (url.pathname) {
      case "/pull":  return this.pull();
      case "/relay": return this.relay(request);
      case "/push":  return this.push(request);
      case "/ws":    return this.ws(request);
      default:       return json(404, { error: "not found" });
    }
  }

  // daemon -> one persistent, hibernatable socket for this room.
  ws(request) {
    if (request.headers.get("Upgrade") !== "websocket") {
      return json(426, { error: "expected websocket" });
    }
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    // ONE daemon per room: a new socket is a restarted daemon, so it replaces
    // whatever was there. Two live sockets would split frames between an old
    // process and a new one - the shape of the 2026-09-23 twin daemons.
    for (const old of this.state.getWebSockets("daemon")) {
      try { old.close(1012, "replaced by a newer daemon connection"); } catch {}
    }
    this.state.acceptWebSocket(server, ["daemon"]);
    return new Response(null, { status: 101, webSocket: client });
  }

  daemonSocket() {
    const all = this.state.getWebSockets("daemon");
    return all.length ? all[all.length - 1] : null;   // newest wins
  }

  // daemon -> reply over the socket. Same semantics as /push: an unknown id is
  // harmless (the phone gave up already).
  async webSocketMessage(ws, message) {
    if (typeof message !== "string") return;
    let data;
    try { data = JSON.parse(message); } catch { return; }
    if (!data || data.kind !== "reply" || typeof data.id !== "string") return;
    const resolve = this.waiting.get(data.id);
    if (resolve) resolve(data);
  }

  async webSocketClose(ws, code) {
    try { ws.close(code === 1005 ? 1000 : code, "closing"); } catch {}
  }

  async webSocketError(ws) {
    try { ws.close(1011, "error"); } catch {}
  }

  // daemon -> next queued frame, or 204 after PULL_TIMEOUT
  async pull() {
    this.lastPull = Date.now();
    if (this.q.length) return json(200, this.q.shift());
    const frame = await new Promise((resolve) => {
      const entry = { resolve, done: false };
      this.pullers.push(entry);
      setTimeout(() => {
        if (entry.done) return;
        entry.done = true;
        this.pullers = this.pullers.filter((p) => p !== entry);
        resolve(null);
      }, PULL_TIMEOUT_MS);
    });
    if (frame === null) return new Response(null, { status: 204 });
    return json(200, frame);
  }

  // phone -> queue a frame, wait for the daemon's reply
  async relay(request) {
    const sock = this.daemonSocket();
    if (!sock && Date.now() - this.lastPull > DAEMON_STALE_MS) {
      return json(503, { error: "no daemon connected for this room" });
    }
    let data;
    try { data = await request.json(); } catch { return json(400, { error: "bad json" }); }
    if (!data || typeof data.cipher !== "string" || typeof data.pub !== "string" || !data.cipher || !data.pub) {
      return json(400, { error: "pub + cipher required" });
    }
    if (this.q.length >= MAX_QUEUE || this.waiting.size >= MAX_WAITING) {
      return json(429, { error: "room busy" });
    }
    const id = crypto.randomUUID().replace(/-/g, "");
    const frame = { id, pub: data.pub, cipher: data.cipher, t: Date.now() / 1000 };
    const reply = new Promise((resolve) => this.waiting.set(id, resolve));
    // The socket first: no queue, no puller, no extra request. If the send
    // throws (the socket died between the check and here) the frame drops
    // through to the long-poll path, which a reconnecting daemon drains.
    let sent = false;
    if (sock) {
      try { sock.send(JSON.stringify({ kind: "frame", ...frame })); sent = true; } catch {}
    }
    if (!sent) {
      // hand straight to a parked puller if one is waiting, else queue
      const puller = this.pullers.find((p) => !p.done);
      if (puller) { puller.done = true; this.pullers = this.pullers.filter((p) => p !== puller); puller.resolve(frame); }
      else this.q.push(frame);
    }
    const timeout = new Promise((resolve) => setTimeout(() => resolve(null), REPLY_TIMEOUT_MS));
    const resp = await Promise.race([reply, timeout]);
    this.waiting.delete(id);
    if (!resp) return json(504, { error: "daemon offline or slow" });
    return json(200, { cipher: typeof resp.cipher === "string" ? resp.cipher : "" });
  }

  // daemon -> reply for a waiting phone request. Unknown id is a harmless 200
  // (the phone may have given up already) - relay.py semantics.
  async push(request) {
    let data;
    try { data = await request.json(); } catch { return json(400, { error: "bad json" }); }
    const resolve = data && this.waiting.get(data.id);
    if (resolve) resolve(data);
    return json(200, { ok: true });
  }
}
