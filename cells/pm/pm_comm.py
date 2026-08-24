# -*- coding: utf-8 -*-
"""PM communication layer - extracted from pm.py (god-file breakup, see
spine/registry/debt.py daemon-god-files). Plain-language "what am I
doing" (DAU): an append-only activity feed plus the two ways the PM reaches
the owner - _say (chat only) and _escalate (chat + presence-aware push).
Computed from the REAL board, never LLM-guessed, so it's reliable.

Depends only on i18n/copilot/sessions/notify - nothing back into pm.py's own
logic, so pm.py (and the extracted pm_resolve.py) import these at module
level with no cycle. PLANS is recomputed independently rather than imported
from pm.py (same value, process-idempotent - importing it would cycle back)."""
import json
import os
import time

from spine.registry import i18n as _i18n
from daemon.paths import DAEMON_ROOT as ROOT

PLANS = os.path.join(ROOT, "pm")
_ACTIVITY = os.path.join(PLANS, "activity.jsonl")


def _activity(kind, msg, card=None):
    """Append one plain-language line the PM 'said' (planned/started/blocked)."""
    try:
        os.makedirs(PLANS, exist_ok=True)
        with open(_ACTIVITY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), "kind": kind,
                                "msg": msg, "card": card}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _say(text):
    """The PM SPEAKS TO YOU: post a message into the owner's board chat so the
    chat MOVES on its own - real proactive communication, not just a silent feed.
    You can reply there and steer it. (cls 'pm' = a PM-authored message.)
    One voice: the shared writer in copilot.say, which the lane pipeline uses
    too - so everything non-interactive speaks in the same chat."""
    try:
        from cells.copilot import copilot
        copilot.say(text, cls="pm")
    except Exception:
        pass


def _escalation_tid():
    """Presence anchor for GOAL-LEVEL escalations (triangle tilt, quota pacing):
    they have no card of their own, but presence.plan wants a card id to decide
    silent/in-app/push. Use the most recently touched working card - that is
    where the owner's attention would be; with none, "" still gives the correct
    present/absent split (nobody can be 'focused' on no card)."""
    try:
        from cells.engineer import sessions
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
    (silent / in-app / push)."""
    _say(text)
    try:
        from spine.comms import notify
        notify.escalate(title or _i18n.t("push.pmAlert"), text[:180],
                        tid or _escalation_tid())
    except Exception as e:
        print("pm: escalate push failed:", e)


def _read_activity(n=20):
    try:
        with open(_ACTIVITY, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        return []
