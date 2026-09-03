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
APP_ROOT = os.path.join(REPO_ROOT, "surfaces", "app")                    # app/ (sibling)
MAX_SOURCE_BYTES = 200_000


def _import_by_bare_name(mod_name, owner_cell_id=None):
    """Cell.start/route_modules store BARE names (e.g. 'routes_pm') because
    they double as the security allowlist (Cell.allowed_files() - see
    read_source()'s docstring: the manifest IS the allowlist). daemon/ is a
    real Python package now, so actually IMPORTING one of these needs its
    real dotted path - tried here in owner-cell-first order, then
    spine.http.routes (the multi-owner/spine route modules),
    rather than storing the dotted path a second place that could drift
    from the physical file."""
    import importlib
    candidates = []
    if owner_cell_id:
        candidates.append(f"cells.{owner_cell_id}.{mod_name}")
    candidates.append(f"spine.http.routes.{mod_name}")
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
                 route_modules=(), ui_files=(), tools=(), repo_files=(),
                 board=(), surfaces=()):
        self.id = id
        self.enabled_key = enabled_key      # policy flag, e.g. "copilotEnabled"
        self.paths = tuple(paths)           # exact owned paths, e.g. ("/processes",)
        self.prefixes = tuple(prefixes)     # owned path prefixes, e.g. ("/pm/",)
        # ("module","func") for ONE lazy lifecycle launcher, or a TUPLE of those
        # for a cell that starts more than one poller under its one flag (e.g.
        # copilot starts both henry_broker's escalation loop and pm's planning
        # loop - merged cell, one enabled_key, two independent loops). None for
        # a cell with no background lifecycle. start_enabled() below normalises
        # either shape.
        self.start = start
        self.role = role                    # harness brief filename OR a short description
        self.surface = surface              # PRIMARY app-side kernel Surface id this cell renders
        self.surfaces = tuple(surfaces)     # ADDITIONAL Surface ids this cell owns beyond the
                                            # primary (a merged cell keeps its absorbed systems'
                                            # tabs: engineer carries surfaces.processes +
                                            # surfaces.connectors). The app's tab-hiding iterates
                                            # the manifest's full list, so disabling the cell
                                            # hides every one of its tabs - same generalisation
                                            # `start` got for multi-loop cells.
        self.modes = tuple(modes)           # sub-modes, e.g. engineer -> ("machine","direct")
        self.logic_files = tuple(logic_files)    # daemon/*.py files, e.g. ("pm.py","pm_state.py")
        self.storage = storage                   # short description, e.g. "loop.json (daemon/pm/)"
        self.harness_file = harness_file         # REPO-ROOT-relative *.md path, or "" if inline/none
        self.route_modules = tuple(route_modules)  # daemon module names, e.g. ("routes_pm",)
        self.ui_files = tuple(ui_files)          # app/-relative paths: surface plugin + real screens
        self.tools = tuple(tools)                # external tool refs this cell's own tooling uses -
                                                  # documentation only, never readable via read_source
        self.repo_files = tuple(repo_files)      # REPO-ROOT-relative logic (not under daemon/ or
                                                  # app/) - e.g. ops/tools/loop_state.py for the buildloop
                                                  # cell, which isn't daemon-hosted like the other 5
        self.board = tuple(board)                # ((station, verbLabelKey), ...): where this cell
                                                  # ACTS on the board pipeline, in flow order - the
                                                  # cell-track band under the pipeline renders from
                                                  # this (copilot's band is DERIVED from its rules'
                                                  # binds instead, see apimeta._cell_tracks). Declared
                                                  # metadata like logic_files: the registry is the one
                                                  # place that says what a cell is responsible for.

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
            out.add(mod.replace(".", "/") + ".py")
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
        (cells/<id>/), then spine/http/routes/ (route_modules
        can legitimately name a SHARED route module - e.g. process cell's
        routes_misc.py/routes_system.py, both multi-owner), then flat
        daemon/ as a last-resort fallback for anything not yet swept into
        one of the above."""
        return (os.path.join(REPO_ROOT, "cells", self.id),
                os.path.join(REPO_ROOT, "spine", "http", "routes"),
                ROOT)


# The registered cells. Order is presentation-only. enabled_key defaults true in
# policy_seed.json, so all of this is a no-op until an owner flips a flag.
CELLS = [
    Cell(
        # THE BUILDER AND HIS WHOLE BUILD PROCESS (owner directive 2026-09-03,
        # second half of the two-agent model: "Du hast ein engineer, der
        # seinen Bau Prozess hat, dazu gehoert alle drei folder. Henry ist der
        # Koordinator"). The former `process` and `connectors` cells merged in
        # here, same evidence-backed shape as pm->copilot: a chain's steps
        # dispatch INTO engineer cards (process's proposer is a stateless
        # one-shot LLM call, no agent identity), and connectors are BUILT by
        # engineer cards and installed only after the same gate. Three folders,
        # one build responsibility, ONE switch - engineerEnabled off = no
        # cards, no chains, no connector scheduler (a deliberate narrowing,
        # decided by the owner, not a side effect).
        #
        # The card/kanban spine-core (Phase 3, the crown jewel). Lifecycle:
        # sessions.start_engineer_lifecycle() launches the zombie reconciler +
        # background-task watcher; the chain poller and connector scheduler
        # ride the same flag as further launchers (Cell.start tuple).
        # machine/direct are MODES here, gated by the separate policy.machine,
        # not a cell.
        id="engineer", enabled_key="engineerEnabled",
        # /processes and /processes/<id>/step live in routes_misc + routes_system,
        # both SHARED modules - path ownership keeps /me (spine) ungated.
        paths=("/tracks", "/processes", "/connectors"),
        prefixes=("/tracks/", "/processes/", "/connectors/"),
        start=(("cards.sessions", "start_engineer_lifecycle"),
               ("chains.processes", "start_chain_poller"),
               ("connectors.connectors", "start_scheduler")),
        role="(card brief, per-task)", surface="surfaces.board",
        # The absorbed systems' tabs stay real screens; disabling this cell
        # hides all three (see Cell.surfaces above).
        surfaces=("surfaces.processes", "surfaces.connectors"),
        modes=("machine", "direct"),
        logic_files=("cards/sessions.py", "cards/lanemachine.py", "cards/dispatch.py",
                     "cards/cardadmin.py", "cards/turnrunner.py",
                     "chains/processes.py", "connectors/connectors.py"),
        storage="tracks + processes + connector_state tables (db.py) + "
                "worktrees + daemon/connectors/ code dir",
        route_modules=("routes.routes_tracks", "routes.routes_track_actions",
                       "routes_misc", "routes_system", "routes.routes_connectors"),
        # the Surface plugins live in the CELL's own folder since phase 3 of
        # the two-mains split (cells/<id>/ui/, repo-root-relative -> repo_files);
        # the route shells + shared widgets stay app-side (ui_files).
        repo_files=("cells/engineer/ui/surface.tsx",
                    "cells/engineer/ui/processes.tsx",
                    "cells/engineer/ui/connectors.tsx"),
        ui_files=("src/ui/board.tsx", "src/app/(tabs)/board.tsx",
                  "src/app/(tabs)/processes.tsx",
                  "src/app/(tabs)/connectors.tsx"),
        # WHERE THIS CELL ACTS on the board: it runs the work (turnrunner in
        # the working lane), its gate checks the result, and the accept hook
        # ships it. The band under the pipeline draws from exactly this.
        board=(("working", "cell.track.eng.working"),
               ("gate", "cell.track.eng.gate"),
               ("deploy", "cell.track.eng.deploy")),
        # documentation-only reference (owner directive, 2026-08-18): the
        # editorial-diagram visual language this cell's own code-map UI
        # (this file's read_source() + surfaces/app/src/ui/cell_diagram.tsx) follows.
        # Not vendored, not a runtime dependency - registered here so the
        # code-map itself shows what informed its own rendering style.
        tools=("github.com/cathrynlavery/diagram-design (visual style ref "
               "for the code-map diagram, not a vendored dependency)",),
    ),
    Cell(
        # MERGED WITH PM (owner directive 2026-09-03, "pm und henry is eins"):
        # PM had no LLM identity, no chat surface and no memory of its own -
        # its _ask() spawned the same copilot.CLAUDE binary Henry uses for a
        # stateless one-shot planning call, and its proactive notices were
        # already routed TO HENRY, never to the owner directly (owner decree
        # 2026-08-30, pm.py's _to_henry). Two registered cells were describing
        # one responsibility with two enable flags; now there is one
        # (copilotEnabled off = no chat AND no backlog planning - a
        # deliberate narrowing, not an oversight, decided by the owner
        # explicitly rather than left as a side effect of the merge).
        id="copilot", enabled_key="copilotEnabled",
        prefixes=("/chat", "/pm/"),
        role="board-copilot.md", surface="surfaces.chat",
        logic_files=("chat/copilot.py", "chat/copilot_stats.py", "chat/copilot_actions.py",
                     "broker/henry_broker.py",
                     "planning/pm.py", "planning/pm_state.py", "planning/pm_budget.py",
                     "planning/pm_triangle.py", "planning/pm_resolve.py",
                     "planning/pm_watchdog.py", "planning/pm_goal.py", "planning/pm_comm.py"),
        storage="copilot_sessions.json, copilot_log.json, escalations.jsonl "
                "(shared bus); loop.json (daemon/pm/ runtime dir - unrelated "
                "to where the code now lives)",
        harness_file="ops/harness/agents/board-copilot.md",   # repo-root-relative (not under daemon/)
        # ops/harness/agents/pm.md rides in repo_files below (harness_file
        # stays singular - board-copilot.md is Henry's primary identity brief,
        # pm.md is a report-shape charter fed to a one-shot planning call).
        route_modules=("routes.routes_copilot", "routes.routes_pm"),
        # Henry's judgement half of the escalation channel (spine/registry/
        # escalations.py is the bus; engineer emits; THIS cell decides), AND
        # the backlog planning loop that used to be pm's own - copilotEnabled
        # off now stops both, per the cell-lifecycle contract.
        start=(("broker.henry_broker", "start_broker"), ("planning.pm", "start_loop")),
        repo_files=("cells/copilot/ui/surface.tsx", "ops/harness/agents/pm.md"),
        ui_files=("src/app/chat.tsx", "src/ui/pm_panel.tsx", "src/app/loopmap.tsx"),
        # WHERE THIS CELL ACTS on the board: `board` is the fallback/declared
        # half (backlog planning, formerly pm's own station) - apimeta.
        # _cell_tracks() joins it with the RULE-derived segments from
        # behavior.track() when both fire at the same station, so the picture
        # keeps every verb ("plant" + "steuert") under one Henry band instead
        # of two.
        board=(("backlog", "cell.track.pm.backlog"),),
    ),
    Cell(
        # Cell #6 - added 2026-08-18 after owner pushback: structurally this
        # has the same shape as every other cell (its own ops/harness/laws,
        # states/gates, UI presence), so it belongs in the registry. It is
        # NOT daemon-hosted like the other 5 though - it governs the CURRENT
        # interactive agent's own workflow via Claude Code's hooks
        # (.claude/settings.json -> ops/tools/loop_state.py), not a spawned
        # daemon worker. No HTTP dispatch gate applies (paths=(),
        # prefixes=()) - ops/tools/loop_state.py reads policy_live.json/
        # policy_seed.json DIRECTLY (see its _build_loop_enabled()), so the
        # flag is real - it actually silences the Stop hook - even when the
        # daemon isn't running. See daemon/debt.py for the full incident/
        # design record and the explicit "never toggle the real policy file
        # to test this" safety note.
        id="buildloop", enabled_key="buildLoopEnabled",
        role="governs the current agent's own build workflow "
             "(ALIGN>ANALYZE>EXECUTE>TEST>CLEAN>BUILD>COMMIT), not a spawned "
             "worker - self-governance, not delegation",
        repo_files=("ops/tools/loop_state.py",),
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
        from spine.auth import policy
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
    """Boot: launch the lifecycle poller(s) of every enabled cell that has one.
    Replaces the flat processes/connectors/pm start calls in serve() with a
    registry-driven loop. Lazy-imports each module so cells.py stays cycle-free.

    `c.start` is either one `(mod, func)` pair or a tuple of them - normalised
    here so a cell with two independent loops under one flag (copilot: the
    escalation broker AND the pm planning loop) starts both, and a failure in
    one loop does not take the other down with it."""
    for c in CELLS:
        if not c.start or not enabled(c):
            continue
        pairs = c.start if isinstance(c.start[0], (tuple, list)) else (c.start,)
        for mod_name, func_name in pairs:
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
        # The FULL surface list (primary + absorbed) - what the app's
        # tab-hiding iterates, so one disabled merged cell hides every one
        # of its tabs. `surface` above stays for wire compat.
        "surfaces": [s for s in (c.surface, *c.surfaces) if s],
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
        # cell-owned daemon files may live in the post-reorg cells/<id>/
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
