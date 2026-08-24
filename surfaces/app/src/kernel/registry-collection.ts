// Registry<T> — a *collection* service that many plugins contribute into
// reversibly. DeepSeek's `ctx.tools` / `ctx.agents` are exactly this shape: not
// a single value, but a set of contributions any plugin can add to, each
// removed cleanly when its owner unloads.
//
// Used for engines and surfaces (the registry-driven navigator reads the
// surface Registry instead of a hard-coded route list).

export interface RegistryEntry<T> {
  readonly ownerId: string;
  readonly key: string;
  readonly value: T;
}

export class Registry<T> {
  private readonly entries = new Map<string, RegistryEntry<T>>();
  private readonly onChange = new Set<() => void>();

  constructor(readonly name: string) {}

  /**
   * Contribute `value` under `key`. Returns a disposer that removes exactly
   * this contribution — the caller's Scope holds it, so unload is automatic.
   * Duplicate keys throw: contributions have a single owner.
   */
  add(ownerId: string, key: string, value: T): () => void {
    if (this.entries.has(key)) {
      throw new Error(`Registry(${this.name}): '${key}' already contributed by '${this.entries.get(key)!.ownerId}'`);
    }
    this.entries.set(key, { ownerId, key, value });
    this.notify();
    return () => {
      // idempotent: only remove if it's still *our* entry.
      const cur = this.entries.get(key);
      if (cur && cur.ownerId === ownerId) {
        this.entries.delete(key);
        this.notify();
      }
    };
  }

  get(key: string): T | undefined {
    return this.entries.get(key)?.value;
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  list(): RegistryEntry<T>[] {
    return [...this.entries.values()];
  }

  keys(): string[] {
    return [...this.entries.keys()];
  }

  /** Subscribe to add/remove; returns an unsubscribe. Drives UI re-render. */
  subscribe(fn: () => void): () => void {
    this.onChange.add(fn);
    return () => this.onChange.delete(fn);
  }

  private notify(): void {
    for (const fn of this.onChange) fn();
  }
}
