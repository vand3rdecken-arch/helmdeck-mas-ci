// Core tier — the FIXED harness services, provided once at boot and never
// unloaded. These wrap what already exists (the daemon api client, the theme
// tokens) so no logic is rewritten; the kernel just becomes their single owner.

import { api } from "@/data/client";
import { tokens } from "@/theme/tokens";
import { KEYS, makeRegistries, type Manifest } from "@/kernel";
import type { Plugin } from "@/kernel";

/** Provides the daemon transport client under KEYS.API. */
export const coreApi: Plugin = {
  id: "core.api",
  tier: "core",
  register(scope) {
    scope.provide(KEYS.API, api as unknown as Record<string, unknown>);
  },
};

/** Provides theme tokens under KEYS.THEME (dark-first, from gen_tokens.py). */
export const coreTheme: Plugin = {
  id: "core.theme",
  tier: "core",
  register(scope) {
    scope.provide(KEYS.THEME, tokens.dark);
  },
};

/**
 * Provides the ENGINES and SURFACES collection registries that plugins
 * contribute into. Core-owned so their lifetime spans the whole app.
 */
export const coreRegistries: Plugin = {
  id: "core.registries",
  tier: "core",
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
  tier: "core",
  register(scope) {
    const empty: Manifest = { engines: [], features: [], defaultEngine: null };
    scope.provide(KEYS.MANIFEST, empty);
  },
};

/** Load order matters: registries before any surface/engine plugin injects them. */
export const CORE_PLUGINS: Plugin[] = [coreApi, coreTheme, coreManifest, coreRegistries];
export const CORE_IDS = CORE_PLUGINS.map((p) => p.id);
