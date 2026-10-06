# -*- coding: utf-8 -*-
"""Silent-truncation pins for agent-facing text in copilot.py: every cap says
what it cut (count at the point of the cut), never reads as exhaustive.

Self-sandboxing (db.DBPATH first), no daemon, no model call.
Run: py -3.12 ops/tests/test_copilot_disclosure.py"""
import inspect
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
SANDBOX = tempfile.mkdtemp(prefix="hd-disclose-")
from spine.storage import db, events                              # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.copilot.chat import copilot                             # noqa: E402

fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


# 3 - pending item cut is marked
short = "x" * copilot.PENDING_ITEM_MAX
ok(copilot._cap_item(short) == short, "item at the cap is untouched")
cut = copilot._cap_item("y" * (copilot.PENDING_ITEM_MAX + 25))
ok(cut.endswith("[... 25 Zeichen gekuerzt]"), "cut item ends with the char count")

# 6 - inbox window + count
U = "tien"
db.chat_append(U, [{"cls": "pm", "text": "Report %d" % i} for i in range(12)])
out = copilot._inbox_since(U, limit=3)
ok(out.startswith("(3 von 12 neuen Eintraegen gezeigt") and "letzten 40" in out,
   "inbox states N of M shown and the 40-row window")
ok(out.endswith("Report 11"), "inbox still ends with the newest entry")
out_all = copilot._inbox_since(U, limit=20)
ok(not out_all.startswith("("), "no cut -> no notice")
src_inbox = open(os.path.join(HERE, "..", "tools", "henry_inbox.py"), encoding="utf-8").read()
ok("letzten 40 Zeilen" in src_inbox and '"nichts Neues seit' not in src_inbox,
   "henry_inbox empty message names the window and classes")

# 7 - plan digest
from cells.copilot.planning import pm                              # noqa: E402
_orig = pm.live_plan
pm.live_plan = lambda: {
    "goal": "g", "open_questions": ["q%d" % i for i in range(6)],
    "risks": ["r%d" % i for i in range(5)],
    "milestones": [{"name": "m%d" % i, "done_when": ["a", "b", "c"]} for i in range(8)]}
try:
    dg = copilot._pm_plan_digest()
finally:
    pm.live_plan = _orig
ok("(+2 weitere offene Owner-Entscheidungen)" in dg, "open_questions cut counted")
ok("(+1 weitere Risiken)" in dg, "risks cut counted")
ok("(+2 Meilensteine)" not in dg and "(+2 weitere Meilensteine)" in dg, "milestones cut counted")
ok("(+1 weitere)" in dg, "done_when cut counted")

# 28 - snapshot clip
ok(copilot._clip("a" * 10, 90) == "a" * 10, "short field has no ellipsis")
ok(copilot._clip("a" * 100, 90).endswith("…"), "cut field ends in an ellipsis")
ssrc = inspect.getsource(copilot._snapshot)
ok("outcome(Anfang)=" in ssrc and "Beispiel-Karte" in ssrc, "snapshot labels outcome and counts hidden examples")

# 5 - card context window
from spine.agent import timeline_store                             # noqa: E402
_f, _r = copilot._find_card, timeline_store.read
copilot._find_card = lambda cid: {"id": cid, "task": "t", "run_dir": "x"}
steps = [{"text": "s%d" % i, "byKind": "worker"} for i in range(55)]
timeline_store.read = lambda rd, limit=400: steps[-limit:] if limit else steps
try:
    ctx = copilot._card_context("c1", limit=40)
finally:
    copilot._find_card, timeline_store.read = _f, _r
ok("letzte 40 von 55 Schritten" in ctx and "15 aeltere" in ctx, "card context states window and older count")
ok("every steer the owner sent" not in ctx, "header no longer claims every steer")

# 30 - bg wake text
_real_chat = copilot.chat
sent = {}
copilot.chat = lambda user, prompt, **kw: sent.setdefault("p", prompt)
copilot._bg_continue("tien", [{"status": "completed", "title": "T", "result": "z" * 500}])
ok("[... gekuerzt]" in sent["p"] and "vollstaendige Ergebnis steht" not in sent["p"],
   "bg wake marks the 300 cut and does not promise the full result")

# 1 - action cap drop is reported
csrc = inspect.getsource(_real_chat)
ok("nicht ausgefuehrt (Limit 6)" in csrc, "chat() reports dropped actions via _pending_actions")

print("\n" + ("FAIL (%d)" % len(fails) if fails else "copilot-disclosure: PASS"))
sys.exit(1 if fails else 0)
