# -*- coding: utf-8 -*-
"""Headless test: clarifications reach the ONE remaining planner turn, and the
question-dedup primitives still hold (pm-lean-advisor, 2026-09-04).

pm.brief() used to run up to 4 turns (planner, verifier, repair, re-verify);
the verifier/repair pair is GONE (a second model pass grading the first's
optimism was the self-verification anti-pattern research shows makes
reasoning worse - see ops/docs/backlog/pm-lean-advisor/README.md). This file
used to test that the verifier's INDEPENDENT pass saw the owner's chat
clarifications; with one turn left there is nothing independent to check -
what still matters, and what stays under test here:

  1. clarifications + reconciled evidence reach the (single) planner prompt,
  2. the planner's own open_questions gets self-deduped (a planner CAN still
     repeat itself in one turn - _merge_questions(qs, []) catches that),
  3. the dedup primitives (_same_question/_merge_questions) still hold on
     their own, unit-tested directly - GRILLEN's clarification flow and any
     future goal_check turn depend on these being right.

Self-sandboxing: pm's plan/loopstate files go to a temp dir, settings/economics/
quota/snapshot are stubbed, and _ask (the LLM) is replaced by a scripted double -
no daemon, no board, no network, no model."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp()

from cells.copilot.planning import pm
from cells.copilot.planning import pm_state

PLANS = os.path.join(SANDBOX, "pm")
pm.PLANS = PLANS
pm_state.PLANS = PLANS
pm_state.LOOPSTATE = os.path.join(PLANS, "loop.json")
os.makedirs(PLANS, exist_ok=True)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- the questions this test is about -----------------------------------------
ANSWERED = "Wie viele Tester brauchst du für den Closed Test?"
CLARIFY = "Wir haben 12 Tester für den Closed Test, die sind schon zugesagt."
# the same ask, the planner repeating itself in different words within ONE turn:
REDERIVED = "Wie viele Tester stehen für den Closed Test bereit?"
UNRESOLVED = "Gibt es einen harten Stichtag für den Store-Launch?"

GOAL = "Play-Store-Launch der App"

PLAN = {"goal": GOAL, "summary": "Launch vorbereiten.",
        "milestones": [{"name": "Closed Test aufsetzen", "est_turns": 8, "priority": "high"}],
        "open_questions": [UNRESOLVED], "budget": {}}

prompts = []          # every prompt _ask saw


def fake_ask(prompt, model=""):
    prompts.append(prompt)
    return json.loads(json.dumps(PLAN))


pm._ask = fake_ask
pm.economics = lambda: {"turns_to_date": 40, "velocity_turns_per_day": 8.0,
                        "quota_turns_per_day": 0, "plan": "max", "spend_to_date": 0.0}
pm._quota_signal = lambda: {"status": "ok"}
pm._system_state = lambda: "(sandbox)"
pm._gate_triangle = lambda *a, **k: None

# settings live in the real store; keep goal/policy reads sandboxed and writes inert
from spine.storage import events
_SET = {"pm": dict(pm.PM_DEFAULTS, goal=GOAL), "policy": {}}
events.settings = lambda: _SET
events.save_settings = lambda d: _SET.update(d)

from cells.copilot.chat import copilot
copilot._snapshot = lambda: "(kein Board)"


def run_brief():
    prompts[:] = []
    return pm.brief()


print("\n[1] one turn only")
b0 = run_brief()
check(len(prompts) == 1, "brief() ran exactly ONE model turn (%d)" % len(prompts))
check(UNRESOLVED in b0.get("open_questions", []), "the planner's own question survives")

print("\n[2] owner answers in chat -> the ONE turn SEES it")
pm.add_clarification(CLARIFY)
b1 = run_brief()
p = prompts[0]
check(CLARIFY in p, "planner prompt carries the OWNER CLARIFICATIONS block")
check("OWNER CLARIFICATIONS" in p, "...under its own header")

print("\n[3] reconciled evidence reaches the planner prompt too")
prev = dict(b1, reconcile={"scope": "Testkonten existieren bereits"})
pm._write_artifact(prev)
run_brief()
p2 = prompts[0]
check("RECONCILED EVIDENCE" in p2 and "Testkonten" in p2,
      "planner prompt carries the reconciled corner evidence")

print("\n[4] the merge dedups by MEANING, not by exact string")
check(pm._merge_questions([ANSWERED], [REDERIVED]) == [ANSWERED],
      "two wordings of one ask collapse to the first")
check(pm._merge_questions([ANSWERED], [UNRESOLVED]) == [ANSWERED, UNRESOLVED],
      "two DIFFERENT asks both survive")
check(pm._merge_questions([" A?  "], ["A?"]) == ["A?"],
      "whitespace/short-question normalisation still works")
check(pm._merge_questions(["Wie ist das Budget?"], ["Wie ist die Deadline?"])
      == ["Wie ist das Budget?", "Wie ist die Deadline?"],
      "one-content-word questions are NOT collapsed (no over-eager merge)")
check(pm._merge_questions([ANSWERED, REDERIVED, UNRESOLVED], [ANSWERED, REDERIVED])
      == [ANSWERED, UNRESOLVED],
      "dupes WITHIN the planner's own list collapse too, order preserved - "
      "this is the exact call brief() makes now (_merge_questions(qs, []))")
check(pm._merge_questions(None, None) == [] and pm._merge_questions([""], [None, 7]) == [],
      "empty/None/non-string inputs are dropped, never crash")

print("\n[5] _Q_SAME sits in the MEASURED gap - both sides pinned")
# same ask, reworded -> MUST collapse (these score 0.571 / 0.667 Jaccard)
for a, b in [(ANSWERED, REDERIVED),
             ("Was ist das Budget für den Launch?", "Wie hoch ist das Budget beim Launch?")]:
    check(pm._same_question(a, b), "same ask reworded collapses: %r" % b[:44])
# DIFFERENT asks that merely share their object -> MUST NOT collapse (0.500)
for a, b in [("Wie ist das Budget für den Closed Test?", "Wie ist die Deadline für den Closed Test?"),
             ("Wer betreut den Closed Test?", "Wann startet der Closed Test?"),
             (UNRESOLVED, ANSWERED)]:
    check(not pm._same_question(a, b), "different asks stay apart: %r" % b[:44])

print("\n%s (%d failure(s))" % ("FAILED" if _fails else "PASS", len(_fails)))
sys.exit(1 if _fails else 0)
