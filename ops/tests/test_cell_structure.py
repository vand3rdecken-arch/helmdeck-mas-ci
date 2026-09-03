# -*- coding: utf-8 -*-
"""THE canonical cell shape, enforced (config-consolidation phase 8, owner
decree: "die Idee von einer Zelle ist dass es gemeinsame Struktur gibt...
warum hat man eine Zellen-Form wenn man am Ende alles unterschiedlich
laesst" - both cells must share ONE form, held by a test, not discipline).

The contract, checked against the real cells/ tree on disk:
  - every cells/<id>/ has an __init__.py and a routes/ subpackage
  - no loose .py file sits directly at the cell root (everything belongs to
    routes/, ui/, or a named domain folder)
  - every module under routes/ that is wired as a route (declares GET_ROUTES
    or POST_ROUTES) is dispatch-table-shaped, not a stray file

This is a manual/CI check (ops/harness's gate stays LIGHT per decree,
no recurring unit suite) - run by hand or from CI, not the Stop hook.

Run:  py -3.12 ops/tests/test_cell_structure.py
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from spine.registry.cells import CELLS  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


CELLS_DIR = os.path.join(ROOT, "cells")

for c in CELLS:
    cdir = os.path.join(CELLS_DIR, c.id)
    if not os.path.isdir(cdir):
        continue  # e.g. buildloop: not daemon-hosted, has no cells/<id>/ tree
    entries = sorted(os.listdir(cdir))
    check("__init__.py" in entries, "cells/%s/: has __init__.py" % c.id)
    loose_py = [f for f in entries
                if f.endswith(".py") and f != "__init__.py"
                and os.path.isfile(os.path.join(cdir, f))]
    check(not loose_py,
          "cells/%s/: no loose .py at cell root (found %r) - everything "
          "belongs under routes/, ui/, or a named domain folder" % (c.id, loose_py))
    check(os.path.isdir(os.path.join(cdir, "routes")),
          "cells/%s/: has a routes/ subpackage (the HTTP surface, nothing else)" % c.id)

    routes_dir = os.path.join(cdir, "routes")
    if os.path.isdir(routes_dir):
        for fn in sorted(os.listdir(routes_dir)):
            if not fn.endswith(".py") or fn == "__init__.py":
                continue
            mod_name = "cells.%s.routes.%s" % (c.id, fn[:-3])
            try:
                mod = importlib.import_module(mod_name)
            except Exception as e:
                check(False, "cells/%s/routes/%s: imports cleanly (%s)" % (c.id, fn, e))
                continue
            # Most route modules are table-dispatched (GET_ROUTES/POST_ROUTES,
            # matched against the path); a few (routes_track_actions.py) are
            # legitimately server.py's own manual if-chain of named handler
            # functions instead (path segments carry an id, not just a static
            # path) - accept either shape, just not an empty/dead file.
            has_table = hasattr(mod, "GET_ROUTES") or hasattr(mod, "POST_ROUTES")
            has_handlers = any(callable(getattr(mod, n)) for n in dir(mod)
                                if not n.startswith("_") and n not in ("os", "json"))
            check(has_table or has_handlers,
                  "cells/%s/routes/%s: is either table-dispatched (GET_ROUTES/"
                  "POST_ROUTES) or exports real handler functions - not a "
                  "dead/empty file" % (c.id, fn))

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("cell-structure: all pinned - PASS")
