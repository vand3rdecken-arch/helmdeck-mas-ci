// The phone half of ops/tests/test_app_relay_socket_e2e.py: THIS is the app's
// real data/relay_socket.ts, compiled and run under node, playing the phone
// against a real relay room (local workerd) and a real daemon bridge (Python).
// It prints one JSON line per step; the Python side asserts on them and
// drives the daemon (e.g. moves `v`) in between.
//
//   npx tsc -p tsconfig.relaysocket.json
//   node .relaysocket-out/data/__relay_socket_e2e__.js   (env: URL, P_SEC, D_PUB)
//
// Sealing is the app's exact box (data/e2ee.ts: tweetnacl, nonce||ct, base64)
// re-stated here only because e2ee.ts imports the React Native RNG polyfill,
// which does not load under node.

import nacl from "tweetnacl";
import util from "tweetnacl-util";

import { RelaySocket, SocketError, SocketRetryHttp } from "./relay_socket";

const URL_ = process.env.URL || "";
const P_SEC = process.env.P_SEC || "";
const D_PUB = process.env.D_PUB || "";

function seal(plain: string): string {
  const nonce = nacl.randomBytes(nacl.box.nonceLength);
  const ct = nacl.box(util.decodeUTF8(plain), nonce, util.decodeBase64(D_PUB), util.decodeBase64(P_SEC));
  const f = new Uint8Array(nonce.length + ct.length);
  f.set(nonce);
  f.set(ct, nonce.length);
  return util.encodeBase64(f);
}

function open(b64: string): string {
  const f = util.decodeBase64(b64);
  const m = nacl.box.open(f.slice(nacl.box.nonceLength), f.slice(0, nacl.box.nonceLength),
    util.decodeBase64(D_PUB), util.decodeBase64(P_SEC));
  if (!m) throw new Error("decrypt failed");
  return util.encodeUTF8(m);
}

const out = (o: Record<string, unknown>) => console.log(JSON.stringify(o));
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function waitFor(pred: () => boolean, ms: number) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (pred()) return true; await sleep(50); }
  return false;
}

async function req(s: RelaySocket, method: string, path: string, body = "") {
  const inner = JSON.stringify({ method, path, headers: { "Content-Type": "application/json" }, body });
  try {
    const r = await s.request(inner, 20_000);
    return { ok: true, status: r.status, len: r.body.length, body: r.body.slice(0, 80) };
  } catch (e) {
    if (e instanceof SocketRetryHttp) return { ok: false, retry: "http" };
    if (e instanceof SocketError) return { ok: false, code: e.code };
    return { ok: false, err: String(e) };
  }
}

(async () => {
  const s = new RelaySocket();
  const events: Array<{ v?: number; c?: number }> = [];
  s.onEvent((e) => events.push(e));
  s.start({ url: () => URL_, seal, open });

  // 1. the join announcement makes events live
  const live = await waitFor(() => s.eventsLive, 10_000);
  out({ step: "live", live, first: events[0] ?? null, open: s.isOpen() });

  // 2. requests over the socket
  out({ step: "me", ...(await req(s, "GET", "/me")) });
  out({ step: "echo", ...(await req(s, "POST", "/echo", JSON.stringify({ hello: "socket" }))) });
  const burst = await Promise.all(Array.from({ length: 8 }, (_, i) => req(s, "GET", `/n/${i}`)));
  out({ step: "burst", ok: burst.filter((r) => r.ok && r.body === `{"n": ${burst.indexOf(r)}}`).length,
        bodies: burst.map((r) => r.body) });
  out({ step: "big", ...(await req(s, "GET", "/big")) });

  // 3. a pushed event after the daemon moves v (Python bumps on this line)
  const n0 = events.length;
  out({ step: "await-bump" });
  const got = await waitFor(() => events.length > n0, 10_000);
  out({ step: "event2", got, ev: events[events.length - 1] ?? null });

  // 4. the DAEMON restarts. The phone's socket hangs on the ROOM, not on the
  // daemon, so it stays up; the room tells the new daemon who is listening,
  // and the new daemon sends this phone its state at once.
  const n1 = events.length;
  out({ step: "await-restart" });            // Python: stop the session, start a new one
  const down = await waitFor(() => false, 1500);   // let the old one go
  void down;
  const during = await req(s, "GET", "/me");       // may land in the gap: 503 or ok
  const reannounced = await waitFor(() => events.length > n1, 20_000);
  out({ step: "daemon-restart", phoneSocketStayedUp: s.isOpen(), reannounced, during });
  out({ step: "after-restart", ...(await req(s, "GET", "/me")) });

  // 5. the PHONE's socket drops (OS killed it, network flip): it must reconnect
  // by itself, and be live again through the same re-announcement.
  const n2 = events.length;
  (s as unknown as { ws: WebSocket }).ws.close();
  const dropped = await waitFor(() => !s.eventsLive, 5_000);
  const back = await waitFor(() => s.eventsLive && events.length > n2, 20_000);
  out({ step: "phone-reconnect", dropped, back, open: s.isOpen() });
  out({ step: "after-reconnect", ...(await req(s, "GET", "/me")) });

  s.stop();
  out({ step: "done" });
  process.exit(0);
})();
