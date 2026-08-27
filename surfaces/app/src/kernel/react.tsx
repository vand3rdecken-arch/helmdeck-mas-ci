// React bindings for the kernel. Surfaces/engines are framework-agnostic; these
// hooks let RN/web components read the live registries and re-render when
// plugins load/unload (reversible effects reach the UI too).

import React, { createContext, useContext, useEffect, useReducer, useSyncExternalStore } from "react";

import type { Kernel } from "./kernel";
import { KEYS, type Engine, type Surface } from "./keys";
import type { Registry } from "./registry-collection";

const KernelContext = createContext<Kernel | null>(null);

export function KernelProvider({ kernel, children }: { kernel: Kernel; children: React.ReactNode }) {
  return <KernelContext.Provider value={kernel}>{children}</KernelContext.Provider>;
}

export function useKernel(): Kernel {
  const k = useContext(KernelContext);
  if (!k) throw new Error("useKernel: no KernelProvider above this component");
  return k;
}

/** Kernel or null if no provider — for surfaces that must render either way. */
export function useKernelOptional(): Kernel | null {
  return useContext(KernelContext);
}

/** Live view of the reconfiguration journal (re-renders as entries append). */
export function useJournal() {
  const k = useContext(KernelContext);
  const [, force] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (!k) return;
    return k.onTracked(() => force());
  }, [k]);
  return k ? k.journal() : [];
}

/** Subscribe to a Registry so the component re-renders on add/remove. */
function useRegistry<T>(reg: Registry<T> | undefined): Registry<T> | undefined {
  useSyncExternalStore(
    (cb) => (reg ? reg.subscribe(cb) : () => {}),
    () => (reg ? reg.keys().join("|") : ""),
    () => (reg ? reg.keys().join("|") : ""),
  );
  return reg;
}

/** All surfaces contributed by loaded plugins, in nav order. Safe with no
 *  KernelProvider above (returns []), so a consumer can fall back cleanly. */
export function useSurfaces(): Surface[] {
  const k = useContext(KernelContext);
  const reg = useRegistry(k?.get(KEYS.SURFACES));
  if (!k || !reg) return [];
  return reg
    .list()
    .map((e) => e.value)
    .sort((a, b) => (a.nav?.order ?? 999) - (b.nav?.order ?? 999));
}

/** The engine chosen by id (or the first available). */
export function useEngine(id?: string): Engine | undefined {
  const k = useKernel();
  const reg = useRegistry(k.get(KEYS.ENGINES));
  if (!reg) return undefined;
  if (id) return reg.get(id);
  return reg.list().map((e) => e.value).find((e) => e.available());
}
