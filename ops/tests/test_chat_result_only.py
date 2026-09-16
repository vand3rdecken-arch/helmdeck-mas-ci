# -*- coding: utf-8 -*-
"""Henry's persisted reply is the RESULT, not the running commentary.

Owner 2026-09-15 17:20: "ich will halt nicht diese Nachricht sehen, nur
Ergebnisse". The FIRST-WORD law (board-copilot.md) makes Henry announce every
tool round with one prose sentence ("Moment, ich schau kurz...") - it streams
live and that is its whole job. copilot.chat() then joined EVERY text delta of
the turn into the bot row, so the announcement sat glued to the answer, often
without a space ("Board-Stand.macOS ist durch"), and read like a leftover
thought that should have vanished with the live preview.

Pinned here, through the REAL copilot.chat() fold (fake stream-json process,
no model, no network):
 1. text -> tool_use -> tool_result -> text: only the text AFTER the last
    tool call is persisted; the preamble is gone from the chat log
 2. a turn without tools keeps its full prose (nothing to drop)
 3. a tail that is only a bare actions block falls back to the full text, so
    the answer never comes out empty (the 2026-09-14 12:47 regression)
 4. hands._land hands Henry the WHOLE report, not a 700-char stump
Run: py -3.12 ops/tests/test_chat_result_only.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-resultonly-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot
copilot.ROOT = SANDBOX

from spine.agent import drivers
from spine.auth import auth
from spine.http import server

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = lambda user: None
copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
from spine.comms import notify
notify.push_fcm = lambda *a, **k: True

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


SENT = []                 # everything chat() writes to the process - the turn itself


class _FakeStdin:
    def write(self, s):
        SENT.append(s)
        return len(s)

    def flush(self):
        pass

    def close(self):
        pass


class _FakeProc:
    def __init__(self, lines):
        self.stdin = _FakeStdin()
        self.stdout = iter(lines)
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


SCRIPT = {"lines": []}


def _text(t):
    return [{"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "text_delta", "text": t}}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": t}],
                                              "usage": {"input_tokens": 100, "output_tokens": 5}}}]


def _tool():
    return [{"type": "assistant", "message": {"content": [
                 {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}],
             "usage": {"input_tokens": 100, "output_tokens": 5}}},
            {"type": "user", "message": {"content": [
                 {"type": "tool_result", "tool_use_id": "t1", "content": "a b c"}]}}]


def _result(t):
    return [{"type": "result", "result": t, "session_id": "sess-test",
             "usage": {"input_tokens": 100, "output_tokens": 8}, "total_cost_usd": 0.001}]


def _fake_popen(*a, **k):
    lines = [{"type": "system", "subtype": "init", "session_id": "sess-test"}] + SCRIPT["lines"]
    return _FakeProc([json.dumps(e) + "\n" for e in lines])


class _FakeSubprocess:
    PIPE = -1
    DEVNULL = -3
    Popen = staticmethod(_fake_popen)


copilot.subprocess = _FakeSubprocess


def last_bot():
    msgs = (copilot.history(OWNER) or {}).get("messages") or []
    bots = [m for m in msgs if m.get("cls") == "bot"]
    return (bots[-1].get("text") if bots else None)


print("result-only reply")

# 1) preamble -> tool -> answer: only the answer is kept
db.chat_clear()
PRE, ANS = "Moment, ich schau kurz auf den Board-Stand.", "macOS ist durch, nichts zu tun."
SCRIPT["lines"] = _text(PRE) + _tool() + _text(ANS) + _result(PRE + ANS)
out = copilot.chat(OWNER, "was nun", role="owner")
check(out.get("reply") == ANS, "reply is the prose after the last tool call (got %r)" % out.get("reply"))
check(last_bot() == ANS, "persisted bot row = answer only (got %r)" % last_bot())
check(PRE not in (last_bot() or ""), "the FIRST-WORD preamble is not in the chat log")

# 2) two tool rounds, two preambles: still only the final prose
db.chat_clear()
SCRIPT["lines"] = (_text("Schau mir den Screenshot an.") + _tool() + _text("Gefunden, ich pruef noch die Karte.")
                   + _tool() + _text("Root Cause: RNW-Textfeld.") + _result("x"))
out = copilot.chat(OWNER, "bug", role="owner")
check(last_bot() == "Root Cause: RNW-Textfeld.", "two rounds -> last prose only (got %r)" % last_bot())

# 3) no tools: the whole prose survives
db.chat_clear()
SCRIPT["lines"] = _text("Direkte Antwort ") + _text("in zwei Blöcken.") + _result("x")
copilot.chat(OWNER, "hi", role="owner")
check(last_bot() == "Direkte Antwort in zwei Blöcken.", "turn without tools keeps its full prose (got %r)" % last_bot())

# 4) tail is a bare actions block: fall back to the full text, never an empty answer
db.chat_clear()
ACT = "```actions\n[]\n```"
SCRIPT["lines"] = _text("Ich steuere die Karte an.") + _tool() + _text(ACT) + _result("x")
out = copilot.chat(OWNER, "go", role="owner")
check((last_bot() or "").strip() != "", "bare actions tail -> full text fallback, reply not empty (got %r)" % last_bot())

# 4b) the owner's question answered BEFORE the tool round is content, not a
#     preamble (2026-09-15 17:27 "This message was ignored"): it stays, as its
#     own paragraph, the short closing status after it too
db.chat_clear()
LONG = ("Alle 4 DMs sind raus. Zur Frage: die Hände-Karte läuft unter Claude Codes eigenem "
        "Auto-Mode-Sicherheits-Layer, der bestimmte UI-Klicks als reale Transaktion einstuft - "
        "bypassPermissions hat genau diese Zusatzsperre aufgehoben. Der Log-Write scheiterte, weil "
        "card_tool_guard Hände-Agents auf ihren Scratch-Ordner beschränkt.")
assert len(LONG) > 200
SCRIPT["lines"] = _text(LONG) + _tool() + _tool() + _text("Log ist nachgetragen.") + _result("x")
copilot.chat(OWNER, "why restrictions", role="owner")
check(last_bot() == LONG + "\n\nLog ist nachgetragen.",
      "a long pre-tool answer survives, paragraph-separated from the closing line (got %r)" % (last_bot() or "")[:80])
db.chat_clear()
SCRIPT["lines"] = (_text("Moment, ich schau kurz.") + _tool() + _text(LONG) + _tool()
                   + _text("Fertig.") + _result("x"))
copilot.chat(OWNER, "mixed", role="owner")
check(last_bot() == LONG + "\n\nFertig.", "short preamble dropped, long middle block kept (got %r)" % (last_bot() or "")[:60])

# 4c) NULL-RESULT guard (2026-09-16 10:54 "Henry hat nicht geantwortet: copilot
#     produced no output"): a resumed process first flushes the CLI's OWN
#     synthetic turn ("Continue from where you left off." -> "No response
#     requested.", zero usage) - that result frame is not ours; keep reading
db.chat_clear()
SYN = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "No response requested."}],
                                         "usage": {"input_tokens": 0, "output_tokens": 0}}},
       {"type": "result", "result": "No response requested.", "session_id": "sess-test",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}}]
SCRIPT["lines"] = SYN + _text("Echte Antwort.") + _result("Echte Antwort.")
out = copilot.chat(OWNER, "hallo", role="owner")
check(last_bot() == "Echte Antwort.", "synthetic zero-usage result skipped, real answer persisted (got %r)" % last_bot())
db.chat_clear()
SCRIPT["lines"] = [{"type": "result", "result": "", "session_id": "sess-test", "usage": {}}] + _text("Nach Notification.") + _result("x")
copilot.chat(OWNER, "hallo", role="owner")
check(last_bot() == "Nach Notification.", "empty zero-usage frame (task-notification turn) skipped too (got %r)" % last_bot())

# 4d) the keepalive ping applies the same guard, else the real "ok" result
#     stays unread and the owner's next turn ends in 0.5s with a stale "ok"
lines = [json.dumps(x) + "\n" for x in [{"type": "result", "result": "", "usage": {}},
                                         {"type": "result", "result": "ok", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100}},
                                         {"type": "result", "result": "STALE", "usage": {"input_tokens": 9}}]]
fp = _FakeProc(lines)
check(copilot._ping_process(fp) is True, "ping answered")
fp2 = _FakeProc(lines)
copilot._ping_process(fp2)
rest = list(fp2.stdout)
check(len(rest) == 1 and "STALE" in rest[0], "ping consumed exactly the null frame + its own result, nothing more (%d left)" % len(rest))

# 5) hands._land: Henry sees the whole report
from cells.copilot.chat import hands
big = "FAILED\n" + "\n".join("- line %02d: %s" % (i, "x" * 60) for i in range(40))
assert len(big) > 700
hid = "test-hands-1"
with hands._lock:
    hands._tasks[hid] = {"title": "t", "status": "failed", "since": 0, "updated": 0, "detail": "",
                         "result": "", "pid": 0, "user": OWNER, "skey": copilot._skey(OWNER, None), "card": None}
copilot._append_log = lambda *a, **k: None
hands._land(hid, "failed", big, 3)
with copilot._pending_lock:
    pend = list(copilot._pending_actions.get(copilot._skey(OWNER, None)) or [])
check(pend and "line 39" in pend[-1], "hands report reaches Henry uncut (%d chars)" % len(pend[-1] if pend else ""))

# 5b) ...and the FOLD into the next turn keeps it whole too (2026-09-16 18:31:
#     _land handed over 4000 chars, the turn assembly cut every item back to
#     400 - Henry read "...once Apple a" and never the "Pending Developer
#     Release" bullet three lines further down, then answered from a two-week
#     old memory). Pinned through the REAL copilot.chat() turn assembly.
db.chat_clear()
del SENT[:]
SCRIPT["lines"] = _text("Gelesen.") + _result("Gelesen.")
copilot.chat(OWNER, "und?", role="owner")
turn = "".join(SENT)
check("ERGEBNIS deiner Aktionen" in turn, "pending hands result is folded into the next turn")
check("line 39" in turn, "the END of the hands report is in the turn, not a 400-char stump (turn has %d chars)" % len(turn))
with copilot._pending_lock:
    check(not copilot._pending_actions.get(copilot._skey(OWNER, None)), "told exactly once - pending drained")


# 6) HENRY'S OWN BACKGROUND AGENTS (owner 2026-09-16 18:51 "Arbeitet aber keine
#    visuelle Rueckmeldung"): an Agent launched with run_in_background from
#    Henry's warm process worked for 9+ minutes and the chat line showed
#    nothing - followups knew broker + hands only. Pinned through the real
#    copilot.chat() pump, the ping reader and _persist_drop.
from cells.copilot.chat import henry_bg
SK = copilot._skey(OWNER, None)


def _agent_launch(uid, desc):
    return [{"type": "assistant", "message": {"content": [
                 {"type": "tool_use", "id": uid, "name": "Agent",
                  "input": {"description": desc, "subagent_type": "Explore", "run_in_background": True,
                            "prompt": "find the onboarding code"}}],
             "usage": {"input_tokens": 100, "output_tokens": 5}}},
            {"type": "user", "message": {"content": [
                 {"type": "tool_result", "tool_use_id": uid,
                  "content": "Async agent launched successfully. agentId: abc"}]}}]


def _bg():
    return (copilot.history(OWNER) or {}).get("followups") or {}


db.chat_clear()
SCRIPT["lines"] = _text("Ich lass recherchieren.") + _agent_launch("tu_bg1", "Explore onboarding code") + _text("Dauert zwei Minuten.") + _result("x")
copilot.chat(OWNER, "verbessere onboarding", role="owner")
t = _bg().get("bg:tu_bg1")
check(t is not None and t.get("status") == "running", "a run_in_background Agent shows on the chat bg line as running (got %r)" % t)
check(t and t.get("title") == "Explore onboarding code", "bg task carries the Agent's description as title")

# the CLI reports the hand-back BETWEEN turns as a system/task_notification
# frame - the ping is the only stdout reader then; it must fold it
lines = [json.dumps(x) + "\n" for x in [
    {"type": "system", "subtype": "task_notification", "tool_use_id": "tu_bg1", "status": "completed",
     "summary": "Found 3 files: onboarding.tsx, demo_seed.py, chat panel"},
    {"type": "result", "result": "ok", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100}}]]
check(copilot._ping_process(_FakeProc(lines), skey=SK) is True, "ping still answers with the notification in front")
t = _bg().get("bg:tu_bg1")
check(t and t.get("status") == "completed" and "onboarding.tsx" in (t.get("result") or ""),
      "task_notification read by the ping closes the task with its summary (got %r)" % t)

# same frame arriving INSIDE a turn (the pump) closes it too
db.chat_clear()
SCRIPT["lines"] = _text("Los.") + _agent_launch("tu_bg2", "Second look") + _result("x")
copilot.chat(OWNER, "nochmal", role="owner")
check((_bg().get("bg:tu_bg2") or {}).get("status") == "running", "second agent registered")
SCRIPT["lines"] = [{"type": "system", "subtype": "task_notification", "tool_use_id": "tu_bg2",
                    "status": "failed", "summary": "agent hit an error"}] + _text("Er ist gescheitert.") + _result("x")
copilot.chat(OWNER, "und?", role="owner")
check((_bg().get("bg:tu_bg2") or {}).get("status") == "failed", "in-turn task_notification closes it with the CLI's status")

# a sync Agent (no run_in_background, plain result) is NOT a background task
SCRIPT["lines"] = _text("Kurz.") + [{"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "tu_sync", "name": "Agent", "input": {"description": "quick check", "prompt": "x"}}],
    "usage": {"input_tokens": 1, "output_tokens": 1}}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_sync", "content": "the answer is 42"}]}}] + _result("x")
copilot.chat(OWNER, "sync", role="owner")
check("bg:tu_sync" not in _bg(), "a synchronous Agent result never becomes a bg line")

# the process dies (_persist_drop) -> its running agents are closed as failed WITH the reason, never left running
SCRIPT["lines"] = _text("Los.") + _agent_launch("tu_bg3", "Dies with the port") + _result("x")
copilot.chat(OWNER, "drei", role="owner")
check((_bg().get("bg:tu_bg3") or {}).get("status") == "running", "third agent registered")


class _DeadProc:
    pid = 4242

    def kill(self):
        pass

    def poll(self):
        return None


with copilot._persist_lock:
    copilot._persist[SK] = {"p": _DeadProc(), "key": ("m", "p")}
copilot._persist_drop(SK)
t = _bg().get("bg:tu_bg3")
check(t and t.get("status") == "failed" and "beendet" in (t.get("result") or ""),
      "_persist_drop reconciles: open agents -> failed with the reason (got %r)" % t)
check(not henry_bg.running_ids(SK), "nothing left running after the drop")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("result-only reply: all pinned - PASS")
