# -*- coding: utf-8 -*-
"""Headless test: an ANSWERED owner question must not come back.

The bug class: brief()'s skeptical second pass (_verify_plan) built its prompt
from the plan + economics + quota ONLY - no _clarifications_block(), no
_reconcile_block(). So its INDEPENDENT must_ask pass re-derived questions the
owner had already answered in chat, in different words; the exact-string merge
(`q not in oq`) never matched a reworded duplicate, and since an open question
is a hard dispatch gate (_state's "ASK"), an answered question held the board.

Under test:
  1. the verifier's prompt CARRIES the owner's clarifications (and reconciled
     evidence),
  2. a resolved question re-derived in other words is dropped at the merge,
  3. a GENUINELY unresolved question (no clarification on file) still survives.

Self-sandboxing: pm's plan/loopstate files go to a temp dir, settings/economics/
quota/snapshot are stubbed, and _ask (the LLM) is replaced by a scripted double -
no daemon, no board, no network, no model."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp()

from cells.pm import pm
from cells.pm import pm_state

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


# -- the two questions this test is about -------------------------------------
ANSWERED = "Wie viele Tester brauchst du für den Closed Test?"
CLARIFY = "Wir haben 12 Tester für den Closed Test, die sind schon zugesagt."
# the same ask, re-derived by an independent pass in different words:
REDERIVED = "Wie viele Tester stehen für den Closed Test bereit?"
# no clarification on file for this one - it MUST survive:
UNRESOLVED = "Gibt es einen harten Stichtag für den Store-Launch?"

GOAL = "Play-Store-Launch der App"

PLAN = {"goal": GOAL, "summary": "Launch vorbereiten.",
        "milestones": [{"name": "Closed Test aufsetzen", "est_turns": 8, "priority": "high"}],
        "open_questions": [UNRESOLVED], "budget": {}}

prompts = []          # every prompt _ask saw: (kind, text)


def fake_ask(prompt, model=""):
    """Scripted stand-in for the CLI. The verifier pass is the one that used to
    re-derive an answered question - it does so here whenever the prompt does
    NOT carry the clarification, which is exactly the regression under test."""
    if prompt.startswith(pm.VERIFY_PROMPT):
        prompts.append(("verify", prompt))
        # an INDEPENDENT pass with no ground truth re-asks the answered question
        must = [] if CLARIFY in prompt else [REDERIVED]
        return {"ready": True, "gate": "", "issues": [], "must_ask": must}
    prompts.append(("plan", prompt))
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

from cells.copilot import copilot
copilot._snapshot = lambda: "(kein Board)"


def run_brief():
    prompts[:] = []
    return pm.brief()


print("\n[1] no clarification on file -> the verifier's ask is a NEW question")
b0 = run_brief()
check(len(prompts) == 2, "planner + verifier both ran (%d prompts)" % len(prompts))
check(REDERIVED in b0.get("open_questions", []),
      "without ground truth the re-derived question DOES surface (bug reproduces)")

print("\n[2] owner answers in chat -> the verifier SEES it")
pm.add_clarification(CLARIFY)
b1 = run_brief()
vp = next((p for k, p in prompts if k == "verify"), "")
check(CLARIFY in vp, "verifier prompt carries the OWNER CLARIFICATIONS block")
check("OWNER CLARIFICATIONS" in vp, "...under the same header brief()'s own prompt uses")

print("\n[3] the resolved question does NOT come back")
oq = b1.get("open_questions", [])
check(REDERIVED not in oq, "re-derived duplicate of the answered question is gone")
check(not any(pm._same_question(q, ANSWERED) for q in oq),
      "no rewording of the answered question survives anywhere in open_questions")

print("\n[4] a genuinely unresolved question still gets asked")
check(UNRESOLVED in oq, "the deadline question (no clarification on file) survives")
check(len(oq) == 1, "exactly one open question left (%r)" % (oq,))

print("\n[5] the merge dedups by MEANING, not by exact string")
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
      "dupes WITHIN the planner's own list collapse too, order preserved")
check(pm._merge_questions(None, None) == [] and pm._merge_questions([""], [None, 7]) == [],
      "empty/None/non-string inputs are dropped, never crash")

print("\n[5b] _Q_SAME sits in the MEASURED gap - both sides pinned")
# same ask, reworded -> MUST collapse (these score 0.571 / 0.667 Jaccard)
for a, b in [(ANSWERED, REDERIVED),
             ("Was ist das Budget für den Launch?", "Wie hoch ist das Budget beim Launch?")]:
    check(pm._same_question(a, b), "same ask reworded collapses: %r" % b[:44])
# DIFFERENT asks that merely share their object -> MUST NOT collapse (0.500)
for a, b in [("Wie ist das Budget für den Closed Test?", "Wie ist die Deadline für den Closed Test?"),
             ("Wer betreut den Closed Test?", "Wann startet der Closed Test?"),
             (UNRESOLVED, ANSWERED)]:
    check(not pm._same_question(a, b), "different asks stay apart: %r" % b[:44])

print("\n[6] reconciled evidence reaches the verifier too")
prev = dict(b1, reconcile={"scope": "Testkonten existieren bereits"})
pm._write_artifact(prev)
run_brief()
vp2 = next((p for k, p in prompts if k == "verify"), "")
check("RECONCILED EVIDENCE" in vp2 and "Testkonten" in vp2,
      "verifier prompt carries the reconciled corner evidence")

print("\n%s (%d failure(s))" % ("FAILED" if _fails else "PASS", len(_fails)))
sys.exit(1 if _fails else 0)
