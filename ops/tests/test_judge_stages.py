# -*- coding: utf-8 -*-
"""Staged judgement (henry_broker._staged_ask) - round 1 decides WITHOUT tools,
`need` buys one daemon-side reload, `hands` buys the only round with tools.

Pinned:
 1. a plain verdict costs ONE tool-less call
 2. `need` -> the daemon fetches, the second call carries the data, still no
    tools, and a second `need` is not honoured (falls through as a verb)
 3. `hands` (privileged) -> the hands round runs with HANDS_TOOLS and the plan
 4. a bare `did` from a tool-less round is read as `hands` (nothing was done)
 5. `hands` on an unprivileged escalation never reaches the hands round
 6. _fetch_need: unknown readers are named, memory needs a term, output is capped
Everything is faked at _ask/_hands_on_ask/_run_reader - no model, no db writes
beyond the escalation notes, which go to a sandbox data root.
Run: py -3.12 ops/tests/test_judge_stages.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ["HELMDECK_DATA_ROOT"] = tempfile.mkdtemp(prefix="helmdeck-judge-stages-")

from cells.copilot.broker import henry_broker as hb      # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


hb.escalations.record_note = lambda *a, **k: None       # notes are not under test
CALLS = []


def fake_ask(prompt, model="", perm=None):
    CALLS.append(("ask", hb._ROUND.get("tools"), prompt, perm))
    return dict(SCRIPT.pop(0))


def fake_hands(prompt, timeout=60):
    CALLS.append(("hands", hb._ROUND.get("tools"), prompt, None))
    return dict(SCRIPT.pop(0))


hb._ask = fake_ask
hb._hands_on_ask = fake_hands
_orig_fetch = hb._fetch_need
hb._fetch_need = lambda items, card: "FETCHED(%s|%s)" % (",".join(items), card)
ESC = {"id": "e1", "card": "k1"}

# 1: a plain verdict
SCRIPT = [{"action": "steer", "text": "nochmal", "why": "x"}]
CALLS.clear()
d = hb._staged_ask("P", ESC, True)
check("plain verdict: one call", len(CALLS) == 1, CALLS)
check("plain verdict: no tools", CALLS[0][1] == hb.STAGE1_TOOLS == "")
check("plain verdict: tail names need/hands", '"need|hands|' in CALLS[0][2])
check("plain verdict: round tools reset", hb._ROUND["tools"] is None)
check("plain verdict: verdict passes through", d["action"] == "steer")

# 2: need -> reload once
SCRIPT = [{"action": "need", "data": ["card", "memory:relay"]},
          {"action": "move", "lane": "review"}]
CALLS.clear()
d = hb._staged_ask("P", ESC, True)
check("need: two calls", len(CALLS) == 2, len(CALLS))
check("need: both without tools", all(c[1] == "" for c in CALLS))
check("need: second prompt carries the fetched data", "FETCHED(card,memory:relay|k1)" in CALLS[1][2])
check("need: second prompt forbids another need", "Ein zweites \"need\" gibt es nicht" in CALLS[1][2])
check("need: final verdict returned", d["action"] == "move")

SCRIPT = [{"action": "need", "data": "board, inbox"}, {"action": "need", "data": ["card"]}]
CALLS.clear()
d = hb._staged_ask("P", ESC, False)
check("need as a comma string is split", "FETCHED(board,inbox|k1)" in CALLS[1][2])
check("a second need is not honoured (unprivileged: falls through)", len(CALLS) == 2 and d["action"] == "need")

# 3: hands (privileged)
SCRIPT = [{"action": "hands", "text": "gate log lesen und fix pushen"},
          {"action": "did", "text": "gefixt"}]
CALLS.clear()
d = hb._staged_ask("P", ESC, True)
check("hands: stage 1 then hands round", [c[0] for c in CALLS] == ["ask", "hands"], CALLS)
check("hands: hands round gets HANDS_TOOLS", CALLS[1][1] == hb.HANDS_TOOLS == "Bash,Read,Edit")
check("hands: the plan is in the hands prompt", "gate log lesen und fix pushen" in CALLS[1][2])
check("hands: stage-1 tail is NOT in the hands prompt", '"need|hands|' not in CALLS[1][2])
check("hands: did returned", d["action"] == "did" and d["text"] == "gefixt")
check("hands: round tools reset", hb._ROUND["tools"] is None)

# 4: bare did from a tool-less round = hands
SCRIPT = [{"action": "did", "text": "ich starte den Daemon neu"}, {"action": "did", "text": "ok"}]
CALLS.clear()
hb._staged_ask("P", ESC, True)
check("bare did from round 1 is read as a plan", [c[0] for c in CALLS] == ["ask", "hands"]
      and "ich starte den Daemon neu" in CALLS[1][2])

# 5: unprivileged hands never reaches the hands round
SCRIPT = [{"action": "hands", "text": "x"}]
CALLS.clear()
d = hb._staged_ask("P", ESC, False)
check("unprivileged hands: no hands round", [c[0] for c in CALLS] == ["ask"])
check("unprivileged hands: surfaces as did for the refusal gate", d["action"] == "did")

# 6: _fetch_need
hb._fetch_need = _orig_fetch            # back to the real one, reader faked
hb._run_reader = lambda script, args, timeout=60: "%s %s" % (script, " ".join(args)) + ("!" * 7000 if "ship" in script else "")
out = hb._fetch_need(["card", "card:k9", "memory:relay", "memory:", "ghost", "ship_facts"], "k1")
check("fetch: card defaults to the escalating card", "board_state.py --card k1" in out)
check("fetch: card:<id> overrides", "board_state.py --card k9" in out)
check("fetch: 'card <id>' (space form) works too",
      "board_state.py --card k7" in hb._fetch_need(["card k7"], "k1"))
check("fetch: memory passes the term", "henry_memory_get.py find relay" in out)
check("fetch: memory without a term is named", "braucht einen Begriff" in out)
check("fetch: unknown reader is named, not guessed", "[ghost] unbekannt" in out)
check("fetch: at most NEED_MAX readers", "ship_facts.py" not in out)
capped = hb._fetch_need(["ship_facts"], "k1")
check("fetch: output is capped", "(gekuerzt)" in capped and len(capped) < hb.NEED_CAP + 200, len(capped))

print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
