// Public surface of the HelmDeck plugin kernel (Phase 1 of the plugin-first
// rewrite). Import from `@/kernel`.
//
// Boot sequence a host (RN entry, web, desktop) follows:
//   1. new Kernel()
//   2. load the CORE tier (fixed harness services) — always, unconditionally.
//   3. resolveProfile(target, docs, coreIds) → selectPlugins(...) → load each.
//   4. render the navigator from the SURFACES registry; pick engine from ENGINES.
// Steps 2 and 3 are the whole "harness is code, policy is data" split.

export { Kernel, serviceKey } from "./kernel";
export type { Clock } from "./kernel";
export { Registry } from "./registry-collection";
export { resolveProfile, dumpConfig, selectPlugins } from "./profiles";
export { KEYS, makeRegistries } from "./keys";
export type { Engine, Surface, Manifest, ApiClient, PolicySet } from "./keys";
export type { ResolvedProfile } from "./profiles";
export type {
  Plugin,
  Scope,
  ServiceKey,
  Disposer,
  Tier,
  Actor,
  TrackEntry,
  KernelEvents,
  ProfileDoc,
} from "./types";
