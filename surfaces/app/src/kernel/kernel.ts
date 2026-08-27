// The kernel: a service registry + event bus + reversible-effect loader, with a
// universal TRACKER. Framework-agnostic (no React import) so it is unit-testable
// under plain node and reusable by web, native, and desktop surfaces alike.
//
// Decree (owner): full dynamism — every module is swappable, by profile, by the
// user (UI) or by the super-agent. The ONE invariant is trackability: no mutation
// path exists that does not append a TrackEntry. Governance rules are not
// unswappable code any more; they are SEEDED policy modules (defaults = the old
// charter) that can be swapped like anything else — but never silently.

import type { Actor, Disposer, KernelEvents, Plugin, Scope, ServiceKey, Tier, TrackEntry } from "./types";

/** Mint a typed service key. Ids are strings so profiles/manifests can name them. */
export function serviceKey<T>(id: string): ServiceKey<T> {
  return { id };
}

interface ServiceCell {
  ownerId: string;
  value: unknown;
}

interface LoadedPlugin {
  plugin: Plugin;
  tier: Tier;
  dispose: Disposer;
}

/** Optional wall-clock source, injected so the kernel stays deterministic in tests. */
export type Clock = () => number;

export class Kernel {
  private readonly services = new Map<string, ServiceCell>();
  private readonly listeners = new Map<string, Set<(p: unknown) => void>>();
  private readonly loaded = new Map<string, LoadedPlugin>();

  // ---- the tracker: append-only, monotonic, the system's glass box --------
  private readonly track: TrackEntry[] = [];
  private seq = 0;
  private readonly onTrack = new Set<(e: TrackEntry) => void>();

  constructor(private readonly clock: Clock | null = null) {}

  private record(e: Omit<TrackEntry, "seq" | "at">): TrackEntry {
    const entry: TrackEntry = { ...e, seq: ++this.seq, at: this.clock ? this.clock() : null };
    this.track.push(entry);
    for (const fn of [...this.onTrack]) fn(entry);
    return entry;
  }

  /** Immutable view of the reconfiguration journal (append-only; never mutated). */
  journal(): readonly TrackEntry[] {
    return this.track.slice();
  }

  /** Subscribe to every tracked mutation (drives an audit surface / daemon sink). */
  onTracked(fn: (e: TrackEntry) => void): Disposer {
    this.onTrack.add(fn);
    return () => this.onTrack.delete(fn);
  }

  // ---- service registry -------------------------------------------------

  private provide<T>(ownerId: string, key: ServiceKey<T>, value: T): Disposer {
    const existing = this.services.get(key.id);
    if (existing) {
      throw new Error(`service '${key.id}' already provided by '${existing.ownerId}'`);
    }
    this.services.set(key.id, { ownerId, value });
    return () => {
      const cur = this.services.get(key.id);
      if (cur && cur.ownerId === ownerId) this.services.delete(key.id);
    };
  }

  get<T>(key: ServiceKey<T>): T | undefined {
    return this.services.get(key.id)?.value as T | undefined;
  }

  require<T>(key: ServiceKey<T>): T {
    const cell = this.services.get(key.id);
    if (!cell) throw new Error(`required service '${key.id}' is not provided`);
    return cell.value as T;
  }

  hasService(id: string): boolean {
    return this.services.has(id);
  }

  // ---- event bus --------------------------------------------------------

  private on<E extends keyof KernelEvents>(
    _ownerId: string,
    event: E,
    handler: (payload: KernelEvents[E]) => void,
  ): Disposer {
    const set = this.listeners.get(event as string) ?? new Set();
    const wrapped = handler as (p: unknown) => void;
    set.add(wrapped);
    this.listeners.set(event as string, set);
    return () => set.delete(wrapped);
  }

  emit<E extends keyof KernelEvents>(event: E, payload: KernelEvents[E]): void {
    const set = this.listeners.get(event as string);
    if (!set) return;
    for (const fn of [...set]) fn(payload);
  }

