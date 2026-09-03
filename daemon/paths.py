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


# config-consolidation phase 7 (owner decree: daemon/ was ~20 loose json/
# jsonl files with no grouping - config/state/content interleaved).
#
# TWO SUBFOLDER NAMES ONLY - "state" for runtime bookkeeping (session/pid/log
# tables a module keeps about its own machinery), "content" for durable data
# a feature produces about itself (Henry's memory notes, a voice/stt cache).
# Never config (that moved into the db in phases 1-6) and never code
# (connectors/ stays a sibling - charter-screened source, not data).
#
# DELIBERATELY NOT HELPER FUNCTIONS HERE. Every module in this repo binds its
# OWN path from `daemon.paths.DAEMON_ROOT` at ITS OWN import time
# (`from daemon.paths import DAEMON_ROOT as ROOT`), and every existing test
# sandboxes by overwriting that MODULE'S already-bound constant directly
# (`copilot.SESS = os.path.join(tmp, ...)`), never by reassigning
# `daemon.paths.DAEMON_ROOT` itself - measured the hard way while adding this
# phase: a shared `daemon.paths.content_dir()` called fresh from inside a
# module wrote into the REAL daemon/content/ during a test run, because no
# existing test patches `daemon.paths.DAEMON_ROOT`, only each module's own
# derived copy. So there is no state_dir()/content_dir() helper - every
# module below joins "state"/"content" onto ITS OWN `ROOT`, the exact same
# shape every flat path already had, sandboxed the exact same way.
STATE_SUBDIR = "state"
CONTENT_SUBDIR = "content"
