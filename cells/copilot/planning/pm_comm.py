# -*- coding: utf-8 -*-
"""PM communication layer - extracted from pm.py (god-file breakup, see
spine/registry/debt.py daemon-god-files). Plain-language "what am I
doing" (DAU): an append-only activity feed plus the two ways the PM reaches
the owner - _say (chat only) and _escalate (chat + presence-aware push).
Computed from the REAL board, never LLM-guessed, so it's reliable.

Depends only on i18n/copilot/sessions/notify - nothing back into pm.py's own
logic, so pm.py (and the extracted pm_resolve.py) import these at module
level with no cycle.

THE NOTICE LAW (owner decree 2026-08-30, verbatim: "Diese Karte sollte in der
Form nicht mehr im Chat sein. Zu viel info.. bzw ich weiss nicht was ich dazu
machen soll.")
------------------------------------------------------------------------
Every automatic notice now has to answer ONE question before it is written:
is there a decision only the OWNER can make?

  yes -> _say / _escalate / _ask_owner. One short line, and spine.comms.notice
         .short() enforces that in the WRITER, not in the caller's good
         intentions - a caller that rambles gets clipped. _ask_owner
         additionally gives him a real BUTTON to tap.
  no  -> _activity (the dashboard feed, pm.activity -> PMStatusPanel) and/or
         _to_henry (the escalation bus, where Henry judges and ACTS on it).
         Never the owner's chat.

The complained-about block was _stakeholder_update's "Ziel vs. Budget" wall:
five sentences of projections with no move for the owner in any of them. The
context watchdog was worse - it was ADDRESSED to Henry ("Karte kompaktieren,
aufteilen oder abschliessen") and delivered to the owner. Both are routed by
the rule above now, not by whoever wrote the string."""
import json
import time

from spine.registry import i18n as _i18n
from spine.comms.notice import short as _short
from daemon.paths import DAEMON_ROOT as ROOT

def _activity(kind, msg, card=None):
    """Append one plain-language line the PM 'said' (planned/started/blocked).
    Store: the pm_activity table (state-into-db phase D; ledger step 7
    imported daemon/pm/activity.jsonl). Best-effort - a feed line must never
    break the planning turn that emits it."""
    try:
        from spine.storage import db
        db.pm_activity_append(kind, msg, card=card, ts=time.strftime("%Y-%m-%d %H:%M"))
    except Exception:                                            # noqa: BLE001
        pass


def _say(text):
    """The PM SPEAKS TO YOU: post a message into the owner's board chat so the
    chat MOVES on its own - real proactive communication, not just a silent feed.
    You can reply there and steer it. (cls 'pm' = a PM-authored message.)
    One voice: the shared writer in copilot.say, which the lane pipeline uses
    too - so everything non-interactive speaks in the same chat.

    NOT clipped (2026-08-30, second pass). The two-sentence law is enforced
    where it belongs - in the AUTHORS, and asserted as such by
    ops/tests/test_notice_routing.py ("it obeys the length law untouched":
    notice.short(line) == line, i.e. the clip must never have to fire). A
    second clip here added nothing for a well-written notice and, for anything
    else, silently amputated the half that carried the owner's move - which is
    exactly what the owner photographed on the Henry card the same day it
    shipped. Use _say only when the owner has a move to make; a notice with no
    move belongs in _activity or _to_henry (see the module docstring)."""
    try:
        from cells.copilot.chat import copilot
        copilot.say(text, cls="pm")
    except Exception:
        pass


def _to_henry(kind, detail, card=None, feed=""):
    """Hand a notice that needs NO OWNER DECISION to HENRY instead of writing
    it into the owner's chat (owner decree 2026-08-30).

    Henry is the exception broker WITH HANDS: he reads the fact, judges it in
    full board context and acts - compact/split/close the bloated card,
    re-derive a red triage corner, hold non-goal work while the quota is
    ahead. That is what every one of these notices was already ASKING FOR in
    prose; it was just asking the wrong person. The context watchdog is the
    clearest case: its own text told the reader to compact the card, which the
    owner cannot do and Henry can.

    Guarded against re-emitting the SAME open exception (same guard shape as
    lifecycle._landed_not_closed and turnrunner's delivered-parked): the PM's
    own dedup latches decide WHEN a fact is news, this makes sure a Henry who
    is still working on it does not get it a second time.

    Also lands in the activity feed, so the dashboard keeps showing it - going
    quiet in the chat must not mean going invisible."""
    _activity("blocked", feed or detail, card=card)
    try:
        from spine.registry import escalations
        if any(e.get("kind") == kind and e.get("card") == card
               for e in escalations.list_open()):
            return ""                    # Henry is already on this exact one
        return escalations.emit(kind, card=card, detail=detail)
    except Exception as e:
        print("pm: henry handoff failed:", e)
        return ""