  // ---- plugin lifecycle (every path records a TrackEntry) ---------------

  /**
   * Load a plugin: verify `inject` deps, build an effect-recording scope, run
   * `register`, remember the aggregate disposer, and APPEND a track entry.
   * `actor` says who did it (seed/profile/user/agent/system) — recorded, never
   * gated. There is no way to load without a track entry.
   */
  load(plugin: Plugin, actor: Actor = "system", note?: string): void {
    if (this.loaded.has(plugin.id)) {
      throw new Error(`plugin '${plugin.id}' already loaded`);
    }
    for (const dep of plugin.inject ?? []) {
      if (!this.services.has(dep)) {
        throw new Error(`plugin '${plugin.id}' requires service '${dep}', not provided (check profile order)`);
      }
    }

    const disposers: Disposer[] = [];
    const scope: Scope = {
      id: plugin.id,
      tier: plugin.tier,
      provide: (key, value) => {
        disposers.push(this.provide(plugin.id, key, value));
      },
      get: (key) => this.get(key),
      require: (key) => this.require(key),
      on: (event, handler) => {
        disposers.push(this.on(plugin.id, event, handler));
      },
      emit: (event, payload) => this.emit(event, payload),
      use: (dispose) => {
        disposers.push(dispose);
      },
    };

    let extra: void | Disposer;
    try {
      extra = plugin.register(scope);
    } catch (err) {
      this.runDisposers(disposers); // partial registration must not leak.
      throw err;
    }
    if (typeof extra === "function") disposers.push(extra);

    this.loaded.set(plugin.id, {
      plugin,
      tier: plugin.tier,
      dispose: () => this.runDisposers(disposers),
    });
    this.record({ op: "load", pluginId: plugin.id, tier: plugin.tier, actor, note });
  }

  /**
   * Unload ANY module — including seeded governance (full-dynamism decree).
   * Reverses all its effects and APPENDS a track entry. Nothing is refused;
   * the only guarantee is that it is recorded and (via effects) reversible.
   */
  unload(pluginId: string, actor: Actor = "system", note?: string): void {
    const lp = this.loaded.get(pluginId);
    if (!lp) return;
    lp.dispose();
    this.loaded.delete(pluginId);
    this.record({ op: "unload", pluginId, tier: lp.tier, actor, note });
  }

  /**
   * Atomically exchange one module for another (the core reconfiguration verb
   * the user/super-agent use). Records a single op:"swap" entry naming the
   * replaced id. Returns a rollback() that restores the previous module —
   * because every swap must be reversible, especially an agent's.
   */
  swap(oldId: string, next: Plugin, actor: Actor = "system", note?: string): Disposer {
    const prev = this.loaded.get(oldId)?.plugin;
    if (prev) {
      prev; // captured for rollback below
      this.loaded.get(oldId)!.dispose();
      this.loaded.delete(oldId);
    }
    this.load(next, actor, note); // records its own load entry...
    // ...then rewrite the just-recorded load into a swap for a clean journal.
    const last = this.track[this.track.length - 1];
    if (last && last.op === "load" && last.pluginId === next.id) {
      (this.track[this.track.length - 1] as { op: TrackEntry["op"]; replaced?: string }).op = "swap";
      (this.track[this.track.length - 1] as { replaced?: string }).replaced = oldId;
    }
    return () => {
      this.unload(next.id, actor, `rollback of swap ${oldId}->${next.id}`);
      if (prev) this.load(prev, actor, `rollback restore ${oldId}`);
    };
  }

  isLoaded(pluginId: string): boolean {
    return this.loaded.has(pluginId);
  }

  loadedIds(): string[] {
    return [...this.loaded.keys()];
  }

  private runDisposers(disposers: Disposer[]): void {
    // reverse order: last effect registered is first undone.
    for (let i = disposers.length - 1; i >= 0; i--) {
      try {
        disposers[i]();
      } catch {
        // a failing disposer must not block the rest of the unwind.
      }
    }
  }
}
