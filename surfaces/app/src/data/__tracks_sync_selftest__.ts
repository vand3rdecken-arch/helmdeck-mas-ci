// Proves board delta sync with the REAL React Query (2026-09-29): after one
// baseline, an open costs a tiny delta; with the network down the cache is
// still returned (fetch failure keeps last-known rows, never an empty board).
//
// Run: npx tsc -p tsconfig.invalidate.json && node .invalidate-out/data/__tracks_sync_selftest__.js
import { QueryClient } from "@tanstack/react-query";

import { makeInvalidator } from "./invalidate";
import { applyPushedPatch, syncTracks, TRACKS_KEY, type PullResponse } from "./tracks_sync";
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

  // -- pushed patch (2026-10-20): the card change rides the event, no /tracks request --
  // the cache is now at cookie 8.1 with card 5
  const before = paths.length;
  const put = (id: string, x: string) => ({ op: "put" as const, key: id, value: row(id, x) });
  check(applyPushedPatch(qc, { from: "8.1", cookie: "8.4", patch: [put("6", ""), put("5", "-v2")] }),
        "patch from our exact cookie applies");
  const b = qc.getQueryData<Track[]>(TRACKS_KEY)!;
  check(b.length === 2 && (b.find((t) => t.id === "5") as unknown as { last_reply: string }).last_reply === "c5-v2",
        "the board holds the pushed values");
  check(qc.getQueryData<string>(["tracksCookie"]) === "8.4", "and the cookie moved to the patch's own");
  check(applyPushedPatch(qc, { from: "8.2", cookie: "8.6", patch: [{ op: "del", key: "6" }] }),
        "a patch from an OLDER point than ours still applies (it holds current values)");
  check(qc.getQueryData<Track[]>(TRACKS_KEY)!.length === 1, "del removed the card");
  check(!applyPushedPatch(qc, { from: "8.9", cookie: "8.12", patch: [put("7", "")] }),
        "a patch from AFTER our cookie is refused - we missed writes, the pull must run");
  check(qc.getQueryData<Track[]>(TRACKS_KEY)!.length === 1, "and the board was not touched");
  check(applyPushedPatch(qc, { from: "8.1", cookie: "8.3", patch: [put("9", "")] }) &&
        !qc.getQueryData<Track[]>(TRACKS_KEY)!.some((t) => t.id === "9"),
        "a patch we are already past: settled, nothing re-applied");
  check(!applyPushedPatch(qc, { from: "7.6", cookie: "7.9", patch: [put("8", "")] }),
        "another daemon process (epoch) is refused");
  check(!applyPushedPatch(qc, { from: "8.6", cookie: "8.9", patch: [{ op: "clear" }] }),
        "a baseline never rides an event");
  check(paths.length === before, "none of this made a /tracks request");

  // the invalidator skips EXACTLY ["tracks"], never the card detail ["tracks", id]
  const hit: string[] = [];
  const fake = {
    invalidateQueries: (f?: { predicate?: (q: { queryKey: unknown[] }) => boolean }) => {
      for (const k of [["tracks"], ["tracks", "5"], ["metrics"], ["engines"]]) {
        if (f?.predicate?.({ queryKey: k })) hit.push(JSON.stringify(k));
      }
      return Promise.resolve();
    },
  };
  const inv = makeInvalidator(fake as never, 0);
  inv.changed(["tracks"], [TRACKS_KEY]);
  await new Promise((r) => setTimeout(r, 20));
  check(!hit.includes('["tracks"]') && hit.includes('["tracks","5"]') && hit.includes('["metrics"]') && !hit.includes('["engines"]'),
        "settled list is not refetched; the card detail and derived views are (" + hit.join(" ") + ")");
  hit.length = 0;
  inv.changed(["tracks"], [TRACKS_KEY]);
  inv.changed(["tracks"], []);              // a second event in the same wave whose patch did not apply
  await new Promise((r) => setTimeout(r, 20));
  check(hit.includes('["tracks"]'), "one unsettled event in the wave: the list IS pulled");
  inv.dispose();

  console.log(fails ? `\n${fails} FAILED` : "\nall ok");
  process.exit(fails ? 1 : 0);
})();
