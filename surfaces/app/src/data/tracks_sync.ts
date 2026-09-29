import type { QueryClient } from "@tanstack/react-query";
import type { Track } from "./types";

// Delta sync for the board (Linear/Slack model): the phone keeps the board in
// its persisted query cache (data/query.ts) and asks the daemon only for what
// moved since its cursor - GET /tracks?since=<v>&epoch=<e>. The reply is
// {epoch, v, full, changed: summary rows, gone: ids deleted/archived}. The
// cursor lives in the query cache too (["tracksCursor"]), so it is persisted
// and hydrated together with the rows it describes. A failed fetch throws:
// React Query then keeps the last-known rows and only flips `error`.
//
// No React/expo imports: the node self-test drives it with a real QueryClient.
export interface TracksDelta { epoch: number; v: number; full: boolean; changed: Track[]; gone: string[] }
interface Cursor { epoch: number; v: number; at: number }

export const TRACKS_KEY = ["tracks"] as const;
const CURSOR_KEY = ["tracksCursor"] as const;
// The daemon derives some fields at read time; a full re-baseline now and then
// bounds any drift a delta could never see. Once an hour is far cheaper than
// the whole list on every open, which is what this replaces.
const REBASE_MS = 60 * 60 * 1000;

export async function syncTracks(
  qc: Pick<QueryClient, "getQueryData" | "setQueryData">,
  get: (path: string) => Promise<TracksDelta | Track[]>,
): Promise<Track[]> {
  const prev = qc.getQueryData<Track[]>(TRACKS_KEY);
  const cur = qc.getQueryData<Cursor>(CURSOR_KEY);
  const usable = Array.isArray(prev) && cur && Date.now() - cur.at < REBASE_MS;
  let r = await get(`/tracks?since=${usable ? cur.v : 0}&epoch=${usable ? cur.epoch : 0}`);
  // A plain array = the whole list (demo board, an older daemon): re-baseline.
  if (Array.isArray(r)) r = { epoch: 0, v: 0, full: true, changed: r, gone: [] };
  if (!Array.isArray(r?.changed)) throw new Error(String((r as { error?: unknown } | undefined)?.error ?? "bad /tracks reply"));
  // Merge over the cache; a re-baseline replaces it (also rebases `at`).
  const base = r.full || !usable ? [] : prev!;
  const gone = new Set(r.gone);
  const byId = new Map(base.filter((t) => !gone.has(t.id)).map((t) => [t.id, t] as const));
  for (const t of r.changed) byId.set(t.id, t);
  const out = [...byId.values()].sort((a, b) => (a.id < b.id ? 1 : -1));   // daemon order: id DESC
  qc.setQueryData(CURSOR_KEY, { epoch: r.epoch, v: r.v, at: r.full || !usable ? Date.now() : cur!.at });
  return out;
}
