# Repo topology: two mains at the ROOT - spine/ and cells/

**Owner decree 2026-08-24.** The architecture is spine + cells, but the folder
tree doesn't say so at the root: ~19 top-level dirs mixing products, ops and
artifacts. Target: the first thing anyone sees is the architecture itself -
`spine/` (everything no cell owns: boot, auth, http, storage, harness) and
`cells/` (one folder per agentic system - engineer, pm, process, connectors,
copilot/henry - each bundling its backend AND its frontend unit).

## What already exists (do not redo)

- The split IS physical since 2026-08-19, one level down: `daemon/spine/`
  (auth, http, storage, registry, turn, ...) and `daemon/cells/<id>/`
  (ARCHITECTURE.md "Physical Cell folders"). Imports survive via the
  flat-module sys.path mechanism (`ensure_cell_paths()`), which makes a
  physical promotion to root CHEAPER than it looks - modules find each other
  by name, not by `daemon.` prefix.
- Frontend modularity per cell exists LOGICALLY: plugin kernel
  (`app/src/kernel/` + `app/src/plugins/<cell>`), and the cell manifest
  already declares each cell's files across daemon and app
  (`GET /cells/<id>/source` allowlist).

## Phases

1. **Kill the husks (no restructure needed).** `web/` is a corpse - the real
   frontend was archived in 6625edc, only two stale build artifacts remain
   tracked - yet CLAUDE.md still tells every agent `cd web && npm run dev`.
   Delete the two files + dir, fix the CLAUDE.md run block and the e2e-smoke
   line. VERIFY THE PREMISE first (nightshift rule): grep tools/loop_state.py
   for how the TYPES state locates the web tsc - it must point at app/, not
   web/, before web/ dies.
2. **Promote the two mains.** `daemon/spine/` -> `spine/`, `daemon/cells/` ->
   `cells/`, daemon boot (`swarm.py` et al.) into `spine/`. Keep the
   flat-module import mechanism. Known path-coupled touchpoints (grepped
   2026-08-24, the actual list - re-grep before trusting):
   deploy/publish_source.sh, tools/{i18n_lint,loop_state,make_tls_cert,
   memory_autocommit,reset,run_gate,run_suite}.py, desktop/tray.py, the
   `py -3.12 -m daemon.swarm` entrypoint, .gitignore `daemon/*` lines,
   CLAUDE.md / HARNESS.md / ARCHITECTURE.md path references, and the
   worktree/card harness (P4 path-shape ownership - re-verify spawn on a
   moved tree).
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
  stubs), that is a SHORTCUT -> register it in daemon/debt.py (or its moved
  successor) in the same commit.

## Verify

- `py -3.12 -m py_compile` equivalent green on the new layout; daemon serves
  on :8140; a card spawn + gate + accept round-trips on a worktree.
- OTA push lands on the phone; publish_source.sh dry-run still lists the
  private paths it filters.
- Repo root after: spine/, cells/, app/ (until phase 3 absorbs its plugins),
  plus ops (deploy/, tools/, tests/, harness/) and data (backlog/, docs/,
  shots/, archive/) - and NOTHING else.
