import type { Track } from "./types";

// A parked turn (status needs_you) is only "the turn ended". What it waits for
// is derived daemon-side per read (lifecycle.card_phase -> track.phase) from the
// open question / waiting_on / lane - never stored, never re-guessed here.
// Without a phase (older daemon, other statuses) the raw status stands.
const PHASE_KEY: Record<string, string> = {
  asking: "status.asking", ready: "status.ready", delivered: "status.delivered",
  background: "status.background",
};

/** i18n key for the badge, or null = fall back to the status vocabulary. */
export const phaseKey = (k: Pick<Track, "phase">) => (k.phase ? PHASE_KEY[k.phase] ?? null : null);

/** Only an open question or a card in Review is the OWNER's move. */
export const needsOwner = (k: Pick<Track, "status" | "phase">) =>
  k.phase === "asking" || k.phase === "ready" || k.status === "bounced";
