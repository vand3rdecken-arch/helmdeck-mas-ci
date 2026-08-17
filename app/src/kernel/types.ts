// HelmDeck plugin kernel — core types.
//
// The rewrite goal (DeepSeek-Harness pattern, expressed in TypeScript so it can
// ship inside a store-built RN app): the app is a *composition of plugins*, not
// a hard-coded tree. Plugins mount into a Context, cooperate through typed
// service keys, and every effect they register is REVERSIBLE — unloading a
// plugin unwinds its services, listeners, routes and surfaces with no orphaned
// state. That reversible-effect rule is also the repo's NO-MONKEY-PATCH law
// (single owner, folded in at event time, unwinds cleanly).
//
// Two tiers, enforced in code (see kernel.ts):
//   - `core`   : the FIXED harness — auth, transport, audit, policy. Always
//                loaded, cannot be disposed. Governance is NEVER a swappable
//                plugin. This is the one line that separates "HelmDeck,
//                modularized" from "HelmDeck, gutted".
//   - `plugin` : the SWAPPABLE layer — engines, surfaces (UI), tools. Loaded
//                from the active profile; disposable.

/** A typed handle to a service in the Context. `T` is the service's shape. */
export interface ServiceKey<T> {
  readonly id: string;
  /** phantom marker so `T` is carried by the type system, never read at runtime. */
  readonly __t?: T;
}

/** Function that reverses a single registered effect. Idempotent. */
export type Disposer = () => void;

export type Tier = "core" | "plugin";

/**
 * The per-plugin view of the kernel handed to `register()`. Every mutating
 * call records a disposer on the plugin's scope, so the kernel can unwind the
 * whole plugin by disposing the scope. Read calls (`get`, `require`) do not.
 */
export interface Scope {
  readonly id: string;
  readonly tier: Tier;

  /** Provide a service under `key`. Fails if already provided (single owner). */
  provide<T>(key: ServiceKey<T>, value: T): void;
  /** Get a service, or `undefined` if absent. */
  get<T>(key: ServiceKey<T>): T | undefined;
  /** Get a service, or throw if absent (declare it via `inject` in the manifest). */
  require<T>(key: ServiceKey<T>): T;

  /** Subscribe to a kernel event; auto-removed on plugin unload. */
  on<E extends keyof KernelEvents>(event: E, handler: (payload: KernelEvents[E]) => void): void;
  /** Emit a kernel event to all current subscribers. */
  emit<E extends keyof KernelEvents>(event: E, payload: KernelEvents[E]): void;

  /** Register an arbitrary cleanup to run on unload (escape hatch). */
  use(dispose: Disposer): void;
}

/**
 * A plugin. `register` runs at load and wires the plugin into the Context via
 * its `Scope`. It must be pure w.r.t. global state — all effects go through the
 * scope so they can be reversed. `inject` names the service keys the plugin
 * depends on; the loader verifies they exist (in load order) before calling
 * `register`, giving deterministic, inspectable composition.
 */
export interface Plugin {
  readonly id: string;
  readonly tier: Tier;
  /** service key ids this plugin requires to already be provided. */
  readonly inject?: readonly string[];
  register(scope: Scope): void | Disposer;
}

/**
 * Kernel-wide event map. Plugins observe/emit these instead of importing each
 * other. Extend via declaration merging in a plugin's own file when it owns a
 * new event family; keep governance-relevant events (audit, policy) core-owned.
 */
export interface KernelEvents {
  /** the active engine for a card changed (single owner: the engine registry). */
  "engine:selected": { cardId: string; engineId: string };
  /** a surface was mounted/unmounted (drives the registry-backed navigator). */
  "surface:changed": { surfaceId: string; present: boolean };
  /** the daemon manifest was (re)loaded — runtime enable/disable within profile. */
  "manifest:loaded": { engines: string[]; features: string[] };
}

/** A profile = ordered plugin ids + patch overlays. See profiles.ts. */
export interface ProfileDoc {
  readonly name: string;
  /** ordered list of plugin ids to load (core plugins load first regardless). */
  readonly plugins: readonly string[];
  /** shallow config patches applied over plugin defaults, keyed by plugin id. */
  readonly patch?: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
  /** profiles this one extends (resolved left-to-right, this doc last). */
  readonly extends?: readonly string[];
}
