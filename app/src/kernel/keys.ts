// Well-known service keys — the stable "context keys" plugins wire through
// (DeepSeek's ctx.tools / ctx.llm / ctx.sessions equivalent). Contributing
// plugins provide these; consuming plugins `inject` them by id.
//
// Collection-shaped services (ENGINES, SURFACES) hold a Registry so many
// plugins contribute; single-value services (API, THEME, MANIFEST) have one
// owner in the core tier.

import type { ComponentType } from "react";
import { serviceKey } from "./kernel";
import { Registry } from "./registry-collection";

// ---- engine contract (an agent backend: Claude / Copilot / DeepSeek) -------
// Thin client of the daemon's per-engine API. The app never runs the agent;
// the fixed daemon does. This interface is what the ~11 scattered
// `import copilot` / `import claude_sessions` branches collapse into.
export interface Engine {
  readonly id: string;
  readonly label: string;
  /** whether this engine is currently usable (manifest-gated at runtime). */
  available(): boolean;
  spawn(cardId: string, brief: unknown): Promise<{ sessionId: string }>;
  send(sessionId: string, message: string): Promise<void>;
  history(user: string): Promise<unknown[]>;
}

// ---- surface contract (a UI area: board / chat / machine / pm / glasses) ---
// A surface contributes screens to the registry-driven navigator. Surfaces are
// swappable plugins; a `headless-companion` profile simply loads none.
export interface Surface {
  readonly id: string;
  readonly title: string;
  /** route path used by expo-router / web navigator. */
  readonly path: string;
  readonly component: ComponentType<Record<string, never>>;
  /** tab/nav placement hint; absent = not in primary nav. */
  readonly nav?: { group: "primary" | "more"; order: number; icon?: string };
  /** service key ids required for this surface to be shown at all. */
  readonly requires?: readonly string[];
}

// ---- daemon manifest (runtime enable/disable *within* the profile) ---------
// Profile decides what SHIPS; manifest decides what SHOWS. Served by the
// daemon at boot (Phase 3), one owner, event-time updates over /stream.
export interface Manifest {
  readonly engines: readonly string[];
  readonly features: readonly string[];
  readonly defaultEngine: string | null;
}

// Minimal shape of the existing src/data/client.ts `api` object, so core can
// publish it without the kernel importing React-Native transport code.
export interface ApiClient {
  [method: string]: unknown;
}

export const KEYS = {
  /** daemon transport client (core-owned). */
  API: serviceKey<ApiClient>("core.api"),
  /** theme tokens accessor (core-owned; from gen_tokens.py palette). */
  THEME: serviceKey<unknown>("core.theme"),
  /** current daemon manifest (core-owned, replaced on reload). */
  MANIFEST: serviceKey<Manifest>("core.manifest"),
  /** engine registry — engines/* plugins contribute. */
  ENGINES: serviceKey<Registry<Engine>>("core.engines"),
  /** surface registry — surfaces/* plugins contribute; navigator reads it. */
  SURFACES: serviceKey<Registry<Surface>>("core.surfaces"),
} as const;

/** Factory for the collection services the core tier provides once at boot. */
export function makeRegistries() {
  return {
    engines: new Registry<Engine>("engines"),
    surfaces: new Registry<Surface>("surfaces"),
  };
}
