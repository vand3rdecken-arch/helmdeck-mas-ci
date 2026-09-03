# -*- coding: utf-8 -*-
"""Per-card BUDGET watchdog + presence-aware PM escalation - pin the invariants
from the 843/226M-token card (no PM guardrail while the owner was steering),
with the owner-decreed PMBOK units: thresholds are ABSOLUTE shares of the REAL
budget (% of the weekly quota on Max, EUR vs the monthly cap on API, shadow-$
only while calibration is cold), scaled by PRIORITY and by how much work shares
the window - never flat shadow-euros.

1. _cost_watch self-baselines a card on its FIRST tick in 'working' and never
   escalates on the baseline itself.
2. Calibrated Max: a MEDIUM card's BAC = watch_base_pct (5%); escalate at 1x,
   re-arm at 2x, 4x ... (control thresholds - a ladder, not a ping per tick,
   and one huge turn fires ONE rung, not a backlog).
3. Priority earns budget: low = 0.5x the base, urgent = 2x.
4. Crowding: (100% - reserve) split over the working set caps the BAC when
   many cards share the window.
5. Unit degradation: cost-calibration missing -> token calibration; both cold
   -> API-equivalent $ ladder (never labeled EUR); API plan with a cap -> EUR.
6. ctx_tokens absolute floor: fire on crossing, clear under (compaction),
   fire again on the next crossing.
7. Leaving 'working' drops the watch entry; re-entering re-baselines.
8. notify.escalate applies the 3-tier presence policy; "" track id still
   pushes when absent (goal-level alerts).
9. pm._escalate = chat line ALWAYS + notify pipe; goal-level alerts borrow
   the proxy card id.

Self-sandboxing: pm's _pm/_save_loopstate/_activity/_escalate, events'
plan_effective/plan_calibration and notify's push_fcm are patched - nothing
touches disk, chat, FCM or the real board.

Run: py -3.12 ops/tests/test_cost_watch.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)
from cells.copilot import pm
from cells.copilot import pm_watchdog
from cells.copilot import pm_comm
from spine.comms import notify
from spine.comms import notice
from spine.comms import presence
from spine.storage import events

FAILS = []


def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond:
        FAILS.append(name)


def track(tid, lane="working", cost=0.0, tok=0, ctx=0, prio="medium", archived=False):
    return {"id": tid, "lane": lane, "ai_cost": cost, "tokens_in": tok, "tokens_out": 0,
            "ctx_tokens": ctx, "priority": prio, "archived": archived,
            "task": "Testkarte " + tid}


# --- sandbox pm + events -----------------------------------------------------
_orig_escalate = pm._escalate
CFG = dict(pm.PM_DEFAULTS)                     # base 5%, reserve 40%, floor $5, ctx 150k
pm._pm = lambda: dict(CFG)   # _cost_watch imports _pm LAZILY (fresh each call) - this seam still works
pm_watchdog._save_loopstate = lambda s: None
pm_watchdog._activity = lambda *a, **k: None
# The two OWNER-FACING seams the watchdog now uses (owner decree 2026-08-30):
# a budget rung ASKS the owner with real buttons, a context crossing is handed
# to HENRY and never reaches the owner at all. ESC keeps its name so every
# budget assertion below still reads as "what the owner was told".
ESC = []
pm_watchdog._ask_owner = lambda text, options, header="", card="", title="": ESC.append(
    {"text": text, "tid": card, "title": title, "options": options, "header": header})
HENRY = []
pm_watchdog._to_henry = lambda kind, detail, card=None, feed="": HENRY.append(
    {"kind": kind, "detail": detail, "card": card, "feed": feed})
PLAN = ["max"]                                 # mutable so scenarios can flip it
CALIB = [{"cost_per_pct": 1.0, "tokens_per_pct": 1_000_000.0}]   # $1 = 1%, 1M tok = 1%
events.plan_effective = lambda s=None: (PLAN[0], "test")
events.plan_calibration = lambda ev=None, s=None: CALIB[0]

print("1. baseline on first tick, no escalation")
st = {}
pm._cost_watch(st, [track("a", cost=1.0, ctx=40_000)])
check("no escalation on the baseline tick", not ESC)
check("baseline snapshotted", st["cost_watch"]["a"]["cost"] == 1.0)

print("2. calibrated Max: medium BAC = 5% of the week, ladder 1x/2x/4x")
pm._cost_watch(st, [track("a", cost=5.0)])     # spent 4% < 5%
check("under budget stays silent", not ESC)
pm._cost_watch(st, [track("a", cost=6.5)])     # spent 5.5% >= 5%
check("over budget escalates once", len(ESC) == 1)
check("escalation names the card id", ESC and ESC[0]["tid"] == "a")
check("budget title used", ESC and ESC[0]["title"] == pm._i18n.t("push.pmCost"))
check("unit is the weekly quota, not EUR",
      ESC and "Wochenkontingent" in ESC[0]["text"] and "€" not in ESC[0]["text"])
check("re-armed at 2x BAC", st["cost_watch"]["a"]["mult"] == 2.0)
pm._cost_watch(st, [track("a", cost=6.5)])
check("same rung does not re-fire", len(ESC) == 1)
pm._cost_watch(st, [track("a", cost=9.5)])     # spent 8.5% < 10%
check("under the next rung stays silent", len(ESC) == 1)
pm._cost_watch(st, [track("a", cost=12.0)])    # spent 11% >= 10%
check("next rung escalates", len(ESC) == 2)

print("3. one huge turn fires ONE rung, mult jumps past the spend")
st = {}; ESC.clear()
pm._cost_watch(st, [track("b", cost=0.0)])
pm._cost_watch(st, [track("b", cost=23.0)])    # spent 23% -> rungs 5,10,20 all crossed
check("single escalation for the jump", len(ESC) == 1)
check("mult jumped past the spend (next rung 40%)", st["cost_watch"]["b"]["mult"] == 8.0)

print("4. priority earns budget: low 2.5%, urgent 10%")
st = {}; ESC.clear()
pm._cost_watch(st, [track("l", prio="low")])
pm._cost_watch(st, [track("l", prio="low", cost=2.0)])       # 2% < 2.5%
check("low under its smaller budget: silent", not ESC)
pm._cost_watch(st, [track("l", prio="low", cost=2.6)])       # 2.6% >= 2.5%
check("low over 2.5%: escalates", len(ESC) == 1)
st = {}; ESC.clear()
pm._cost_watch(st, [track("u", prio="urgent")])
pm._cost_watch(st, [track("u", prio="urgent", cost=9.5)])    # 9.5% < 10%
check("urgent gets 2x the budget: still silent at 9.5%", not ESC)
pm._cost_watch(st, [track("u", prio="urgent", cost=10.5)])
check("urgent over 10%: escalates", len(ESC) == 1)

print("5. crowding: the pool (100-reserve) caps BAC when work piles up")
st = {}; ESC.clear()
crowd = [track("c%d" % i) for i in range(15)]   # 15 medium: 60%/15 = 4% < base 5%
pm._cost_watch(st, crowd)                        # baselines
grown = [track("c0", cost=4.4)] + crowd[1:]      # 4.4% >= 4% crowded BAC
pm._cost_watch(st, grown)
check("crowded BAC (4%) fires where solo (5%) would not", len(ESC) == 1
      and ESC[0]["tid"] == "c0")

print("6. unit degradation: tokens when cost-calib missing, $ ladder when cold")
CALIB[0] = {"tokens_per_pct": 1_000_000.0}       # no cost basis -> token basis
st = {}; ESC.clear()
pm._cost_watch(st, [track("t")])
pm._cost_watch(st, [track("t", tok=5_500_000)])  # 5.5% of the week in tokens
check("token calibration fires the same 5% budget", len(ESC) == 1)
CALIB[0] = None                                  # calibration cold
st = {}; ESC.clear()
pm._cost_watch(st, [track("d")])
pm._cost_watch(st, [track("d", cost=4.0)])
check("cold: under the $5 floor stays silent", not ESC)
pm._cost_watch(st, [track("d", cost=5.5)])
check("cold: shadow-$ ladder fires", len(ESC) == 1)
check("cold: labeled API-equivalent $, never EUR",
      "$" in ESC[0]["text"] and "API-Gegenwert" in ESC[0]["text"])
CALIB[0] = {"cost_per_pct": 1.0, "tokens_per_pct": 1_000_000.0}

print("7. API plan with a cap: budget in real money")
PLAN[0] = "api"; CFG["monthly_eur"] = 200        # medium BAC = 5% of 200 = 10
st = {}; ESC.clear()
pm._cost_watch(st, [track("e")])
pm._cost_watch(st, [track("e", cost=9.0)])
check("api: under the EUR budget stays silent", not ESC)
pm._cost_watch(st, [track("e", cost=10.5)])
check("api: over the EUR budget escalates", len(ESC) == 1 and "€" in ESC[0]["text"])
PLAN[0] = "max"

print("8. ctx floor: hand to HENRY on crossing, clear under, hand again")
st = {}; ESC.clear(); HENRY.clear()
pm._cost_watch(st, [track("a", ctx=40_000)])
pm._cost_watch(st, [track("a", ctx=160_000)])
check("ctx crossing goes to Henry", len(HENRY) == 1 and HENRY[0]["kind"] == "context-bloat")
check("ctx crossing names the card", HENRY and HENRY[0]["card"] == "a")
# the whole point of the 2026-08-30 decree: this one is a work order for Henry
# (compact/split/close), so the owner must not be woken by it at all
check("ctx crossing never reaches the owner", not ESC)
pm._cost_watch(st, [track("a", ctx=170_000)])
check("still hot does not re-fire", len(HENRY) == 1)
pm._cost_watch(st, [track("a", ctx=90_000)])
check("compaction clears the corner", len(HENRY) == 1 and not st["cost_watch"]["a"]["ctx_hot"])
pm._cost_watch(st, [track("a", ctx=155_000)])
check("next crossing hands over again", len(HENRY) == 2)

print("8b. an over-budget rung ASKS the owner, with real buttons")
st = {}; ESC.clear(); HENRY.clear()
pm._cost_watch(st, [track("a", cost=1.0)])
pm._cost_watch(st, [track("a", cost=7.0)])
check("over budget asks the owner", len(ESC) == 1)
check("the ask carries tappable options", ESC and len(ESC[0]["options"]) >= 2
      and all(o.get("label") for o in ESC[0]["options"]))
# written short ENOUGH that the writer's clip never fires - a cap that has to
# engage would take the actionable half of the sentence with it
check("the ask already obeys the length law untouched",
      ESC and notice.short(ESC[0]["text"]) == ESC[0]["text"])

print("9. leaving 'working' drops the entry; re-entry re-baselines")
st = {}; ESC.clear()
pm._cost_watch(st, [track("a", cost=1.0)])
pm._cost_watch(st, [track("a", lane="review", cost=100.0)])
check("watch entry dropped on leave", "a" not in st["cost_watch"])
pm._cost_watch(st, [track("a", cost=100.0)])
check("re-entry re-baselines, no false alarm", not ESC
      and st["cost_watch"]["a"]["cost"] == 100.0)

print("10. archived working cards are ignored")
pm._cost_watch(st, [track("z", cost=50.0, archived=True)])
check("archived card not watched", "z" not in st["cost_watch"])

print("11. notify.escalate: 3-tier presence policy")
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

print("12. pm._escalate: chat always, notify pipe with proxy id")
SAID, PIPED = [], []
pm_comm._say = lambda text: SAID.append(text)
pm_comm._escalation_tid = lambda: "proxy-card"
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
