# -*- coding: utf-8 -*-
"""Headless test for the HENRY REPLY PUSH - the reverse leg of the one-inbox
decree (owner report 2026-08-29 18:09: "Henrys Chat-Antworten loesen KEINE
Notification auf Watch/Handy aus - nur Worker-Karten-Events tun das").

The card mirror carries a CARD's news into the Henry chat; nothing carried the
chat's own news back out. Henry finished a turn, wrote the answer into the
transcript, and the owner found out by opening the app on the off chance.

What is pinned here, in the order the news travels:

 1. the summary a notification can carry: no <helmdeck-ask> block, no markdown,
    one line, clipped on a word boundary and SAYING it was clipped
 2. a finished Henry turn pushes - sealed, trackless, kind "chat" (which is what
    the app routes into the Henry chat instead of the dashboard)
 3. PRESENCE is the whole quiet policy: an app the owner can actually see
    absorbs the answer, so no buzz; nothing visible buzzes every paired device
 4. quiet hours do NOT hold it: this is SOLICITED (he typed the question minutes
    ago), unlike the autonomous overnight work quiet hours exist to mute
 5. a door whose own response IS the delivery (the watch, the glasses) does not
    push - but the transcript is written either way, exactly like the mirror's
    core property: suppressing a BUZZ must never suppress the INBOX
 6. a CARD-scoped Henry turn does not push: that reply lands in the card's
    timeline, and a notification promising the Henry chat would open a chat that
    never mentions it
 7. worker-card notifications are untouched (notify.card_event still owns them)

Self-sandboxing: temp db/events/settings/chatlog/sessions/stats + a FAKE claude
process (stream-json lines, no model, no network, no cost). The real
copilot.chat() runs - that is the point: the hook sits at the line where an
answer becomes news, and a test that stubbed it would prove nothing.
Run: py -3.12 ops/tests/test_chat_push.py
"""
import contextlib, io, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-chatpush-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, copilot_stats
from cells.copilot.routes import routes_copilot
# Every file this turn writes goes to the sandbox. copilot_runs/ and the
# attachment dir hang off copilot.ROOT; the other three are module constants
# resolved at import. Miss one and a test turn edits the owner's live PM
# session - the class of accident that once wiped real recordings.
copilot.ROOT = SANDBOX

from spine.agent import drivers
from spine.auth import auth
from spine.comms import notify, presence

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
USER = {"name": OWNER, "role": "owner"}

# Never spawn a real model. argv_form_safe(False) takes the ONE-SHOT branch, so
# there is no warm process and no watchdog thread to reason about.
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = lambda user: None      # would spawn its own turn
# The announce is backgrounded in production (FCM is a network call and the
# owner's /chat request must not wait on it). Run it INLINE here - the same
# stub the card-mirror test uses - so what is asserted is the decision, not a
# thread's timing.
from spine.http import server
server._bg = lambda name, fn: fn()

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# -- the fake claude: the exact stream-json shape the pump reads --------------
REPLY = {"text": "ok"}


class _FakeStdin:
    def write(self, s):
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


def _fake_popen(*a, **k):
    txt = REPLY["text"]
    lines = [
        {"type": "system", "subtype": "init", "session_id": "sess-test"},
        {"type": "assistant", "message": {"usage": {"input_tokens": 120,
                                                    "output_tokens": 8}}},
        {"type": "stream_event", "event": {"type": "content_block_delta",
                                           "delta": {"type": "text_delta", "text": txt}}},
        {"type": "result", "result": txt, "session_id": "sess-test",
         "usage": {"input_tokens": 120, "output_tokens": 8},
         "total_cost_usd": 0.002},
    ]
    return _FakeProc([json.dumps(e) + "\n" for e in lines])


class _FakeSubprocess:
    PIPE = -1
    DEVNULL = -3
    Popen = staticmethod(_fake_popen)


copilot.subprocess = _FakeSubprocess

# every push is captured, never sent. The REAL function is kept: section 4
# calls it directly to prove the quiet-hours gate itself, which a stub could
# only assert about itself.
REAL_PUSH_FCM = notify.push_fcm
PUSHED = []
notify.push_fcm = lambda *a, **k: PUSHED.append((a, k)) or True


