# -*- coding: utf-8 -*-
"""Auto-routing must never pick a model that cannot HOLD the resumed session.

THE FAILURE THIS REPLAYS (2026-08-30, card 20260830-065545): the owner typed
"Ok" into a card chat to accept a PRD. Two characters. Henry answered "Prompt is
too long".

Nothing about the card explained it - the card's context meter read 110,377 /
55%. That meter belonged to the card WORKER's session. The reply came from
HENRY (`byKind: "henry"` in the card timeline), whose own session is one
long-lived conversation per user and stood at 615,889 tokens
(daemon/copilot_stats.json). Two different conversations rendered into one chat
pane; the owner read the wrong one, and so would anyone.

The routing bug underneath: `_EASY` matches "Ok", len < 40, so the CHEAP tier
was picked - Haiku, whose window is 200k. The CLI resumes the WHOLE transcript
on `--resume`, so 615,889 > 200,000 and the API refused the request before the
model read a single word of the new message. The message length decided the
model; nothing checked whether that model could still carry the history.

Numbers below are the MEASURED ones from that incident, hardcoded on purpose:
this test must keep passing after daemon/copilot_stats.json has moved on.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from spine.agent import turnopts                                  # noqa: E402

HENRY_CTX = 615_889          # Henry's session at 14:47:35, copilot_stats.json
CARD_CTX = 110_377           # the card worker's meter - the number the owner saw

fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


print("context-window fit (turnopts)")

# the trigger is still live - if this ever stops matching, the test below is moot
ok(len("Ok") < 40 and bool(turnopts._EASY.search("Ok")),
   "'Ok' still routes to the cheap tier by text")
ok(turnopts.model_window("claude-haiku-4-5") == 200_000,
   "haiku window is measured at 200k")
ok(turnopts.model_window("claude-haiku-4-5-20251001") == 200_000,
   "dated haiku id resolves to the same window")
ok(turnopts.model_window("claude-sonnet-5") == 1_000_000,
   "sonnet-5 window is measured at 1M")
ok(turnopts.model_window("claude-fable-5[1m]") == 1_000_000,
   "the CLI's [1m] suffix is honoured as a witness")
ok(turnopts.model_window("some-future-model") is None,
   "an unknown model has no guessed window")

# THE BUG: cheap tier on a session no cheap model can hold
ok(turnopts.pick_model("Ok", signals={"ctx_tokens": HENRY_CTX}) != "claude-haiku-4-5",
   "a 615k session is never routed into a 200k window")
ok(turnopts.model_window(turnopts.pick_model("Ok", signals={"ctx_tokens": HENRY_CTX}))
   >= HENRY_CTX + turnopts.CTX_HEADROOM,
   "the escalated pick actually fits, with headroom")

# the voice path pins haiku explicitly (routes_copilot.py) - same crash, so the
# lift applies to an explicit pick too, but ONLY when it provably cannot run
ok(turnopts.resolve_model("haiku", "Ok", False, {"ctx_tokens": HENRY_CTX})[0]
   != "claude-haiku-4-5",
   "the pinned voice model is lifted off a session it cannot hold")

# ...and nothing else moves.
ok(turnopts.pick_model("Ok", signals={"ctx_tokens": 5_000}) == "claude-haiku-4-5",
   "a small session still gets the cheap tier")
ok(turnopts.pick_model("Ok") == "claude-haiku-4-5",
   "no ctx reading = no action (never a guess)")
ok(turnopts.pick_model("Ok", signals={"ctx_tokens": 0}) == "claude-haiku-4-5",
   "a zero reading is treated as no reading")
ok(turnopts.pick_model("add a null check", signals={"ctx_tokens": 5_000})
   == "claude-sonnet-5", "ordinary work still routes to sonnet")
ok(turnopts.pick_model("debug this", signals={"ctx_tokens": HENRY_CTX,
                                              "priority": "urgent"})
   == "claude-opus-5", "urgent work still routes to opus")
ok(turnopts.resolve_model("claude-opus-5", "x", False, {"ctx_tokens": HENRY_CTX})[0]
   == "claude-opus-5", "an explicit pick that fits is untouched")
ok(turnopts.resolve_model("haiku", "x", False, {"ctx_tokens": 5_000})[0]
   == "claude-haiku-4-5", "an explicit cheap pick on a small session is honoured")
ok(turnopts.fits_window("some-future-model", HENRY_CTX) == "some-future-model",
   "an unknown model is never second-guessed")
ok(turnopts.fits_window("claude-haiku-4-5", CARD_CTX) == "claude-haiku-4-5",
   "the card's own 110k session still fits the cheap tier")

print("\n%s (%d checks, %d failed)" % ("PASS" if not fails else "FAIL", 17, len(fails)))
sys.exit(1 if fails else 0)
