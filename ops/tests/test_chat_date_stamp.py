# -*- coding: utf-8 -*-
"""Headless test for the CHAT LOG'S DATE STAMP (copilot._append_log).

Owner, 2026-08-29, with a screenshot of his watch's SMS app: he wants date
separators between days. The log stored only time.strftime("%H:%M"), which
cannot tell a message sent today from one sent three weeks ago - a separator
was impossible to draw honestly.

The stamp is applied in _append_log, the ONE writer, rather than at the six-plus
call sites that build entries. That is the property most worth pinning: a future
call site that builds its own entry must get a date without knowing it has to
ask for one.

What is pinned here:
 1. every entry gains a date, whatever `cls` it is and whichever path built it
 2. the format is exactly "%Y-%m-%d" - the watch groups by STRING equality
    against its own SimpleDateFormat("yyyy-MM-dd"), so a drift here silently
    puts every message under its own separator
 3. a date already on the entry is NOT overwritten
 4. the CALLER's dict is not mutated - entries are built and reused by callers
    (the you/bot pair is one list), and stamping in place would be a side effect
    on someone else's object
 5. FORWARD-ONLY: entries written before this existed keep no date, and reading
    the log back does not invent one for them
 6. non-dict entries do not crash the writer

Self-sandboxing: temp events/settings/log, no model call, no network.
Run: py -3.12 ops/tests/test_chat_date_stamp.py
"""
import json, os, re, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-chatdate-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


USER = "owner"
TODAY = time.strftime("%Y-%m-%d")


def logged():
    return (copilot.history(USER) or {}).get("messages") or []


# -- 1./2. every entry gains a correctly formatted date --------------------
copilot._append_log(USER, [
    {"cls": "you", "text": "frage", "ts": "10:00"},
    {"cls": "bot", "text": "antwort", "ts": "10:00"},
    {"cls": "error", "text": "rotiert", "ts": "10:00"},
    {"cls": "act", "text": "aktion ausgefuehrt"},
])
msgs = logged()
check(len(msgs) == 4 and all(m.get("date") for m in msgs),
      "EVERY entry gets a date - you, bot, error and act alike, from the one "
      "writer rather than from each call site")
check(all(m.get("date") == TODAY for m in msgs),
      "and it is today's date")
check(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.get("date") or "") for m in msgs),
      "the format is exactly %Y-%m-%d - the watch groups by string equality "
      "against SimpleDateFormat(\"yyyy-MM-dd\")")

# -- 3. an explicit date survives -----------------------------------------
copilot._append_log(USER, [{"cls": "bot", "text": "importiert",
                            "ts": "09:00", "date": "2026-01-02"}])
check(logged()[-1].get("date") == "2026-01-02",
      "a date already on the entry is kept, never overwritten")

# -- 4. the caller's dict is untouched ------------------------------------
mine = {"cls": "you", "text": "meins", "ts": "11:00"}
copilot._append_log(USER, [mine])
check("date" not in mine,
      "the CALLER's dict is not mutated - _append_log copies before stamping")
check(logged()[-1].get("date") == TODAY,
      "while the STORED copy does carry the date")

# -- 5. forward-only: an old entry keeps no date --------------------------
# an entry that reached the store WITHOUT passing the stamping writer -
# what every row imported from the pre-stamp file looks like
db.chat_append(USER, [{"cls": "bot", "text": "alteintrag", "ts": "08:00"}])
old = logged()[-1]
check(old.get("text") == "alteintrag" and not old.get("date"),
      "an entry written before the stamp existed keeps NO date - reading the "
      "log back never invents one (the watch then draws no separator for it)")

# -- 6. a non-dict entry does not crash the writer ------------------------
try:
    copilot._append_log(USER, ["kaputt"])
    ok = True
except Exception as e:                                  # noqa: BLE001
    ok = False
    print("   raised:", e)
check(ok, "a non-dict entry is passed through instead of crashing the log write")

# -- the wear route carries it through ------------------------------------
from spine.http.routes import routes_wear as W

sent = {}


class _Stub:
    path = "/wear/chat"

    def _send(self, code, payload):
        sent["body"] = json.loads(payload)


W.wear_chat_get(_Stub(), {"role": "owner", "name": USER})
out = (sent.get("body") or {}).get("messages") or []
check(any(m.get("date") == TODAY for m in out),
      "GET /wear/chat passes the date through to the watch")
check(all(m.get("text") != "kaputt" for m in out),
      "and the malformed entry above is SKIPPED, not fatal - one bad line in "
      "the log file must not cost the watch its whole transcript")
check(all("date" in m for m in out),
      "the key is always present on the wire - '' for an undated line, so the "
      "client branches on a value rather than on a missing key")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHAT DATE STAMP CHECKS PASSED")
