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

# -- card screen -----------------------------------------------------------
from spine.ops.wear_screen import card_screen
row = {"id": "k1", "task": "Task", "status": "needs_you", "body": "Antworttext",
       "detail": "Grund", "question": {"id": "rq1", "questions": [
           {"question": "Weiter?", "header": "Next", "multiSelect": False,
            "options": [{"label": "Ja"}, {"label": "Nein"}]}]}}
cs = card_screen(row, "question")
tt = [i["t"] for i in cs["items"]]
assert tt[:3] == ["header", "button", "preview"] and cs["items"][1]["action"] == {"do": "back"}
assert any(i["t"] == "text" and i["text"] == "Frage offen" for i in cs["items"])
opts = [i for i in cs["items"] if i["t"] == "button" and i["action"].get("do") == "pick"]
assert [o["label"] for o in opts] == ["Ja", "Nein"]
# one single-select question: the tap IS the answer
then = opts[0]["action"]["then"]
assert then["path"] == "/tracks/k1/answer" and then["body"] == {"request_id": "rq1"}
assert then["picks_into"] == "answers"
assert cs["items"][-1]["action"] == {"do": "dictate", "prompt": "Frage an Henry", "card": "k1"}
# detail that merely echoes the body's start is dropped
echo = card_screen({"id": "k", "task": "t", "body": "Fertig und gut", "detail": "Fertig und gut"}, "delivered")
assert [i["detail_title"] for i in echo["items"] if i["t"] == "preview"] == ["Aufgabe", "Antwort"]
# two questions: no submit-on-tap, a Senden button gated on both keys
two = card_screen({"id": "k", "task": "t", "question": {"id": "r", "questions": [
    {"question": "a", "header": "A", "options": [{"label": "x"}]},
    {"question": "b", "header": "B", "options": [{"label": "y"}]}]}}, "question")
picks = [i for i in two["items"] if i["t"] == "button" and i["action"].get("do") == "pick"]
assert all("then" not in p["action"] for p in picks)
send = [i for i in two["items"] if i["t"] == "button" and i["label"] == "Senden"][0]
assert send["needs"] == ["A", "B"]
json.dumps(cs)
print("PASS test_wear_screen")
