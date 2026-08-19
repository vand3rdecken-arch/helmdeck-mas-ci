# -*- coding: utf-8 -*-
"""Cells - the agentic-system registry (the daemon half of the plugin decree).

A CELL is a self-contained agentic system (a role like PM or Engineer): its own
orchestration logic, storage, harness/role, API connector routes, UI surface,
lifecycle, and an enable flag. A cell plugs INTO the shared spine (auth,
append-only audit/events, economics, the agent-run primitive, worktree
isolation, policy/tracking, db, the app shell) - the spine is infrastructure
every cell uses and no cell owns, so it is NOT itself a cell.

This module is the single source of truth for "which agentic systems exist and
whether each is on". It is deliberately PURE DATA + light helpers - it imports
nothing heavy at module load (no pm/processes/sessions), so it cannot create an
import cycle. Route ownership is expressed as PATH PATTERNS, not route-module
references, because some route modules are shared (routes_misc holds both the
Process cell's /processes AND the spine's /me) - a cell owns specific paths, not
a whole file.

Enable-state is DERIVED from policy.get_policies() at request/boot/event time
(the NO-MONKEY-PATCH law: one owner, read live, never a stored reconstructed
flag), and toggled ONLY through the existing tracked policy.swap() path
(mirrored into the append-only events sink). All flags default true, so a fresh
seed is behaviourally identical to the pre-cell daemon.

Machine-control and direct-task are NOT peer cells: they are MODES of the
Engineer cell (a card variant with machine=True, forking dispatch/accept/agent-
selection only), gated by the existing policy.machine. See daemon/debt.py.

`logic_files`/`storage`/`harness_file`/`route_modules` are the cell's DECLARED
metadata for the UI code-map (GET /cells, GET /cells/<id>/source) - this same
metadata is BOTH what the app displays AND the allowlist read_source() checks
against, so nothing is readable that isn't already named as belonging to that
cell (no separate list that could drift or be more permissive than the manifest
itself claims)."""

import os

from daemon.paths import DAEMON_ROOT as ROOT, REPO_ROOT
APP_ROOT = os.path.join(REPO_ROOT, "app")                    # app/ (sibling)
MAX_SOURCE_BYTES = 200_000


def _import_by_bare_name(mod_name, owner_cell_id=None):
    """Cell.start/route_modules store BARE names (e.g. 'routes_pm') because
    they double as the security allowlist (Cell.allowed_files() - see
    read_source()'s docstring: the manifest IS the allowlist). daemon/ is a
    real Python package now, so actually IMPORTING one of these needs its
    real dotted path - tried here in owner-cell-first order, then
    daemon.spine.http.routes (the multi-owner/spine route modules),
    rather than storing the dotted path a second place that could drift
    from the physical file."""
    import importlib
    candidates = []
    if owner_cell_id:
        candidates.append(f"daemon.cells.{owner_cell_id}.{mod_name}")
    candidates.append(f"daemon.spine.http.routes.{mod_name}")
    last_err = None
    for cand in candidates:
        try:
            return importlib.import_module(cand)
        except ImportError as e:
            last_err = e
            continue
    raise last_err or ImportError(mod_name)


