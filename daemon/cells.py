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
"""


class Cell:
    """A registered agentic system. Pure descriptor - behaviour lives in the
    cell's own modules; this just names the seams (routes, lifecycle, flag)."""

    def __init__(self, id, enabled_key, paths=(), prefixes=(), start=None,
                 role="", surface="", modes=()):
        self.id = id
        self.enabled_key = enabled_key      # policy flag, e.g. "pmEnabled"
        self.paths = tuple(paths)           # exact owned paths, e.g. ("/processes",)
        self.prefixes = tuple(prefixes)     # owned path prefixes, e.g. ("/pm/",)
        self.start = start                  # ("module","func") lazy lifecycle launcher, or None
        self.role = role                    # harness brief filename (informational/manifest)
        self.surface = surface              # app-side kernel Surface id this cell renders
        self.modes = tuple(modes)           # sub-modes, e.g. engineer -> ("machine","direct")

    def owns(self, path):
        """Does this cell own the given request path?"""
        if path in self.paths:
            return True
        return any(path.startswith(pre) for pre in self.prefixes)


# The registered cells. Order is presentation-only. enabled_key defaults true in
# policy_seed.json, so all of this is a no-op until an owner flips a flag.
CELLS = [
    Cell(
        id="engineer", enabled_key="engineerEnabled",
        # the card/kanban spine-core. Its lifecycle (reconciler/watcher) stays a
        # spine call in serve() for now - conformed last (Phase 3). machine/
        # direct are MODES here, gated by the separate policy.machine, not a cell.
        paths=("/tracks",), prefixes=("/tracks/", "/track/"),
        role="(card brief)", surface="surfaces.board",
        modes=("machine", "direct"),
    ),
    Cell(
        id="pm", enabled_key="pmEnabled",
        prefixes=("/pm/",),
        start=("pm", "start_loop"),
        role="pm.role.md", surface="surfaces.pm",
    ),
    Cell(
        id="process", enabled_key="processEnabled",
        # /processes and /processes/<id>/step live in routes_misc + routes_system,
        # both SHARED modules - path ownership keeps /me (spine) ungated.
        paths=("/processes",), prefixes=("/processes/",),
        start=("processes", "start_chain_poller"),
        role="(inline proposer prompt)", surface="surfaces.processes",
    ),
    Cell(
        id="connectors", enabled_key="connectorsEnabled",
        paths=("/connectors",), prefixes=("/connectors/",),
        start=("connectors", "start_scheduler"),
        role="(card-worker builds it)", surface="surfaces.connectors",
    ),
    Cell(
        id="copilot", enabled_key="copilotEnabled",
        prefixes=("/chat",),
        role="board-copilot.md", surface="surfaces.chat",
    ),
]

_BY_ID = {c.id: c for c in CELLS}


def _policies():
    try:
        import policy
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
            mod = __import__(mod_name)
            getattr(mod, func_name)()
        except Exception as e:
            print("cells: %s.%s failed to start: %s" % (mod_name, func_name, e))


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
    } for c in CELLS]
