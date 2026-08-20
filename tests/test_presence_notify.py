# -*- coding: utf-8 -*-
"""Headless test for PRESENCE-AWARE notifications (Phase 2.1-2.3).

The behaviour being fixed: HelmDeck pushed on every turn end, so working on the
board meant being notified about your own work - which is exactly how a
notification channel trains you to ignore it.

What this pins:
 1. The three tiers: focused -> silent, present-elsewhere -> in-app (no push),
    absent -> push. "connected" is never presence; only real user activity is.
 2. Freshness: a client that stopped reporting past FRESH_S is absent again, so
    an app left open on a desk does not mute notifications forever.
 3. Clock skew: a device reporting a future timestamp cannot be present forever.
 4. Dedup: one pending question pushes ONCE (first-only); a NEW question is news
    again, and steering the card re-arms the channel.
 5. Errors and background waits are NEVER pushed, whatever presence says.

Self-sandboxing: temp DB/events/settings, push transport stubbed - no network.
Run: py -3.12 tests/test_presence_notify.py
"""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-pres-")

from daemon.spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from daemon.spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from daemon.spine.comms import notify, presence

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


CARD = {"id": "c1", "task": "Login bauen"}
OTHER = {"id": "c2", "task": "Andere Karte"}

_pushed = []
notify.push_fcm = lambda title, body, track_id="": _pushed.append((title, track_id))


def _reset():
    presence.clear()
    _pushed.clear()
    notify.clear_dedup("c1")
    notify.clear_dedup("c2")


def test_tiers():
    print("3-tier policy:")
    _reset()
    check(presence.plan("c1") == "push", "nobody present -> push")

    _reset()
    presence.record("owner", "android", focused_card="c1", app_visible=True)
    check(presence.plan("c1") == "silent", "focused on THIS card -> silent")
    check(presence.plan("c2") == "inapp", "focused elsewhere -> in-app, not push")

    _reset()
    presence.record("owner", "android", focused_card="c1", app_visible=False)
    check(presence.plan("c1") == "inapp",
          "app backgrounded on this card -> in-app (not silent)")

    _reset()
    presence.record("owner", "android", focused_card=None, app_visible=True)
    check(presence.plan("c1") == "inapp", "present on the board -> in-app")

    # one focused client silences the others
    _reset()
    presence.record("owner", "web", focused_card=None, app_visible=True)
    presence.record("owner", "android", focused_card="c1", app_visible=True)
    check(presence.plan("c1") == "silent",
          "any focused client is enough to stay silent")


def test_freshness_and_skew():
    print("freshness:")
    _reset()
    presence.record("owner", "android", focused_card="c1", app_visible=True,
                    activity_at=time.time() - presence.FRESH_S - 5)
    check(presence.plan("c1") == "push",
          "a stale client is absent again (an app left open does not mute forever)")

    _reset()
    presence.record("owner", "android", focused_card="c1", app_visible=True,
                    activity_at=time.time() + 86400)
    check(presence.plan("c1") == "silent", "a future timestamp is clamped, still present")
    # ...and it must not be present forever: clamped to now, so it ages normally
    fresh = presence.snapshot()["clients"][0]["idle_s"]
    check(fresh >= 0, "clamped activity never reports negative idle (got %r)" % fresh)


def test_push_gating():
    print("card_event gating:")
    _reset()
    notify.card_event(CARD, "needs_you")
    check(len(_pushed) == 1, "absent owner gets the push")

    _reset()
    presence.record("owner", "android", focused_card="c1", app_visible=True)
    notify.card_event(CARD, "needs_you")
    check(not _pushed, "no push about the card the owner is looking at")

    _reset()
    presence.record("owner", "android", focused_card="c2", app_visible=True)
    notify.card_event(CARD, "needs_you")
    check(not _pushed, "present elsewhere -> in-app only, still no push")


def test_never_push():
    print("never-push reasons:")
    _reset()
    notify.card_event(dict(CARD, waiting_on="background"), "background")
    check(not _pushed, "a background wait never pushes (not the owner's move)")
    _reset()
    notify.card_event(CARD, "error")
    check(not _pushed, "an error never pushes")


def test_dedup():
    print("dedup:")
    _reset()
    q1 = dict(CARD, question={"id": "q-1", "questions": []})
    notify.card_event(q1, "question")
    notify.card_event(q1, "question")
    check(len(_pushed) == 1, "the same pending question pushes exactly once")

    q2 = dict(CARD, question={"id": "q-2", "questions": []})
    notify.card_event(q2, "question")
    check(len(_pushed) == 2, "a NEW question is news again")

    _reset()
    notify.card_event(CARD, "needs_you")
    notify.card_event(CARD, "needs_you")
    check(len(_pushed) == 1, "a repeated turn-end reason pushes once")
    notify.clear_dedup("c1")          # what a steer does
    notify.card_event(CARD, "needs_you")
    check(len(_pushed) == 2, "steering the card re-arms the channel")


test_tiers()
test_freshness_and_skew()
test_push_gating()
test_never_push()
test_dedup()

print()
if _fails:
    print("FAILED: %d check(s): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("ALL PRESENCE/NOTIFY CHECKS PASSED")
