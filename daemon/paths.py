# Single source of truth for daemon/repo path roots. Every daemon/*.py module
# used to compute its OWN ROOT via `dirname(abspath(__file__))` (1 or 2
# levels) - ~25 independent copies, the orphan-root-paths-events-jsonl-
# incident debt (spine/debt.py). Each copy silently assumed the
# FILE'S OWN location (flat in daemon/), so moving any file into a subfolder
# (cells/<id>/, spine/) would have broken its path math with
# no error, just a wrong path. This module stays flat in daemon/ forever
# (never itself relocated), so it is the one place a dirname() depth is
# allowed to be hardcoded - every other module imports REPO_ROOT/DAEMON_ROOT
# from here instead of recomputing them.
#
# daemon/ is a REAL Python package now (import cells.copilot.pm, not a
# sys.path trick) - this module holds only the two path CONSTANTS every
# storage/data path is built from, it does not touch sys.path at all.
import os

_HERE = os.path.dirname(os.path.abspath(__file__))   # daemon/, always - this
                                                       # file never moves
DAEMON_ROOT = _HERE
REPO_ROOT = os.path.dirname(_HERE)
