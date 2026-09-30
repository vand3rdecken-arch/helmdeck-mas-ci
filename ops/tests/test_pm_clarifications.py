# -*- coding: utf-8 -*-
"""Headless test: the owner's clarifications reach the ONE planner (Henry) and
the question-dedup primitive still holds.

Since 2026-09-30 there is no PM plan turn (owner: "alles zusammen legen"):
clarifications ride in the GOAL evidence (goal_drive.goal_state/goal_line,
rendered into both board snapshots and every goal wake). What stays under
test here:

  1. clarifications recorded against the CURRENT goal reach the goal
     evidence; a goal change drops them
  2. _same_question sits in the MEASURED gap (duplicate_check depends on it)
  3. card Q&A never evicts a chat clarification (2026-09-15: 11 macOS-card
     answers pushed "iOS ist genehmigt" out of the ring)

Self-sandboxing: the loop state is a db row, the db is a temp file - no
daemon, no board, no network, no model."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "test.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.copilot.planning import pm, goal_drive

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


GOAL = "Play-Store-Launch der App"
pm.set_goal(GOAL)


def facts():
    return goal_drive.goal_state(tracks=[], processes=[], ev=[], goal_pid="")["facts"]


print("\n[1] owner clarifications reach the goal evidence")
pm.add_clarification("Wir haben 12 Tester fuer den Closed Test, die sind schon zugesagt.")
check(facts() == ["Wir haben 12 Tester fuer den Closed Test, die sind schon zugesagt."],
      "the fact is in goal_state")
line = goal_drive.goal_line(goal_drive.goal_state(tracks=[], processes=[], ev=[], goal_pid=""))
check("Owner-Fakt: Wir haben 12 Tester" in line, "... and in the goal line Henry reads")
pm.set_goal("Etwas ganz anderes")
check(goal_drive.goal_state(tracks=[], processes=[], ev=[], goal_pid="")["facts"] == [],
      "a new goal drops the old goal's facts")
pm.set_goal(GOAL)

print("\n[2] _same_question sits in the MEASURED gap - both sides pinned")
for a, b in [("Wie viele Tester brauchst du für den Closed Test?",
              "Wie viele Tester stehen für den Closed Test bereit?"),
             ("Was ist das Budget für den Launch?", "Wie hoch ist das Budget beim Launch?")]:
    check(pm._same_question(a, b), "same ask reworded collapses: %r" % b[:44])
for a, b in [("Wie ist das Budget für den Closed Test?", "Wie ist die Deadline für den Closed Test?"),
             ("Wer betreut den Closed Test?", "Wann startet der Closed Test?")]:
    check(not pm._same_question(a, b), "different asks stay apart: %r" % b[:44])

print("\n[3] card Q&A never evicts a chat clarification")
IOS = "iOS-Produktionseinreichung ist bereits von Apple genehmigt - kein Demo-Video noetig"
pm.add_clarification(IOS)
for i in range(11):
    pm.add_clarification("Karte 'macOS': Rueckfrage %d -> Antwort: mach weiter" % i,
                         source="card", card="20260913-215533-machine")
for i in range(4):
    pm.add_clarification("Karte 'wear': Rueckfrage %d -> Antwort: ja" % i,
                         source="card", card="20260911-182039-machine")
blk = "\n".join(facts())
check(IOS in blk, "the chat clarification survives 15 card answers")
check(blk.count("Karte 'macOS'") <= pm._CLARIFY_PER_CARD,
      "card answers are capped per card (%d)" % blk.count("Karte 'macOS'"))
check(blk.count("Rueckfrage") <= pm._CLARIFY_CARD_MAX, "card answers are capped overall")
check("Rueckfrage 10" in blk and "Rueckfrage 0 ->" not in blk, "the NEWEST card answers are the ones kept")
for i in range(20):
    pm.add_clarification("chat fact %d" % i)
blk = "\n".join(facts())
check("chat fact 19" in blk and "chat fact 7" not in blk and IOS not in blk,
      "chat ring itself still rolls at %d" % pm._CLARIFY_MAX)

print("\n%s (%d failure(s))" % ("FAILED" if _fails else "PASS", len(_fails)))
sys.exit(1 if _fails else 0)
