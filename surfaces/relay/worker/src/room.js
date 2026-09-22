// One Durable Object per relay room. Holds ONLY transient state in memory:
// the queue of sealed frames the phone posted, and the callers waiting for a
// reply. Nothing is persisted - a frame that is not pulled within its timeout
// is gone, exactly like relay.py. The DO sees ciphertext only (NaCl box,
// sealed end-to-end between phone and daemon - see spine/comms/e2ee.py).

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
  }

  async fetch(request) {
    const url = new URL(request.url);
    switch (url.pathname) {
      case "/pull":  return this.pull();
      case "/relay": return this.relay(request);
      case "/push":  return this.push(request);
      default:       return json(404, { error: "not found" });
    }
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
    if (Date.now() - this.lastPull > DAEMON_STALE_MS) {
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
    // hand straight to a parked puller if one is waiting, else queue
    const puller = this.pullers.find((p) => !p.done);
    if (puller) { puller.done = true; this.pullers = this.pullers.filter((p) => p !== puller); puller.resolve(frame); }
    else this.q.push(frame);
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
