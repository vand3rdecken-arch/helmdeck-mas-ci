// Seed charter — CLAUDE.md as a MODULE, not an outside law. Seeded from today's
// content; swappable by user/agent via a tracked swap (kernel.swap emits a
// journal entry + returns rollback). The on-disk CLAUDE.md is the `source`
// materialization the outer Claude Code harness also reads, so a real swap
// edits that file AND records the reconfiguration.
//
// agentMaySwap (in the seeded PolicySet) defaults false: an agent-initiated
// swap of this module wants a human confirm until you seed it true. Nothing
// here is immovable — it's just tracked and reversible.

import { KEYS, type CharterDoc, type Plugin } from "@/kernel";

/** The load-bearing laws, seeded as data. Reworded from the old "fixed harness"
 *  stance into the full-dynamism decree: the floor is trackability, not
 *  immovability. Swap this module to change them. */
export const CHARTER_SEED: CharterDoc = {
  source: "CLAUDE.md",
  version: 1,
  laws: [
    "Nothing mutates untracked: every module/state/rule change appends a TrackEntry.",
    "Rules are seeded (not deleted) and swappable; every swap is reversible.",
    "Load-bearing state is derived and verified from runtime signals, folded in at "
      + "event time, mutated at exactly one owner (generalized NO-MONKEY-PATCH).",
    "Secrets (settings.json, users.json, helmdeck.db, tokens) are git-ignored, never committed.",
    "UI changes are screenshot-and-JUDGED, not just confirmed to render.",
  ],
};

/** Seed plugin: provides KEYS.CHARTER. tier:"seed" = came from the charter. */
export const seedCharter: Plugin = {
  id: "seed.charter",
  tier: "seed",
  register(scope) {
    scope.provide(KEYS.CHARTER, CHARTER_SEED);
  },
};
