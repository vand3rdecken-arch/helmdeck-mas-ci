// Proves board delta sync with the REAL React Query (2026-09-29): after one
// baseline, an open costs a tiny delta; with the network down the cache is
// still returned (fetch failure keeps last-known rows, never an empty board).
//
// Run: npx tsc -p tsconfig.invalidate.json && node .invalidate-out/data/__tracks_sync_selftest__.js
import { QueryClient } from "@tanstack/react-query";

import { syncTracks, TRACKS_KEY, type PullResponse } from "./tracks_sync";
import type { Track } from "./types";

let fails = 0;
const check = (ok: boolean, msg: string) => {
  console.log((ok ? "  ok  " : "  FAIL ") + msg);
  if (!ok) fails++;
};
const row = (id: string, x = ""): Track => ({ id, last_reply: "c" + id + x } as unknown as Track);

(async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const paths: string[] = [];
  const sizes: number[] = [];
  let reply: PullResponse | Track[] | Error;
  const get = async (p: string) => {
    paths.push(p);
    if (reply instanceof Error) throw reply;
    sizes.push(JSON.stringify(reply).length);
    return reply;
  };
  const fetchBoard = () => qc.fetchQuery({ queryKey: TRACKS_KEY, queryFn: () => syncTracks(qc, get), staleTime: 0 });

  const big = Array.from({ length: 400 }, (_, i) => row(String(3000 - i), "x".repeat(200)));
  reply = { cookie: "7.50", patch: [{ op: "clear" }, ...big.map((t) => ({ op: "put" as const, key: t.id, value: t }))] };
  let rows = await fetchBoard();
  check(rows.length === 400 && paths[0] === "/tracks?cookie=", "first open = baseline");

  reply = { cookie: "7.53", patch: [{ op: "put", key: "3000", value: row("3000", "NEW") }, { op: "put", key: "9000", value: row("9000") }, { op: "del", key: "2999" }] };
  rows = await fetchBoard();
  check(paths[1] === "/tracks?cookie=7.50", "second open sends the cursor");
  check(rows.length === 400 && rows[0].id === "9000" && rows.find((r) => r.id === "3000")!.last_reply!.endsWith("NEW")
        && !rows.some((r) => r.id === "2999"), "delta merged: new on top, changed replaced, gone removed");
  check(sizes[1] < sizes[0] / 50, `delta reply is small (${sizes[1]} B vs ${sizes[0]} B baseline)`);

  reply = new Error("network down");
  let threw = false;
  try { await fetchBoard(); } catch { threw = true; }
  check(threw && qc.getQueryData<Track[]>(TRACKS_KEY)!.length === 400, "offline: fetch fails but the cached board stays");

  reply = { cookie: "8.1", patch: [{ op: "clear" }, { op: "put", key: "5", value: row("5") }] };   // daemon restarted
  await fetchBoard();
  check(paths[3] === "/tracks?cookie=7.53" && qc.getQueryData<Track[]>(TRACKS_KEY)!.length === 1,
        "clear op = full re-baseline replaces the cache");

  console.log(fails ? `\n${fails} FAILED` : "\nall ok");
  process.exit(fails ? 1 : 0);
})();
