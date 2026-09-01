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
  /** the screen component. Optional for nav-only surfaces whose component is
   *  owned by an expo-router file (the file-based router renders it, not us). */
  readonly component?: ComponentType<Record<string, never>>;
  /** the expo-router <Tabs.Screen> name for nav-only surfaces (= the route file). */
  readonly route?: string;
  /** tab/nav placement + presentation. absent = not in primary nav. */
  readonly nav?: {
    group: "primary" | "more";
    order: number;
    icon?: string;
    /** i18n key for the label (rendered through the translator). */
    labelKey?: string;
    /** i18n key for a sidebar section header shown above this item. */
    sectionKey?: string;
    /** The capability (spine/auth/permissions.py CAPS) the daemon route this
     *  surface renders actually requires - checked via `can(me, cap)`
     *  (src/kernel/caps.ts) against `/me`'s live `caps` list. Replaces the old
     *  teamOnly/ownerOnly booleans (ops/docs/backlog/rbac-gxp card 4): one
     *  field, matched 1:1 to a real server-side gate, instead of a second
     *  hand-maintained role tier that could drift from what the route
     *  actually enforces. `"team.member"` is the interim stand-in for the
     *  old teamOnly (client excluded, no daemon capability backs it yet). */
    cap?: string;
    /** shown only in the desktop sidebar, not the phone bottom bar. */
    desktopOnly?: boolean;
    /** shown only on the phone bottom bar, not the desktop sidebar (e.g. More). */
    phoneOnly?: boolean;
    /** REGISTERED but never drawn - in neither the sidebar nor the bottom bar.
     *
     *  Not the same as omitting the surface, and the difference is
     *  load-bearing: (tabs)/_layout.tsx builds its navigator with
     *  useOnlyUserDefinedScreens=true, so a route that is not rendered as a
     *  <Tabs.Screen> is not in the navigator AT ALL and can no longer be
     *  navigated to. The settings-hub redirects (/automation and /modules ->
     *  /settings?door=...) must stay REACHABLE for deep links and chat
     *  references while being gone from every nav list, which is exactly and
     *  only what this flag expresses. Added in accounts-boards-prd phase 4,
     *  the first time a route needed it. */
    hidden?: boolean;
  };
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

// ---- policies (your old rules, SEEDED as swappable data) -------------------
// The charter used to be hard-wired code. Under the full-dynamism decree it is
// SEEDED defaults instead: booted as a policy module, readable by any module,
// swappable by user/agent — every change tracked. Enforcement modules
// (daemon-side, later) READ these; they no longer own the on/off switch.
export interface PolicySet {
  /** gate-before-review: a card is reviewed only after the suite passes. */
  readonly gateBeforeReview: boolean;
  /** append-only audit/events — the one your tracker mirrors app-side. */
  readonly auditAppendOnly: boolean;
  /** worktree isolation for card work. */
  readonly worktreeIsolation: boolean;
  /** auth required for owner/operator surfaces. */
  readonly authRequired: boolean;
  /** measured economics: budgets in % of weekly quota, not invented €. */
  readonly measuredEconomics: boolean;
  /** WIP limit (running cards). */
  readonly wipLimit: number;
  /** whether the super-agent may swap modules without a user confirm. */
  readonly agentMaySwap: boolean;
  // Per-CELL enable flags (the agentic-system registry, daemon cells.py). Each
  // toggles a whole agentic system on/off through the same tracked policy.swap;
  // the app filters nav surfaces by the matching flag. All default true.
  /** Engineer cell — the cards/kanban system (machine + direct are its modes). */
  readonly engineerEnabled: boolean;
  /** PM cell — the proactive daily-loop / planning role. */
  readonly pmEnabled: boolean;
  /** Process cell — the n8n-style step-chain pipelines. */
  readonly processEnabled: boolean;
  /** Connectors cell — user-built integration modules. */
  readonly connectorsEnabled: boolean;
  /** Copilot cell — the board chat / coordination agent. */
  readonly copilotEnabled: boolean;
  /** Cell #6 — the build loop (cells.py "buildloop"). NOT daemon-hosted
   * like the other 5: governs the CURRENT agent's own workflow via Claude
   * Code's hooks (ops/tools/loop_state.py reads this flag directly, no daemon
   * round-trip needed). Self-governance, not delegation. */
  readonly buildLoopEnabled: boolean;
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
  /** the seeded (swappable, tracked) policy set — your old charter as data. */
  POLICIES: serviceKey<PolicySet>("core.policies"),
  /** the seeded instruction module — CLAUDE.md/charter is a module too. */
  CHARTER: serviceKey<CharterDoc>("core.charter"),
} as const;

// ---- charter / instructions (CLAUDE.md is a module, not an outside law) -----
// Natural-language rules the LLM/agents read. Seeded from today's content,
// swappable by user/agent via a tracked swap, reversible. `source` points at
// the on-disk materialization (CLAUDE.md) that the outer harness also reads.
export interface CharterDoc {
  readonly source: string;
  readonly version: number;
  /** the load-bearing laws, as data — swap the module to change them. */
  readonly laws: readonly string[];
}

/** Factory for the collection services the core tier provides once at boot. */
export function makeRegistries() {
  return {
    engines: new Registry<Engine>("engines"),
    surfaces: new Registry<Surface>("surfaces"),
  };
}
