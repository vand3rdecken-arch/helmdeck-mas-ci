# -*- coding: utf-8 -*-
"""_is_agent_pid's image-name guard (daemon/spine/agent/proctable.py).

Pins a real bug found and fixed while wiring the codex/opencode/pi native
drivers (docs/multi-engine-build-plan.md Cards 6-8): a short, common
substring like "pi" would match "pip.exe" - a near-universal process on any
dev machine - which would have made reap_orphans/tree-kill treat a random
pip install as one of the daemon's own agent processes. "omp" had the exact
same latent shape (matches "compress.exe"/"compact.exe") despite already
being shipped (Card 8) - fixed here too, not left for later.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon.spine.agent import proctable

FAILS = []


def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond:
        FAILS.append(name)


if os.name != "nt":
    print("non-Windows: _is_agent_pid always returns True, nothing to pin here.")
    sys.exit(0)

_real_pid_table = proctable._pid_table


def _with_image(img):
    proctable._pid_table = lambda: [(4242, 1, img)]
    try:
        return proctable._is_agent_pid(4242)
    finally:
        proctable._pid_table = _real_pid_table


print("real agent images are recognized:")
check("claude.exe", _with_image("claude.exe"))
check("node.exe", _with_image("node.exe"))
check("omp.exe (exact)", _with_image("omp.exe"))
check("pi.exe (exact)", _with_image("pi.exe"))
check("codex.exe (substring - long/distinctive enough to be safe)", _with_image("codex.exe"))
check("opencode.exe (substring)", _with_image("opencode.exe"))

print("unrelated processes are NOT falsely matched (the bug this pins):")
check("pip.exe is NOT matched despite containing \"pi\"", not _with_image("pip.exe"))
check("compress.exe is NOT matched despite containing \"omp\"", not _with_image("compress.exe"))
check("compact.exe is NOT matched despite containing \"omp\"", not _with_image("compact.exe"))
check("explorer.exe is not matched", not _with_image("explorer.exe"))
check("notepad.exe is not matched", not _with_image("notepad.exe"))

print("a pid not in the table at all is not matched:")
proctable._pid_table = lambda: []
try:
    check("empty table -> False", proctable._is_agent_pid(4242) is False)
finally:
    proctable._pid_table = _real_pid_table

if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\nagent-pid-guard: all pinned - PASS")