class Cell:
    """A registered agentic system. Pure descriptor - behaviour lives in the
    cell's own modules; this just names the seams (routes, lifecycle, flag)."""

    def __init__(self, id, enabled_key, paths=(), prefixes=(), start=None,
                 role="", surface="", modes=(),
                 logic_files=(), storage="", harness_file="",
                 route_modules=(), ui_files=(), tools=(), repo_files=()):
        self.id = id
        self.enabled_key = enabled_key      # policy flag, e.g. "pmEnabled"
        self.paths = tuple(paths)           # exact owned paths, e.g. ("/processes",)
        self.prefixes = tuple(prefixes)     # owned path prefixes, e.g. ("/pm/",)
        self.start = start                  # ("module","func") lazy lifecycle launcher, or None
        self.role = role                    # harness brief filename OR a short description
        self.surface = surface              # app-side kernel Surface id this cell renders
        self.modes = tuple(modes)           # sub-modes, e.g. engineer -> ("machine","direct")
        self.logic_files = tuple(logic_files)    # daemon/*.py files, e.g. ("pm.py","pm_state.py")
        self.storage = storage                   # short description, e.g. "loop.json (daemon/pm/)"
        self.harness_file = harness_file         # REPO-ROOT-relative *.md path, or "" if inline/none
        self.route_modules = tuple(route_modules)  # daemon module names, e.g. ("routes_pm",)
        self.ui_files = tuple(ui_files)          # app/-relative paths: surface plugin + real screens
        self.tools = tuple(tools)                # external tools/refs this cell's own tooling uses -
                                                  # documentation only, never readable via read_source
        self.repo_files = tuple(repo_files)      # REPO-ROOT-relative logic (not under daemon/ or
                                                  # app/) - e.g. tools/loop_state.py for the buildloop
                                                  # cell, which isn't daemon-hosted like the other 5

    def owns(self, path):
        """Does this cell own the given request path?"""
        if path in self.paths:
            return True
        return any(path.startswith(pre) for pre in self.prefixes)

    def allowed_files(self):
        """Every filename this cell will serve via read_source() - the
        allowlist. Built from this cell's OWN declared metadata only."""
        out = set(f + ".py" if not f.endswith(".py") else f for f in self.logic_files)
        if self.harness_file:
            out.add(self.harness_file)
        for mod in self.route_modules:
            out.add(mod + ".py")
        for f in self.ui_files:
            out.add(f)
        for f in self.repo_files:
            out.add(f)
        return out

    def where(self, fname):
        """Which root `fname` resolves under: 'app', 'repo', or 'daemon'."""
        if fname in self.repo_files:
            return "repo"
        if fname in self.ui_files:
            return "app"
        if fname == self.harness_file:
            return "repo"
        return "daemon"

    def daemon_roots(self):
        """Candidate physical directories for this cell's OWN daemon-local
        files, in search order: this cell's own folder first
        (daemon/cells/<id>/), then daemon/spine/http/routes/ (route_modules
        can legitimately name a SHARED route module - e.g. process cell's
        routes_misc.py/routes_system.py, both multi-owner), then flat
        daemon/ as a last-resort fallback for anything not yet swept into
        one of the above."""
        return (os.path.join(ROOT, "cells", self.id),
                os.path.join(ROOT, "spine", "http", "routes"),
                ROOT)


