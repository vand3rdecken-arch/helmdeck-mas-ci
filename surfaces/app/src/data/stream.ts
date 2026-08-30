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
