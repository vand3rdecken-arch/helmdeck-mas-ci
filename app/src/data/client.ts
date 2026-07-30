import { useConfig } from "./config";
import type { Track, Metrics, Me } from "./types";

export class AuthRequired extends Error {}

// The daemon speaks Bearer-token auth uniformly (daemon/auth.py); we no longer
// rely on the web's same-origin cookie. Reads baseUrl+token live from the store
// so re-pairing / re-pointing takes effect without reconstructing a client.
function headers(): Record<string, string> {
  const { token } = useConfig.getState();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const { baseUrl } = useConfig.getState();
  const r = await fetch(baseUrl + path, {
    method,
    headers: headers(),
    body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
    signal,
  });
  if (r.status === 401) throw new AuthRequired();
  const txt = await r.text();
  return (txt ? JSON.parse(txt) : {}) as T;
}

/** One transcript/feed row — a loose shape woven from the daemon's transcript
 *  turns + lifecycle notes; rendered by the card feed. */
export interface Step {
  cls?: string; kind?: string; role?: string; text?: string; ts?: string;
  tool?: string; input?: unknown; result?: string; name?: string;
}
export interface ChatMsg { cls: string; text: string; ts?: string }

export interface SteerOpts { model?: string; thinking?: string; mode?: string }

export const api = {
  get: <T,>(path: string) => req<T>("GET", path),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) => req<T>("POST", path, body, signal),

  // board / cards
  tracks: () => req<Track[]>("GET", "/tracks"),
  metrics: () => req<Metrics>("GET", "/dashboard/data"),
  me: () => req<Me>("GET", "/me"),
  moveLane: (id: string, lane: string) => req("POST", `/tracks/${id}/lane`, { lane }),
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
  history: (id: string) => req<Step[]>("GET", `/tracks/${id}/history`),
  turns: (id: string) => req<unknown[]>("GET", `/tracks/${id}/turns`),

  // copilot chat
  chat: (text: string, o: SteerOpts & { card?: string } = {}) => req<ChatMsg>("POST", "/chat", { text, ...o }),
  chatHistory: () => req<{ messages: ChatMsg[]; session_id?: string }>("GET", "/chat/history"),

  models: () => req<string[]>("GET", "/models"),
  automation: () => req<Record<string, unknown>>("GET", "/automation"),

  // Phase 2 section lists
  processes: () => req<any[]>("GET", "/processes"),
  runs: () => req<any[]>("GET", "/runs"),
  claudeSessions: () => req<any[]>("GET", "/sessions/claude"),
  gitHistory: () => req<any[]>("GET", "/history"),
};

