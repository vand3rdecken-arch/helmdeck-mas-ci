# -*- coding: utf-8 -*-
"""Headless test for the CARD EVENT MIRROR - the Henry chat as the one inbox
(owner decree 2026-08-29).

The defect: a working card's question or turn-end result only ever reached that
CARD's transcript. The owner had to know which card to open - and on the watch
and the glasses, where card navigation does not exist at all, a card's question
was structurally unreachable.

What is pinned here, in the order the news travels:

 1. a card that ASKS produces a labelled `card` entry in the Henry chat, bound
    to the card id, carrying the WHOLE ask block (so options stay tappable and
    the answer can name a request_id)
 2. a turn that ENDS produces a `result` entry carrying the card's own reply
 3. THE PROPERTY THE WHOLE DECREE RESTS ON: the mirror writes even when the
    push is suppressed. Presence, quiet hours and dedup all correctly silence a
    BUZZ; every one of them is a reason the inbox line matters more, not less.
    If this check ever goes red the feature is gone while looking present -
    the chat would simply be empty, which is also what a quiet board looks like.
 4. the mirror's dedup is its OWN: a repeated transition prints once, a NEW
    question prints again, and a started turn re-arms both channels together
 5. the mirror does NOT own terminal lane outcomes - `done`/`bounced` stay with
    lanemachine._say_card, so an accept is not printed twice
 6. the watch KEEPS these entries (they were filtered out as chrome) and gets
    the label parts plus wrist-trimmed options
 7. an owner reply bound to a card is ROUTED to that card - as a settled answer
    when the card asked, as a steer otherwise - and never as a Henry turn

Self-sandboxing: temp db/events/settings/chatlog, the board in memory, notify's
FCM and presence stubbed, sessions.steer/answer_question captured. No daemon, no
network, no model call.
Run: py -3.12 ops/tests/test_chat_mirror.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-mirror-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, card_mirror
copilot.CHATLOG = os.path.join(SANDBOX, "copilot_log.json")

from spine.auth import auth
from spine.comms import notify, presence

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
# Never let a test touch the real FCM path. `recipients` is re-derived at send
# time from pinned keys, so an empty settings file would already skip it - but
# stubbing says so out loud instead of relying on a side effect.
notify.push_fcm = lambda *a, **k: False

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def logged():
    return (copilot.history(OWNER) or {}).get("messages") or []


def cards():
    return [m for m in logged() if m.get("cls") == card_mirror.CLS]


def reset():
    copilot._append_log  # noqa: B018  - keep the import honest
    try:
        os.remove(copilot.CHATLOG)
    except OSError:
        pass
    card_mirror._last.clear()
    notify._last_push.clear()


def ask_block(qid, header="Weg", opts=("A", "B")):
    return {"id": qid, "kind": "question",
            "questions": [{"question": "Welchen Weg nehmen wir?", "header": header,
                           "options": [{"label": o, "description": "d " + o}
                                       for o in opts],
                           "multiSelect": False, "idx": 0}],
            "asked": "2026-08-29 10:00:00", "ta": 1.0}


def card(tid="c-1", **kw):
    t = {"id": tid, "task": "Henry-Chat wird der zentrale Posteingang\nzweite Zeile",
         "status": "needs_you", "lane": "working", "waiting_on": "you"}
    t.update(kw)
    return t


print("card event mirror")

# -- 1. a QUESTION becomes a labelled, bound, answerable chat entry -----------
reset()
presence.plan = lambda tid: "push"
q = ask_block("q-1")
notify.card_event(card(question=q), "question")
cs = cards()
check(len(cs) == 1, "a card question writes exactly one chat entry")
e = cs[0] if cs else {}
check(e.get("kind") == card_mirror.KIND_QUESTION,
      "it is labelled as a QUESTION (Frage), not as generic news")
check(e.get("card") == "c-1",
      "it carries the CARD ID - the binding a reply is routed by, so nothing "
      "downstream has to guess the card from the text")
check(e.get("cardName") and "\n" not in e.get("cardName", "x") and
      len(e.get("cardName", "")) <= 43,
      "it carries a one-line KURZNAME for the label, clipped, never multi-line")
check((e.get("question") or {}).get("id") == "q-1",
      "the WHOLE ask block rides along - without the request_id a pick could "
      "not be checked for staleness and would silently answer the next question")
check("Welchen Weg" in (e.get("text") or ""),
      "the text is the question itself, not 'a card needs you'")

# -- 2. a turn END becomes a result entry carrying the card's own reply -------
reset()
notify.card_event(card(last_reply="Fertig: der Mirror haengt an card_event."),
                  "needs_you")
cs = cards()
check(len(cs) == 1 and cs[0].get("kind") == card_mirror.KIND_RESULT,
      "a turn end writes a RESULT (Ergebnis) entry")
check("der Mirror haengt" in (cs[0].get("text") or ""),
      "the result carries the card's OWN closing words, not a generic 'done'")

# a turn that ended with nothing to say must not print an empty bubble
reset()
notify.card_event(card(last_reply="   "), "needs_you")
check(not cards(), "a turn end with no reply text writes NOTHING (no empty bubble)")
# ...and must not have BURNED the dedup key doing it. Claiming the key before
# knowing there is anything to print would swallow the next real message under
# that key as a repeat of one that was never written.
notify.card_event(card(last_reply="jetzt habe ich doch etwas zu sagen"), "needs_you")
check(len(cards()) == 1,
      "a silent transition does not consume the dedup key - the next real "
      "message under the same key still prints")

# a long reply reaches the chat WHOLE (owner decision 2026-08-30, replacing the
# clip this block used to pin). The mirror has no length budget of its own: the
# chat scrolls and folds, and on a card the owner started FROM the chat there is
# no second copy to tap through to - the clip destroyed the only one he had a
# route to. Measured that day: 10 of 10 clipped mirror lines were such cards.
reset()
long_reply = "wort " * 400
notify.card_event(card(last_reply=long_reply), "needs_you")
txt = cards()[0]["text"] if cards() else ""
check(txt == long_reply.strip(),
      "an over-long result is mirrored WHOLE - no clip and no ' …' marker")
check(not hasattr(card_mirror, "RESULT_MAX"),
      "the cap is GONE, not merely raised - a dormant constant is the next "
      "agent's invitation to reintroduce the clip")

# -- 3. THE CORE PROPERTY: suppressed push, written inbox ---------------------
for decision, why in (("silent", "the owner is looking at that very card"),
                      ("inapp", "the owner is present on another screen")):
    reset()
    presence.plan = lambda tid, _d=decision: _d
    pushed = []
    notify.push_fcm = lambda *a, **k: pushed.append(a) or False
    notify.card_event(card(question=ask_block("q-s")), "question")
    check(len(cards()) == 1 and not pushed,
          "push suppressed (%s) but the chat line IS written - %s" % (decision, why))
notify.push_fcm = lambda *a, **k: False

# quiet hours silence the buzz, never the inbox
reset()
presence.plan = lambda tid: "push"
notify._quiet_now = lambda s: True
pushed = []
notify.push_fcm = lambda *a, **k: pushed.append(a) or False
notify.card_event(card(question=ask_block("q-q")), "question")
check(len(cards()) == 1, "quiet hours hold the push but never the inbox line")
notify._quiet_now = lambda s: False
notify.push_fcm = lambda *a, **k: False

# -- 4. the mirror's own dedup ------------------------------------------------
reset()
presence.plan = lambda tid: "push"
t = card(question=ask_block("q-a"))
notify.card_event(t, "question")
notify.card_event(t, "question")
check(len(cards()) == 1, "the SAME pending question is mirrored once, not per settle")
notify.card_event(card(question=ask_block("q-b")), "question")
check(len(cards()) == 2, "a NEW question is news again and does print")

reset()
notify.card_event(card(question=ask_block("q-c")), "question")
notify.clear_dedup("c-1")
notify.card_event(card(question=ask_block("q-c")), "question")
check(len(cards()) == 2,
      "a STARTED turn re-arms the mirror together with the push - if only the "
      "push re-armed, a notification would point at a chat that never said it")

# -- 5. the mirror does not double-print terminal lane outcomes ---------------
reset()
notify.card_event(card(lane="done", status="accepted"), "done")
notify.card_event(card(), "bounced")
check(not cards(),
      "done/bounced are NOT mirrored here - lanemachine._say_card already "
      "reports every terminal lane outcome, and two owners would print twice")
notify.card_event(card(waiting_on="background"), "background")
check(not cards(), "a card waiting on its OWN task is not the owner's move")

# -- 6. the watch keeps them, with label parts and wrist-sized options --------
reset()
notify.card_event(card(question=ask_block("q-w")), "question")
notify.card_event(card(tid="c-2", last_reply="Ergebnis fuer die Uhr"), "needs_you")

from spine.http.routes import routes_wear


class FakeReq:
    def __init__(self):
        self.body = None

    def _send(self, code, payload):
        self.body = json.loads(payload)
        return None


req = FakeReq()
routes_wear.wear_chat_get(req, {"name": OWNER, "role": "owner"})
wm = (req.body or {}).get("messages") or []
check(len(wm) == 2,
      "the watch KEEPS mirrored card entries - it used to drop every class "
      "outside (you,bot,error), so the inbox was invisible on the one surface "
      "that has no card navigation at all")
qrow = next((r for r in wm if r.get("kind") == card_mirror.KIND_QUESTION), None)
check(bool(qrow) and qrow.get("cardName"),
      "the wrist gets the LABEL parts (kind + card short name)")
check(bool(((qrow or {}).get("question") or {}).get("questions")),
      "and the tappable OPTIONS, trimmed by the same _glance_question the "
      "glasses and /wear/talk already use - one question shape on the wrist")
opt = ((((qrow or {}).get("question") or {}).get("questions") or [{}])[0]
       .get("options") or [{}])[0]
check(opt.get("label") == "A",
      "option labels ride VERBATIM - validate_answers matches by equality, so "
      "a trimmed label would arrive as free text instead of a preset pick")

# markdown must not reach the wrist
reset()
notify.card_event(card(last_reply="## Titel\n**fett** und `code`"), "needs_you")
req = FakeReq()
routes_wear.wear_chat_get(req, {"name": OWNER, "role": "owner"})
wtxt = ((req.body or {}).get("messages") or [{}])[0].get("text", "")
check("**" not in wtxt and "##" not in wtxt and "`" not in wtxt,
      "markdown is stripped for the wrist (this route used to slice raw while "
      "/wear/board stripped - one wrist-text policy now)")

# -- 7. an owner reply bound to a card is ROUTED to that card -----------------
from cells.copilot.routes import routes_copilot
from cells.engineer.cards import sessions
from spine.http import server

server._bg = lambda name, fn: fn()          # run the backgrounded work inline
auth.owns_card = lambda user, t: True

steered, answered = [], []
# Grab the REAL answer_question before stubbing it - section 8 exercises it for
# real, and reading it back off the module afterwards would silently get this
# stub instead (the two names are the same attribute on the same module object).
REAL_ANSWER = sessions.answer_question
sessions.steer = lambda tid, text, **kw: steered.append((tid, text))
sessions.answer_question = lambda tid, answers, **kw: answered.append(
    (tid, answers, kw.get("request_id")))

reset()
PEND = card(question=ask_block("q-r"))
sessions.get_track = lambda tid: PEND if tid == "c-1" else None

req = FakeReq()
routes_copilot.chat_post(req, {"name": OWNER, "role": "owner"},
                         {"text": "A", "reply_to_card": "c-1"})
check(answered and answered[0][0] == "c-1" and answered[0][2] == "q-r",
      "a reply to a card that ASKED settles the question on THAT card, with "
      "the request_id, so a stale pick fails loudly instead of answering the "
      "card's next question")
check(not steered, "and it does NOT also steer")
check((req.body or {}).get("routed") == {"card": "c-1", "as": "answer"},
      "the response says where it went, so the client can show it")

# free text is a valid answer (the 'Other' escape hatch), not a loose remark
del answered[:]
reset()
req = FakeReq()
routes_copilot.chat_post(req, {"name": OWNER, "role": "owner"},
                         {"text": "keins von beiden, nimm C",
                          "reply_to_card": "c-1"})
check(answered and answered[0][1] == {"Weg": "keins von beiden, nimm C"},
      "FREE TEXT settles the question too - otherwise the question would stay "
      "open next to the answer and the card would ask again")

# no pending question -> a plain steer
del steered[:]
del answered[:]
reset()
PLAIN = card(tid="c-3")
sessions.get_track = lambda tid: PLAIN
req = FakeReq()
routes_copilot.chat_post(req, {"name": OWNER, "role": "owner"},
                         {"text": "mach bitte weiter", "reply_to_card": "c-3"})
check(steered and steered[0] == ("c-3", "mach bitte weiter") and not answered,
      "a reply to a card with no open question is a STEER")
check(any(m.get("cls") == "you" and m.get("card") == "c-3" for m in logged()),
      "the owner's own words stay in the Henry transcript, bound to the card - "
      "he typed at his inbox and must not watch it swallow the message")

# an unowned / unknown card must not silently vanish into a Henry turn
sessions.get_track = lambda tid: None
req = FakeReq()
routes_copilot.chat_post(req, {"name": OWNER, "role": "owner"},
                         {"text": "x", "reply_to_card": "nope"})
check((req.body or {}).get("error"),
      "an unknown card errors instead of falling back to a Henry turn - a "
      "silent fallback would send work meant for a worker to the wrong agent")

# the WRIST routes through the same door - a tapped option must settle the
# card, not arrive in Henry's advisory session as a contextless "A"
del steered[:]
del answered[:]
reset()
sessions.get_track = lambda tid: PEND
req = FakeReq()
routes_wear.wear_talk_post(req, {"name": OWNER, "role": "owner"},
                           {"message": "A", "reply_to_card": "c-1"})
check(answered and answered[0][0] == "c-1" and not steered,
      "a wrist tap on a mirrored card's option ANSWERS that card - the watch's "
      "options used to re-send the label to Henry, which cannot settle a "
      "worker's question and leaves the card waiting")
check((req.body or {}).get("routed", {}).get("as") == "answer"
      and not (req.body or {}).get("voice"),
      "and it renders no speech - nothing was said TO the owner, the card's "
      "answer comes back as a mirrored result on the next poll")
check(sessions.reply_door(PLAIN, "mach weiter")[0] == "steer"
      and sessions.reply_door(PEND, "A")[0] == "answer",
      "phone and watch share ONE reply_door rule - two copies would be two "
      "surfaces disagreeing about whether a sentence settled a question")

# -- 8. an answer given ANYWHERE closes the question in the inbox -------------
# The panel, the watch, the glasses and the notification buttons all answer
# through sessions.answer_question and write nothing to the chat of their own.
# Without an echo there, the mirrored question would keep offering options it
# had already spent, and the owner would answer it again into a certain 409.
reset()
ANS = card(question=ask_block("q-e"), run_dir=SANDBOX)
notify.card_event(ANS, "question")
sessions._mutate = lambda tid, fn: (fn(ANS), ANS)[1]
REAL_ANSWER("c-1", {"Weg": "A"}, request_id="q-e")
check(any(m.get("cls") == "you" and m.get("card") == "c-1" for m in logged()),
      "answering from ANY surface echoes into the Henry chat, bound to the "
      "card - so the inbox stops offering a question that is already spent")

# and the inline-chat caller must NOT get a second, re-rendered copy
reset()
ANS2 = card(question=ask_block("q-f"), run_dir=SANDBOX)
notify.card_event(ANS2, "question")
sessions._mutate = lambda tid, fn: (fn(ANS2), ANS2)[1]
REAL_ANSWER("c-1", {"Weg": "A"}, request_id="q-f", echo_chat=False)
check(not [m for m in logged() if m.get("cls") == "you"],
      "echo_chat=False leaves it to the caller that already logged the owner's "
      "verbatim words - a re-rendered second copy would duplicate the message "
      "AND pin the app's optimistic bubble forever (it never finds its text)")

# -- 8. a card that is DELETED or ARCHIVED says so, bound to its id ----------
# Owner screenshot 2026-09-11 18:02: a deleted card's question stayed the newest
# unsettled `card` entry, so the composer kept pinning the dead card as the
# reply target (derived from the transcript, chat.tsx openChatQuestion: open
# until a LATER entry bound to the same card lands) and every send died with
# 'no such card'. The entry that settles it is written by the ONE owner of the
# transition, at event time - the real cardadmin.delete_track / archive_track
# against the sandbox db, not a stub.
from cells.engineer.cards import cardadmin
from spine.storage import db as _db

def _closed_after(tid, kind_key="closed"):
    ms = logged()
    qi = max((i for i, m in enumerate(ms) if m.get("card") == tid and m.get("kind") == "question"), default=-1)
    return [m for m in ms[qi + 1:] if m.get("card") == tid and m.get("kind") == kind_key]

reset()
GONE = card(tid="c-del", question=ask_block("q-del"), run_dir=SANDBOX,
            repo=SANDBOX, branch="hd/c-del", worktree=None)
_db.track_put(GONE)
notify.card_event(GONE, "question")
check(_closed_after("c-del") == [], "before the delete nothing bound to the card follows its question")
cardadmin.delete_track("c-del", actor="tien")
cl = _closed_after("c-del")
check(len(cl) == 1 and cl[0].get("cls") == card_mirror.CLS,
      "DELETE writes exactly one card-bound CLOSED entry AFTER the question - "
      "the later same-card entry that releases the composer's derived target")
check(cl and cl[0].get("cardName") and cl[0]["cardName"] != "c-del",
      "it still carries the card's short name (written before the row went)")
check(_db.track_get("c-del") is None, "and the row is really gone")

reset()
ARCH = card(tid="c-arc", question=ask_block("q-arc"), run_dir=SANDBOX,
            repo=SANDBOX, branch="hd/c-arc", worktree=None)
_db.track_put(ARCH)
notify.card_event(ARCH, "question")
cardadmin.archive_track("c-arc", on=True, actor="tien")
check(len(_closed_after("c-arc")) == 1,
      "ARCHIVE (on) writes the same card-bound CLOSED entry")
cardadmin.archive_track("c-arc", on=False, actor="tien")
check(len(_closed_after("c-arc")) == 1,
      "UNARCHIVE does not: the card is back on the board, nothing closed")

# -- 9. a reply to a card the store no longer has heals the transcript --------
# Pre-fix history (deleted before say_closed existed) or a race with the delete:
# the failed lookup IS the runtime's evidence, folded in at the moment it is
# observed - then still 404, the words were not delivered.
reset()
sessions.get_track = lambda tid: None
req = FakeReq()
routes_copilot.chat_post(req, {"name": OWNER, "role": "owner"},
                         {"text": "nochmal", "reply_to_card": "ghost"})
check((req.body or {}).get("error") == "no such card", "the reply still errors - nothing pretends to be delivered")
check(any(m.get("card") == "ghost" and m.get("kind") == card_mirror.KIND_CLOSED for m in logged()),
      "but a card-bound CLOSED entry is folded in, so the next history poll "
      "releases the ghost target instead of dead-ending on every send")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all card-event-mirror checks passed")
