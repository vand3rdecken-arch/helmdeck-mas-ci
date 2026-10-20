import type { QueryClient } from "@tanstack/react-query";
import type { Track } from "./types";

// Delta sync for the board, the Replicache pull shape (rocicorp/mono
// packages/replicache/src/puller.ts PullResponseOKV1, patch-operation.ts,
// sync/patch.ts): the client sends the opaque `cookie` of its last pull, the
// server answers {cookie, patch:[{op:"put",key,value} | {op:"del",key} |
// {op:"clear"}]}, and the patch is applied to the local copy in one step.
// `clear` is how the server forces a re-baseline (unknown/foreign cookie).
// The board lives in the persisted query cache (data/query.ts); the cookie
// lives there too (["tracksCookie"]), so both are hydrated together. A failed
// pull throws: React Query then keeps the last-known rows and only flips
// `error`, so the screen shows the cache with an offline hint, never nothing.
//
// No React/expo imports: the node self-test drives it with a real QueryClient.
export type PatchOp =
  | { op: "put"; key: string; value: Track }
  | { op: "del"; key: string }
  | { op: "clear" };
/** `older_done`: how many done cards the server holds back (past its window).
 *  Sent on a full baseline only; the client keeps the last value. */
export interface PullResponse { cookie: string; patch: PatchOp[]; older_done?: number }

export const TRACKS_KEY = ["tracks"] as const;
export const OLDER_KEY = ["tracksOlder"] as const;
const COOKIE_KEY = ["tracksCookie"] as const;

export async function syncTracks(
  qc: Pick<QueryClient, "getQueryData" | "setQueryData">,
  get: (path: string) => Promise<PullResponse | Track[]>,
): Promise<Track[]> {
  const prev = qc.getQueryData<Track[]>(TRACKS_KEY);
  const cookie = Array.isArray(prev) ? qc.getQueryData<string>(COOKIE_KEY) : undefined;
  let r = await get(`/tracks?cookie=${cookie ?? ""}`);
  // A plain array = the whole list (demo board, an older daemon): re-baseline.
  if (Array.isArray(r)) r = { cookie: "", patch: [{ op: "clear" }, ...r.map((t): PatchOp => ({ op: "put", key: t.id, value: t }))] };
  if (!Array.isArray(r?.patch)) throw new Error(String((r as { error?: unknown } | undefined)?.error ?? "bad /tracks reply"));
  const rows = applyPatch(cookie ? prev! : [], r.patch);
  qc.setQueryData(COOKIE_KEY, r.cookie);
  if (typeof r.older_done === "number") qc.setQueryData(OLDER_KEY, r.older_done);
  return rows;
}

function applyPatch(prev: readonly Track[], patch: readonly PatchOp[]): Track[] {
  const byId = new Map(prev.map((t) => [t.id, t] as const));
  for (const p of patch) {
    if (p.op === "clear") byId.clear();
    else if (p.op === "del") byId.delete(p.key);
    else byId.set(p.key, p.value);
  }
  return [...byId.values()].sort((a, b) => (a.id < b.id ? 1 : -1));   // daemon order: id DESC
}

/** A card patch that rode a pushed event (relay_client._EventPublisher `tp`,
 *  computed by the SAME routes_tracks.tracks_patch the pull uses). Paseo's
 *  agent_update carries the agent the same way: the phone updates its board
 *  without a /tracks request.
 *
 *  A patch "since F" holds every card changed after F with its CURRENT value,
 *  so it is correct for any local state between F and its own cookie T: apply
 *  when the epoch matches and F <= ours <= T. Older than F = we missed writes
 *  (a dropped socket) - return false and the topic's pull catches up. Newer
 *  than T = we already have it. Nothing cached = nothing to patch onto. */
export function applyPushedPatch(
  qc: Pick<QueryClient, "getQueryData" | "setQueryData">,
  tp: { from: string; cookie: string; patch: PatchOp[] } | undefined,
): boolean {
  if (!tp || !Array.isArray(tp.patch) || tp.patch.some((p) => p.op === "clear")) return false;
  const prev = qc.getQueryData<Track[]>(TRACKS_KEY);
  const mine = qc.getQueryData<string>(COOKIE_KEY);
  if (!Array.isArray(prev) || !mine) return false;
  const [me, mv] = mine.split(".").map(Number);
  const [fe, fv] = tp.from.split(".").map(Number);
  const [te, tv] = tp.cookie.split(".").map(Number);
  if (![me, mv, fe, fv, te, tv].every(Number.isFinite) || me !== fe || fe !== te) return false;
  if (mv > tv) return true;                  // already at or past this patch
  if (mv < fv) return false;                 // a gap: pull
  qc.setQueryData(TRACKS_KEY, applyPatch(prev, tp.patch));
  qc.setQueryData(COOKIE_KEY, tp.cookie);
  return true;
}
