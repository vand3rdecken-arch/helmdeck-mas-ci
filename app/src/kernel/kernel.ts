// The kernel: a service registry + event bus + reversible-effect loader.
// Framework-agnostic on purpose (no React import) so it is unit-testable under
// plain node and reusable by web, native, and desktop surfaces alike.

import type { Disposer, KernelEvents, Plugin, Scope, ServiceKey, Tier } from "./types";

/** Mint a typed service key. Ids are strings so profiles/manifests can name them. */
export function serviceKey<T>(id: string): ServiceKey<T> {
  return { id };
}

interface ServiceCell {
  ownerId: string;
  value: unknown;
}

interface LoadedPlugin {
  id: string;
  tier: Tier;
  dispose: Disposer;
}

export class Kernel {
  private readonly services = new Map<string, ServiceCell>();
  private readonly listeners = new Map<string, Set<(p: unknown) => void>>();
  private readonly loaded = new Map<string, LoadedPlugin>();

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
    ownerId: string,
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

  // ---- plugin lifecycle -------------------------------------------------

  /**
   * Load a plugin: verify its declared `inject` deps exist, build a scope that
   * records every effect, run `register`, and remember the aggregate disposer.
   * Core plugins are loaded the same way but refused by `unload`.
   */
  load(plugin: Plugin): void {
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
      // partial registration must not leak — unwind whatever landed.
      this.runDisposers(disposers);
      throw err;
    }
    if (typeof extra === "function") disposers.push(extra);

    this.loaded.set(plugin.id, {
      id: plugin.id,
      tier: plugin.tier,
      dispose: () => this.runDisposers(disposers),
    });
  }

  /**
   * Unload a swappable plugin, reversing all its effects. Core plugins are
   * fixed — attempting to unload one is a programming error, not a runtime
   * toggle. This is the enforcement point for the two-tier law.
   */
  unload(pluginId: string): void {
    const lp = this.loaded.get(pluginId);
    if (!lp) return;
    if (lp.tier === "core") {
      throw new Error(`refusing to unload core plugin '${pluginId}': the fixed harness is not swappable`);
    }
    lp.dispose();
    this.loaded.delete(pluginId);
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
