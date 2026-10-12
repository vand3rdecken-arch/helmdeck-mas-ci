# -*- coding: utf-8 -*-
"""A HENRY TURN MEANS THE SAME THING ON EVERY ENGINE.

Owner 2026-10-12: "warum Opencode anders als Claude - muss ich dann fuer alle
verschiedene Module pflegen. Das ist nicht akzeptabel." The finding behind it:
with a DeepSeek / OpenCode model as Henry the `hands` action was parsed and
RETURNED but never executed - copilot._chat_via_opencode was a second, shorter
pipeline that stopped after parse/log/notify, while the claude path ran the
actions inside chat().

Now an engine only runs the turn; copilot._conclude_turn is the one end of it.
Pinned here by driving the REAL copilot.chat() down BOTH engines (fake claude
stream-json process; faked opencode_driver.run) with the SAME reply and
asserting the SAME consequences:
 1. the ```actions``` block is executed (a `hands` action reaches _run_action)
 2. the persisted bot row is the prose only (the fence is stripped)
 3. a <memory-save> sentinel is applied (it used to be dead on OpenCode too)
 4. the session pointer advances in the ENGINE'S OWN slot, never the other's
 5. the advisory door (allow_actions=False) refuses the action on both
Run: py -3.12 ops/tests/test_chat_engine_parity.py
"""
import json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-parity-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)

from spine.agent import drivers, opencode_driver, turnopts
from spine.auth import auth
from spine.http import server
from spine.comms import notify

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = lambda user, agent=False, immediate=False: None
copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


PROSE = "Ich starte die Haende."
TASK = "Pruefe den RDP-Server"
REPLY = (PROSE + "\n```actions\n" + json.dumps([{"type": "hands", "task": TASK, "why": "test"}]) + "\n```")

# ---- what ran: _run_action is the seam (chat() runs it on a thread) ----------
RAN = []
_ran_evt = threading.Event()


def _fake_run_action(a, user, role, owner_msg=""):
    RAN.append(dict(a))
    _ran_evt.set()
    return "Haende gestartet (fake)"


copilot._run_action = _fake_run_action

# ---- fake claude process -----------------------------------------------------
class _Stdin:
    def write(self, s):
        return len(s)

    def flush(self):
        pass

    def close(self):
        pass


class _Proc:
    def __init__(self, lines):
        self.stdin = _Stdin()
        self.stdout = iter(lines)
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


def _claude_lines(text):
    ev = [{"type": "system", "subtype": "init", "session_id": "claude-sess-1"},
          {"type": "stream_event", "event": {"type": "content_block_delta",
                                             "delta": {"type": "text_delta", "text": text}}},
          {"type": "assistant", "message": {"content": [{"type": "text", "text": text}],
                                            "usage": {"input_tokens": 100, "output_tokens": 5}}},
          {"type": "result", "result": text, "session_id": "claude-sess-1",
           "usage": {"input_tokens": 100, "output_tokens": 8}, "total_cost_usd": 0.001}]
    return [json.dumps(e) + "\n" for e in ev]


class _FakeSubprocess:
    PIPE = -1
    DEVNULL = -3
    Popen = staticmethod(lambda *a, **k: _Proc(_claude_lines(CURRENT["text"])))


copilot.subprocess = _FakeSubprocess
CURRENT = {"text": REPLY}

# ---- fake opencode engine ----------------------------------------------------
OC_CALLS = []


def _fake_oc_run(cfg, base, prompt):
    OC_CALLS.append({"cfg": cfg, "session_id": base.get("session_id")})
    return "ses_oc_1", CURRENT["text"], {"cost_usd": 0.002}


opencode_driver.run = _fake_oc_run


def last_bot():
    msgs = (copilot.history(OWNER) or {}).get("messages") or []
    bots = [m for m in msgs if m.get("cls") == "bot"]
    return (bots[-1].get("text") if bots else None)


