# -*- coding: utf-8 -*-
"""Headless test for the PRIVATE HENRY of a restricted role (operator).

The model call is stubbed; everything around it is the real code. The point of the
feature is what does NOT reach the prompt, so most cases are leaks:

 1. Only the operator gets one: owner (has the full chat) and client (rooms) -> 403.
 2. The prompt holds the operator's OWN, ASSIGNED and SHARED cards (summary only) and
    their own notes - never another card, a repo path, the owner's notes or another
    person's notes.
 3. Messages are stored in the `chat` table by account: the user's line at once,
    Henry's reply after; an admin reads them only through chat_grants (consent).
 4. A <memory-save> lands in the PERSON scope of that account, not the owner's store.
 5. Turns for one person run one after the other; a failing model is said out loud.

Self-sandboxing: temp DB, no real CLI. Run: py -3.12 ops/tests/test_private_henry.py
"""
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-privhenry-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from cells.copilot.chat import private_henry, chat_grants, copilot_memory
from cells.copilot.routes import routes_henry
from spine.storage.trackstore import _save_track

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("ops", "operator"), ("ops2", "operator"), ("member", "client")):
    auth.create_user(n, PW, r, actor="test")
U = {n: {"name": n, "role": r} for n, r in
     (("tien", "owner"), ("ops", "operator"), ("ops2", "operator"), ("member", "client"))}


def card(cid, **kw):
    t = {"id": cid, "task": "Aufgabe " + cid, "lane": "working", "status": "idle", "client": "",
         "dispatched_by": "tien", "repo": "C:/secret/" + cid, "worktree": "C:/wt/" + cid,
         "run_dir": "C:/rec/" + cid, "session_id": "sess-" + cid, "last_reply": "Ergebnis " + cid,
         "created": "2026-10-05 10:00:00", "updated": "2026-10-05 10:00:00"}
    t.update(kw)
    _save_track(t)


card("own", client="ops", dispatched_by="ops")
card("assigned", zugewiesen_an=["ops"])
card("shared", geteilt_mit=["ops"])
card("foreign-owner")
card("foreign-ops2", client="ops2", dispatched_by="ops2")

db.memory_put("depot", "GEHEIM Depot 50k AAA", actor="henry")                       # the owner's
db.memory_put("ops2-note", "OPS2PRIVAT mag keine Meetings", actor="henry", account="ops2")
db.memory_put("ops-pref", "OPSPREF immer kurze Antworten", actor="henry", account="ops")

prompts = []


def stub(system, prompt):
    prompts.append((system, prompt))
    return ("Klar, ich kuemmere mich um 'own'.\n"
            "<memory-save name=\"ops-gewohnheit\">Arbeitet morgens an Angeboten</memory-save>"), {}


class Req(object):
    def __init__(self):
        self.sent = None

    def _send(self, status, body):
        self.sent = (status, json.loads(body))


def call(handler, user, body=None):
    q = Req()
    handler(q, U[user], body) if body is not None else handler(q, U[user])
    return q.sent


# -- 1. who gets one --------------------------------------------------------------------
for who in ("tien", "member"):
    check(call(routes_henry.henry_history_get, who)[0] == 403
          and call(routes_henry.henry_post_post, who, {"text": "hi"})[0] == 403,
          "%s has no private Henry (the owner has the full chat, a guest has rooms)" % who)
check(auth.restricted_post_allowed(U["ops"], "/henry/post") and not auth.restricted_post_allowed(U["member"], "/henry/post"),
      "the operator may POST /henry/post, the guest may not")

# -- 2./3. the turn ---------------------------------------------------------------------------
e = private_henry.post(U["ops"], "Wo stehe ich mit meinen Karten?", background=False, runner=stub)
check(e["role"] == "user" and e["by"] == "ops", "the person's line is stored")
sysmsg, p = prompts[0]
for need in ("[own]", "[assigned]", "[shared]", "OPSPREF", "Wo stehe ich mit meinen Karten?"):
    check(need in p, "the prompt holds %s" % need)
check("[nur geteilt]" in p.split("[shared]")[1].split("\n")[0], "a merely shared card is marked as such")
for leak in ("foreign-owner", "foreign-ops2", "C:/secret", "C:/wt", "C:/rec", "sess-", "GEHEIM", "AAA", "OPS2PRIVAT"):
    check(leak not in p, "the prompt never holds %r" % leak)
check("Du bist Henry und hilfst genau einer Person" in sysmsg, "the system brief is the PRIVATE brief")

hist = call(routes_henry.henry_history_get, "ops")[1]["entries"]
check([x["role"] for x in hist] == ["user", "assistant"] and hist[-1]["by"] == "Henry",
      "history returns the person's line and Henry's reply, oldest first")
check("memory-save" not in hist[-1]["text"], "the sentinel block is stripped from the visible reply")

# -- 4. memory ----------------------------------------------------------------------------------
mine = copilot_memory.all_notes(copilot_memory.viewer_for("ops", "operator"))
check("ops-gewohnheit" in mine and "ops-pref" in mine and "ops2-note" not in mine and "depot" not in mine,
      "the save landed in THEIR person scope; they read their notes, nobody else's")
check("ops-gewohnheit" not in db.memory_all(), "and not in the owner's store")

# -- consent: an admin reads it only through a grant ----------------------------------------------
try:
    chat_grants.read("tien", "ops")
    check(False, "the owner cannot read the operator's private chat without a grant")
except PermissionError:
    check(True, "the owner cannot read the operator's private chat without a grant")
chat_grants.grant("ops", "tien", 2)
out = chat_grants.read("tien", "ops")
check([x["role"] for x in out["entries"]] == ["user", "assistant"],
      "with the operator's grant the owner reads exactly this conversation")

# -- 5. order and failure ---------------------------------------------------------------------------
order = []


def slow(system, prompt):
    order.append("start")
    time.sleep(0.15)
    order.append("end")
    return "ok", {}


for msg in ("erste", "zweite"):
    db.chat_append("ops", [private_henry._entry("user", msg, "ops")])
ts = [threading.Thread(target=private_henry.answer, args=(U["ops"], m, slow)) for m in ("erste", "zweite")]
for t in ts:
    t.start()
    time.sleep(0.03)
for t in ts:
    t.join()
check(order == ["start", "end", "start", "end"], "two messages from one person are answered one after the other")


def boom(system, prompt):
    raise RuntimeError("rate limit")


r = private_henry.answer(U["ops"], "hilf", boom)
check(r.get("error") and "rate limit" in r["text"], "a failing model leaves an honest note, never silence")

try:
    private_henry.post(U["ops"], "  ", background=False, runner=stub)
    check(False, "an empty message is refused")
except ValueError:
    check(True, "an empty message is refused")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("PRIVATE HENRY: all pinned - PASS")
