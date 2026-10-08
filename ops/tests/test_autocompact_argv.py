# -*- coding: utf-8 -*-
"""Mid-turn context cap (debt tool-results-never-evicted-quadratic-turn-cost):
drivers.build_argv - the ONE assembly point of a card/machine claude argv -
must pass --autocompact <tokens>, clamped to the CLI's 100k-1M, configurable
per driver cfg, 0 = off. Pure argv assembly, no process, no db."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import drivers

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _val(cfg):
    argv = drivers.build_argv("card-worker", cfg, "brief", exe="claude")
    return argv[argv.index("--autocompact") + 1] if "--autocompact" in argv else None


check(_val({}) == "150000", "default cap 150k is on the argv (got %r)" % _val({}))
check(_val({"autocompact": 200000}) == "200000", "cfg value is honoured")
check(_val({"autocompact": 5000}) == "100000", "below the CLI minimum -> clamped to 100k")
check(_val({"autocompact": 9999999}) == "1000000", "above the CLI maximum -> clamped to 1M")
check(_val({"autocompact": 0}) is None, "0 = off, flag omitted")
check(_val({"autocompact": "junk"}) == "150000", "unparseable value -> default, never a crash")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("autocompact argv: all pinned - PASS")
