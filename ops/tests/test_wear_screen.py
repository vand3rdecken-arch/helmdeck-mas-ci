# -*- coding: utf-8 -*-
"""Pins spine/ops/wear_screen.py: the board as a screen description."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spine.ops.wear_screen import board_screen

def types(s): return [i["t"] for i in s["items"]]

empty = board_screen({})
assert empty["v"] == 1 and empty["items"][1]["text"] == "Nichts wartet auf dich"
assert types(empty) == ["header", "text", "button", "button"], types(empty)
assert not any(i["t"] == "age" for i in empty["items"])  # no ts -> no stamp

full = board_screen({
    "needs_you": [{"id": "a", "task": "T1", "status": "needs_you"}],
    "yours": [{"id": "b", "task": "T2", "status": "queued"}],
    "pipeline": {"working": [{"id": "c", "task": "T3", "status": "running"}], "working_total": 3,
                 "backlog": [{"id": "d", "task": "T4", "status": "queued"}], "backlog_total": 9},
    "econ": {"wip_limit": 4}, "ts": 1700000000})
texts = [i["text"] for i in full["items"] if i["t"] == "text"]
assert texts == ["1 wartet auf dich", "Von dir", "In Arbeit: 3 von 4", "Backlog: 9"], texts
cards = [i for i in full["items"] if i["t"] == "card"]
assert [c["action"]["id"] for c in cards] == ["a", "b", "c", "d"]
assert cards[0]["status"] == "needs_you"
assert full["items"][-3]["t"] == "age" and full["items"][-2]["action"] == {"do": "nav", "to": "henry"}
assert full["items"][-1]["action"] == {"do": "reload"}
json.dumps(full)
print("PASS test_wear_screen")
