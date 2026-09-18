# -*- coding: utf-8 -*-
"""Henry's broker decisions must reach the CHAT whole.

Owner report 2026-08-28: Henry's messages in the board chat AND the card chat
"end mid-word" ('... und mel', '... and ve'). Root cause: _decide built ONE
string for the FCM push and reused it as the chat message, so the push's length
budget silently became the chat's - `(text or why)[:180]` on the notify line,
`text[:200]`/`[:120]` on the card audit note (which the card chat renders as a
`note` row), and `detail[:200]` on the notify_owner / give-up lines.

The rule pinned here: a length budget belongs to the CONSUMER that has one.
Only push_fcm truncates. copilot.say (chat) and the ActionLog note get the
whole message.

Sandboxed: no daemon, no network, no model. _ask and every sink are stubbed.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.copilot.broker import henry_broker as hb
# Imported UP HERE, before section 4 swaps package attributes around: pm_comm
# binds `from spine.registry import i18n as _i18n` at module level, so importing
# it while that attribute is stubbed would freeze the stub into the module.
from cells.copilot.planning import pm_comm
from cells.copilot.chat import copilot as _  # noqa: F401 (registers cells.copilot.chat before section 4 swaps its attribute)

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# Longer than every cap that used to sit on this path (180 / 200 / 230), ending
# in the shape the owner saw mangled: a real word, then punctuation and a
# non-ASCII glyph, so a silent slice shows up as a broken tail.
TAIL = "und melde mich sobald der Deploy gruen ist - geprueft (98243a6) ✓"
LONG = ("fixed it in 98243a6, and verified the build twice; " * 8) + TAIL
assert len(LONG) > 400, "fixture must exceed every historical cap"


class _Sinks:
    def __init__(self):
        self.notified, self.audited = [], []


def _decide_with(verb):
    """Run ONE real _decide round with the model + side effects stubbed, and
    capture what _decide hands to its two owner-facing sinks."""
    s = _Sinks()
    esc = {"id": "e1", "kind": "deploy_failed", "card": "c1", "detail": "d"}

    class _Esc:
        record_attempt = staticmethod(lambda *a, **k: None)
        record_note = staticmethod(lambda *a, **k: None)
        record_decision = staticmethod(lambda *a, **k: None)

    class _Events:
        settings = staticmethod(lambda: {})

    saved = {k: getattr(hb, k) for k in
             ("escalations", "_ask", "_hands_on_ask", "_execute", "_audit",
              "_notify_owner", "_find_track", "_dispatcher_privileged",
              "_card_log_tail", "_audit_context", "_snapshot")}
    sys.modules["spine.storage.events"] = _Events
    hb.escalations = _Esc()
    hb._ask = lambda *a, **k: dict(verb)
    hb._hands_on_ask = lambda *a, **k: dict(verb)
    hb._execute = lambda *a, **k: True
    hb._find_track = lambda c: {"id": "c1"} if c else None
    hb._dispatcher_privileged = lambda t: True
    hb._card_log_tail = lambda *a, **k: ""
    hb._audit_context = lambda t: ""
    hb._snapshot = lambda: ""
    hb._audit = lambda c, note: s.audited.append(note)
    hb._notify_owner = lambda text, t, push=True: s.notified.append(text)
    try:
        hb._decide(esc)
    finally:
        for k, v in saved.items():
            setattr(hb, k, v)
    return s


# ---------------------------------------------------------------------------
# 1) `did` - the verb behind the owner's 'fixed it in 98243a6, and ve...' sample
s = _decide_with({"action": "did", "card": "c1", "text": LONG, "why": "build war rot"})
check(any(LONG in n for n in s.notified),
      "did: _notify_owner is handed the FULL text (no pre-truncation for the push)")
check(any(n.rstrip().endswith(TAIL) for n in s.notified),
      "did: the message ends on the real tail, not mid-word")
check(any(LONG in a for a in s.audited),
      "did: the card audit note (a `note` row in the card chat) is full too")

# 2) `steer` - the verb behind the '... und mel...' sample
s = _decide_with({"action": "steer", "card": "c1", "text": LONG, "why": "w"})
check(any(LONG in n for n in s.notified), "steer: full text reaches the chat sink")

# 3) `why` carries the message when there is no text - also uncut. Since
# 2026-09-12 a move to REVIEW/DONE had NO Henry bubble of its own (the lane
# pipeline's line carried his note only) - reversed 2026-09-18 (owner:
# "warum muss ich nochmal fragen"): a move now DOES report back too, full
# text, same as every other closing action - see ops/tests/test_henry_dedup.py
# for the push-dedup half of that change (still no SECOND push on done).
s = _decide_with({"action": "move", "card": "c1", "lane": "review", "text": "", "why": LONG})
check(any(LONG in n for n in s.audited), "move: full `why` reaches the card audit note")
check(any(LONG in n for n in s.notified), "move: full `why` also reaches the Henry chat bubble")

# ---------------------------------------------------------------------------
# 4) _notify_owner itself: the push is the ONLY consumer allowed to truncate.
pushed, said = [], []


class _Notify:
    # since 2026-09-12 _notify_owner pushes through the presence-gated
    # notify.escalate (same budget, one door); the raw push_fcm stub stays so
    # a regression back to it is caught as "pushed twice", not silently.
    escalate = staticmethod(lambda title, body, track_id="": pushed.append(body))
    push_fcm = staticmethod(lambda title, body, *a, **k: pushed.append(body))


class _I18n:
    t = staticmethod(lambda k, **kw: "Henry")


class _Copilot:
    say = staticmethod(lambda text, cls="pm", card=None: said.append(text))


# `from X import Y` resolves Y as an ATTRIBUTE of the package once X is
# imported, so setting the attribute is what actually intercepts the import
# (and avoids dragging in the real, daemon-bound modules).
import spine.comms, spine.registry, cells.copilot
_prev = (getattr(spine.comms, "notify", None), getattr(spine.registry, "i18n", None),
         getattr(cells.copilot, "copilot", None))
spine.comms.notify, spine.registry.i18n, cells.copilot.chat.copilot = _Notify, _I18n, _Copilot
try:
    hb._notify_owner("Henry (deploy_failed): " + LONG, None)
finally:
    spine.comms.notify, spine.registry.i18n, cells.copilot.chat.copilot = _prev

check(said and LONG in said[0], "_notify_owner: the CHAT gets the whole message")
check(said and said[0].rstrip().endswith(TAIL), "_notify_owner: chat message is not mangled")
check(pushed and len(pushed[0]) <= 230, "_notify_owner: the FCM push stays in its budget")
check(pushed and said and len(pushed[0]) < len(said[0]),
      "_notify_owner: push is the truncated one - chat is not")
check(len(pushed) == 1, "_notify_owner: exactly ONE push per decision (escalate, not push_fcm too)")

# ---------------------------------------------------------------------------
# 5) THE OTHER DOOR into the same chat card (owner report 2026-08-30, 14:08
# screenshot). Henry is not the only writer of a cls:"pm" entry - the PM cell
# writes through pm_comm._say/_escalate, and the app renders BOTH with the
# identical component (chat.tsx toStep -> card_transcript.tsx, byKind "henry").
# A clip on either door therefore produces the same mid-thought "…" card, and
# pinning only Henry's door is how the 2026-08-28 fix came back as the
# 2026-08-30 bug: notice.short() was wired into pm_comm._say the same day.
#
# Pinned HERE, in the file whose subject is "the chat gets it whole", and not in
# ops/tests/test_notice_routing.py - that suite asserts a notice is BORN short
# (short(line) == line), a different and complementary rule, which is exactly
# why it stayed green straight through the regression.
pm_pushed = []


class _Notify2:
    escalate = staticmethod(lambda title, body, tid: pm_pushed.append(body))


spine.comms.notify, cells.copilot.chat.copilot = _Notify2, _Copilot
said[:] = []
try:
    pm_comm._say(LONG)
    check(said and said[0] == LONG, "pm _say: the chat gets the whole notice")
    check(said and said[0].rstrip().endswith(TAIL), "pm _say: not mangled")

    said[:] = []
    pm_comm._escalate(LONG, tid="c1", title="T")
    check(said and said[0] == LONG, "pm _escalate: the CHAT copy is whole")
    check(pm_pushed and len(pm_pushed[0]) <= 180,
          "pm _escalate: only the PUSH is clipped, to its own 180 budget")
    check(pm_pushed and pm_pushed[0].endswith(" …"),
          "pm _escalate: the clipped push ADMITS it was clipped")
    # word boundary: strip the marker, and the next character in the source must
    # be whitespace - i.e. the cut fell between words, never inside one. This is
    # the property a raw [:180] cannot give and the owner reported twice.
    _body = pm_pushed[0][:-2] if pm_pushed else ""
    check(bool(_body) and LONG.startswith(_body) and LONG[len(_body):len(_body) + 1].isspace(),
          "pm _escalate: the push cut lands between words, not mid-word")
finally:
    spine.comms.notify, cells.copilot.chat.copilot = _prev[0], _prev[2]

# 6) `chars` is a TRUE ceiling - the " …" marker is paid out of the budget, not
# added on top. A caller at a hard limit must not have to write chars-2 itself.
from spine.comms import notice as _n
check(len(_n.short("x" * 500, chars=180)) == 180, "short(): `chars` is a true ceiling")
check(len(_n.short("wort " * 200)) <= _n.MAX_CHARS, "short(): default budget respected")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("henry-chat-full-text: all pinned - PASS")
