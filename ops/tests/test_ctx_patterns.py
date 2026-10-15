# -*- coding: utf-8 -*-
"""The three context patterns borrowed 2026-10-07 (owner: "wir implementieren
die drei Muster") - pinned so none of them silently degrades to a lossy cut:

 1. (REMOVED 2026-10-15) the restorable tool-result prune: it rewrote the CLI's
    own transcript and loaded the whole 374 MB board session per run. Size is
    bounded by session rotation instead (ops/tests/test_session_rotate.py).
 2. CAP AT THE SOURCE (ops/tools/ctxout): a reader's output above its budget
    is shown head+tail with a note naming the full file; under the budget it
    passes byte-identical; HELMDECK_CTX_CAP=0 never cuts.
 3. EARLY, STRUCTURED COMPACTION (copilot): the cost line sits at half the
    window, and the /compact call carries the schema.
 4. The chat loads a chosen tool list, overridable by setting.
No model, no live db (data root sandboxed). Run: py -3.12 ops/tests/test_ctx_patterns.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
TMP = tempfile.mkdtemp(prefix="helmdeck-ctx-patterns-")
os.environ["HELMDECK_DATA_ROOT"] = TMP

import ctxout                                              # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# 2: cap at the source
os.environ.pop("HELMDECK_CTX_CAP", None)
small = "x" * 100
shown, p = ctxout.cut(small, "t", cap=1000)
check("cap: under budget passes byte-identical", shown == small and p is None)
big = "".join("line %04d\n" % i for i in range(2000))                     # 20 KB
shown, p = ctxout.cut(big, "t", cap=4000)
check("cap: over budget is shorter than budget + note", len(shown) < 4000 + 400, len(shown))
check("cap: shows head AND tail", shown.startswith("line 0000") and shown.rstrip().endswith("line 1999"))
check("cap: note names size and file", "gekürzt: 4000 von 20000 Zeichen" in shown and p and p in shown)
check("cap: the file is the full output", open(p, encoding="utf-8").read() == big)
check("cap: file lives under the sandboxed data root", p.startswith(TMP.replace("\\", "/")), p)
os.environ["HELMDECK_CTX_CAP"] = "0"
check("cap: HELMDECK_CTX_CAP=0 never cuts", ctxout.cut(big, "t", cap=100)[0] == big)
os.environ.pop("HELMDECK_CTX_CAP")


def reader(argv):
    print(big, end="")
    return 3


import io                                                                  # noqa: E402
real = sys.stdout
sys.stdout = cap = io.StringIO()
rc = ctxout.run(reader, [], "r", cap=4000)
sys.stdout = real
check("run: exit code passes through", rc == 3, rc)
check("run: printed the capped text", "gekürzt: 4000 von" in cap.getvalue())

# 3: early, structured compaction
from cells.copilot.chat import copilot as cp                               # noqa: E402
check("compact: cost line at half the window", cp.COMPACT_COST_LINE <= 100_000, cp.COMPACT_COST_LINE)
for h in ("ZIEL", "ENTSCHEIDUNGEN", "LAUFEND", "OFFEN", "OWNER-WUENSCHE", "DATEIEN"):
    check("compact: schema has " + h, h in cp.COMPACT_INSTRUCTIONS)
src = open(os.path.join(ROOT, "cells", "copilot", "chat", "copilot.py"), encoding="utf-8").read()
check("compact: the /compact call carries the schema", '"/compact " + COMPACT_INSTRUCTIONS' in src)

# 4: chat tools
from spine.storage import events                                           # noqa: E402
_orig = events.settings
events.settings = lambda: {}
check("tools: default list drops Skill/NotebookEdit, keeps Agent",
      "Skill" not in cp.henry_chat_tools() and "Agent" in cp.henry_chat_tools())
events.settings = lambda: {"henry_chat_tools": "default"}
check("tools: 'default' = the CLI's whole block (no --tools)", cp.henry_chat_tools() is None)
events.settings = lambda: {"henry_chat_tools": "Bash,Read"}
check("tools: setting overrides", cp.henry_chat_tools() == "Bash,Read")
events.settings = _orig

print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
