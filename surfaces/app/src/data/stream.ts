import { create } from "zustand";

/**
 * What the DAEMON on the other end of /stream/wait can actually do.
 *
 * This exists for one measured hazard: an OTA bundle and a daemon restart are
 * INDEPENDENT events on the owner's machine (DEPLOY.md - JS ships in seconds,
 * the daemon keeps running whatever it booted with). So a phone can easily be
 * running this bundle while the PC still runs a daemon that has never heard of
 * the chat cursor.
 *
 * Without this flag that skew is a silent regression, not a graceful one: the
 * new chat.tsx has NO refetchInterval because it trusts the stream, and an old
 * daemon never returns `c` - so the transcript would simply stop updating on
 * the phone until the owner happened to restart his daemon, which looks exactly
 * like the delay this whole change set out to remove.
 *
 * The signal is the reply shape itself, not a version string or a capability
 * probe: `c` present means the daemon has the cursor, absent means it does not.
 * Derived from the runtime's own answer at event time and owned in exactly one
 * place (useGlobalStream) - the no-monkey-patches rule, not a stored guess.
 */
type StreamCaps = {
  /** null = not yet known (no successful stream reply). */
  chatEvents: boolean | null;
  setChatEvents: (v: boolean) => void;
};

export const useStreamCaps = create<StreamCaps>((set) => ({
  chatEvents: null,
  setChatEvents: (v) => set((s) => (s.chatEvents === v ? s : { chatEvents: v })),
}));

/**
 * How often the chat may fall back to asking, in ms, or `false` for never.
 *
 * `false` as soon as the daemon proves it pushes chat events - that is the
 * point of the change. 8000 only while we KNOW it cannot (old daemon), which
 * is precisely the interval that shipped before, so the degraded path is the
 * old behaviour rather than a new, worse one.
 *
 * While still unknown (null, i.e. before the first stream reply) we also poll:
 * the first seconds after a cold start are exactly when the owner opens the
 * chat, and guessing "it pushes" there would show him a stale transcript at the
 * worst possible moment. It costs at most one extra fetch before the stream
 * answers and switches it off.
 */
export function chatFallbackInterval(chatEvents: boolean | null): number | false {
  return chatEvents === true ? false : 8000;
}

/**
 * CATCH-UP for the chat transcript - the missing half of the event stream.
 *
 * The wake-up (`c` moved on /stream/wait) and the data (GET /chat/history)
 * are two separate requests, and the loop in _layout.tsx advances its cursor
 * on the wake-up alone. So one failed refetch - a 20s relay timeout, a
 * backgrounded socket, retry:1 exhausted - used to leave the transcript
 * stuck: the cursor was consumed, no fallback poll runs against a daemon that
 * pushes events, and nothing tried again until the NEXT chat write or an app
 * restart (owner, 2026-09-12 22:06: "Antwort kam erst nach App-Neustart",
 * same on the watch). The glasses never had this defect because /glance/chat
 * returns the transcript INSIDE the hanging GET - wake and data are one
 * request, so a failure leaves the cursor where it was.
 *
 * This is the phone's equivalent: refetch until React Query reports success,
 * with capped backoff, single-flight (a second wake while one catch-up runs
 * just marks it to go once more). Import cycle note: query.ts must not import
 * this module, so the client is passed in.
 */
import type { QueryClient } from "@tanstack/react-query";

/**
 * IS A CATCH-UP RUNNING - the signal chat.tsx shows a loading state from,
 * same shape as `useStreamCaps` above (derived at event time, one owner).
 *
 * Without this the chat screen had no way to tell "old transcript, still
 * fresh" from "old transcript, a refetch is in flight" - ensureChatFresh ran
 * silently in the background (owner report 2026-09-14: nothing on screen said
 * a reload was happening, so a stale transcript read as current). This
 * reuses the SAME ActivityIndicator convention settings.tsx already has
 * (`{isLoading && owner ? <ActivityIndicator .../> : null}`) rather than
 * inventing a new loading affordance.
 *
 * `attempt`/`long` exist for the NN Group response-time thresholds (0.1/1/10s,
 * the same guideline Material Design and Apple HIG build on): a retry loop
 * that can run past 10s (worst case here: 3000ms doubling to 30000ms over 12
 * tries) must stop reading as "spinner stuck" past that point. `long` flips
 * once the loop has been retrying for >=10s so chat.tsx can swap the bare
 * spinner for an attempt-numbered status line - still derived at event time
 * from ensureChatFresh's own clock, not a separate guess.
 */
export const useChatCatchup = create<{ active: boolean; attempt: number; long: boolean }>(() => ({
  active: false,
  attempt: 0,
  long: false,
}));

let _inflight = false;
let _again = false;

export async function ensureChatFresh(qc: QueryClient): Promise<void> {
  if (_inflight) { _again = true; return; }
  _inflight = true;
  const startedAt = Date.now();
  useChatCatchup.setState({ active: true, attempt: 0, long: false });
  try {
    let delay = 3000;
    // ~5 minutes of trying, then give up until the next wake (never forever:
    // an unpaired or logged-out client must not hammer the relay).
    for (let i = 0; i < 12; i++) {
      _again = false;
      await qc.refetchQueries({ queryKey: ["chatHistory"] });
      void qc.invalidateQueries({ queryKey: ["chatThreads"] });   // previews/order follow the chat
      const st = qc.getQueryState(["chatHistory"]);
      // no observer/never fetched (chat not open) counts as fresh: the screen
      // fetches on mount, and refetchQueries above is a no-op for it anyway.
      if (!st || st.status !== "error") {
        if (_again) { delay = 3000; continue; }
        return;
      }
      useChatCatchup.setState({ attempt: i + 1, long: Date.now() - startedAt >= 10000 });
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 30000);
    }
  } finally {
    _inflight = false;
    useChatCatchup.setState({ active: false, attempt: 0, long: false });
  }
}
