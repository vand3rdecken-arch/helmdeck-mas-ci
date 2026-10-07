# -*- coding: utf-8 -*-
"""The three context patterns borrowed 2026-10-07 (owner: "wir implementieren
die drei Muster") - pinned so none of them silently degrades to a lossy cut:

 1. RESTORABLE PRUNE (copilot_prune + file_store): an old, big tool_result is
    replaced by a pointer - head text + the path of a file holding ALL of it;
    without a store the old opaque placeholder stays.
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

from cells.copilot.chat import copilot_prune as pr          # noqa: E402
import ctxout                                              # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def user(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def tool_use(tid, name):
    return json.dumps({"type": "assistant", "message": {"role": "assistant",
                       "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]}})


def tool_result(tid, text):
    return json.dumps({"type": "user", "message": {"role": "user",
                       "content": [{"type": "tool_result", "tool_use_id": tid, "content": text}]}})


BIG = "BOARD\n" + "\n".join("card-%03d running 12%%" % i for i in range(400))      # ~8 KB
lines = [user("hi"), tool_use("t1", "Bash"), tool_result("t1", BIG)] + [user("turn %d" % i) for i in range(8)]

# 1: restorable prune
store_dir = os.path.join(TMP, "ctx", "sess")
out, n, saved = pr.prune_lines(lines, store=pr.file_store(store_dir))
check("prune: one block pruned", n == 1, n)
rec = json.loads(out[2])
ph = rec["message"]["content"][0]["content"]
check("prune: placeholder names the tool and the file", "[gekürzt: Bash" in ph and "voll: " in ph and "/t1.txt" in ph, ph[:120])
check("prune: placeholder keeps the head text", "BOARD card-000 running 12%" in ph, ph[:160])
path = ph.split("voll: ", 1)[1].split("]", 1)[0]
check("prune: the file holds ALL of it", os.path.isfile(path) and open(path, encoding="utf-8").read() == BIG)
check("prune: bytes really freed", saved > 7000, saved)
out2, n2, _ = pr.prune_lines(lines)
ph2 = json.loads(out2[2])["message"]["content"][0]["content"]
check("prune: without a store the old opaque placeholder stays", ph2.startswith("[gekürzt: Bash") and "voll" not in ph2, ph2)
check("prune: a young result is untouched",
      pr.prune_lines([user("a"), tool_use("t2", "Bash"), tool_result("t2", BIG), user("b")], store=pr.file_store(store_dir))[1] == 0)

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
