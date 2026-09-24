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
//
// AND THE PHONE AS A SOCKET (2026-09-24, owner: "warum gibt es noch in app
// sachen, die gepollt sind"). Paseo's relay (packages/relay/src/
// cloudflare-adapter.ts) keeps BOTH ends as hibernating sockets and forwards
// socket to socket; its app polls nothing the daemon could push. Here the
// phone joins with /client?pub=<its key> (tags "client" + "pub:<key>"):
//   phone  {kind:"req", id, cipher}      -> daemon {kind:"frame", id, pub, cipher, t, via:"ws"}
//   daemon {kind:"reply", id, to, cipher} -> phone {kind:"res", id, cipher}
//   daemon {kind:"event", to, cipher}     -> phone {kind:"event", cipher}
//   (new phone socket)                    -> daemon {kind:"client", pub}
// SELF-ADDRESSED REPLIES are the load-bearing choice: between a forwarded
// frame and its reply NOTHING keeps this object awake (no open HTTP request),
// so an in-memory id->socket map would be empty after hibernation. The reply
// names its recipient (`to`), the socket is found by its tag - both survive
// hibernation. HTTP callers keep their in-memory waiter: their open request
// holds the object awake. The payloads stay NaCl-sealed end to end; the room
// learns only which device key a message is for, which it already knew.

const PULL_TIMEOUT_MS = 25_000;   // daemon long-poll (relay.py PULL_TIMEOUT)
const REPLY_TIMEOUT_MS = 120_000; // phone waits for the daemon's reply (REPLY_TIMEOUT)
const DAEMON_STALE_MS = (25 + 15) * 1000; // no pull for this long = "no daemon connected"
const MAX_QUEUE = 64;             // frames queued but not yet pulled
const MAX_WAITING = 64;           // phone requests awaiting a reply
const PUB_RE = /^[A-Za-z0-9+/=_-]{16,128}$/;   // a device public key (base64, 32 bytes = 44)

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
      case "/client": return this.client(request, url);
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
    server.serializeAttachment({ role: "daemon" });
    // Tell the NEW daemon who is already listening, so it can send each of
    // them the current state at once instead of on the next change.
    for (const c of this.state.getWebSockets("client")) {
      const a = attachment(c);
      if (a && a.pub) { try { server.send(JSON.stringify({ kind: "client", pub: a.pub })); } catch {} }
    }
    return new Response(null, { status: 101, webSocket: client });
  }

  // phone -> one persistent, hibernatable socket, addressed by its device key.
  client(request, url) {
    if (request.headers.get("Upgrade") !== "websocket") {
      return json(426, { error: "expected websocket" });
    }
    const pub = url.searchParams.get("pub") || "";
    if (!PUB_RE.test(pub)) return json(400, { error: "pub required" });
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.state.acceptWebSocket(server, ["client", "pub:" + pub]);
    server.serializeAttachment({ role: "client", pub });
    // The daemon answers with the current state (a new daemon does; an old one
    // ignores the unknown kind - and THAT silence is how the phone knows to
    // stay on its long-poll: it switches only after the first event arrives).
    const d = this.daemonSocket();
    if (d) { try { d.send(JSON.stringify({ kind: "client", pub })); } catch {} }
    return new Response(null, { status: 101, webSocket: client });
  }

  // Deliver a daemon reply: the HTTP waiter if one holds this id (it keeps the
  // object awake), else the phone socket(s) the reply is addressed to.
  routeReply(data) {
    const resolve = this.waiting.get(data.id);
    if (resolve) { resolve(data); return; }
    if (typeof data.to !== "string" || !data.to) return;
    for (const c of this.state.getWebSockets("pub:" + data.to)) {
      try {
        c.send(JSON.stringify({ kind: "res", id: data.id, cipher: data.cipher }));
      } catch {
        // Too big for one socket message (a board can be ~2 MB) or the socket
        // died: tell the phone to fetch it over HTTP. Never silence.
        try { c.send(JSON.stringify({ kind: "res", id: data.id, retry: "http" })); } catch {}
      }
    }
  }

  daemonSocket() {
    const all = this.state.getWebSockets("daemon");
    return all.length ? all[all.length - 1] : null;   // newest wins
  }

  // Both ends talk here. The role comes from the socket's own attachment,
  // which survives hibernation - never from the message claiming a role.
  async webSocketMessage(ws, message) {
    if (typeof message !== "string") return;
    let data;
    try { data = JSON.parse(message); } catch { return; }
    if (!data || typeof data.kind !== "string") return;
    const me = attachment(ws) || {};
    if (me.role === "daemon") {
      if (data.kind === "reply" && typeof data.id === "string") this.routeReply(data);
      else if (data.kind === "event" && typeof data.to === "string") {
        for (const c of this.state.getWebSockets("pub:" + data.to)) {
          try { c.send(JSON.stringify({ kind: "event", cipher: data.cipher })); } catch {}
        }
      }
      return;
    }
    if (me.role === "client" && data.kind === "req" && typeof data.id === "string"
        && typeof data.cipher === "string") {
      const d = this.daemonSocket();
      if (!d) {
        // No daemon SOCKET. A long-polling daemon may still be here, but an
        // older one would answer over /push WITHOUT `to` and the reply could
        // not find this socket - so hand the request back to HTTP, which that
        // daemon does serve. No daemon at all -> say so, like /relay's 503.
        const fresh = Date.now() - this.lastPull <= DAEMON_STALE_MS;
        ws.send(JSON.stringify(fresh
          ? { kind: "res", id: data.id, retry: "http" }
          : { kind: "res", id: data.id, status: 503, error: "no daemon connected for this room" }));
        return;
      }
      try {
        d.send(JSON.stringify({ kind: "frame", id: data.id, pub: me.pub, cipher: data.cipher,
                                t: Date.now() / 1000, via: "ws" }));
      } catch {
        ws.send(JSON.stringify({ kind: "res", id: data.id, retry: "http" }));
      }
    }
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
    if (data && typeof data.id === "string") this.routeReply(data);
    return json(200, { ok: true });
  }
}

function attachment(ws) {
  try { return ws.deserializeAttachment(); } catch { return null; }
}
