// Seed tier — the modules booted from the charter defaults. Under the
// full-dynamism decree these are NOT unswappable; tier:"seed" just records that
// they came from the seed set (your old rules), and every later swap of them is
// tracked. They wrap what already exists (api client, theme, policies) so no
// logic is rewritten; the kernel becomes their single owner.

import { api } from "@/data/client";
import { tokens } from "@/theme/tokens";
import { KEYS, makeRegistries, type Manifest } from "@/kernel";
import type { Plugin } from "@/kernel";

import { seedPolicies } from "./policies";
import { seedCharter } from "./charter";

/** Provides the daemon transport client under KEYS.API. */
export const coreApi: Plugin = {
  id: "core.api",
  tier: "seed",
  register(scope) {
    scope.provide(KEYS.API, api as unknown as Record<string, unknown>);
  },
};

/** Provides theme tokens under KEYS.THEME (dark-first, from gen_tokens.py). */
export const coreTheme: Plugin = {
  id: "core.theme",
  tier: "seed",
  register(scope) {
    scope.provide(KEYS.THEME, tokens.dark);
  },
};

/**
 * Provides the ENGINES and SURFACES collection registries that plugins
 * contribute into. Seeded so their lifetime spans the whole app.
 */
export const coreRegistries: Plugin = {
  id: "core.registries",
  tier: "seed",
  register(scope) {
    const { engines, surfaces } = makeRegistries();
    scope.provide(KEYS.ENGINES, engines);
    scope.provide(KEYS.SURFACES, surfaces);
  },
};

/**
 * Provides an initial (empty) manifest under KEYS.MANIFEST. Phase 3 replaces
 * the value from GET /manifest at boot and on the /stream tick — one owner,
 * event-time. Until then everything the profile ships is treated as available.
 */
export const coreManifest: Plugin = {
  id: "core.manifest",
  tier: "seed",
  register(scope) {
    const empty: Manifest = { engines: [], features: [], defaultEngine: null };
    scope.provide(KEYS.MANIFEST, empty);
  },
};

/** Load order matters: registries + policies before anything injects them. */
export const CORE_PLUGINS: Plugin[] = [coreApi, coreTheme, coreManifest, coreRegistries, seedPolicies, seedCharter];
export const CORE_IDS = CORE_PLUGINS.map((p) => p.id);
