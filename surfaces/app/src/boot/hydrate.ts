// Hydrate the seeded policy/charter modules from the daemon's canonical source
// (GET /policy). Day-one boot seeds hardcoded defaults synchronously (offline-
// safe); this then replaces them with the daemon values via kernel.swap — so
// hydration itself is a tracked, reversible reconfiguration (actor:"profile"),
// not a silent overwrite. Makes daemon/policy_seed.json the single source.

import { KEYS, type Kernel, type Plugin, type PolicySet, type CharterDoc } from "@/kernel";

interface PolicyResponse {
  policies?: Partial<PolicySet>;
  charter?: Partial<CharterDoc>;
}

/** Fetch /policy and swap the seed modules to the daemon values. No-op on
 *  failure (offline / unauthorized) — the hardcoded seed stays in force. */
export async function hydratePolicies(kernel: Kernel): Promise<boolean> {
  const api = kernel.get(KEYS.API) as { get?: <T>(p: string) => Promise<T> } | undefined;
  if (!api?.get) return false;
  let resp: PolicyResponse;
  try {
    resp = await api.get<PolicyResponse>("/policy");
  } catch {
    return false; // offline / 403 — keep the seeded defaults, untouched.
  }
  if (resp.policies) {
    const pol = resp.policies as PolicySet;
    const next: Plugin = {
      id: "seed.policies",
      tier: "seed",
      register: (s) => s.provide(KEYS.POLICIES, pol),
    };
    kernel.swap("seed.policies", next, "profile", "hydrate from daemon /policy");
  }
  if (resp.charter) {
    const ch = resp.charter as CharterDoc;
    const next: Plugin = {
      id: "seed.charter",
      tier: "seed",
      register: (s) => s.provide(KEYS.CHARTER, ch),
    };
    kernel.swap("seed.charter", next, "profile", "hydrate charter from daemon /policy");
  }
  return true;
}
