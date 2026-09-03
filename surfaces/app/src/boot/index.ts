// Boot assembler — turns a profile name into a live Kernel.
//
//   1. new Kernel()
//   2. load CORE_PLUGINS (fixed harness, unconditional)
//   3. resolveProfile → selectPlugins → load each swappable plugin in order
//
// This is the "harness is code, policy is data" split made executable: steps 1-2
// are fixed; step 3 is entirely profile-driven. `dump(profile)` prints the
// resolved composition without booting (DeepSeek's --dump-config).

import { Kernel, resolveProfile, selectPlugins, dumpConfig } from "@/kernel";
import type { Plugin, ProfileDoc } from "@/kernel";

import { CORE_PLUGINS, CORE_IDS } from "./core";
// processes/connectors surfaces live under the ENGINEER cell since the
// merge (owner directive 2026-09-03: the builder owns his whole build
// process) - real tabs, unchanged screens, one cell attribution.
import { boardSurface } from "@cells/engineer/ui/surface";
import { connectorsSurface } from "@cells/engineer/ui/connectors";
import { processesSurface } from "@cells/engineer/ui/processes";
import { copilotSurface } from "@cells/copilot/ui/surface";
import { tabsNav } from "@/plugins/surfaces/tabs";
import { claudeEngine } from "@/plugins/engines/claude";
import { copilotEngine } from "@/plugins/engines/copilot";
import { deepseekEngine } from "@/plugins/engines/deepseek";

import phase2 from "../../profiles/phase2.json";
import appProfile from "../../profiles/app.json";
import store from "../../profiles/store.json";
import owner from "../../profiles/owner.json";
import demo from "../../profiles/demo.json";
import headless from "../../profiles/headless-companion.json";

/** All profile docs shipped in the bundle, by name. */
export const PROFILE_DOCS: Record<string, ProfileDoc> = {
  phase2: phase2 as ProfileDoc,
  app: appProfile as ProfileDoc,
  store: store as ProfileDoc,
  owner: owner as ProfileDoc,
  demo: demo as ProfileDoc,
  "headless-companion": headless as ProfileDoc,
};

/**
 * Every swappable plugin bundled in this build, by id. A profile naming an id
 * absent here fails loudly at boot (no silent skip) — see selectPlugins.
 * Grows one entry per migrated surface/engine; the rest of the app is untouched.
 *
 * NO "surfaces.pm" (owner directive 2026-09-03, "pm und henry is eins"): the
 * pm cell merged into copilot, and its screens (PMStatusPanel, the loop map)
 * were never wired into nav.tabs anyway - "surfaces.chat" is Henry's one
 * kernel surface now, same as the daemon's one merged Cell.
 */
export const AVAILABLE_PLUGINS: Record<string, Plugin> = {
  "surfaces.board": boardSurface,
  "surfaces.connectors": connectorsSurface,
  "surfaces.processes": processesSurface,
  "surfaces.chat": copilotSurface,
  "nav.tabs": tabsNav,
  "engines.claude": claudeEngine,
  "engines.copilot": copilotEngine,
  "engines.deepseek": deepseekEngine,
};

/** Assemble and return a booted Kernel for `profileName`. */
export function boot(profileName: string): Kernel {
  const k = new Kernel();
  for (const p of CORE_PLUGINS) k.load(p, "seed");

  const resolved = resolveProfile(profileName, PROFILE_DOCS, CORE_IDS);
  // core ids are forced into resolved.order; they're already loaded, so skip them.
  const swappable = { ...AVAILABLE_PLUGINS };
  const plugins = selectPlugins(
    { ...resolved, order: resolved.order.filter((id) => !CORE_IDS.includes(id)) },
    swappable,
  );
  for (const p of plugins) k.load(p, "profile");
  return k;
}

/** Resolved-composition string for a profile, without booting. */
export function dump(profileName: string): string {
  return dumpConfig(resolveProfile(profileName, PROFILE_DOCS, CORE_IDS));
}
