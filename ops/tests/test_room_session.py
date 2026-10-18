# -*- coding: utf-8 -*-
"""Headless test for the ROOM'S RESUMABLE HENRY SESSION (owner 2026-10-12).

Every room has an id and ONE resumable Henry conversation under it. The CLI is a
tiny python child printing real stream-json frames (an assistant call with usage,
a result with session_id); everything around it is the real code.

 1. A first turn runs fresh (no --resume, the WHOLE record in the prompt); the
    result's session_id becomes the room's pointer and the LAST assistant call's
    usage is the meter (not the summed result usage).
 2. The next turn resumes it (--resume <sid>) and carries only what the room
    said since Henry's last answer - incl. a reply quote.
 3. At the compaction mark the session is rotated: pointer + meter cleared, the
    next turn is fresh again (rebuilt from the record).
 4. A resume the CLI refuses falls back to a fresh turn once, never to silence.
 5. Only the OWNER's model pick counts, and it sticks as the room's model.

Self-sandboxing: temp DB, no network, no real CLI.
Run: py -3.12 ops/tests/test_room_session.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-roomsess-")

from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from cells.copilot.chat import rooms, room_henry, copilot
import spine.agent.drivers as drivers

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


for n, r in (("tien", "owner"), ("member", "client")):
    auth.create_user(n, "Correct-Horse-Battery-9", r, actor="test")
room = rooms.create("Familie", "tien", ["member"])
RID = room["id"]

ARGV = os.path.join(SANDBOX, "argv.json")
CHILD = os.path.join(SANDBOX, "fake_cli.py")
with open(CHILD, "w", encoding="utf-8") as f:
    f.write("import sys, json, os\n"
            "sys.stdin.read()\n"
            "fail = os.path.exists(%r)\n" % os.path.join(SANDBOX, "FAIL")
            + "if fail:\n"
              "    print(json.dumps({'type': 'result', 'is_error': True, 'result': 'No conversation found'}), flush=True)\n"
              "    sys.exit(1)\n"
              "print(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 10, 'cache_read_input_tokens': 4000}}}), flush=True)\n"
              "print(json.dumps({'type': 'result', 'is_error': False, 'result': 'Hallo.', 'session_id': os.environ.get('FAKE_SID', 'S1'),\n"
              "                  'usage': {'input_tokens': 99999}, 'modelUsage': {'claude-sonnet-5-5': {}}, 'total_cost_usd': 0.01}), flush=True)\n")

seen = []


def _cmd_line(argv):
    seen.append(list(argv))
    return [sys.executable, CHILD]


drivers._cmd_line = _cmd_line
room_henry._empty_cwd = lambda: SANDBOX

# ---- 1. fresh first turn
m1 = rooms.post(RID, "member", "@henry was gibt es zum Abendessen?")
hist = rooms.history(RID, "member")
prompt, resumed = room_henry.turn_prompt(rooms.get(RID), hist, "member", m1["text"], {})
check(not resumed and "VERLAUF" in prompt, "1. no session yet: the whole record rides in")
reply, raw = room_henry.run_claude("brief", prompt, model="sonnet", rid=RID, resume="")
check("--resume" not in seen[-1], "1. a first turn is not a resume")
check(room_henry.session_id(RID) == "S1", "1. the result's session_id is the room's pointer")
st = room_henry.stats(RID)
check(st["ctx_tokens"] == 4010, "1. the meter is the LAST call's fill (%r), not the summed result usage" % st["ctx_tokens"])
check(st["turns"] == 1 and st["ctx_window"], "1. the turn is folded into the room's stats")
check(room_henry.skey(RID) not in {u["name"] for u in auth.list_users()}, "1. the key can never be an account name")

# ---- 2. resumed turn = delta only
rooms.post(RID, "Henry", "Pasta.", by_kind="henry", extra={"to": "member"})
rooms.post(RID, "tien", "und als Nachtisch?", extra={"reply_to": {"text": "Pasta.", "by": "Henry"}})
m3 = rooms.post(RID, "member", "@henry bitte Vorschlaege")
hist = rooms.history(RID, "member")
prompt, resumed = room_henry.turn_prompt(rooms.get(RID), hist, "member", m3["text"], {})
check(resumed and "und als Nachtisch?" in prompt and "Abendessen" not in prompt,
      "2. a live session gets only what came after Henry's last answer")
check('Antwort auf Henry: "Pasta."' in prompt, "2. a reply quote reaches Henry")
room_henry.run_claude("brief", prompt, model="sonnet", rid=RID, resume=room_henry.session_id(RID))
check(seen[-1][seen[-1].index("--resume") + 1] == "S1", "2. the turn resumes the room's session")

# an errored Henry row never advanced the session -> not the "last answer"
rooms.post(RID, "Henry", "Ich konnte gerade nicht antworten", by_kind="henry", extra={"error": True})
d = room_henry.delta_prompt(rooms.get(RID), rooms.history(RID, "member"), "member", "x")
check("bitte Vorschlaege" in d and "Ich konnte gerade nicht" in d, "2. an error row does not cut the delta")

# ---- 3. rotation at the compaction mark
check(not room_henry.maybe_rotate(RID), "3. below the mark nothing rotates")
all_st = copilot._stats()
all_st[room_henry.skey(RID)]["ctx_tokens"] = 900_000
copilot._save_stats(all_st)
check(room_henry.maybe_rotate(RID), "3. at the mark the session rotates")
check(room_henry.session_id(RID) == "" and not room_henry.stats(RID)["ctx_tokens"],
      "3. pointer and meter are cleared (never the old session's number)")
prompt, resumed = room_henry.turn_prompt(rooms.get(RID), rooms.history(RID, "member"), "member", "x", {})
check(not resumed and "VERLAUF" in prompt, "3. the next turn is rebuilt from the record")

# ---- 4. a refused resume falls back to ONE fresh turn
os.environ["FAKE_SID"] = "S2"
room_henry.run_claude("brief", "p", model="sonnet", rid=RID, resume="")      # S2 is the pointer now
check(room_henry.session_id(RID) == "S2", "4. setup: a new session after the rotation")
open(os.path.join(SANDBOX, "FAIL"), "w").close()
calls = []
real = room_henry.run_claude


def flaky(system, prompt, **kw):
    calls.append(kw.get("resume", ""))
    if len(calls) == 2:
        os.remove(os.path.join(SANDBOX, "FAIL"))
    return real(system, prompt, **kw)


room_henry.run_claude = flaky
os.environ["FAKE_SID"] = "S3"
rooms.post(RID, "member", "@henry noch da?")
posted = room_henry.answer(RID, "member", "@henry noch da?", opts={})
room_henry.run_claude = real
check(calls[0] == "S2" and calls[1] == "", "4. resume tried, then ONE fresh retry: %r" % calls)
check(posted and not posted.get("error") and room_henry.session_id(RID) == "S3",
      "4. the answer lands and the pointer moved to the new session")

# ---- 5. model: only the owner's pick counts
base = room_henry.pick_model(RID, "member", "", "x")
check(room_henry.pick_model(RID, "member", "haiku", "x") == base and not room_henry.stats(RID)["model"],
      "5. a member's pick is ignored and sticks to nothing")
picked = room_henry.pick_model(RID, "tien", "haiku", "x")
check(picked and room_henry.stats(RID)["model"] == picked, "5. the owner's pick sticks as the room's model: %r" % picked)
check(room_henry.pick_model(RID, "member", "", "x") == picked, "5. and then every turn of the room uses it")

print()
print("ROOM SESSION: %s" % ("PASS" if not _fails else "FAIL - %d" % len(_fails)))
sys.exit(1 if _fails else 0)
