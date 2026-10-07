# -*- coding: utf-8 -*-
"""status=needs_you is only "the turn ended" - what the card waits FOR is derived
(lifecycle.card_phase), never stored. Pure functions, no db, no network.
Fails on the old code: card_phase did not exist and every needs_you card was
bucketed `needs_input` / pushed as "your call"."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cells.copilot.chat import threads
from cells.engineer.cards import lifecycle

Q = {"id": "q1", "kind": "question", "questions": [{"question": "Which db?"}]}
fails = []


def check(name, got, want):
    if got != want:
        fails.append("%s: got %r want %r" % (name, got, want))


P = lifecycle.card_phase
check("running has no phase", P({"status": "running", "lane": "working"}), None)
check("open question", P({"status": "needs_you", "lane": "working", "question": Q}), "asking")
check("turn ended, no question", P({"status": "needs_you", "lane": "working"}), "delivered")
check("background task", P({"status": "needs_you", "lane": "working", "waiting_on": "background"}), "background")
check("review lane", P({"status": "needs_you", "lane": "review"}), "ready")
check("question beats review", P({"status": "needs_you", "lane": "review", "question": Q}), "asking")

check("present adds phase", lifecycle.present({"id": "x", "status": "needs_you", "lane": "working"}).get("phase"), "delivered")
check("present: bounced has none", "phase" in lifecycle.present({"id": "x", "status": "bounced", "lane": "working"}), False)

B = threads._bucket
check("bucket asking", B({"status": "needs_you", "lane": "working", "question": Q}), "needs_input")
check("bucket delivered", B({"status": "needs_you", "lane": "working"}), "attention")
check("bucket ready", B({"status": "needs_you", "lane": "review"}), "attention")
check("bucket background", B({"status": "needs_you", "lane": "working", "waiting_on": "background"}), "running")

if fails:
    print("FAIL\n" + "\n".join(fails))
    sys.exit(1)
print("ok - card phase")
