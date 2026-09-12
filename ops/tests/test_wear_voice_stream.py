# -*- coding: utf-8 -*-
"""Headless test for the WATCH'S SPOKEN CATCH-UP PATH (GET /wear/voice).

The defect this pins (owner, 2026-09-02: "Stimme aktivieren ist ziemlich
broken"): the watch only ever spoke a reply that came back inside POST
/wear/talk's own HTTP response. Every other way an answer reaches the wrist -
a turn that outlived the request, a turn started on the phone or the glasses, a
reply that landed with the display off - arrives over GET /wear/chat, which
carried no audio at all and no way to name a line. See
ops/docs/backlog/wear-voice-stream-playback/README.md.

What is pinned here:
 1. a speakable line carries a `key` on /wear/chat, and a non-speakable one
    (you / card / act) does not - presence of the key IS the "can be spoken"
    marker the watch keys on
 2. the SAME key identifies the line on both routes, so the watch can hand back
    what /wear/chat gave it and be understood
 3. /wear/voice renders that line, ask-block stripped and bounded
 4. NO HISTORY: a key that is no longer the newest speakable line renders
    NOTHING, and the current key comes back instead (the backlog card's
    Leitplanke 2, enforced server-side rather than trusted to the client)
 5. the identity is stable across reads and separates two otherwise-identical
    messages sent at different times
 6. a talk reply claims the BOT line even when a `pm` line lands in the same
    instant - the pm must stay unclaimed or the watch would swallow it
 7. `voice: false` on /wear/talk renders no clip at all (the toggle defaults to
    OFF on the watch, and the old unconditional render paid a speech round trip
    per turn for a clip the wrist threw away) while still naming the line
 8. the usual door checks: no key -> 400, client role -> 403

Self-sandboxing: temp db/events/settings/chatlog, no model call, no network -
voice.render_b64 is replaced by a stub that records what it was asked to say.
Run: py -3.12 ops/tests/test_wear_voice_stream.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-wearvoice-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot

from spine.http.routes import routes_wear as W
from spine.media import voice as voice_mod

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


USER = "owner"
OWNER = {"name": USER, "role": "owner"}
CLIENT = {"name": "kunde", "role": "client"}


# ---------------------------------------------------------------- test doubles

class Handler:
    """The two attributes the routes actually touch: `path` (they read the query
    off it, exactly as /stream/wait does) and `_send`."""

    def __init__(self, path="/wear/voice"):
        self.path = path
        self.status = None
        self.body = None

    def _send(self, status, body):
        self.status = status
        self.body = body

    def json(self):
        return json.loads(self.body or "{}")


_rendered = []


def fake_render_b64(text, voice=""):
    """Stands in for the speech service - records the TEXT it was asked to say,
    which is the half this test can assert. Returns the same {id,mime,b64} shape
    voice.render_b64 does."""
    _rendered.append(text)
    return {"id": "stub", "mime": "audio/mpeg", "b64": "AAAA"}


voice_mod.render_b64 = fake_render_b64


def get_voice(key):
    h = Handler("/wear/voice?key=" + key if key is not None else "/wear/voice")
    W.wear_voice_get(h, OWNER)
    return h


def chat_rows():
    h = Handler("/wear/chat")
    W.wear_chat_get(h, OWNER)
    return h.json().get("messages") or []


# ------------------------------------------------------------------- the log

ASK = ('<helmdeck-ask>\n{"questions": [{"question": "Weiter?", '
       '"header": "Weiter", "options": [{"label": "Ja", "description": "los"}]}]}\n'
       '</helmdeck-ask>')

copilot._append_log(USER, [
    {"cls": "you", "text": "Was ist offen?", "ts": "10:00", "date": "2026-09-02"},
    {"cls": "bot", "text": "Zwei Karten warten auf dich.\n" + ASK,
     "ts": "10:01", "date": "2026-09-02"},
    {"cls": "card", "text": "Worker fragt nach", "kind": "question",
     "card": "c1", "cardName": "Karte", "ts": "10:02", "date": "2026-09-02"},
    {"cls": "act", "text": "action: start c1", "ts": "10:03", "date": "2026-09-02"},
])

print("1. /wear/chat marks exactly the speakable lines")
rows = chat_rows()
by_text = {r["text"][:12]: r for r in rows}
check(len(rows) == 4, "all four classes still render (%d rows)" % len(rows))
bot_row = next((r for r in rows if r["text"].startswith("Zwei Karten")), None)
check(bot_row is not None and bot_row.get("key"), "the bot line carries a key")
check(not by_text.get("Was ist offe", {}).get("key"), "the owner's own line has no key")
check(not by_text.get("Worker fragt", {}).get("key"), "a mirrored card line has no key")
check(not by_text.get("action: sta", {}).get("key")
      and not by_text.get("action: star", {}).get("key"),
      "an action receipt has no key")

print("2. the key names the SAME line on both routes")
bot_key = bot_row["key"]
newest = W._wear_newest_speakable(USER)
check(newest is not None and W._wear_msg_key(newest) == bot_key,
      "the newest speakable line hashes to the key /wear/chat published")

print("3. /wear/voice renders that line")
_rendered[:] = []
h = get_voice(bot_key)
check(h.status == 200, "200 for the current key (got %s)" % h.status)
check(bool(h.json().get("voice")), "a clip comes back")
check(h.json().get("key") == bot_key, "the response names the line it spoke")
check(len(_rendered) == 1, "exactly one render was asked for")
spoken = _rendered[0] if _rendered else ""
check("helmdeck-ask" not in spoken and "{" not in spoken,
      "the ask-block never reaches the speech service: %r" % spoken[:60])
check(spoken.startswith("Zwei Karten warten"), "the prose is what is spoken")

print("4. NO HISTORY - a stale key renders nothing")
copilot._append_log(USER, [
    {"cls": "bot", "text": "Jetzt ist alles fertig.", "ts": "10:05",
     "date": "2026-09-02"},
])
_rendered[:] = []
h = get_voice(bot_key)
check(h.status == 200, "a stale key is not an error (got %s)" % h.status)
check("voice" not in h.json(), "the superseded answer is NOT spoken again")
check(not _rendered, "and nothing was rendered for it")
new_key = h.json().get("key")
check(bool(new_key) and new_key != bot_key,
      "the CURRENT key comes back so a late watch knows what to ask for")

_rendered[:] = []
h = get_voice(new_key)
check(bool(h.json().get("voice")), "the newest answer does play")
check(_rendered and _rendered[0] == "Jetzt ist alles fertig.",
      "and it is the newest text: %r" % (_rendered[0] if _rendered else None))

print("5. identity is stable, and separates two identical sentences")
newest = W._wear_newest_speakable(USER)
check(W._wear_msg_key(newest) == W._wear_msg_key(newest), "hashing twice agrees")
a = {"cls": "bot", "text": "Fertig.", "ts": "10:06", "date": "2026-09-02"}
b = {"cls": "bot", "text": "Fertig.", "ts": "10:07", "date": "2026-09-02"}
check(W._wear_msg_key(a) != W._wear_msg_key(b),
      "the same sentence a minute later is a DIFFERENT line")
check(W._wear_msg_key(a) != W._wear_msg_key(dict(a, cls="pm")),
      "the same text from a different class is a different line")

print("6. a talk reply claims the BOT line, not a pm that raced it")
copilot._append_log(USER, [
    {"cls": "pm", "text": "Lane fertig - eine Karte wartet.", "ts": "10:08",
     "date": "2026-09-02"},
])
bot_only = W._wear_newest_speakable(USER, only=("bot",))
any_voice = W._wear_newest_speakable(USER)
check(bot_only is not None and bot_only.get("text") == "Jetzt ist alles fertig.",
      "only=('bot',) skips the newer pm line")
check(any_voice is not None and any_voice.get("cls") == "pm",
      "the default picks up the pm line - Henry's proactive half is speakable")
check(W._wear_msg_key(bot_only) != W._wear_msg_key(any_voice),
      "so the pm stays unclaimed and can still be spoken")

print("7. door checks")
h = Handler("/wear/voice")
W.wear_voice_get(h, OWNER)
check(h.status == 400, "no key -> 400 (got %s)" % h.status)
h = Handler("/wear/voice?key=" + new_key)
W.wear_voice_get(h, CLIENT)
check(h.status == 403, "a client role is refused (got %s)" % h.status)
_rendered[:] = []
h = get_voice("0123456789abcdef")
check(h.status == 200 and "voice" not in h.json() and not _rendered,
      "an invented key renders nothing")

print("8. /wear/talk honours the watch's voice switch")


def fake_chat(user, msg, **kw):
    copilot._append_log(user, [
        {"cls": "you", "text": msg, "ts": "11:00", "date": "2026-09-02"},
        {"cls": "bot", "text": "Alles ruhig.\n" + ASK, "ts": "11:00",
         "date": "2026-09-02"},
    ])
    return {"reply": "Alles ruhig.\n" + ASK, "refused": []}


copilot.chat = fake_chat

_rendered[:] = []
h = Handler("/wear/talk")
W.wear_talk_post(h, OWNER, {"message": "Wie sieht es aus?", "voice": False})
out = h.json()
check(h.status == 200, "talk answers 200 (got %s)" % h.status)
check("voice" not in out, "voice:false renders NO clip")
check(not _rendered, "and costs no speech round trip")
check(bool(out.get("voiceKey")), "but still names the line it just wrote")
check(out["voiceKey"] == W._wear_msg_key(W._wear_newest_speakable(USER, only=("bot",))),
      "and that name is the one /wear/chat will publish for it")

_rendered[:] = []
h = Handler("/wear/talk")
W.wear_talk_post(h, OWNER, {"message": "Und jetzt?", "voice": True})
out = h.json()
check(bool(out.get("voice")), "voice:true still returns the inline clip")
check(len(_rendered) == 1, "exactly one render")
check(out.get("voiceKey") and out["voiceKey"] != bot_key,
      "with the key of THIS reply")

print("9. the claimed key is what silences the refresh path")
rows = chat_rows()
newest_row_key = next((r["key"] for r in reversed(rows) if r.get("key")), None)
check(newest_row_key == out["voiceKey"],
      "the watch sees the SAME key it already claimed -> it does not speak twice")

print("10. the route is actually reachable over HTTP")
# The SERVER'S OWN dispatch expression, not a paraphrase of it: do_GET cuts the
# query off with path.split("?")[0] and then looks the result up in this table
# (spine/http/server.py). Pinned together because the two halves fail as one -
# a route registered under the full "/wear/voice?key=..." would never match, and
# the watch would see a 404 with no hint that the handler exists.
p = "/wear/voice?key=" + new_key
check(p.split("?")[0] in W.GET_ROUTES, "GET /wear/voice with a query dispatches")
check(W.GET_ROUTES[p.split("?")[0]] is W.wear_voice_get, "and lands on the handler")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("RESULT: PASS")
