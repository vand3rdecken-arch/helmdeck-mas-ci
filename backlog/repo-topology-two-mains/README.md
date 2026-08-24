# Repo topology: two mains at the ROOT - spine/ and cells/

> **PHASES 1+2 SHIPPED 2026-08-24 (owner: "fixe direkt hier")**: `daemon/spine`
> -> `spine/`, `daemon/cells` -> `cells/` via git mv + mechanical rewrite of
> every qualified import/path reference (202 files). `daemon/` DELIBERATELY
> remains as thin launcher (`python -m daemon.swarm`) + paths.py (decreed
> never-moves anchor, DAEMON_ROOT = runtime-data home) + colocated tests - so
> the desktop tray spawn, the live sqlite WAL and every data path survived
> unchanged. run_gate.py compiles all three trees + wires spine.http.server
> (daemon.swarm alone is thin now); electron-builder.yml ships spine/ + cells/
> with the same allowlist discipline. web/ husk deleted, CLAUDE.md rewritten.
> STRAYS DONE 2026-08-24 (e577a85): gxp.py + mint_token.py -> spine/auth/
> (gxp is GOVERNANCE over all cells, not a cell - the zero-cells litmus),
> daemon/test_*.py -> tests/ (one suite home, run_suite scans tests/ only).
> daemon/connectors/ deliberately STAYS: it is the connectors cell's runtime
> INSTALL target (connectors.py CDIR), data-home state like pm.role.md and
> policy_seed.json. Daemon restarted onto the new layout, :8140 HTTP 200.
> PHASE 3 SHIPPED 2026-08-24 (c2545c1, owner "direkt hier"): the five cell
> Surface plugins live at cells/<id>/ui/surface.tsx, wired into the ONE Expo
> app via metro.config.js (watchFolders + @cells + nodeModulesPaths) and
> tsconfig @cells paths. TRAP (measured): Metro reads tsconfig.json `paths`
> at runtime - the bare-module tsc fallback the out-of-tree files need lives
> QUARANTINED in tsconfig.typecheck.json (loop_state + CLAUDE.md typecheck
> with -p). kernel-demo deleted; cell manifest surface entries moved
> ui_files -> repo_files. Verified: tsc 0, expo export web 0, gate PASS.
> The dual-nav debt itself stays OPEN for its last item: per-screen
> COMPONENTS (route files still render their own imports, not the registry).
> ROOT-MINIMIZATION 2026-08-24 (owner frame: "daemon+app are the execution
> parts, everything else justifies itself"): shots/ -> docs/shots/ (closes a
> privacy inconsistency - tracked board PNGs were NOT mirror-filtered while
> docs/store/screenshots deliberately are; writer paths in asc_guide/
> meta_wearables_guide/ios_credentials updated), .smoke/ -> tests/smoke/
> (a test harness, not a root citizen; its EVIDENCE.md shot refs are
> dir-relative and survived), acceptance.md -> docs/ (historical Define-round
> doc, gxp-conformity already flagged it as outdated). worker/ was a doc,
> not a surface (docs/relay-durable-object-sketch.md).
> OPEN: phase 4 (optional surface grooming); consolidate the doubled data
> homes (.attachments/ + backups/ at root vs their daemon/ twins - the
> root .attachments/ has 5 tracked legacy jpgs and publish-filter paths
> attached, needs its own careful cut).

**Owner decree 2026-08-24.** The architecture is spine + cells, but the folder
tree doesn't say so at the root: ~19 top-level dirs mixing products, ops and
artifacts. Target: the first thing anyone sees is the architecture itself -
`spine/` (everything no cell owns: boot, auth, http, storage, harness) and
`cells/` (one folder per agentic system - engineer, pm, process, connectors,
copilot/henry - each bundling its backend AND its frontend unit).

## Phases

1. **DONE 2026-08-24. Kill the husks.** `web/` was a corpse - the real
   frontend was archived in 6625edc, two stale build artifacts remained
   tracked while CLAUDE.md still told every agent `cd web && npm run dev`.
   Premise verified first (nightshift rule): loop_state.py already pointed
   TYPES at app/.
2. **DONE 2026-08-24. Promote the two mains.** Executed as described in the
   banner above. Departure from the original sketch: daemon boot did NOT move
   into spine/ - `daemon/` stays as launcher + data home ON PURPOSE (tray
   compat, no live-DB migration, paths.py decree). Code does not go there.
3. **Frontend into the cell folders.** `app/src/plugins/<cell>` ->
   `cells/<id>/ui/`, wired back into the ONE Expo app via metro
   `watchFolders` + tsconfig paths (the app stays a single buildable
   project - Metro/OTA demand it; a cell ships a frontend UNIT, not its own
   app). BLOCKED BY the `plugin-kernel-dual-nav` debt: cut production nav
   over to the kernel first, so exactly one consumer reads the plugins.
4. **Optional root grooming.** Surfaces (glasses/, desktop/, relay/, worker/)
   could group under one dir - LOW value, each has deploy scripts bound to
   its path. Decide only after 1-3 are green.

## Ontology (aligned with owner 2026-08-24 - the worker inherits this)

Two axes, never conflated: CELLS are vertical function slices (henry, pm,
engineer, ...); SURFACES are horizontal delivery vehicles (android app,
desktop, glasses, relay, site). Every surface build ships ALL enabled cells -
cell on/off is POLICY DATA (`<cell>Enabled`), never a build variant, so there
is no per-cell build and never will be (it would be an NxM matrix and break
one-bundle-per-runtimeVersion OTA). Consequences:
- Builds stay with surfaces: `deploy/` one entrypoint per surface + CI.
  Phase 2/3 must NOT pull build machinery into cell folders.
- The spine's job IS "merge and change cells": daemon-side the cell registry
  (`cells.py`), app-side the plugin kernel. Same mechanism-vs-policy line.
- Litmus test for file placement: would it exist with ZERO cells installed?
  Yes -> spine or surface. No -> the cell.
- A cell MAY carry per-surface UI variants as subunits (`cells/<id>/ui/...`),
  but the shell and the build never move in.

## Traps

- `docs` in .gitignore and the tracked `.attachments/` jpgs are OWNER
  DECISIONS (publish_source.sh documents both) - a restructure worker must
  not "fix" them.
- publish_source.sh's private-path grep matches on path prefixes - moved
  paths must be re-added or the filter silently stops filtering.
- OTA/deploy: any file app.json or ship.sh fingerprints moving = native_fp
  churn; do phase 3 in a quiet window and emulator-verify.
- If any phase keeps a compatibility shim (sys.path aliasing, re-export
  stubs), that is a SHORTCUT -> register it in spine/registry/debt.py in the
  same commit. (Phases 1+2 shipped with NO shim - imports were rewritten for
  real, and the daemon/ launcher is a real package, not an alias.)

## Verify

- `py -3.12 -m py_compile` equivalent green on the new layout; daemon serves
  on :8140; a card spawn + gate + accept round-trips on a worktree.
- OTA push lands on the phone; publish_source.sh dry-run still lists the
  private paths it filters.
- Repo root after: spine/, cells/, app/ (until phase 3 absorbs its plugins),
  plus ops (deploy/, tools/, tests/, harness/) and data (backlog/, docs/,
  shots/, archive/) - and NOTHING else.
