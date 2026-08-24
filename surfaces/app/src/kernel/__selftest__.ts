// Zero-dependency self-test for the kernel. Run under plain node after tsc:
//   npx tsc -p src/kernel/tsconfig.selftest.json && node .kernel-out/__selftest__.js
// Exits non-zero on the first failed assertion. This is the kernel gate.
//
// Under the full-dynamism decree the floor changed: nothing is refused, but
// nothing mutates untracked, and every swap is reversible.

import { Kernel, serviceKey } from "./kernel";
import { resolveProfile, dumpConfig, selectPlugins } from "./profiles";
import type { Plugin, ProfileDoc } from "./types";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) console.log(`  ok   - ${msg}`);
  else {
    failures++;
    console.log(`  FAIL - ${msg}`);
  }
}
function throws(fn: () => void, msg: string): void {
  let threw = false;
  try {
    fn();
  } catch {
    threw = true;
  }
  ok(threw, msg);
}

const AUDIT = serviceKey<{ log: (s: string) => void }>("core.audit");
const GREETER = serviceKey<() => string>("plugin.greeter");

const auditLines: string[] = [];
const seedPlugin: Plugin = {
  id: "core.audit",
  tier: "seed",
  register(scope) {
    scope.provide(AUDIT, { log: (s) => auditLines.push(s) });
  },
};

let greeterEvents = 0;
const greeterPlugin: Plugin = {
  id: "surfaces.greeter",
  tier: "plugin",
  inject: ["core.audit"],
  register(scope) {
    scope.require(AUDIT).log("greeter registered");
    scope.provide(GREETER, () => "hello");
    scope.on("surface:changed", () => {
      greeterEvents++;
    });
  },
};

console.log("kernel self-test");

// 1. seed loads, service present.
const k = new Kernel();
k.load(seedPlugin, "seed");
ok(k.get(AUDIT) !== undefined, "seed service provided");

// 2. inject gate: plugin needing a missing service is refused.
const k2 = new Kernel();
throws(() => k2.load(greeterPlugin), "plugin refused when injected dep absent");

// 3. plugin loads once deps present; consumes seed.
k.load(greeterPlugin, "profile");
ok(k.get(GREETER) !== undefined, "plugin service provided");
ok(auditLines.includes("greeter registered"), "plugin consumed seed service");

// 4. events reach subscribers.
k.emit("surface:changed", { surfaceId: "greeter", present: true });
ok(greeterEvents === 1, "event delivered to plugin subscriber");

// 5. duplicate service is rejected (single owner).
throws(
  () => k.load({ id: "dupe", tier: "plugin", register: (s) => s.provide(GREETER, () => "x") }),
  "duplicate service provider rejected",
);

// 6. EVERY mutation is tracked (the one invariant). No untracked path.
const j = k.journal();
ok(j.length === 2, "journal has exactly the two loads");
ok(j[0].op === "load" && j[0].pluginId === "core.audit" && j[0].actor === "seed", "seed load tracked with actor=seed");
ok(j[1].actor === "profile", "profile load tracked with actor=profile");
ok(j[0].seq === 1 && j[1].seq === 2, "track seq is monotonic");

// 7. a subscriber sees mutations live (audit sink).
let sunk = 0;
const off = k.onTracked(() => {
  sunk++;
});
k.load({ id: "extra", tier: "plugin", register: () => {} }, "user");
ok(sunk === 1, "onTracked fired for a live load");
ok(k.journal()[2].actor === "user", "user-initiated load attributed to actor=user");
off();

// 8. seed governance IS unloadable now (full dynamism) — and it's tracked.
k.unload("core.audit", "agent", "agent swapped out audit");
ok(k.get(AUDIT) === undefined, "seed module unloaded (nothing is unswappable)");
const uj = k.journal()[k.journal().length - 1];
ok(uj.op === "unload" && uj.actor === "agent" && uj.note === "agent swapped out audit", "unload tracked with agent actor + note");

// 9. unloading reverses effects (no orphan listener).
k.unload("surfaces.greeter", "user");
k.emit("surface:changed", { surfaceId: "greeter", present: false });
ok(greeterEvents === 1, "plugin listener removed on unload (no orphan)");

// 10. swap is atomic, tracked as op:"swap" naming the replaced id, and reversible.
const k3 = new Kernel();
const V1: Plugin = { id: "engine.v1", tier: "seed", register: (s) => s.provide(GREETER, () => "v1") };
const V2: Plugin = { id: "engine.v2", tier: "plugin", register: (s) => s.provide(GREETER, () => "v2") };
k3.load(V1, "seed");
const rollback = k3.swap("engine.v1", V2, "agent", "upgrade to v2");
ok(k3.isLoaded("engine.v2") && !k3.isLoaded("engine.v1"), "swap replaced the module");
const sw = k3.journal()[k3.journal().length - 1];
ok(sw.op === "swap" && sw.replaced === "engine.v1" && sw.actor === "agent", "swap tracked with replaced id + actor");
rollback();
ok(k3.isLoaded("engine.v1") && !k3.isLoaded("engine.v2"), "rollback restored the previous module");

// 11. partial-registration failure leaves no leak — AND still no orphan service.
const k4 = new Kernel();
throws(
  () =>
    k4.load({
      id: "bad",
      tier: "plugin",
      register(s) {
        s.provide(GREETER, () => "y");
        throw new Error("boom");
      },
    }),
  "throwing register propagates",
);
ok(k4.get(GREETER) === undefined, "failed register leaves no orphaned service");

// 12. profile resolution: seed forced first, extends + patch merged, dump works.
const docs: Record<string, ProfileDoc> = {
  base: { name: "base", plugins: ["surfaces.board"], patch: { "surfaces.board": { cols: 3 } } },
  store: { name: "store", extends: ["base"], plugins: ["surfaces.greeter"], patch: { "surfaces.board": { cols: 4 } } },
};
const resolved = resolveProfile("store", docs, ["core.audit"]);
ok(resolved.order[0] === "core.audit", "seed plugin forced to front of load order");
ok(resolved.patch["surfaces.board"].cols === 4, "later patch overrides base patch");
throws(() => resolveProfile("nope", docs, []), "unknown profile throws");
throws(() => selectPlugins(resolved, { "core.audit": seedPlugin }), "unbundled plugin id throws (no silent skip)");

// 13. the charter/instructions module is itself swappable + tracked (the point
//     of "CLAUDE.md is a module"): swap a seed.charter, journal records it,
//     rollback restores the original laws.
const k5 = new Kernel();
const CHARTER = serviceKey<{ laws: string[] }>("core.charter");
const v1charter: Plugin = { id: "seed.charter", tier: "seed", register: (s) => s.provide(CHARTER, { laws: ["a"] }) };
const v2charter: Plugin = { id: "seed.charter.v2", tier: "plugin", register: (s) => s.provide(CHARTER, { laws: ["a", "b"] }) };
k5.load(v1charter, "seed");
const undoCharter = k5.swap("seed.charter", v2charter, "user", "user edited CLAUDE.md");
ok(k5.get(CHARTER)?.laws.length === 2, "charter module swapped (CLAUDE.md is a module)");
ok(k5.journal()[k5.journal().length - 1].note === "user edited CLAUDE.md", "charter swap tracked with reason");
undoCharter();
ok(k5.get(CHARTER)?.laws.length === 1, "charter swap reversible (rollback restored old laws)");

console.log(dumpConfig(resolved));
console.log(failures === 0 ? "\nALL PASS" : `\n${failures} FAILURE(S)`);
if (failures > 0) process.exit(1);
