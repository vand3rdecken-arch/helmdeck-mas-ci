# -*- coding: utf-8 -*-
"""The EVENT MIRROR: a card's question / result / blocker as a message in the
owner's Henry chat (owner decree 2026-08-29, "der Henry-Chat ist der zentrale
Posteingang").

The defect it closes: when a working card asked something or handed work back,
that only ever reached the CARD's own transcript. The owner had to know which
card to open. On the watch and the glasses that is not merely inconvenient -
there is no card navigation there at all, only the Henry chat, so a card's
question was structurally unreachable from the two surfaces most likely to be
in reach when it arrives.

WHERE THIS HANGS, and why it is not a poller
--------------------------------------------
`notify.card_event(track, status)` is already the ONE place every
owner-actionable card transition passes through - `_finish_turn` calls it with
the reason it just computed, the zombie reconciler calls it, the lane pipeline
calls it. Folding the mirror in THERE means the chat line is written at event
time from the runtime's own signal, by one owner, with no second scan of the
board and no stored flag anybody has to remember to clear. Anything else would
be the reconstruction CLAUDE.md's no-monkey-patches law forbids.

WHAT THIS OWNS, and what it deliberately does not
-------------------------------------------------
Only `question` -> Frage and `needs_you` -> Ergebnis. The terminal lane
outcomes (`done`, `bounced`) already speak in the board chat through
lanemachine._say_card, and have since the lane-visibility fix; mirroring them
here as well would print every accept and every red gate TWICE. `_say_card`
stays their one owner and simply gained the same label/binding fields (it now
calls say_card() below). `background` is excluded for the reason notify's own
NEVER_PUSH excludes it: a card waiting on its own task is not the owner's move.

DEDUP IS SEPARATE FROM THE PUSH'S, ON PURPOSE
---------------------------------------------
This runs BEFORE notify.should_push and never consults it. A push is suppressed
when the owner is present, when quiet hours are on, or when it already fired -
all correct for something that BUZZES, all wrong for an inbox. notify's own
comment says a suppressed push is fine because "in-app is enough"; this module
is what makes that sentence true. It keeps its own registry (`_last`) keyed by
notify._dedup_key so the two channels agree on what "the same news" means
without sharing the state that decides delivery.
"""
import threading

from spine.comms import notice as _notice

# The chat entry class. NOT "pm": that is Henry's own proactive voice, and the
# watch's transcript filter keeps a per-class allowlist - a mirror line needs to
# be distinguishable from a Henry remark by both the phone (which draws a
# card-labelled header and, for a question, real option buttons) and the watch.
CLS = "card"

KIND_QUESTION = "question"     # the card is ASKING - the owner's move
KIND_RESULT = "result"         # a turn ended and handed work back
KIND_BLOCKER = "blocker"       # the card cannot proceed on its own
KIND_CLOSED = "closed"         # the card is GONE (deleted/archived) - nothing bound to it can be answered any more

# notify reason -> mirror kind. Absent reasons are not mirrored at all (see the
# module docstring for why `done`/`bounced`/`background` are not here).
REASONS = {"question": KIND_QUESTION, "needs_you": KIND_RESULT}

# A card's closing reply is mirrored WHOLE. There is deliberately NO length
# constant here, and the one that stood in its place (RESULT_MAX = 400) was
# removed on an owner decision (2026-08-30) taken against measured data.
#
# Its premise was: "this is an inbox entry, not the document - the full text is
# one tap away in the card transcript." That premise holds for a DISPATCHED
# worker card, which has its own conversation the owner opens. It does not hold
# for a card the owner started FROM THIS CHAT: there the Henry chat IS the
# card's conversation and there is no second place to tap to. Measured on the
# owner's own log the day it was removed: 10 of 10 clipped mirror lines were
# exactly those cards, each losing ~3.600-4.300 characters - including the
# answer to the question he had asked in that same chat minutes earlier.
#
# "Whole" is not "unbounded": the reply is already capped where it is actually
# stored (turnrunner.REPLY_MAX, 6000), and the transcript folds a long message
# behind card_transcript.tsx's "mehr anzeigen" toggle instead of throwing it
# away. A cap here was a FOURTH answer to "how long may a line be", on the one
# surface that can scroll - see spine/comms/notice.short's docstring for which
# channels legitimately have a length budget.

_last = {}
_lock = threading.Lock()


