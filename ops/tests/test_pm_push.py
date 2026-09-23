# -*- coding: utf-8 -*-
"""The push sweep (cells/copilot/planning/pm_push.py) - the PM half that asks
whether filed work is actually moving. Pins the four stall kinds, oldest-first
order, the once-a-day latch that re-arms on a NEW stall, and the length law on
the question line. Pure derivation over injected processes/tracks: no db, no
daemon, no LLM."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.copilot.planning import pm_push as pp

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


NOW = time.mktime(time.strptime("2026-09-23 16:00:00", "%Y-%m-%d %H:%M:%S"))
D = 86400.0

PROCS = [
    # never accepted, oldest (05.08.)
    {"id": "p-old", "status": "ready", "created": "2026-08-05 13:09:49",
     "request": "HIGHEST PRIO: HelmDeck-Android in den Google Play Store deployen.",
     "steps": [{"title": "a", "mode": "do", "state": "proposed", "track": None},
               {"title": "b", "mode": "do", "state": "proposed", "track": None}]},
    # never accepted, newer
    {"id": "p-goal", "status": "ready", "created": "2026-09-19 14:06:38",
     "request": "Ersten fremden User fuer HelmDeck finden bis 2026-09-30.",
     "steps": [{"title": "Show HN", "mode": "do", "state": "proposed", "track": None}] * 4},
    # running: a human step ready + a step whose card was archived
    {"id": "p-run", "status": "running", "created": "2026-09-18 09:11:19",
     "request": "Positionierung auf alle Kanaele ziehen, dann Show HN.",
     "steps": [{"title": "done1", "mode": "do", "state": "done", "track": "c-done"},
               {"title": "Post Show HN", "mode": "human", "state": "ready", "track": "c-human"},
               {"title": "Triage HN", "mode": "do", "state": "waiting", "track": "c-wait"}]},
    {"id": "p-dead", "status": "running", "created": "2026-08-14 14:56:01",
     "request": "iOS bauen",
     "steps": [{"title": "done1", "mode": "do", "state": "done", "track": "c-done"},
               {"title": "Signierung", "mode": "cowork", "state": "working", "track": "c-archived"},
               {"title": "Gone", "mode": "do", "state": "proposed", "track": "c-missing"}]},
    # finished / cancelled: never a stall
    {"id": "p-done", "status": "done", "created": "2026-08-01 00:00:00", "request": "x",
     "steps": [{"title": "a", "mode": "do", "state": "proposed", "track": None}]},
    {"id": "p-cancel", "status": "cancelled", "created": "2026-08-01 00:00:00", "request": "x",
     "steps": [{"title": "a", "mode": "do", "state": "proposed", "track": None}]},
]
TRACKS = [
    {"id": "c-done", "lane": "done", "created": "2026-09-18 10:00:00"},
    {"id": "c-human", "lane": "backlog", "status": "queued", "mode": "human",
     "created": "2026-09-18 09:23:12", "task": "HUMAN STEP: Post Show HN"},
    {"id": "c-wait", "lane": "backlog", "status": "queued", "created": "2026-09-18 09:23:13"},
    {"id": "c-archived", "lane": "review", "status": "bounced", "archived": True,
     "updated": "2026-08-20 12:00:00"},
    # parked on the owner for two days
    {"id": "c-parked", "lane": "working", "status": "needs_you", "task": "Wear font fix",
     "created": "2026-09-21 10:00:00", "updated": "2026-09-21 12:00:00"},
    # parked one hour ago: NOT a stall yet
    {"id": "c-fresh", "lane": "working", "status": "needs_you", "task": "fresh",
     "created": "2026-09-23 15:00:00", "updated": "2026-09-23 15:00:00"},
    # archived needs_you: never a stall
    {"id": "c-arch-parked", "lane": "working", "status": "needs_you", "archived": True,
     "task": "old", "updated": "2026-09-01 12:00:00"},
]

items = pp.derive(NOW, processes=PROCS, tracks=TRACKS, goal_pid="p-goal")
kinds = [(x["kind"], x["key"]) for x in items]
print("   derived:", kinds)

# 1) the four kinds, nothing from done/cancelled/fresh/archived
check({x["kind"] for x in items} == {"proposal", "human", "dead", "parked"}, "all four stall kinds derived")
check(not any("p-done" in x["key"] or "p-cancel" in x["key"] for x in items), "done/cancelled processes never stall")
check(not any(x["card"] == "c-fresh" for x in items), "a needs_you card parked 1h is not a stall")
check(not any(x["card"] == "c-arch-parked" for x in items), "an archived parked card is not a stall")

# 2) both never-accepted processes, the human step, both dead steps, the parked card
check(sum(1 for x in items if x["kind"] == "proposal") == 2, "two never-accepted processes")
check(sum(1 for x in items if x["kind"] == "human") == 1, "one human step waiting")
check(sum(1 for x in items if x["kind"] == "dead") == 1, "archived + missing step cards collapse to ONE dead item per process")
check(next(x for x in items if x["kind"] == "dead")["label"].endswith("2 Schritt-Karten weg, Kette steht"), "dead item counts its steps")
check(sum(1 for x in items if x["kind"] == "parked") == 1, "one parked card")

# 3) order: the GOAL process first, then human > proposal > dead > parked, oldest within
check(items[0]["key"] == "proposal:p-goal", "the goal's own process leads")
check([x["kind"] for x in items[1:]] == ["human", "proposal", "dead", "parked"], "then human > proposal > dead > parked")
plain = pp.derive(NOW, processes=PROCS, tracks=TRACKS, goal_pid="")
check([x["key"] for x in plain if x["kind"] == "proposal"] == ["proposal:p-old", "proposal:p-goal"], "no goal pid -> oldest first within a kind")

# 4) the option verbs Henry's brief executes
opts = {x["kind"]: x["option"] for x in items}
check(opts["proposal"].startswith("Starten: "), "proposal -> 'Starten: '")
check(opts["human"].startswith("Erledigt: "), "human step -> 'Erledigt: '")
check(opts["dead"].startswith("Streichen: "), "dead chain -> 'Streichen: <prozess>'")
check(opts["parked"].startswith("Zeig mir: "), "parked card -> 'Zeig mir: '")

# 5) the question: two sentences, goal deadline, <= 6 options, obeys the clip law
line, header, options = pp.question(items, "Ersten fremden User finden bis 2026-09-30.", NOW)
print("   line:", line)
from spine.comms import notice
check(notice.short(line) == line, "question line survives notice.short untouched")
check(line.startswith("Ziel in 7 Tagen"), "goal deadline from the goal text (7 days)")
check("seit 49 Tagen" in line, "oldest stall age in the line")
check(len(options) <= 6 and options[-1]["label"] == "Nichts davon", "<= 6 options, 'Nichts davon' last")
check(header == "Vorantreiben", "header")
check(pp.goal_deadline("kein datum") is None, "no date in goal -> no deadline")

# 6) the latch: once per day, re-armed by a NEW stall, cleared when nothing stalls
sent, feed = [], []
st = {}
pp.derive_real = pp.derive
pp.derive = lambda now=None, processes=None, tracks=None, goal_pid=None: pp.derive_real(now, PROCS, TRACKS, "p-goal")
ok1 = pp.sweep(st, NOW, ask=lambda l, o, h: sent.append((l, o, h)) or True,
               feed=lambda k, m: feed.append(m), save=lambda s: None)
ok2 = pp.sweep(st, NOW + 3600, ask=lambda l, o, h: sent.append((l, o, h)) or True,
               feed=lambda k, m: feed.append(m), save=lambda s: None)
check(ok1 and not ok2 and len(sent) == 1, "asked once, not again an hour later")
check(st["push_asked"]["day"] == "20260923" and len(st["push_asked"]["keys"]) == len(items), "latch carries day + keys")
check(feed and feed[0].startswith("Vorantreiben: %d Stillstaende" % len(items)), "activity feed line")
# a new stall the same day -> asks again
more = PROCS + [{"id": "p-new", "status": "ready", "created": "2026-09-23 15:00:00", "request": "neu",
                 "steps": [{"title": "a", "mode": "do", "state": "proposed", "track": None}]}]
pp.derive = lambda now=None, processes=None, tracks=None, goal_pid=None: pp.derive_real(now, more, TRACKS, "p-goal")
ok3 = pp.sweep(st, NOW + 7200, ask=lambda l, o, h: sent.append((l, o, h)) or True,
               feed=lambda k, m: None, save=lambda s: None)
check(ok3 and len(sent) == 2, "a NEW stall the same day re-arms the question")
# next day, same stalls -> asks again (daily heartbeat)
ok4 = pp.sweep(st, NOW + D, ask=lambda l, o, h: sent.append((l, o, h)) or True,
               feed=lambda k, m: None, save=lambda s: None)
check(ok4 and len(sent) == 3, "next day -> asked again")
# nothing stalls -> latch cleared, nothing asked
pp.derive = lambda now=None, processes=None, tracks=None, goal_pid=None: []
ok5 = pp.sweep(st, NOW + 2 * D, ask=lambda l, o, h: sent.append((l, o, h)) or True,
               feed=lambda k, m: None, save=lambda s: None)
check(not ok5 and "push_asked" not in st and len(sent) == 3, "no stalls -> silent, latch cleared")
pp.derive = pp.derive_real

print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