# The registered cells. Order is presentation-only. enabled_key defaults true in
# policy_seed.json, so all of this is a no-op until an owner flips a flag.
CELLS = [
    Cell(
        id="engineer", enabled_key="engineerEnabled",
        # the card/kanban spine-core, conformed last (Phase 3, the crown
        # jewel). Lifecycle: sessions.start_engineer_lifecycle() launches the
        # zombie reconciler + background-task watcher, both of which operate
        # directly on track/session state - genuinely this cell's own
        # lifecycle, not spine-adjacent housekeeping - so disabling
        # engineerEnabled also stops them, same as every other cell's poller.
        # machine/direct are MODES here, gated by the separate policy.machine,
        # not a cell.
        paths=("/tracks",), prefixes=("/tracks/",),
        start=("sessions", "start_engineer_lifecycle"),
        role="(card brief, per-task)", surface="surfaces.board",
        modes=("machine", "direct"),
        logic_files=("sessions.py", "lanemachine.py", "dispatch.py",
                     "cardadmin.py", "turnrunner.py"),
        storage="tracks table + worktrees (db.py)",
        route_modules=("routes_tracks", "routes_track_actions"),
        ui_files=("src/plugins/surfaces/board.tsx", "src/ui/board.tsx",
                   "src/app/(tabs)/board.tsx"),
        # documentation-only reference (owner directive, 2026-08-18): the
        # editorial-diagram visual language this cell's own code-map UI
        # (this file's read_source() + app/src/ui/cell_diagram.tsx) follows.
        # Not vendored, not a runtime dependency - registered here so the
        # code-map itself shows what informed its own rendering style.
        tools=("github.com/cathrynlavery/diagram-design (visual style ref "
               "for the code-map diagram, not a vendored dependency)",),
    ),
    Cell(
        id="pm", enabled_key="pmEnabled",
        prefixes=("/pm/",),
        start=("pm", "start_loop"),
        role="pm.role.md", surface="surfaces.pm",
        logic_files=("pm.py", "pm_state.py", "pm_budget.py"),
        storage="loop.json (daemon/pm/)",
        harness_file="daemon/pm.role.md",
        route_modules=("routes_pm",),
        ui_files=("src/plugins/surfaces/pm.tsx", "src/ui/pm_panel.tsx",
                   "src/app/loopmap.tsx"),
    ),
    Cell(
        id="process", enabled_key="processEnabled",
        # /processes and /processes/<id>/step live in routes_misc + routes_system,
        # both SHARED modules - path ownership keeps /me (spine) ungated.
        paths=("/processes",), prefixes=("/processes/",),
        start=("processes", "start_chain_poller"),
        role="(inline proposer prompt in processes.py)", surface="surfaces.processes",
        logic_files=("processes.py",),
        storage="processes table (db.py)",
        route_modules=("routes_misc", "routes_system"),
        ui_files=("src/plugins/surfaces/processes.tsx",
                   "src/app/(tabs)/processes.tsx"),
    ),
    Cell(
        id="connectors", enabled_key="connectorsEnabled",
        paths=("/connectors",), prefixes=("/connectors/",),
        start=("connectors", "start_scheduler"),
        role="(card-worker builds it)", surface="surfaces.connectors",
        logic_files=("connectors.py",),
        storage="connector_state table (db.py) + connectors/ code dir",
        route_modules=("routes_connectors",),
        ui_files=("src/plugins/surfaces/connectors.tsx",
                   "src/app/(tabs)/connectors.tsx"),
    ),
    Cell(
        id="copilot", enabled_key="copilotEnabled",
        prefixes=("/chat",),
        role="board-copilot.md", surface="surfaces.chat",
        logic_files=("copilot.py", "copilot_stats.py", "copilot_actions.py"),
        storage="copilot_sessions.json, copilot_log.json",
        harness_file="harness/agents/board-copilot.md",   # repo-root-relative (not under daemon/)
        route_modules=("routes_copilot",),
        ui_files=("src/plugins/surfaces/copilot.tsx", "src/app/chat.tsx"),
    ),
    Cell(
        # Cell #6 - added 2026-08-18 after owner pushback: structurally this
        # has the same shape as every other cell (its own harness/laws,
        # states/gates, UI presence), so it belongs in the registry. It is
        # NOT daemon-hosted like the other 5 though - it governs the CURRENT
        # interactive agent's own workflow via Claude Code's hooks
        # (.claude/settings.json -> tools/loop_state.py), not a spawned
        # daemon worker. No HTTP dispatch gate applies (paths=(),
        # prefixes=()) - tools/loop_state.py reads policy_live.json/
        # policy_seed.json DIRECTLY (see its _build_loop_enabled()), so the
        # flag is real - it actually silences the Stop hook - even when the
        # daemon isn't running. See daemon/debt.py for the full incident/
        # design record and the explicit "never toggle the real policy file
        # to test this" safety note.
        id="buildloop", enabled_key="buildLoopEnabled",
        role="governs the current agent's own build workflow "
             "(ALIGN>ANALYZE>EXECUTE>TEST>CLEAN>BUILD>COMMIT), not a spawned "
             "worker - self-governance, not delegation",
        repo_files=("tools/loop_state.py",),
        storage="derived live from git status + compile/test/tsc results "
                "(no persisted table - this cell IS its own NO-MONKEY-PATCH example)",
        harness_file="CLAUDE.md",
        # route_modules deliberately empty: /loop/map (routes_info.py) is a
        # SHARED read-only mirror (engineer's lane/gate flow + this cell's
        # build state merged in one response) - attributing routes_info's
        # other, unrelated routes (debt/charter/harness-version/models) to
        # this cell would repeat the exact inaccuracy already flagged for
        # loopmap.tsx's UI sharing. Informational only, not an owned surface.
        ui_files=("src/app/loopmap.tsx",),  # shared with engineer, noted above
    ),
]

_BY_ID = {c.id: c for c in CELLS}


def _policies():
    try:
        from daemon.spine.auth import policy
        return policy.get_policies()
    except Exception:
        return {}


def enabled(cell):
    """Is this cell on? Derived live from the policy plane, default true."""
    return bool(_policies().get(cell.enabled_key, True))


