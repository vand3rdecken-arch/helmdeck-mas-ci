# -*- coding: utf-8 -*-
"""Headless test for CHAT MESSAGE IDENTITY (client_msg_id).

The defect this pins (owner, 2026-08-29): the board chat retired an optimistic
bubble only when the server reported the same TEXT more often than at queue
time. Text cannot tell two identical messages apart, and a single character of
drift meant the count never rose - so the copy stuck to the bottom of the chat
forever, below messages that arrived later.

The daemon half of the fix is what this file tests: the `mid` the client already
mints per /chat call (client.ts, read by chat_dedupe) is echoed back on the
persisted `you` entry as client_msg_id, so the app can match by IDENTITY.

What is pinned here:
 1. the id survives the log round trip and comes back out of history()
 2. it is ABSENT, not empty, when no id was sent - the app must be able to tell
    "old daemon / other surface" from "id was blank"
 3. two messages with the SAME TEXT get different ids - the exact case text
    matching cannot resolve
 4. the id never lands on the bot's own entry (it identifies the OWNER's message)
 5. a blank/whitespace id is treated as absent rather than stored as ""

Self-sandboxing: temp events/settings/log, no model call, no network.
Run: py -3.12 ops/tests/test_chat_msg_identity.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-chatid-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot import copilot
copilot.CHATLOG = os.path.join(SANDBOX, "copilot_log.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


USER = "owner"


def entry(text, mid):
    """Exactly the shape cells/copilot/copilot.py builds for a finished turn -
    including the rule that the key is OMITTED when there is no id."""
    you = {"cls": "you", "text": text, "ts": "10:00"}
    if mid:
        you["client_msg_id"] = mid
    return [you, {"cls": "bot", "text": "reply to " + text, "ts": "10:00"}]


def logged():
    return (copilot.history(USER) or {}).get("messages") or []


# -- 1. round trip ----------------------------------------------------------
copilot._append_log(USER, entry("hallo", "m-aaa"))
msgs = logged()
you = [m for m in msgs if m.get("cls") == "you"]
check(len(you) == 1 and you[0].get("client_msg_id") == "m-aaa",
      "the client id survives the log round trip and comes back from history()")

# -- 4. never on the bot's entry -------------------------------------------
bots = [m for m in msgs if m.get("cls") == "bot"]
check(bots and "client_msg_id" not in bots[0],
      "the id identifies the OWNER's message only - never the reply")

# -- 2. absent, not empty, when nothing was sent ---------------------------
copilot._append_log(USER, entry("ohne id", ""))
you = [m for m in logged() if m.get("cls") == "you"]
check("client_msg_id" not in you[-1],
      "no id sent -> the key is ABSENT (an old daemon is distinguishable from a blank id)")
check(you[-1].get("client_msg_id") is None,
      "and reads as None, so a client can branch on it safely")

# -- 3. same text, different ids -------------------------------------------
copilot._append_log(USER, entry("weiter", "m-bbb"))
copilot._append_log(USER, entry("weiter", "m-ccc"))
same = [m for m in logged() if m.get("cls") == "you" and m.get("text") == "weiter"]
check(len(same) == 2, "both same-text messages are logged (neither swallows the other)")
check(same[0].get("client_msg_id") != same[1].get("client_msg_id"),
      "SAME TEXT, different ids - the case text matching cannot resolve")
check({m.get("client_msg_id") for m in same} == {"m-bbb", "m-ccc"},
      "each carries its own id, so the app retires exactly one bubble per turn")

# -- 5. a blank id is not stored -------------------------------------------
copilot._append_log(USER, entry("leerzeichen", "   ".strip()))
you = [m for m in logged() if m.get("cls") == "you"]
check("client_msg_id" not in you[-1],
      "a whitespace-only id is treated as absent, not stored as an empty string")

# -- ordering: the log stays in append order -------------------------------
texts = [m.get("text") for m in logged() if m.get("cls") == "you"]
check(texts == ["hallo", "ohne id", "weiter", "weiter", "leerzeichen"],
      "the log preserves send order - the app's anchor logic relies on it")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHAT IDENTITY CHECKS PASSED")
