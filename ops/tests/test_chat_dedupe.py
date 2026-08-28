# -*- coding: utf-8 -*-
"""Pins for cells/copilot/chat_dedupe.py - the POST /chat idempotency window.

The bug it exists for is in the module's own docstring (owner report
2026-08-28: three messages, each enqueued twice into the persistent chat
process, each answered twice). What is pinned here is the part that is easy to
get subtly wrong and impossible to notice afterwards:

  * a replay must be dropped WHILE the original turn is still running - that is
    the case actually measured (the third pair's replay was already blocked on
    the turn lock 43ms after turn one's last message), and a naive "have I
    already ANSWERED this?" check misses it entirely;
  * a deliberate repeat must still work, or the fix trades a duplicate-message
    bug for a swallowed-message bug, which is strictly worse (a duplicate is
    visible; a message that never happened is not);
  * a FAILED turn must not settle - otherwise an error leaves a 10-minute hole
    in which the owner cannot re-send the thing that just failed.

Run: py -3.12 ops/tests/test_chat_dedupe.py
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cells.copilot import chat_dedupe as dd   # noqa: E402

_fails = []


def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def fresh():
    dd._reset_for_tests()


def age(seconds):
    """Push every settled claim `seconds` into the past. Ages the ledger against
    the REAL WINDOW instead of setting WINDOW=0 - which does not work here:
    time.time() has ~15ms granularity on Windows, so a settle and the claim
    right after it can share a timestamp exactly, `now - settled` is 0.0, and
    `<= 0` is true. Found by this file failing on the first run."""
    for e in dd._entries:
        if e["settled"]:
            e["settled"] -= seconds


# --- the measured bug: identical bytes, replayed ---------------------------
print("\nreplay of the same send (the reported bug)")
fresh()
e1, dup1 = dd.claim("owner", "Nein erstmal nur privat", None, None, mid="m1")
ok(dup1 is None, "first send owns the turn")
_e2, dup2 = dd.claim("owner", "Nein erstmal nur privat", None, None, mid="m1")
ok(dup2 is e1, "same mid mid-turn -> duplicate, points at the original claim")
dd.settle(e1, {"reply": "Verstanden"})
_e3, dup3 = dd.claim("owner", "Nein erstmal nur privat", None, None, mid="m1")
ok(dup3 is e1, "same mid AFTER the turn finished is still a duplicate")
ok(dd.await_result(dup3, 0.1) == {"reply": "Verstanden"},
   "a duplicate gets the ORIGINAL turn's answer, not an empty reply")

# --- in-flight identical content, fresh mid --------------------------------
print("\nidentical content while the first turn is still running")
fresh()
e1, _ = dd.claim("owner", "Warum doppelt", None, None, mid="a")
_e2, dup = dd.claim("owner", "Warum doppelt", None, None, mid="b")
ok(dup is e1, "different mid but the original turn is STILL RUNNING -> duplicate")

# --- deliberate repeat after an answer -------------------------------------
print("\ndeliberate repeat (must NOT be swallowed)")
fresh()
e1, _ = dd.claim("owner", "Weiter?", None, None, mid="a")
dd.settle(e1, {"reply": "ja"})
_e2, dup = dd.claim("owner", "Weiter?", None, None, mid="b")
ok(dup is None, "a client that minted a NEW mid gets a real turn for the same text")

# --- legacy client with no mid ---------------------------------------------
print("\nclient that sends no mid (app one OTA behind)")
fresh()
e1, _ = dd.claim("owner", "Weiter?", None, None)
dd.settle(e1, {"reply": "ja"})
_e2, dup = dd.claim("owner", "Weiter?", None, None)
ok(dup is e1, "no mid -> content hash inside the window is the fallback")
age(dd.WINDOW + 1)
_e3, dup2 = dd.claim("owner", "Weiter?", None, None)
ok(dup2 is None, "no mid, window elapsed -> a real turn again")

# --- scoping: a duplicate is per user, per card, per attachment ------------
print("\nscoping")
fresh()
e1, _ = dd.claim("owner", "status?", None, None)
_e2, dup = dd.claim("operator", "status?", None, None)
ok(dup is None, "same text from a DIFFERENT user is not a duplicate")
_e3, dup = dd.claim("owner", "status?", "card-7", None)
ok(dup is None, "same text scoped to a card is a different message")
fresh()
a1 = [{"name": "shot.jpg", "data": "AAAA"}]
a2 = [{"name": "shot.jpg", "data": "BBBBBB"}]
dd.claim("owner", "guck mal", None, a1)
_e, dup = dd.claim("owner", "guck mal", None, a2)
ok(dup is None, "same caption, DIFFERENT attachment bytes -> not a duplicate")
fresh()
dd.claim("owner", "guck mal", None, a1)
_e, dup = dd.claim("owner", "guck mal", None, a1)
ok(dup is not None, "same caption AND same attachment -> duplicate")

# --- a failed turn must not leave a hole ------------------------------------
print("\nfailed turn")
fresh()
e1, _ = dd.claim("owner", "mach das", None, None, mid="x")
dd.fail(e1)
_e2, dup = dd.claim("owner", "mach das", None, None, mid="x")
ok(dup is None, "after a failed turn the SAME send may run for real")
ok(e1["done"].is_set(), "fail() releases anyone already waiting on the claim")

# --- a duplicate waits for, and is released by, the original ----------------
print("\nduplicate released by the original turn")
fresh()
e1, _ = dd.claim("owner", "lange antwort", None, None, mid="q")
_e2, dup = dd.claim("owner", "lange antwort", None, None, mid="q")
threading.Timer(0.15, lambda: dd.settle(e1, {"reply": "fertig"})).start()
t0 = time.time()
got = dd.await_result(dup, 5)
ok(got == {"reply": "fertig"}, "the waiting duplicate is handed the real answer")
ok(time.time() - t0 < 4, "and it is released when the turn ends, not by its timeout")
fresh()
e1, _ = dd.claim("owner", "sehr lange antwort", None, None, mid="z")
_e2, dup = dd.claim("owner", "sehr lange antwort", None, None, mid="z")
ok(dd.await_result(dup, 0.05) is None,
   "still running when the wait runs out -> None (caller answers duplicate:true)")

# --- concurrency: exactly one claimer wins ----------------------------------
print("\nconcurrency")
fresh()
winners = []
lock = threading.Lock()


def race():
    _e, d = dd.claim("owner", "gleichzeitig", None, None, mid="same")
    if d is None:
        with lock:
            winners.append(1)


ts = [threading.Thread(target=race) for _ in range(24)]
for t in ts:
    t.start()
for t in ts:
    t.join()
ok(len(winners) == 1, "24 concurrent replays of one send -> exactly 1 turn (got %d)" % len(winners))

# --- the ledger does not grow without bound ---------------------------------
print("\nledger hygiene")
fresh()
for i in range(50):
    e, _ = dd.claim("owner", "msg %d" % i, None, None, mid="m%d" % i)
    dd.settle(e, {"reply": "r"})
age(dd.WINDOW + 1)
dd.claim("owner", "trigger gc", None, None, mid="last")
ok(len(dd._entries) == 1, "settled entries past the window are collected (%d left)" % len(dd._entries))
fresh()
running, _ = dd.claim("owner", "laeuft noch", None, None, mid="r1")
e, _ = dd.claim("owner", "etwas anderes", None, None, mid="r2")
dd.settle(e, {"reply": "r"})
age(dd.WINDOW + 1)
dd.claim("owner", "und noch was", None, None, mid="r3")
ok(running in dd._entries, "an UNFINISHED turn is never collected, however long it runs")

# --- the ROUTE, end to end -------------------------------------------------
# The unit checks above pin the ledger; this drives the thing the owner
# actually reported through routes_copilot.chat_post with the model turn
# stubbed, because the defect was never in the ledger - it was that nothing
# consulted one before running a turn and appending to the chat log.
print("\nPOST /chat, replayed (route level)")
fresh()
import json as _json                                   # noqa: E402
from cells.copilot import copilot as _copilot          # noqa: E402
from cells.copilot import routes_copilot as _routes    # noqa: E402

turns, chatlog, sent = [], [], []
_real_chat = _copilot.chat


def _stub_chat(user, message, **kw):
    turns.append(message)
    # what the real chat() does at the end of a board turn (copilot.py
    # _append_log) - the `you` entry is the visible half of the reported bug
    chatlog.append({"cls": "you", "text": message})
    chatlog.append({"cls": "bot", "text": "antwort %d" % len(turns)})
    return {"reply": "antwort %d" % len(turns), "actions": []}


class _Req(object):
    def _send(self, code, body):
        sent.append((code, _json.loads(body)))
        return None


_copilot.chat = _stub_chat
try:
    body = {"text": "Warum kommen meine Nachrichten doppelt an", "mid": "dup-1"}
    user = {"name": "owner", "role": "owner"}
    _routes.chat_post(_Req(), user, dict(body))
    _routes.chat_post(_Req(), user, dict(body))       # the replay
    ok(len(turns) == 1, "a replayed POST /chat runs ONE turn, not two (ran %d)" % len(turns))
    ok(len([m for m in chatlog if m["cls"] == "you"]) == 1,
       "and writes ONE `you` entry to the chat log")
    ok(len(sent) == 2 and sent[0][0] == 200 and sent[1][0] == 200,
       "both callers still get a 200 - a replay is not an error")
    ok(sent[1][1].get("duplicate") is True, "the replay's response is flagged duplicate")
    ok(sent[1][1].get("reply") == "antwort 1",
       "and carries the ORIGINAL turn's answer, so the replaying client is not left empty")

    # a genuinely new send must still get through the same route
    _routes.chat_post(_Req(), user, {"text": "Warum kommen meine Nachrichten doppelt an",
                                     "mid": "new-2"})
    ok(len(turns) == 2, "a fresh mid after the answer runs a real second turn")

    # a turn that RAISES must not settle the claim
    fresh()
    del turns[:]

    def _boom(user, message, **kw):
        turns.append(message)
        raise RuntimeError("copilot produced no output")

    _copilot.chat = _boom
    _routes.chat_post(_Req(), user, {"text": "kaputt", "mid": "e1"})
    ok(sent[-1][0] == 500, "a failing turn still answers 500")
    _copilot.chat = _stub_chat
    _routes.chat_post(_Req(), user, {"text": "kaputt", "mid": "e1"})
    ok(len(turns) == 2, "re-sending after a failure runs a real turn (no 10-minute hole)")

    # THE REGRESSION THIS SECTION EXISTS FOR: the turn succeeds but writing the
    # response fails, because the client that gave up on a 3-minute turn has
    # closed its socket. That lands in the SAME except: as a failed turn - and
    # if it dropped the claim, the replay already on its way would get a second
    # real turn, which is the original bug wearing a different hat.
    fresh()
    del turns[:]

    class _DeadSocket(object):
        def _send(self, code, body):
            raise IOError("[WinError 10053] connection aborted by the host")

    try:
        _routes.chat_post(_DeadSocket(), user, {"text": "lange antwort", "mid": "p1"})
    except Exception:
        pass
    _routes.chat_post(_Req(), user, {"text": "lange antwort", "mid": "p1"})
    ok(len(turns) == 1,
       "turn ran, response write failed, replay arrives -> still ONE turn (ran %d)" % len(turns))
    ok(sent[-1][1].get("reply") == "antwort 1",
       "and the replay is handed the answer the hung-up client never received")
finally:
    _copilot.chat = _real_chat

print("\n%d check(s) failed" % len(_fails) if _fails else "\nall chat_dedupe checks passed")
sys.exit(1 if _fails else 0)