def enabled_id(cid):
    """Is the cell with this id on? Safe for cross-cell event hooks to call as a
    one-line guard (the ONE owner deciding, per NO-MONKEY-PATCH). Unknown id ->
    True (an unregistered caller is never silently disabled)."""
    c = _BY_ID.get(cid)
    return True if c is None else enabled(c)


def owning_cell(path):
    """The cell that owns a request path, or None if the path is spine/unowned."""
    for c in CELLS:
        if c.owns(path):
            return c
    return None


def path_disabled(path):
    """True iff a registered cell owns this path AND that cell is disabled. Used
    at ONE point in server.py's dispatch, after the auth gate, so a disabled
    cell's routes 404 cleanly without editing every route body. Returns False
    for every path while all flags default true - zero behaviour change."""
    c = owning_cell(path)
    return c is not None and not enabled(c)


def start_enabled():
    """Boot: launch the lifecycle poller of every enabled cell that has one.
    Replaces the flat processes/connectors/pm start calls in serve() with a
    registry-driven loop. Lazy-imports each module so cells.py stays cycle-free."""
    for c in CELLS:
        if not c.start or not enabled(c):
            continue
        mod_name, func_name = c.start
        try:
            mod = _import_by_bare_name(mod_name, c.id)
            getattr(mod, func_name)()
        except Exception as e:
            print("cells: %s.%s failed to start: %s" % (mod_name, func_name, e))


def _cell_routes(c):
    """DERIVE this cell's live endpoint list from its route modules' actual
    GET_ROUTES/POST_ROUTES dicts - never hand-duplicated, so it can't drift
    from what server.py really dispatches. Best-effort: an import error just
    yields fewer entries, never a 500 (this feeds a read-only manifest)."""
    out = []
    for mod_name in c.route_modules:
        try:
            mod = _import_by_bare_name(mod_name, c.id)
        except Exception:
            continue
        for p in sorted(getattr(mod, "GET_ROUTES", {}) or {}):
            out.append("GET " + p)
        for p in sorted(getattr(mod, "POST_ROUTES", {}) or {}):
            out.append("POST " + p)
    return out


def manifest():
    """Read-only description of every cell + its live enable-state, for GET
    /cells. The app renders exactly the cells that are enabled here."""
    return [{
        "id": c.id,
        "enabled": enabled(c),
        "enabledKey": c.enabled_key,
        "role": c.role,
        "surface": c.surface,
        "modes": list(c.modes),
        "logicFiles": list(c.logic_files) + list(c.repo_files),
        "storage": c.storage,
        "harnessFile": c.harness_file,
        "routes": _cell_routes(c),
        "uiFiles": list(c.ui_files),
        "tools": list(c.tools),
    } for c in CELLS]


def read_source(cid, fname):
    """Return the text of `fname` if it is EXACTLY one of the cell `cid`'s own
    declared files (logic_files/harness_file/route_modules/ui_files) - the
    ALLOWLIST. Returns None on any mismatch (unknown cell, unknown file, not
    that cell's file) - the caller turns None into a 404, never a path. Never
    joins user input into a path beyond this fixed, pre-validated lookup - no
    traversal is possible because `fname` is matched against a closed set of
    known-safe relative paths, not used to build a path directly."""
    c = _BY_ID.get(cid)
    if c is None or fname not in c.allowed_files():
        return None
    where = c.where(fname)
    if where != "daemon":
        roots = ({"app": APP_ROOT, "repo": REPO_ROOT}[where],)
    else:
        # cell-owned daemon files may live in the post-reorg daemon/cells/<id>/
        # or the pre-move flat daemon/ - try both (see Cell.daemon_roots()).
        roots = c.daemon_roots()
    for root in roots:
        root = os.path.normpath(root)
        full = os.path.normpath(os.path.join(root, fname))
        # belt-and-suspenders: even though fname came from a closed allowlist,
        # confirm the resolved path is still under the expected root before
        # opening it - the allowlist is the real guarantee, this is a backstop.
        if os.path.commonpath([full, root]) != root:
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                text = f.read(MAX_SOURCE_BYTES + 1)
        except OSError:
            continue
        if len(text) > MAX_SOURCE_BYTES:
            text = text[:MAX_SOURCE_BYTES] + "\n\n... (truncated)"
        return text
    return None
