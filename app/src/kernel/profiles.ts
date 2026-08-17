// Profiles — the pre-config layer (DeepSeek's profile/bundle/patch model).
//
// A profile is an ordered list of plugin ids plus patch overlays. `store`,
// `owner`, `demo`, `headless-companion` are the shipping profiles. EAS build
// profiles bake one in per store target (store.json for App Store / Play).
//
// Composability is only testable if you can see the final composition BEFORE
// running — `dumpConfig` is that (DeepSeek's `dsh --dump-config`). Profiles are
// JSON (not YAML) to stay zero-dependency inside the RN bundle.

import type { Plugin, ProfileDoc } from "./types";

export interface ResolvedProfile {
  readonly name: string;
  /** plugin ids in final load order (core first, then profile order). */
  readonly order: string[];
  /** merged patch overlays (later profiles / this doc win). */
  readonly patch: Record<string, Record<string, unknown>>;
}

/**
 * Resolve a profile against a set of known profile docs, applying `extends`
 * left-to-right (base first). Core plugin ids are forced to the front so the
 * fixed harness is always present and always loads before anything injects it.
 */
export function resolveProfile(
  target: string,
  docs: Record<string, ProfileDoc>,
  corePluginIds: readonly string[],
): ResolvedProfile {
  const doc = docs[target];
  if (!doc) throw new Error(`unknown profile '${target}' (have: ${Object.keys(docs).join(", ")})`);

  const chain: ProfileDoc[] = [];
  const seen = new Set<string>();
  const visit = (d: ProfileDoc) => {
    if (seen.has(d.name)) throw new Error(`profile extends-cycle at '${d.name}'`);
    seen.add(d.name);
    for (const base of d.extends ?? []) {
      const bd = docs[base];
      if (!bd) throw new Error(`profile '${d.name}' extends unknown '${base}'`);
      visit(bd);
    }
    chain.push(d);
  };
  visit(doc);

  // merge plugin lists (dedup, preserve first-seen order) and patches.
  const pluginOrder: string[] = [];
  const patch: Record<string, Record<string, unknown>> = {};
  for (const d of chain) {
    for (const id of d.plugins) if (!pluginOrder.includes(id)) pluginOrder.push(id);
    for (const [id, p] of Object.entries(d.patch ?? {})) {
      patch[id] = { ...(patch[id] ?? {}), ...p };
    }
  }

  // core first (in the given order), then the rest of the profile order.
  const core = [...corePluginIds];
  const rest = pluginOrder.filter((id) => !core.includes(id));
  const order = [...core, ...rest];

  return { name: doc.name, order, patch };
}

/**
 * Human-readable dump of the fully-composed boot config. Print this from a CLI
 * (`npx helm dump-config --profile store`) or a dev screen to prove exactly
 * what a build ships — no surprises hidden behind extends/patch layers.
 */
export function dumpConfig(resolved: ResolvedProfile): string {
  const lines: string[] = [];
  lines.push(`profile: ${resolved.name}`);
  lines.push(`plugins (${resolved.order.length}, load order):`);
  for (const id of resolved.order) {
    const p = resolved.patch[id];
    const suffix = p ? `  patch=${JSON.stringify(p)}` : "";
    lines.push(`  - ${id}${suffix}`);
  }
  return lines.join("\n");
}

/**
 * Load the ordered plugins from a registry of available plugin factories,
 * failing loudly if a profile names a plugin that isn't bundled (a real error,
 * never a silent skip — silent truncation reads as "shipped everything").
 */
export function selectPlugins(
  resolved: ResolvedProfile,
  available: Record<string, Plugin>,
): Plugin[] {
  const out: Plugin[] = [];
  for (const id of resolved.order) {
    const p = available[id];
    if (!p) throw new Error(`profile '${resolved.name}' names plugin '${id}' which is not bundled`);
    out.push(p);
  }
  return out;
}
