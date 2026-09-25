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
export function makeInvalidator(qc: Pick<QueryClient, "invalidateQueries">, everyMs = 2000) {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const fire = () => {
    timer = null;
    last = Date.now();
    void qc.invalidateQueries(undefined, { cancelRefetch: false });
  };
  return {
    /** Something moved: schedule one refetch wave (coalesced). */
    changed() {
      if (timer) return;
      timer = setTimeout(fire, Math.max(0, last + everyMs - Date.now()));
    },
    dispose() {
      if (timer) clearTimeout(timer);
      timer = null;
    },
  };
}
