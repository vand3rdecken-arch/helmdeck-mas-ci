// Seed policies — your previous rules, NOT deleted, seeded as swappable data.
// Day-one defaults reproduce today's charter exactly; a user (UI) or the
// super-agent can later swap this module for a different PolicySet, and the
// change lands in the kernel journal like any other reconfiguration.

import { KEYS, type PolicySet, type Plugin } from "@/kernel";

/** The charter, as data. Change these only via a tracked swap, never in place. */
export const CHARTER_DEFAULTS: PolicySet = {
  gateBeforeReview: true,
  auditAppendOnly: true,
  worktreeIsolation: true,
  authRequired: true,
  measuredEconomics: true,
  wipLimit: 3,
  // the super-agent may reconfigure, but a module swap is a big move — default
  // to requiring a user confirm; flip via a tracked swap if you want it autonomous.
  agentMaySwap: false,
};

/** Seed plugin: provides KEYS.POLICIES. tier:"seed" = came from the charter. */
export const seedPolicies: Plugin = {
  id: "seed.policies",
  tier: "seed",
  register(scope) {
    scope.provide(KEYS.POLICIES, CHARTER_DEFAULTS);
  },
};
