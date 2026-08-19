# Single source of truth for daemon/repo path roots + cell-subfolder sys.path
# wiring. Every daemon/*.py module used to compute its OWN ROOT via
# `dirname(abspath(__file__))` (1 or 2 levels) - ~25 independent copies, the
# open orphan-root-paths-events-jsonl-incident debt (daemon/debt.py). Each
# copy silently assumed the FILE'S OWN location (flat in daemon/), so moving
# any one file into a subfolder (daemon/cells/<id>/, daemon/spine/) would
# have broken its path math with no error, just a wrong path. This module
# stays flat in daemon/ forever (never itself relocated), so it is the one
# place a dirname() depth is allowed to be hardcoded - every other module
# imports REPO_ROOT/DAEMON_ROOT from here instead of recomputing them.
import os, sys

_HERE = os.path.dirname(os.path.abspath(__file__))   # daemon/, always - this
                                                       # file never moves
DAEMON_ROOT = _HERE
REPO_ROOT = os.path.dirname(_HERE)


def ensure_cell_paths():
    """Adds daemon/spine and every daemon/cells/<id> to sys.path (if they
    exist), so flat `import sessions` / `import events` keep resolving after
    physical relocation into those subfolders. No-op for any subfolder that
    doesn't exist yet (safe to call before/during/after the phased move).
    Call once per process, before any other daemon-local import - the top of
    every entrypoint (swarm.py) and every test_*.py's/tools/*.py's existing
    sys.path.insert(0, DAEMON) block."""
    for sub in ("spine", "cells/engineer", "cells/pm", "cells/process",
                "cells/connectors", "cells/copilot"):
        p = os.path.join(DAEMON_ROOT, *sub.split("/"))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