def reset(reply="Alles erledigt."):
    del PUSHED[:]
    REPLY["text"] = reply
    db.chat_clear()


def logged():
    return (copilot.history(OWNER) or {}).get("messages") or []


def turn(text="wie steht es?", **kw):
    return copilot.chat(OWNER, text, role="owner", **kw)


print("henry reply push")

# -- 1. the summary a notification can carry ---------------------------------
s = notify.chat_summary("## Titel\n**fertig** und `code` - alles gut")
check("**" not in s and "##" not in s and "`" not in s,
      "markdown is stripped - the model writes for a surface that renders it, "
      "and a notification renders nothing (the same glyphs edge-tts read aloud)")

s = notify.chat_summary(
    "Ja, das passt so.\n<helmdeck-ask>\n{\"questions\": []}\n</helmdeck-ask>")
check("helmdeck-ask" not in s and "questions" not in s and s.startswith("Ja"),
      "a trailing ask block never reaches the lockscreen as raw JSON")

s = notify.chat_summary("wort " * 200)
check(s.endswith("…") and len(s) <= notify.CHAT_BODY_MAX + 4,
      "a long answer is clipped AND says so - a silent cut reads as the whole "
      "answer (d243545's lesson on the wrist)")
check(" ".join(s.split()) == s and "\n" not in s,
      "one line, not a layout - the watch draws the body into a fixed box")
check(notify.chat_summary("") == "" and notify.chat_summary(None) == "",
      "nothing to say pushes nothing (a cancelled turn must not buzz)")

# -- 2. a finished Henry turn pushes -----------------------------------------
# kept before the first stub so section 3 can put the REAL policy back and drive
# it with real heartbeats - a stub can only prove chat_reply reads the decision,
# never that presence.plan produces the right one.
_REAL_PLAN = presence.plan
reset("Drei Karten warten auf dich.")
presence.plan = lambda cid: "push"
turn()
check(len(PUSHED) == 1, "a finished Henry turn raises exactly one push")
args, kw = PUSHED[0] if PUSHED else ((), {})
check("Drei Karten" in (args[1] if len(args) > 1 else ""),
      "the body is the ANSWER's own first words, not a generic 'Henry hat "
      "geantwortet' the owner would have to open the app to decode")
check(kw.get("kind") == "chat",
      "kind='chat' - the app routes it into the Henry chat; without it the "
      "trackless branch drops him on the dashboard, one tab from the answer")
check((args[2] if len(args) > 2 else "?") == "",
      "no track: this is not a card, and a made-up id would deep-link into one")
check(any(m.get("cls") == "bot" and "Drei Karten" in (m.get("text") or "")
          for m in logged()),
      "and the transcript is written as before - the push is a second channel, "
      "never a replacement for the chat")

# ...through the door the phone actually uses, not only the function under it


class FakeReq:
    def __init__(self):
        self.body = None

    def _send(self, code, payload):
        self.body = json.loads(payload)
        return None


reset("Antwort ueber die echte Route.")
req = FakeReq()
routes_copilot.chat_post(req, USER, {"text": "status bitte?", "mid": "m-1"})
check(len(PUSHED) == 1 and "Antwort ueber" in (PUSHED[0][0][1] if PUSHED else ""),
      "POST /chat pushes too - the hook sits under every door, so no route can "
      "answer into silence by forgetting to call it")
check((req.body or {}).get("reply") == "Antwort ueber die echte Route.",
      "and the route still answers the caller normally")

# -- 3. presence is the whole quiet policy, and it is asked about the CHAT ----
# Regression 2026-08-30: this used to pin "inapp -> no buzz" on the theory that
# an open app means the answer is already on screen. It is not - 'inapp' means a
# window exists SOMEWHERE (the desktop shell, a board tab, the card list), and
# the measured cost was that every single Henry reply for a day logged
# "suppressed (inapp)" and not one push ever left the daemon. Only the client
# actually FOCUSED on the chat may suppress.
reset()
_asked = []
presence.plan = lambda cid: (_asked.append(cid), "silent")[1]
turn()
check(_asked and _asked[0] == presence.CHAT,
      "chat_reply asks presence about the CHAT screen (%r), not about "
      "'somewhere' - that is what makes 'focused' usable here" % presence.CHAT)
