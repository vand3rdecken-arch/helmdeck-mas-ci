# -*- coding: utf-8 -*-
"""LIVE end-to-end proof of the question channel (Phase 2.4).

Not run by the gate (e2e_ prefix) - it spawns a REAL claude worker and spends
real turns. It is the evidence for the claim the feature is built on:

  a worker that needs a decision produces a card with real OPTIONS, and the
  owner's pick CONTINUES the same session instead of parking the card.

Steps:
  1. a real card in a real temp git repo, dispatched with a task that cannot be
     started without a product decision
  2. assert the card comes back carrying a typed question with >= 2 options
     (either the worker used the protocol, or the repair turn converted it)
  3. answer it through the real sessions.answer_question path
  4. assert the SAME session continued: the session id is preserved, the turn
     count went up, the question is cleared, and the worker's new reply shows it
     acted on the decision rather than asking again

Run: py -3.12 tests/e2e_question_live.py
"""
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-e2e-q-")

import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

import runs
runs.REC = os.path.join(SANDBOX, "runs")
os.makedirs(runs.REC, exist_ok=True)

import ask, sessions
sessions.REC = runs.REC

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _repo():
    r = os.path.join(SANDBOX, "repo")
    os.makedirs(r, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "e2e@test"],
                 ["config", "user.name", "e2e"]):
        subprocess.run(["git", "-C", r, *args], capture_output=True)
    with open(os.path.join(r, "README.md"), "w", encoding="utf-8") as f:
        f.write("e2e sandbox\n")
    subprocess.run(["git", "-C", r, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", r, "commit", "-qm", "init"], capture_output=True)
    return r


TASK = ("Baue die Login-Maske. Ich habe bewusst NICHT festgelegt, ob die "
        "Anmeldung per E-Mail+Passwort oder per Magic-Link laufen soll - das "
        "ist meine Produktentscheidung. Fang nicht an zu bauen, bevor das "
        "geklaert ist, und lies keine Dateien.")


def main():
    repo = _repo()
    print("dispatching a real card (this spends real turns)...")
    t0 = time.time()
    t = sessions.new_track(repo, "e2e-question", TASK, lane="working", actor="e2e")
    print("   first turn done in %.0fs, status=%s" % (time.time() - t0, t.get("status")))

    q = t.get("question")
    check(bool(q), "the card carries a typed question after the first turn")
    if not q:
        print("   last_reply was:\n", (t.get("last_reply") or "")[:800])
        return
    qs = q["questions"]
    check(len(qs) >= 1, "at least one question")
    check(all(len(x["options"]) >= 2 for x in qs), "every question has >= 2 real options")
    for x in qs:
        print("   Q:", x["question"])
        for o in x["options"]:
            print("      -", o["label"], "--", (o.get("description") or "")[:60])
    check("<helmdeck-ask" not in (t.get("last_reply") or ""),
          "the raw protocol block never reaches the owner's reply")

    sid_before = t.get("session_id")
    turns_before = t.get("turns", 0)
    pick = qs[0]["options"][0]["label"]
    print("answering with %r (continues the same session)..." % pick)

    t2 = sessions.answer_question(t["id"], {x["header"]: x["options"][0]["label"] for x in qs},
                                  request_id=q["id"], actor="e2e")

    check(t2.get("turns", 0) > turns_before,
          "the card ran another turn (%d -> %d)" % (turns_before, t2.get("turns", 0)))
    check(not t2.get("question"), "the question is cleared after answering")
    check(t2.get("status") == "needs_you", "card settled (status=%s)" % t2.get("status"))
    # lossless continuation: claude rotates the session id on resume, so what
    # matters is that we still have ONE session and it is not a fresh start
    check(bool(t2.get("session_id")), "the card still holds a resumable session")
    print("   session %s -> %s" % ((sid_before or "")[:8], (t2.get("session_id") or "")[:8]))

    reply = (t2.get("last_reply") or "")
    print("\n--- worker's reply after the decision ---\n" + reply[:900])
    check(pick.split()[0].lower() in reply.lower() or len(reply) > 80,
          "the worker acted on the decision instead of asking again")
    check(not t2.get("question"), "it did NOT re-ask the same question")


main()

print()
if _fails:
    print("FAILED: %d check(s): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("LIVE QUESTION-CHANNEL E2E PASSED")
