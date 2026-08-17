// Zero-dependency self-test for the kernel. Run under plain node after tsc:
//   npx tsc -p src/kernel/tsconfig.selftest.json && node .kernel-out/__selftest__.js
// Exits non-zero on the first failed assertion. This is the Phase 1 gate.

import { Kernel, serviceKey } from "./kernel";
import { resolveProfile, dumpConfig, selectPlugins } from "./profiles";
import type { Plugin, ProfileDoc } from "./types";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) {
    console.log(`  ok   - ${msg}`);
  } else {
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

// --- service keys ---------------------------------------------------------
const AUDIT = serviceKey<{ log: (s: string) => void }>("core.audit");
const GREETER = serviceKey<() => string>("plugin.greeter");

// --- fixtures -------------------------------------------------------------
const auditLines: string[] = [];
const corePlugin: Plugin = {
  id: "core.audit",
  tier: "core",
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
    const audit = scope.require(AUDIT);
    audit.log("greeter registered");
    scope.provide(GREETER, () => "hello");
    scope.on("surface:changed", () => {
      greeterEvents++;
    });
  },
};

console.log("kernel self-test");

// 1. core loads, service present.
const k = new Kernel();
k.load(corePlugin);
ok(k.get(AUDIT) !== undefined, "core service provided");

// 2. inject gate: plugin needing a missing service is refused.
const k2 = new Kernel();
throws(() => k2.load(greeterPlugin), "plugin refused when injected dep absent");

// 3. plugin loads once deps present; can consume core.
k.load(greeterPlugin);
ok(k.get(GREETER) !== undefined, "plugin service provided");
ok(auditLines.includes("greeter registered"), "plugin consumed core service");

// 4. events reach subscribers.
k.emit("surface:changed", { surfaceId: "greeter", present: true });
ok(greeterEvents === 1, "event delivered to plugin subscriber");

// 5. duplicate service is rejected (single owner).
throws(
  () => k.load({ id: "dupe", tier: "plugin", register: (s) => s.provide(GREETER, () => "x") }),
  "duplicate service provider rejected",
);

// 6. core cannot be unloaded (the fixed-harness law).
throws(() => k.unload("core.audit"), "core plugin refuses unload");

// 7. unloading a swappable plugin reverses ALL its effects.
k.unload("surfaces.greeter");
ok(k.get(GREETER) === undefined, "plugin service removed on unload");
k.emit("surface:changed", { surfaceId: "greeter", present: false });
ok(greeterEvents === 1, "plugin listener removed on unload (no orphan)");

// 8. partial-registration failure leaves no leak.
const k3 = new Kernel();
k3.load(corePlugin);
throws(
  () =>
    k3.load({
      id: "bad",
      tier: "plugin",
      register(s) {
        s.provide(GREETER, () => "y");
        throw new Error("boom");
      },
    }),
  "throwing register propagates",
);
ok(k3.get(GREETER) === undefined, "failed register leaves no orphaned service");

// 9. profile resolution: core forced first, extends + patch merged, dump works.
const docs: Record<string, ProfileDoc> = {
  base: { name: "base", plugins: ["surfaces.board"], patch: { "surfaces.board": { cols: 3 } } },
  store: {
    name: "store",
    extends: ["base"],
    plugins: ["surfaces.greeter"],
    patch: { "surfaces.board": { cols: 4 } },
  },
};
const resolved = resolveProfile("store", docs, ["core.audit"]);
ok(resolved.order[0] === "core.audit", "core plugin forced to front of load order");
ok(resolved.order.includes("surfaces.board") && resolved.order.includes("surfaces.greeter"), "extends merged plugin lists");
ok(resolved.patch["surfaces.board"].cols === 4, "later patch overrides base patch");
throws(() => resolveProfile("nope", docs, []), "unknown profile throws");

// 10. selectPlugins fails loudly on an unbundled plugin id.
throws(
  () => selectPlugins(resolved, { "core.audit": corePlugin }),
  "profile naming an unbundled plugin throws (no silent skip)",
);

console.log(dumpConfig(resolved));
console.log(failures === 0 ? "\nALL PASS" : `\n${failures} FAILURE(S)`);
if (failures > 0) process.exit(1);