check(not PUSHED,
      "presence 'silent' -> no buzz: he is reading the very transcript it "
      "lands in")
check(any(m.get("cls") == "bot" for m in logged()),
      "...and the answer is still IN the chat (a suppressed buzz must "
      "never suppress the inbox)")

reset()
presence.plan = lambda cid: "inapp"
turn()
check(PUSHED,
      "presence 'inapp' DOES buzz - an app open on another screen or another "
      "device never shows a Henry answer; suppressing there is how the whole "
      "feature went silent")

# and the same thing end-to-end through the REAL presence module: a client that
# is visible but NOT on the chat must not be able to eat the push.
reset()
presence.plan = _REAL_PLAN
presence.clear()
presence.record("owner", "desktop", focused_card=None, app_visible=True)
turn()
check(PUSHED,
      "real presence: a visible desktop parked on the board still buzzes the "
      "phone (this is the exact live state that suppressed everything)")
reset()
presence.clear()
presence.record("owner", "phone", focused_card=presence.CHAT, app_visible=True)
turn()
check(not PUSHED,
      "real presence: the same instrument goes quiet once a client reports the "
      "chat as its focused screen")
presence.clear()

# -- 4. quiet hours do NOT hold a solicited answer ---------------------------
reset()
presence.plan = lambda cid: "push"
turn()
check(PUSHED and PUSHED[0][1].get("urgent") is True,
      "the push is marked SOLICITED (urgent) - the owner typed the question "
      "minutes ago; quiet hours exist for autonomous overnight work")

# and that flag really is what walks past the quiet gate - asserted on the REAL
# push_fcm (the sandboxed settings hold no token and no relay key, so it can
# only ever reach its own "missing recipient" line, never the network).
_quiet_before = notify._quiet_now
notify._quiet_now = lambda s: True
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    REAL_PUSH_FCM("Henry", "solicited answer", "", urgent=True)
    held = buf.getvalue()
    REAL_PUSH_FCM("Henry", "proactive remark", "")
out = buf.getvalue()
notify._quiet_now = _quiet_before
check("quiet hours" not in held,
      "push_fcm lets an urgent (solicited) message THROUGH quiet hours - it "
      "gets as far as reporting a missing recipient, which is not a hold")
check("quiet hours" in out[len(held):],
      "...while a non-urgent one is still held, so nothing changes for the "
      "proactive traffic quiet hours was actually written for")

# -- 5. a door that delivers the reply itself does not push ------------------
reset()
presence.plan = lambda cid: "push"
turn(announce=False)
check(not PUSHED,
      "announce=False (the watch and the glasses render AND speak the reply in "
      "this same request) - a push would buzz the wrist about the sentence it "
      "is reading out loud")
check(any(m.get("cls") == "bot" for m in logged()),
      "...and that door still writes the shared transcript, so the phone sees "
      "what was said on the wrist")

# the wear and glance routes must actually PASS that flag - the whole point of
# the wiring, and a silent regression if someone drops the kwarg
import inspect
from spine.http.routes import routes_glance, routes_wear
for mod, fn in ((routes_wear, "wear_talk_post"), (routes_glance, "glance_talk")):
    src = inspect.getsource(getattr(mod, fn))
    check("announce=False" in src,
          "%s.%s asks copilot.chat NOT to announce" % (mod.__name__.split(".")[-1], fn))

# -- 6. a CARD-scoped Henry turn does not push -------------------------------
reset()
copilot._find_card = lambda cid: {"id": "c-9", "branch": "b", "task": "eine Karte",
                                  "run_dir": SANDBOX}
turn(card="c-9")
check(not PUSHED,
      "a card-scoped Henry answer lands in the CARD's timeline, so a push "
      "promising the Henry chat would open a chat that never mentions it")