def short_name(track):
    """A card's KURZNAME for the label - what the owner would call it out loud.

    The task text's first line, clipped on a word boundary. Falls back to the
    id, never to "" : a mirror line whose label is blank is worse than one
    labelled with an ugly id, because the owner cannot tell WHICH card spoke.

    The clipping itself moved to spine.comms.notice.label (2026-08-30) because
    the PM's budget question needs the same label and lives in another cell -
    it was shipping a raw [:60] slice that cut mid-word. Same rule, one owner;
    this keeps the track-shaped signature and the id fallback."""
    return _notice.label(((track or {}).get("task") or ""),
                         fallback=(track or {}).get("id") or "?")


def say_card(track, kind, text, question=None):
    """Write ONE labelled card message into the owner's Henry chat.

    Public because the lane pipeline uses it too (lanemachine._say_card): a lane
    outcome is a card RESULT and must carry the same binding and label as a
    mirrored turn end, or the owner would get two visually different kinds of
    card news in one transcript and only one of them would be answerable.

    Best-effort, like everything downstream of copilot.say - reporting a card
    event must never break the event."""
    if not text:
        return False
    try:
        from cells.copilot.chat import copilot
        tid = (track or {}).get("id") or ""
        extra = {"kind": kind, "cardName": short_name(track)}
        if question:
            # The WHOLE ask block rides along, not just a summary: the phone
            # renders the real options through the existing QuestionPanel and
            # answers with `question["id"]` as request_id, which is what makes a
            # stale pick fail loudly (409) instead of silently answering the
            # card's NEXT question. A summary string could not carry that id.
            extra["question"] = question
        copilot.say(text, cls=CLS, card=tid or None, extra=extra)
        return True
    except Exception:
        return False


def say_closed(track, how, actor="owner"):
    """The card is GONE - say so IN THE TRANSCRIPT, bound to its id.

    THE DEFECT (owner screenshot 2026-09-11 18:02): a deleted card's last
    question stayed the newest unsettled `card` entry in the Henry chat, so
    the composer kept pinning that card as the reply target on every device
    and every send died with 'no such card' - there was no way to change the
    context, because the target is DERIVED from the transcript (chat.tsx
    openChatQuestion: a card question is open until a later entry bound to
    the same card lands) and nothing bound to the card ever landed again.
    This line is that entry, written by the ONE owner of the transition
    (cardadmin.delete_track / archive_track) at event time - not a client
    heuristic, not a stored flag. `how` is "deleted" | "archived"."""
    label = {"deleted": "geloescht", "archived": "archiviert"}.get(how, how)
    return say_card(track, KIND_CLOSED, "Karte %s (%s)." % (label, actor))


def mirror(track, status):
    """Fold a card transition into the Henry chat. Called by notify.card_event.

    Returns True when a line was written - for tests and for the caller's log,
    never as control flow for the push (the two channels decide independently).
    """
    kind = REASONS.get(status)
    if not kind:
        return False
    try:
        tid = (track or {}).get("id") or ""
        if not tid:
            return False
        # Build the line FIRST, claim the dedup key only once there is something
        # to say. Claiming up front would let a transition with nothing to print
        # (a turn that ended silently) burn the key, so the next real message
        # under the same key - the one the owner actually needs - would be
        # swallowed as a repeat of a message that was never written.
        q = None
        if kind == KIND_QUESTION:
            from spine.ops import ask
            q = track.get("question") or {}
            text = ask.summary(q) or ""
        else:
            # KIND_RESULT: the card's own closing words, WHOLE (see the note
            # where RESULT_MAX used to live). `last_reply` is already the
            # ask-block-stripped reply _finish_turn persisted, so a raw
            # <helmdeck-ask> can never leak into the inbox.
            text = (track.get("last_reply") or "").strip()
        if not text:
            return False
        from spine.comms import notify
        key = notify._dedup_key(track, status)
        with _lock:
            if _last.get(tid) == key:
                return False
            _last[tid] = key
        return say_card(track, kind, text, question=q or None)
    except Exception:
        return False


def clear_dedup(track_id):
    """The card moved on, so its next transition is news again. Paired with
    notify.clear_dedup at exactly the same call site (a turn STARTING), because
    the two registries must re-arm together - if only the push's cleared, a
    steered card would buzz the phone about a question the chat refused to
    reprint, and the owner would tap a notification into a chat that never
    mentioned it."""
    with _lock:
        _last.pop(track_id, None)
