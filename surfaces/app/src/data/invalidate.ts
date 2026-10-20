import type { QueryClient } from "@tanstack/react-query";

// The brake between PUSHED change events and refetching (2026-09-25).
//
// A busy daemon moves its `v` cursor several times a second, and every pushed
// event used to call queryClient.invalidateQueries() - whose default
// cancelRefetch abandons the fetch that is still running and starts the next.
// The phone forgot the old request; the daemon still served it to its 115 s
// timeout on its own thread: 1,504 threads, 4.8 GB, 100 % CPU, "Desktop
// offline". The long-poll never did this because its own round-trip was the
// brake; push has none, so this is it:
//   - at most one refetch wave per `everyMs`, TRAILING (the last change in a
//     burst always lands, nothing is missed);
//   - cancelRefetch:false - a query that is already fetching is left to
//     finish, never restarted. The next wave picks up whatever moved since.
//
// No React/expo imports: the node self-test drives it with a real QueryClient.
// WHICH queries a topic refreshes (2026-10-19, "warum soviele ... vs paseo").
// The daemon names a topic at every write (spine/storage/db.py bump(topic=...))
// and sends what moved since the last event as `t`. Paseo's app never calls
// invalidateQueries() without a key either (push-router.ts scopes every
// invalidation); before this, ONE board tick refetched every mounted query
// plus every chat image - 25 requests over the relay per tick.
// A topic missing here, "*" or an event without `t` (older daemon, join
// announce) refetches everything: unknown is never treated as "nothing moved".
// Chat streams (chatHistory, rooms, henry) ride the `c` cursor, not this.
export const TOPIC_KEYS: Record<string, readonly string[]> = {
  tracks: ["tracks", "tracksArchived", "metrics", "chatThreads", "pmPlan", "loopmap", "history", "runs",
    "turns", "ckpts", "attachments", "transcript", "escalations", "usage", "debt", "sessions",
    "claude-sessions", "checkpoints", "run-timeline", "cpdiff"],
  events: ["metrics", "usage", "history", "debt", "gxpState", "checkpoints", "ckpts", "pmPlan",
    "escalations", "audit", "daemonStatus"],
  escalations: ["escalations", "chatThreads", "tracks", "pmPlan"],
  pm: ["pmPlan", "automation", "processes"],
  processes: ["processes", "chatThreads", "pmPlan", "automation", "tracks"],
  process_templates: ["automation", "processes"],
  projects: ["projectsShared", "projectBrowse", "repoTemplates", "tracks", "loopmap", "harnessConfig"],
  project_config: ["harnessConfig", "harness", "harnessBrief", "projectsShared", "settings", "loopmap"],
  workspace_config: ["settings", "me", "cells", "engines", "models", "modelsProbe", "harness",
    "harnessBrief", "harnessConfig", "gxpState", "devices", "automation", "daemonStatus", "usage",
    "connectors", "invites", "users", "roomAccounts", "chatGrants", "accessGrants", "peers", "repoTemplates", "takeout",
    "foreignMemory"],
  policy: ["settings", "harness", "harnessConfig", "harnessBrief", "gxpState"],
  user_config: ["me", "settings", "cells"],
  boards: ["tracks", "me", "metrics"],
  connectors: ["connectors"],
  models: ["models", "modelsProbe", "engines"],
  secrets: ["me", "engines", "models", "modelsProbe", "settings"],
};

/** Query roots that a board topic never refreshes, on purpose: the chat
 *  streams follow the `c` cursor (data/stream.ts ensureChatFresh), and a chat
 *  image is immutable by its URL. Every OTHER query root in the app must sit in
 *  TOPIC_KEYS - ops/tests/test_query_topic_coverage.py scans the source and fails otherwise,
 *  so a new screen cannot silently stop refreshing. */
export const NOT_BOARD_KEYS: readonly string[] = ["chatHistory", "rooms", "room", "henry", "chat-image"];

/** The query-key roots a set of topics refreshes, or null = everything. */
export function keysFor(topics: readonly string[] | undefined): Set<string> | null {
  if (!topics) return null;
  const out = new Set<string>();
  for (const t of topics) {
    const keys = TOPIC_KEYS[t];
    if (!keys) return null;                    // "*" or a topic this bundle does not know
    for (const k of keys) out.add(k);
  }
  return out;
}

export function makeInvalidator(qc: Pick<QueryClient, "invalidateQueries">, everyMs = 2000) {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  // what the pending wave refreshes: null = everything, else the union of the
  // events' keys since the last wave (a burst of different topics never loses one)
  let pending: Set<string> | null | undefined;
  // EXACT query keys the wave's events already brought the data for (a pushed
  // card patch fills ["tracks"] - but not ["tracks", id], the full card the
  // detail screen holds). Only what EVERY event in the wave settled counts:
  // one event whose patch could not apply means the pull must still run.
  let settledAll: Set<string> | undefined;
  const fire = () => {
    timer = null;
    last = Date.now();
    const keys = pending;
    const settled = settledAll ?? new Set<string>();
    pending = undefined;
    settledAll = undefined;
    if (keys === null || keys === undefined) {
      void qc.invalidateQueries(undefined, { cancelRefetch: false });
    } else if (keys.size) {
      void qc.invalidateQueries({
        predicate: (q) => keys.has(String(q.queryKey[0])) && !settled.has(JSON.stringify(q.queryKey)),
      }, { cancelRefetch: false });
    }
  };
  return {
    /** Something moved: schedule one refetch wave (coalesced). `topics` = what
     *  the daemon said moved; omitted = unknown, refetch everything. `settled`
     *  = exact query keys this event already filled (never refetched for it). */
    changed(topics?: readonly string[], settled: readonly (readonly unknown[])[] = []) {
      const keys = keysFor(topics);
      if (keys === null || pending === null) pending = null;
      else pending = new Set([...(pending ?? []), ...keys]);
      const mine = new Set(settled.map((k) => JSON.stringify(k)));
      settledAll = settledAll === undefined ? mine : new Set([...settledAll].filter((k) => mine.has(k)));
      if (timer) return;
      timer = setTimeout(fire, Math.max(0, last + everyMs - Date.now()));
    },
    dispose() {
      if (timer) clearTimeout(timer);
      timer = null;
    },
  };
}