# -- 7. worker-card notifications are untouched ------------------------------
reset()
notify._last_push.clear()
track = {"id": "c-1", "task": "Karte die dich braucht", "status": "needs_you"}
notify.card_event(track, "needs_you")
check(len(PUSHED) == 1 and PUSHED[0][1].get("kind") == "needs_you",
      "notify.card_event still owns worker-card pushes, unchanged - it keeps "
      "its own reason table, dedup and card deep-link")

# -- 8. the WIRE: what the phone and the watch actually decrypt ---------------
# Everything above asserts the decision; this asserts the bytes. push_fcm runs
# for real (fake transport, fake service account, keys generated here), so the
# payload the app's decryptPush() parses is read back out of the sealed box
# instead of assumed from the call site.
from spine.comms import e2ee

sk_d, pk_d = e2ee.generate_keypair()          # the daemon
sk_p, pk_p = e2ee.generate_keypair()          # a paired phone
sk_w, pk_w = e2ee.generate_keypair()          # and the watch
events.save_settings({
    "relay": {"sk": e2ee.export_sec(sk_d),
              "phone_pub": e2ee.export_pub(pk_p),
              "phone_pubs": [e2ee.export_pub(pk_p), e2ee.export_pub(pk_w)]},
    "push": {"fcm_token": "phone-token",
             "devices": {e2ee.export_pub(pk_w): {"token": "watch-token",
                                                 "label": "Watch"}}}})

_SA_FILE = os.path.join(SANDBOX, "fcm_service_account.json")
with open(_SA_FILE, "w", encoding="utf-8") as f:
    json.dump({"project_id": "helmdeck-test", "client_email": "x@y.z",
               "token_uri": "https://example.invalid/token", "private_key": "-"}, f)
notify._SA = _SA_FILE
notify._access_token = lambda: "bearer-test"

SENT = []


class _FakeRequest:
    def __init__(self, url, data=None, method=None):
        self.url, self.data = url, data

    def add_header(self, k, v):
        pass


class _FakeUrlopen:
    def __init__(self, req, timeout=None):
        SENT.append(json.loads(req.data.decode()))

    def read(self):
        return b"{}"


class _FakeUrllib:
    class request:
        Request = _FakeRequest
        urlopen = _FakeUrlopen


_urllib_before = notify.urllib
notify.urllib = _FakeUrllib
notify.push_fcm = REAL_PUSH_FCM                # the real sender, fake transport
try:
    reset("Der Deploy laeuft, ich melde mich wenn er durch ist.")
    presence.plan = lambda cid: "push"
    turn()
    check(len(SENT) == 2,
          "one sealed message PER DEVICE - the phone and the watch each get "
          "their own box (a shared ciphertext would let either open the "
          "other's mail)")
    opened = []
    for msg, sk_dev in ((SENT[0] if SENT else {}), sk_p), ((SENT[1] if len(SENT) > 1 else {}), sk_w):
        cipher = ((msg.get("message") or {}).get("data") or {}).get("cipher")
        opened.append(json.loads(e2ee.open_b64(cipher, sk_dev, pk_d)) if cipher else {})
    check(all(o.get("kind") == "chat" and o.get("track") == "" for o in opened),
          "both devices decrypt kind='chat' and an empty track - the exact two "
          "fields the app routes a tap on (_layout.tsx) and the only reason it "
          "lands in the Henry chat instead of the dashboard")
    check(all("Der Deploy laeuft" in (o.get("body") or "") for o in opened),
          "...carrying the answer's own words, on the wrist as on the phone")
    check(all(o.get("title") for o in opened) and "ask" not in opened[0],
          "a title but no ask block - a Henry answer has no options to tap, and "
          "an empty one would render as dead buttons")
    check(all(t in json.dumps(SENT) for t in ("phone-token", "watch-token")),
          "addressed to BOTH registered tokens, so the wrist buzzes even with "
          "the phone in another room")
finally:
    notify.urllib = _urllib_before
    notify.push_fcm = lambda *a, **k: PUSHED.append((a, k)) or True

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all henry-reply-push checks passed")
