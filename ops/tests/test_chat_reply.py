# -*- coding: utf-8 -*-
"""MESSENGER-STYLE REPLY (owner 2026-09-25: "direkt auf Nachrichten antworten
wie in einer Messenger-App").

Through the real route + chat() on the one-shot path:
 1. POST /chat with reply_to persists it on the owner's row (sanitised:
    text excerpt, sender, seq) - the app draws the quote from it
 2. Henry's turn text carries the quoted message in front of the owner's
    words, so "ja, mach das" means THAT message
 3. junk reply_to (no text / not a dict) is dropped, the turn still runs
 4. a reply to a card's mirrored message (reply_to_card) keeps the quote on
    the owner's row too
Run: py -3.12 ops/tests/test_chat_reply.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-reply-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.copilot.chat import copilot
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)
from spine.agent import drivers
from spine.auth import auth
from spine.http import server
from spine.comms import notify

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


PROMPTS = []


class _In:
    def write(self, s):
        PROMPTS.append(s)
        return len(s)
    def flush(self): pass
    def close(self): pass


class _P:
    pid = 6161
    def __init__(self):
        self.stdin = _In()
        self.stdout = iter([json.dumps(e) + "\n" for e in [
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Mach ich."}],
                                              "usage": {"input_tokens": 5, "output_tokens": 5}}},
            {"type": "result", "result": "Mach ich.", "session_id": "s1",
             "usage": {"input_tokens": 5, "output_tokens": 5}, "total_cost_usd": 0.0}]])
        self.returncode = 0
    def poll(self): return 0
    def wait(self, timeout=None): return 0
    def kill(self): pass


class _Sub:
    PIPE, DEVNULL = -1, -3
    Popen = staticmethod(lambda *a, **k: _P())


copilot.subprocess = _Sub
from cells.copilot.routes import routes_copilot


class _H:
    def _send(self, code, body, *a, **k):
        self.sent = (code, json.loads(body))


def you_rows():
    return [m for m in copilot.history(OWNER)["messages"] if m.get("cls") == "you"]


print("messenger-style reply")
db.chat_clear()
h = _H()
routes_copilot.chat_post(h, {"name": OWNER, "role": "owner"},
                         {"text": "ja, mach das", "mid": "r1",
                          "reply_to": {"text": "Soll ich die LinkedIn-Zeile loeschen? " + "x" * 600,
                                       "by": "Henry", "seq": 41}})
r = (you_rows() or [{}])[-1]
q = r.get("reply_to") or {}
check(h.sent[0] == 200, "the turn ran (%r)" % (h.sent,))
check(q.get("by") == "Henry" and q.get("seq") == 41 and q.get("text", "").startswith("Soll ich"),
      "1. reply_to persisted on the owner's row (%r)" % {k: q.get(k) for k in ("by", "seq")})
check(len(q.get("text", "")) <= 300, "1. the quote is an excerpt (%d chars)" % len(q.get("text", "")))
turn = "".join(PROMPTS)
check('[Antwort auf Henry: "Soll ich die LinkedIn-Zeile' in turn and "ja, mach das" in turn,
      "2. Henry's turn carries the quoted message before the owner's words")

PROMPTS[:] = []
routes_copilot.chat_post(h, {"name": OWNER, "role": "owner"},
                         {"text": "und sonst?", "mid": "r2", "reply_to": {"by": "Henry"}})
r = (you_rows() or [{}])[-1]
check(h.sent[0] == 200 and "reply_to" not in r and "Antwort auf" not in "".join(PROMPTS),
      "3. a reply_to without text is dropped, the turn still runs")
routes_copilot.chat_post(h, {"name": OWNER, "role": "owner"},
                         {"text": "noch was", "mid": "r3", "reply_to": "kaputt"})
check(h.sent[0] == 200 and "reply_to" not in (you_rows() or [{}])[-1], "3. a non-dict reply_to is dropped")

# 4) reply to a card's mirrored message
from cells.engineer.cards import sessions
t = {"id": "card-77", "task": "Deploy", "lane": "working", "branch": "b", "repo": SANDBOX}
sessions.get_track = lambda tid: t if tid == "card-77" else None
auth.owns_card = lambda user, tr: True
sessions.reply_door = lambda tr, text: ("steer", None, None)
sessions.steer = lambda *a, **k: None
routes_copilot.chat_post(h, {"name": OWNER, "role": "owner"},
                         {"text": "nimm Port 8800", "mid": "r4", "reply_to_card": "card-77",
                          "reply_to": {"text": "Port 8799 ist belegt", "by": "Frage · Deploy", "seq": 50}})
r = (you_rows() or [{}])[-1]
check(r.get("card") == "card-77" and (r.get("reply_to") or {}).get("seq") == 50,
      "4. a reply to a card's message keeps the quote on the row it routes (%r)" % r.get("reply_to"))

print("PASS test_chat_reply" if not _fails else "FAIL test_chat_reply (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