def _ask_owner(text, options, header="", card=None, title=""):
    """The PM ASKS: ONE short line plus REAL TAP BUTTONS in the owner's chat.

    The owner's complaint was two-sided - too long AND "ich weiss nicht was ich
    dazu machen soll". A cap alone fixes only the first half; this fixes the
    second, for the notices that genuinely hold an owner decision (a card over
    budget, the goal at risk before the quota reset).

    The question is built by round-tripping a real <helmdeck-ask> block through
    ask.parse rather than hand-rolling the dict: shape and validation then keep
    exactly ONE owner (spine/ops/ask.py), so a PM question can never drift from
    a worker's, and an unusable option list is REJECTED there instead of
    rendering a dead panel.

    Posted as cls "bot" because that is the class the question channel is keyed
    on at BOTH ends - copilot.open_question (which routes_copilot._answer_text
    checks the tapped request_id against) and the app's openChatQuestion. A
    "pm"-class entry carrying a question renders as prose with buttons nobody
    can tap. The tapped answer therefore walks the ordinary chat path into
    HENRY, who has the hands to execute it - which is the right split: the PM
    detects and asks, Henry acts.

    ONE OPEN QUESTION AT A TIME - and this was got WRONG first.

    The chat offers exactly one answerable question (copilot.open_question:
    the newest, with nothing said after it). The first version of this
    function reasoned that the callers' dedup latches made collisions
    impossible. They do not: a latch stops the SAME notice repeating, not two
    DIFFERENT notices firing in one tick. Measured on the very first live tick
    after the rework, 2026-08-30 12:47 - two over-budget cards and the
    goal-at-risk warning posted back to back, and the two budget questions,
    the more urgent pair, were dead panels the moment the third landed.

    So: if a question is already open and unanswered, the FIRST one keeps the
    slot and this one goes to Henry instead. Nothing is lost - he gets the
    full text and the options as an escalation and can act on it himself or
    re-raise it once the owner has answered - and the owner keeps the property
    that every button he can see is a button that works. The guard reads the
    log, not a stored flag: answering (or anyone speaking) settles the open
    question by itself, so the slot re-arms with no state to clear.

    Degrades to a plain short line (never silence) if the question cannot be
    built or the chat write fails."""
    line = _short(text)
    try:
        from cells.copilot.chat import copilot
        pending = copilot.chat_question_open()
    except Exception as e:
        print("pm: open-question probe failed:", e)
        pending = None
    if pending:
        # `text`, not `line`: Henry is a machine consumer with no length budget
        # at all, and handing him the button-panel's clip meant he took over a
        # question whose second half had been thrown away - then reported back
        # on it, and THAT report got clipped again (the owner's 2026-08-30 13:13
        # / 14:04 cards both read "Uebernimm sie: ... vor dem Reset …"). Clip for
        # the surface that needs it, never for the one that doesn't.
        _to_henry("owner-ask-deferred", card=card,
                  detail=("Diese Frage an den Owner konnte nicht gestellt werden - im Chat "
                          "wartet bereits eine unbeantwortete Frage, und eine zweite waere "
                          "ein totes Panel. Uebernimm sie: %s (Optionen: %s)"
                          % (text, " / ".join(str(o.get("label") or o)
                                              for o in (options or [])))),
                  feed="Frage an Owner zurueckgestellt (andere Frage offen): %s" % line[:80])
        return False
    q = None
    try:
        from spine.ops import ask
        block = ("<helmdeck-ask>"
                 + json.dumps({"questions": [{"question": line,
                                              "header": header or line,
                                              "options": options}]},
                              ensure_ascii=False)
                 + "</helmdeck-ask>")
        q, _cleaned = ask.parse(block)
    except Exception as e:
        print("pm: ask build failed:", e)
    if not q:
        _escalate(line, tid=card or "", title=title)
        return False
    try:
        from cells.copilot.chat import copilot
        copilot.say(line, cls="bot", card=card or None, extra={"question": q})
    except Exception as e:
        print("pm: ask say failed:", e)
        return False
    try:
        from spine.comms import notify
        notify.escalate(title or _i18n.t("push.pmAlert"), line[:180],
                        card or _escalation_tid())
    except Exception as e:
        print("pm: ask push failed:", e)
    return True


def _escalation_tid():
    """Presence anchor for GOAL-LEVEL escalations (triangle tilt, quota pacing):
    they have no card of their own, but presence.plan wants a card id to decide
    silent/in-app/push. Use the most recently touched working card - that is
    where the owner's attention would be; with none, "" still gives the correct
    present/absent split (nobody can be 'focused' on no card)."""
    try:
        from cells.engineer.cards import sessions
        working = [t for t in sessions.list_tracks()
                   if t.get("lane") == "working" and not t.get("archived")]
        if working:
            return max(working, key=lambda t: t.get("updated")
                       or t.get("created") or "")["id"]
    except Exception:
        pass
    return ""


def _escalate(text, tid="", title=""):
    """An ESCALATION, vs. _say (chat only): the chat line always lands, AND the
    alert goes through notify's presence-aware pipe so it reaches the phone as
    a sealed FCM push when the owner is actually AWAY - the route Burn Guard
    proved (_push_burn). _say alone let the €843 card burn for days: its
    warnings sat in a chat nobody had open. Dedup stays with the caller
    (content hash / level ladder); notify.escalate only decides delivery
    (silent / in-app / push).

    The chat gets the line WHOLE; only the push is clipped, at its own edge
    (2026-08-30). Clipping once up front looked like it kept the two channels
    in agreement, but what it actually did was give the transcript the
    notification's length budget - the same inversion henry_broker._notify_owner
    warns about, and the one the owner reported twice (2026-08-28 "Nachrichten
    enden mitten im Wort", 2026-08-30 the Henry card ending in "…"). _short is
    used rather than a raw [:180] so the push cuts on a word boundary and says
    it was cut; the chat carries the full sentence the push is a pointer to."""
    _say(text)
    try:
        from spine.comms import notify
        notify.escalate(title or _i18n.t("push.pmAlert"), _short(text, chars=180),
                        tid or _escalation_tid())
    except Exception as e:
        print("pm: escalate push failed:", e)


def _read_activity(n=20):
    try:
        from spine.storage import db
        return db.pm_activity_tail(n)
    except Exception:                                            # noqa: BLE001
        return []
