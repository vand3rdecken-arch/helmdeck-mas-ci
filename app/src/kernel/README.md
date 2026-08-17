# HelmDeck plugin kernel (Phase 1)

Plugin-first rewrite of the app (DeepSeek-Harness pattern, in TypeScript so it
ships inside store-built RN). The app becomes a *composition of plugins*; the
Python daemon stays the fixed harness the app talks to (a store app can't embed
Python — that boundary is permanent).

## Two tiers (the one non-negotiable line)

- **core** — fixed harness services (auth, transport, audit, policy). Always
  loaded, `unload()` refuses them. Governance is NEVER a swappable plugin.
- **plugin** — swappable: engines, surfaces (UI), tools. Loaded from the active
  profile; disposable with fully reversible effects.

## Files

- `types.ts` — Plugin / Scope / ServiceKey / ProfileDoc contracts.
- `kernel.ts` — `Kernel`: service registry + event bus + reversible loader.
- `registry-collection.ts` — `Registry<T>`, the many-contributors service shape
  (engines, surfaces) — DeepSeek's `ctx.tools` equivalent.
- `keys.ts` — well-known service keys + `Engine` / `Surface` / `Manifest`.
- `profiles.ts` — profile resolve + patch overlay + `dumpConfig` (`--dump-config`).
- `../../profiles/*.json` — `store`, `owner`, `demo`, `headless-companion`.

## Gate

```
npx tsc -p src/kernel/tsconfig.selftest.json && node .kernel-out/__selftest__.js
```

16 assertions, incl. the charter enforcers: core refuses unload; a plugin's
listeners/services vanish on unload (no orphan); failed register leaves no leak.

## Boot sequence (host wires this in Phase 2)

1. `const k = new Kernel()`
2. load the **core** tier (provide `KEYS.API`, `KEYS.THEME`, registries).
3. `resolveProfile(target, docs, coreIds)` → `selectPlugins` → `k.load` each.
4. render navigator from the `SURFACES` registry; pick engine from `ENGINES`.

## Phase 2 (next worker card)

Strangler-wrap existing screens as `surfaces/*` plugins (no logic rewritten,
only re-seated), make the root navigator read the `SURFACES` registry instead of
the hard-coded `(tabs)` list, and wrap `claude_sessions`/`copilot` API calls as
`engines/*`. That commit introduces the old+new dual path → register it in
`daemon/debt.py` in the same commit (charter law).
