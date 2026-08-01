import { useConfig } from "./config";
import { open, seal } from "./e2ee";
import type { Track, Metrics, Me } from "./types";

export class AuthRequired extends Error {}

function authHeaders(): Record<string, string> {
  const { token } = useConfig.getState();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

// Relay path: seal {method,path,headers,body} to the daemon's pubkey, POST it to
// the relay room, open the sealed {status,headers,body} reply. Byte-compatible
// with daemon/relay_client.py + e2ee.py. The relay only ever sees ciphertext.
async function relayReq(method: string, path: string, bodyStr: string): Promise<{ status: number; body: string }> {
  const { relayUrl, room, daemonPub, mySec, myPub } = useConfig.getState();
  const inner = JSON.stringify({ method, path, headers: authHeaders(), body: bodyStr });
  const cipher = seal(inner, mySec, daemonPub);
  const r = await fetch(`${relayUrl}/relay?room=${room}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pub: myPub, cipher }),
  });
  if (!r.ok) throw new Error(r.status === 503 ? "Desktop nicht erreichbar" : `relay ${r.status}`);
  const out = JSON.parse(await r.text());
  if (!out.cipher) throw new Error("Desktop antwortet nicht");
  const resp = JSON.parse(open(out.cipher, mySec, daemonPub));
  return { status: resp.status ?? 200, body: resp.body ?? "" };
}

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const cfg = useConfig.getState();
  const bodyStr = method === "GET" ? "" : JSON.stringify(body ?? {});
  let status: number, txt: string;
  if (cfg.relayMode()) {
    ({ status, body: txt } = await relayReq(method, path, bodyStr));
  } else {
    const r = await fetch(cfg.baseUrl + path, {
      method, headers: authHeaders(),
      body: method === "GET" ? undefined : bodyStr, signal,
    });
    status = r.status; txt = await r.text();
  }
  if (status === 401) throw new AuthRequired();
  return (txt ? JSON.parse(txt) : {}) as T;
}

/** One transcript/feed row — a loose shape woven from the daemon's transcript
 *  turns + lifecycle notes; rendered by the card feed. */
export interface Step {
  cls?: string; kind?: string; role?: string; text?: string; ts?: string;
  tool?: string; input?: unknown; result?: string; name?: string;
}
export interface ChatMsg { cls: string; text: string; ts?: string }
// POST /chat returns the copilot's answer, not a ChatMsg: {reply, actions, ...}
// (or {error} on a rejection). Keep ChatMsg for /chat/history entries.
export interface ChatReply { reply?: string; error?: string; cost?: number;
  actions?: { tool?: string; detail?: string }[]; usage?: unknown }

export interface SteerOpts { model?: string; thinking?: string; mode?: string }

export const api = {
  get: <T,>(path: string) => req<T>("GET", path),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) => req<T>("POST", path, body, signal),
  // Board PUSH long-poll: blocks until the data version passes `v` (or ~22s),
  // returns the new version. Works over the sealed relay AND direct; the app
  // loops it and invalidates queries on change (replaces the direct-only SSE).
  boardWait: (v: number) => req<{ v: number }>("GET", `/stream/wait?v=${v}`),

  // board / cards
  tracks: () => req<Track[]>("GET", "/tracks"),
  metrics: () => req<Metrics>("GET", "/dashboard/data"),
  me: () => req<Me>("GET", "/me"),
  moveLane: (id: string, lane: string) => req<Track>("POST", `/tracks/${id}/lane`, { lane }),
  reorder: (ids: string[]) => req("POST", "/tracks/reorder", { ids }),
  newTrack: (b: Record<string, unknown>) => req("POST", "/tracks/new", b),
  update: (id: string, patch: Record<string, unknown>) => req("POST", `/tracks/${id}/update`, patch),
  archive: (id: string) => req("POST", `/tracks/${id}/archive`),
  fork: (id: string, from = "") => req("POST", `/tracks/${id}/fork`, { from }),
  del: (id: string) => req("POST", `/tracks/${id}/delete`),
  cancel: (id: string) => req("POST", `/tracks/${id}/cancel`),
  steer: (id: string, text: string, o: SteerOpts = {}) =>
    req("POST", `/tracks/${id}/steer`, { text, ...o }),

  // card detail feeds
  transcript: (id: string) => req<Step[]>("GET", `/tracks/${id}/transcript`),
  // Long-poll PUSH: the daemon holds this until the transcript changes (or ~22s)
  // then returns {v, steps}. Works over the sealed relay AND direct — the phone
  // loops it, passing back the last v, for real streaming latency (no SSE).
  transcriptLive: (id: string, v: string) =>
    req<{ v: string; steps: Step[] }>("GET", `/tracks/${id}/transcript/live?v=${encodeURIComponent(v)}`),
  history: (id: string) => req<Step[]>("GET", `/tracks/${id}/history`),
  turns: (id: string) => req<unknown[]>("GET", `/tracks/${id}/turns`),

  // copilot chat
  chat: (text: string, o: SteerOpts & { card?: string } = {}) => req<ChatReply>("POST", "/chat", { text, ...o }),
  chatCancel: () => req("POST", "/chat/cancel", {}),
  chatHistory: () => req<{ messages: ChatMsg[]; session_id?: string }>("GET", "/chat/history"),

  models: () => req<{ id: string; label?: string; desc?: string }[]>("GET", "/models"),
  automation: () => req<Record<string, unknown>>("GET", "/automation"),

  // Phase 2 section lists
  processes: () => req<any[]>("GET", "/processes"),
  runs: () => req<any[]>("GET", "/runs"),
  claudeSessions: () => req<any[]>("GET", "/sessions/claude"),
  adoptClaude: (b: Record<string, unknown>) => req<{ id?: string; error?: string }>("POST", "/sessions/claude/adopt", b),
  gitHistory: () => req<any[]>("GET", "/history"),

  // settings / users / connectors
  settings: () => req<Record<string, any>>("GET", "/settings"),
  saveSettings: (patch: Record<string, unknown>) => req("POST", "/settings", patch),
  users: () => req<import("./types").UserRow[]>("GET", "/users"),
  setRole: (name: string, role: string) => req("POST", `/users/${name}/role`, { role }),
  issueToken: (name: string, label: string) => req<{ token: string }>("POST", `/users/${name}/tokens`, { label }),
  connectors: () => req<any[]>("GET", "/connectors"),
  runConnector: (name: string) => req<{ cards?: number }>("POST", `/connectors/${name}/run`),
  rollbackConnector: (name: string) => req("POST", `/connectors/${name}/rollback`),
};

