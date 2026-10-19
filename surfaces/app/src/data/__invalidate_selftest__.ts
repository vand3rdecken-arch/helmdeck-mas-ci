// Proves the push->refetch brake with the REAL React Query (2026-09-25).
// A query whose fetch takes 500 ms is observed (as a mounted screen would);
// 50 change events arrive within one second, like a busy daemon's cursor.
// Counted: how many fetches the daemon would have to serve, and how many of
// them the phone ABANDONED (aborted while the daemon still worked on them).
//
// Run: npx tsc -p tsconfig.invalidate.json && node .invalidate-out/data/__invalidate_selftest__.js
import { QueryClient, QueryObserver } from "@tanstack/react-query";

import { keysFor, makeInvalidator } from "./invalidate";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (ok: boolean, msg: string) => {
  console.log((ok ? "  ok  " : "  FAIL ") + msg);
  if (!ok) fails++;
};

async function run(mode: "old" | "new") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let started = 0;
  let abandoned = 0;
  const obs = new QueryObserver(qc, {
    queryKey: ["metrics"],
    queryFn: async ({ signal }) => {
      started++;
      let aborted = false;
      signal.addEventListener("abort", () => { aborted = true; });
      await sleep(500);                       // the daemon keeps working either way
      if (aborted) abandoned++;
      return started;
    },
  });
  const unsub = obs.subscribe(() => {});
  await sleep(700);                           // initial load done
  started = 0;
  abandoned = 0;
  const inv = makeInvalidator(qc, 2000);
  for (let i = 0; i < 50; i++) {              // 50 pushed changes in 1 s
    if (mode === "old") void qc.invalidateQueries();
    else inv.changed();
    await sleep(20);
  }
  await sleep(3500);                          // let everything settle
  inv.dispose();
  unsub();
  qc.clear();
  return { started, abandoned };
}

// 2026-10-19 ("warum soviele ... vs paseo"): what ONE pushed event costs. The
// queries the phone had mounted that evening (System screen over the Henry
// chat with 12 images) - one board tick used to refetch every one of them.
const PHONE = ["tracks", "metrics", "chatThreads", "settings", "me", "cells", "engines", "models",
  "devices", "daemonStatus", "pmPlan", "rooms", "chatHistory",
  ...Array.from({ length: 12 }, (_, i) => "chat-image#" + i)];

async function oneEvent(topics: string[] | undefined) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const hits: string[] = [];
  const unsubs = PHONE.map((k) => {
    const [root, n] = k.split("#");
    const o = new QueryObserver(qc, {
      queryKey: n === undefined ? [root] : [root, n],
      queryFn: async () => { hits.push(k); return k; },
      staleTime: Infinity,
    });
    return o.subscribe(() => {});
  });
  await sleep(50);
  hits.length = 0;
  const inv = makeInvalidator(qc, 0);
  inv.changed(topics);
  await sleep(100);
  inv.dispose();
  unsubs.forEach((u) => u());
  qc.clear();
  return hits;
}

async function topicsRun() {
  const all = await oneEvent(undefined);
  check(all.length === PHONE.length, "an event without topics still refetches everything it holds (" + all.length + ")");
  const card = await oneEvent(["tracks"]);
  check(card.length > 0 && card.length <= 4, "a card write refetches only card views: " + card.join(","));
  check(!card.some((k) => ["engines", "models", "settings", "me"].includes(k) || k.startsWith("chat-image")), "never engines/models/settings/images for a card write");
  const ev = await oneEvent(["events"]);
  check(!ev.some((k) => k.startsWith("chat-image")), "an audit event never refetches the chat images (" + ev.join(",") + ")");
  const unknown = await oneEvent(["something-new"]);
  check(unknown.length === PHONE.length, "a topic this bundle does not know: refetch all, never nothing");
  check(keysFor(["*"]) === null, "'*' means everything");
  const burst = makeInvalidator({ invalidateQueries: (() => Promise.resolve()) as never }, 0);
  burst.dispose();
}

(async () => {
  await topicsRun();
  const old = await run("old");
  const neu = await run("new");
  console.log("   old: %d fetches, %d abandoned mid-flight", old.started, old.abandoned);
  console.log("   new: %d fetches, %d abandoned mid-flight", neu.started, neu.abandoned);
  check(old.started >= 20, "the OLD invalidate-per-event really floods (" + old.started + " fetches for 50 events)");
  check(neu.started >= 1 && neu.started <= 2, "the brake: 50 events in 1 s -> " + neu.started + " fetch(es)");
  check(neu.abandoned === 0, "no fetch is abandoned while the daemon still serves it (" + neu.abandoned + ")");
  console.log(fails ? "\n" + fails + " FAIL" : "\nall ok");
  process.exit(fails ? 1 : 0);
})();
