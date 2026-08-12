# -*- coding: utf-8 -*-
"""Per-card cost watchdog + presence-aware PM escalation - pin the invariants
from the €843/226M-token card (no PM guardrail while the owner was steering):

1. _cost_watch self-baselines a card on its FIRST tick in 'working' and never
   escalates on the baseline itself (a card already expensive at deploy time
   must not alert-storm).
2. Cost escalates only when growth is BOTH >= the € floor AND to >= factor x
   the last level, then RE-ARMS at the new level (a ladder 5 -> 15 -> 45 ...,
   not one ping and silence, not a ping per tick).
3. ctx_tokens is an absolute floor: escalate once on crossing, CLEAR when
   compaction brings it back under, escalate again on the next crossing.
4. Leaving 'working' drops the watch entry; re-entering re-baselines at the
   current meters (no false alarm on the accumulated history).
5. notify.escalate applies the 3-tier presence policy: absent -> push,
   focused on that card -> silent, present elsewhere -> in-app; "" track id
   still pushes when absent (goal-level alerts).
6. pm._escalate = chat line ALWAYS + notify pipe; goal-level alerts borrow the
   proxy card id.

Self-sandboxing: pm's _pm/_save_loopstate/_activity/_escalate and notify's
push_fcm are patched - nothing touches disk, chat, FCM or the real board.

Run: py -3.12 tests/test_cost_watch.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)
import pm
import notify
import presence

FAILS = []


def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond:
        FAILS.append(name)


def track(tid, lane="working", cost=0.0, ctx=0, archived=False):
    return {"id": tid, "lane": lane, "ai_cost": cost, "ctx_tokens": ctx,
            "archived": archived, "task": "Testkarte " + tid}


# --- sandbox pm --------------------------------------------------------------
_orig_escalate = pm._escalate
pm._pm = lambda: dict(pm.PM_DEFAULTS)          # floor €5, factor 3x, ctx 150k
pm._save_loopstate = lambda s: None
pm._activity = lambda *a, **k: None
ESC = []
pm._escalate = lambda text, tid="", title="": ESC.append(
    {"text": text, "tid": tid, "title": title})

print("1. baseline on first tick, no escalation")
st = {}
pm._cost_watch(st, [track("a", cost=1.0, ctx=40_000)])
check("no escalation on the baseline tick", not ESC)
check("baseline snapshotted", st["cost_watch"]["a"]["base"] == 1.0)

print("2. growth under the floor stays silent")
pm._cost_watch(st, [track("a", cost=4.0)])
check("under-floor growth silent (+3 < 5)", not ESC)

print("3. floor crossed -> ONE cost escalation, re-armed")
pm._cost_watch(st, [track("a", cost=6.5)])
check("escalated once", len(ESC) == 1)
check("escalation names the card id", ESC and ESC[0]["tid"] == "a")
check("cost title used", ESC and ESC[0]["title"] == pm._i18n.t("push.pmCost"))
check("level re-armed at current cost", st["cost_watch"]["a"]["level"] == 6.5)
pm._cost_watch(st, [track("a", cost=6.5)])
check("same level does not re-fire", len(ESC) == 1)

print("4. the factor guard: floor growth alone is not enough")
pm._cost_watch(st, [track("a", cost=12.0)])       # +5.5 >= floor, but < 3 x 6.5
check("under 3x the level stays silent", len(ESC) == 1)

print("5. the ladder: 3x the level + floor fires again")
pm._cost_watch(st, [track("a", cost=25.0)])
check("next rung escalates", len(ESC) == 2)

print("6. ctx floor: fire on crossing, clear under, fire again")
pm._cost_watch(st, [track("a", cost=25.0, ctx=160_000)])
check("ctx crossing escalates", len(ESC) == 3 and ESC[2]["title"] == pm._i18n.t("push.pmCtx"))
pm._cost_watch(st, [track("a", cost=25.0, ctx=170_000)])
check("still hot does not re-fire", len(ESC) == 3)
pm._cost_watch(st, [track("a", cost=25.0, ctx=90_000)])
check("compaction clears the corner", len(ESC) == 3 and not st["cost_watch"]["a"]["ctx_hot"])
pm._cost_watch(st, [track("a", cost=25.0, ctx=155_000)])
check("next crossing escalates again", len(ESC) == 4)

print("7. leaving 'working' drops the entry; re-entry re-baselines")
pm._cost_watch(st, [track("a", lane="review", cost=100.0)])
check("watch entry dropped on leave", "a" not in st["cost_watch"])
pm._cost_watch(st, [track("a", cost=100.0)])
check("re-entry re-baselines, no false alarm", len(ESC) == 4
      and st["cost_watch"]["a"]["base"] == 100.0)

print("8. archived working cards are ignored")
pm._cost_watch(st, [track("z", cost=50.0, archived=True)])
check("archived card not watched", "z" not in st["cost_watch"])

print("9. notify.escalate: 3-tier presence policy")
PUSHED = []
_orig_push = notify.push_fcm
notify.push_fcm = lambda title, body, tid="": PUSHED.append((title, body, tid)) or True
try:
    presence.clear()
    check("absent -> push", notify.escalate("T", "B", "a") and len(PUSHED) == 1)
    check("goal-level ('' id) absent -> push", notify.escalate("T", "B", "") and len(PUSHED) == 2)
    presence.record("owner", "phone", focused_card="a", app_visible=True)
    check("focused on the card -> silent", not notify.escalate("T", "B", "a") and len(PUSHED) == 2)
    check("present elsewhere -> in-app only", not notify.escalate("T", "B", "other")
          and len(PUSHED) == 2)
    check("goal-level while present -> in-app only", not notify.escalate("T", "B", "")
          and len(PUSHED) == 2)
finally:
    notify.push_fcm = _orig_push
    presence.clear()

print("10. pm._escalate: chat always, notify pipe with proxy id")
SAID, PIPED = [], []
pm._say = lambda text: SAID.append(text)
pm._escalation_tid = lambda: "proxy-card"
_orig_notify_escalate = notify.escalate
notify.escalate = lambda title, body, tid="": PIPED.append((title, body, tid)) or True
try:
    _orig_escalate("ein Alarm", tid="", title="")
    check("chat line always lands", SAID == ["ein Alarm"])
    check("goal-level borrows the proxy card id", PIPED and PIPED[0][2] == "proxy-card")
    check("default title is the generic PM alert", PIPED[0][0] == pm._i18n.t("push.pmAlert"))
    _orig_escalate("x" * 500, tid="card-7", title="T")
    check("explicit card id wins over the proxy", PIPED[1][2] == "card-7")
    check("push body clipped to 180 chars", len(PIPED[1][1]) == 180)
finally:
    notify.escalate = _orig_notify_escalate

print()
if FAILS:
    print("FAILED: %d check(s): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL COST-WATCH CHECKS PASSED")