def wait_ran(n, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and len(RAN) < n:
        time.sleep(0.05)


def run_engine(name, **kw):
    """One turn through chat() on the named engine."""
    turnopts.engine_for = (lambda mid: name)
    db.chat_clear()
    del RAN[:]
    return copilot.chat(OWNER, "starte die Haende", role="owner", **kw)


_real_engine_for = turnopts.engine_for

for engine in ("claude", "opencode"):
    print("engine: %s" % engine)
    CURRENT["text"] = REPLY
    out = run_engine(engine)
    wait_ran(1)
    check(len(RAN) == 1 and RAN[0].get("type") == "hands" and RAN[0].get("task") == TASK,
          "%s: the hands action reached _run_action (got %r)" % (engine, RAN))
    check(last_bot() == PROSE, "%s: persisted bot row is the prose, fence stripped (got %r)" % (engine, last_bot()))
    check("```" not in (out.get("reply") or ""), "%s: returned reply has no actions fence" % engine)
    sess = copilot._sessions()
    if engine == "claude":
        check(sess.get(copilot._skey(OWNER, None)) == "claude-sess-1" or any(v == "claude-sess-1" for v in sess.values()),
              "claude: session pointer advanced to the claude session")
        check(not any(v == "ses_oc_1" for v in sess.values()), "claude: the opencode id was not written anywhere")
    else:
        slot_vals = {k: v for k, v in sess.items() if v == "ses_oc_1"}
        check(len(slot_vals) == 1 and all(k.endswith("\x00opencode") for k in slot_vals),
              "opencode: session pointer advanced in the opencode-only slot (got %r)" % list(slot_vals))
        check(not any(v == "claude-sess-1" and k.endswith("\x00opencode") for k, v in sess.items()),
              "opencode: no claude uuid in the opencode slot")

    # memory sentinel: applied on both (dead on OpenCode before)
    from cells.copilot.chat import copilot_memory
    mem = "parity-%s" % engine
    CURRENT["text"] = 'Notiert.\n<memory-save name="%s">engine parity test</memory-save>' % mem
    out = run_engine(engine)
    check("memory-save" not in (last_bot() or ""), "%s: the memory sentinel block is stripped from the chat row (got %r)" % (engine, last_bot()))
    check(mem in (copilot_memory.db_notes() or {}),
          "%s: the <memory-save> was APPLIED (note %r in the db)" % (engine, mem))

    # advisory door: the action must NOT run, the refusal comes back
    CURRENT["text"] = REPLY
    out = run_engine(engine, allow_actions=False)
    time.sleep(0.3)
    check(not RAN, "%s: allow_actions=False runs nothing (ran %r)" % (engine, RAN))
    check("hands" in (out.get("refused") or []), "%s: the refusal names the dropped action (got %r)" % (engine, out.get("refused")))

# ---- Stop and takeover on an OpenCode turn (debt opencode-turn-not-interruptible)
print("opencode: Stop and takeover")
import types

_started = threading.Event()
_gate = threading.Event()
ABORTS = []
RUN_COUNT = [0]


def _blocking_oc_run(cfg, base, prompt):
    """A turn that runs until opencode_driver.cancel() is called for ITS session."""
    RUN_COUNT[0] += 1
    _started.set()
    _gate.wait(15)
    if ABORTS and ABORTS[-1] == base["id"]:
        return "ses_oc_1", "(turn cancelled by you)", {"usage": {}, "cost_usd": None, "canceled": True}
    return "ses_oc_1", "fertig", {"cost_usd": 0.001}


def _fake_cancel(tid):
    ABORTS.append(tid)
    _gate.set()
    return True


opencode_driver.run = _blocking_oc_run
opencode_driver.cancel = _fake_cancel
_real_fb = turnopts.fallback_model
turnopts.fallback_model = lambda user: "opencode/fallback-model"      # a retry WOULD run if cancel were mistaken for a poor reply
turnopts.engine_for = lambda mid: "opencode"


def start_turn(text):
    _started.clear(); _gate.clear(); del ABORTS[:]
    box = {}
    t = threading.Thread(target=lambda: box.update(out=copilot.chat(OWNER, text, role="owner")), daemon=True)
    t.start()
    _started.wait(10)
    return t, box


check(copilot.supersede(OWNER) is False, "supersede with no turn running is a no-op (False)")

# Stop
db.chat_clear(); RUN_COUNT[0] = 0
t, box = start_turn("lang laufende frage")
check(OWNER in copilot._running and copilot.live(OWNER).get("running"),
      "a running OpenCode turn is registered in _running (live().running)")
check(os.path.exists(os.path.join(SANDBOX, "state", "chat_turns.json"))
      and OWNER in json.load(open(os.path.join(SANDBOX, "state", "chat_turns.json"))),
      "restart_daemon's witness (chat_turns.json) lists the OpenCode turn")
check(copilot.cancel(OWNER) is True, "cancel() reaches the running OpenCode turn")
t.join(10)
check(not t.is_alive() and (box.get("out") or {}).get("reply") == "(stopped)", "Stop ends the turn with '(stopped)' (got %r)" % (box.get("out"),))
check(len(ABORTS) == 1 and ABORTS[0].startswith("henry-"), "the engine's own abort was called for Henry's session (got %r)" % ABORTS)
check(RUN_COUNT[0] == 1, "a cancelled turn does NOT retry on the fallback model (runs: %d)" % RUN_COUNT[0])
check(last_bot() is None, "a stopped turn persists no bot row (got %r)" % last_bot())
check(OWNER not in copilot._running, "the turn is unregistered afterwards")
_ct = os.path.join(SANDBOX, "state", "chat_turns.json")
check(OWNER not in (json.load(open(_ct)) if os.path.exists(_ct) else {}), "the restart witness is cleared afterwards")

# Takeover by a newer owner message
db.chat_clear(); RUN_COUNT[0] = 0
t, box = start_turn("erste frage")
check(copilot.supersede(OWNER) is True, "supersede() interrupts the running OpenCode turn")
t.join(10)
out1 = box.get("out") or {}
check(out1.get("superseded") is True and not out1.get("reply"), "the superseded turn ends quietly (got %r)" % (out1,))
check(last_bot() is None, "no half answer is persisted")
_pend = " ".join(copilot._pending_actions.get(copilot._skey(OWNER, None), []))
check("UNTERBROCHEN" in _pend and "erste frage" in _pend,
      "Henry's NEXT turn is told what was cut off (got %r)" % _pend[:80])
check(RUN_COUNT[0] == 1, "no fallback retry on a takeover (runs: %d)" % RUN_COUNT[0])

# a turn that FINISHED before the interrupt landed keeps its answer
_gate.set()
CURRENT["text"] = "fertig"
opencode_driver.run = _fake_oc_run
out2 = copilot.chat(OWNER, "zweite frage", role="owner")
check(out2.get("reply") == "fertig" and last_bot() == "fertig", "the next turn runs normally behind it (got %r)" % (out2.get("reply"),))

turnopts.fallback_model = _real_fb
turnopts.engine_for = _real_engine_for
print()
if _fails:
    print("FAIL test_chat_engine_parity (%d)" % len(_fails))
    sys.exit(1)
print("PASS test_chat_engine_parity - one end of turn, two engines")
