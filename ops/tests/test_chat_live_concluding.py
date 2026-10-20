# -*- coding: utf-8 -*-
"""/chat/live says running until the turn CONCLUDED (2026-10-20).

Owner 2026-10-19 21:18: "Ich schau, ob die Hands fertig sind." stayed on screen
under the spinner until the next answer. The engine's `finally` pops _running
BEFORE _conclude_turn persists the answer, so live() said running=false in a
gap where the answer was not stored yet - the app could not tell "not
persisted yet" from "this turn persists nothing" and kept the streamed text.

Drives the REAL copilot.chat wrapper and the REAL copilot.live(); only the turn
body (_chat) is a stand-in that reproduces the gap: register like a turn, end
the engine (pop _running), then - still inside chat() - "persist".

SELF-SANDBOXING (DATA_ROOT -> temp). Run: py -3.12 ops/tests/test_chat_live_concluding.py
"""
import os, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-concl-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX

from cells.copilot.chat import copilot as cp   # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


seen = {}


def turn(user, message, *a, **k):
    # register exactly like the engines do
    cp._running[user] = object()
    cp._concluding[user] = threading.get_ident()
    cp._turn_started[user] = 1.0
    seen["during"] = cp.live(user)["running"]
    cp._running.pop(user, None)              # the engine's finally: BEFORE persisting
    seen["gap"] = cp.live(user)["running"]   # _conclude_turn would persist here
    if message == "boom":
        raise RuntimeError("turn failed")
    return {"reply": "ok"}


cp._chat = turn

cp.chat("owner", "hi")
check(seen["during"] is True, "running while the engine runs")
check(seen["gap"] is True, "STILL running after the engine stopped, before the answer is persisted")
check(cp.live("owner")["running"] is False, "not running once chat() returned - the answer is in")

try:
    cp.chat("owner", "boom")
except RuntimeError:
    pass
check(cp.live("owner")["running"] is False, "a failed turn concludes too - never stuck 'running'")

# a message queued behind the turn lock (another thread) must not end the
# running turn's mark when it returns
cp._concluding["owner"] = 12345              # the running turn's thread
cp._chat = lambda user, message, *a, **k: {"reply": "queued, did not register"}
cp.chat("owner", "second")
check(cp.live("owner")["running"] is True, "another call returning never clears the running turn's mark")
cp._concluding.pop("owner", None)
check(cp.live("owner")["running"] is False, "...which its own call clears")

print("RESULT:", "PASS" if not _fails else "FAIL (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
