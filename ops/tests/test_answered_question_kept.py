# -*- coding: utf-8 -*-
"""An answered question stays visible (owner 2026-10-18: "Fragen laufen weg sobald die beantwortet werden").

  1. ask.answered_record keeps every asked question, its options and what was chosen (labels + own text);
  2. answer_question writes it into the Henry chat entry bound to the card (extra.answered);
  3. copilot.say folds it into the CARD's timeline as an `answered` item by the owner - not a Henry note.

Sandboxed db; chat + timeline writes are captured, no daemon.  Run: py -3.12 ops/tests/test_answered_question_kept.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.storage import db                                  # noqa: E402

db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-answered-"), "test.db")
db.init()
from spine.ops import ask                                     # noqa: E402
from cells.copilot.chat import copilot                        # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


Q = {"id": "q-1", "questions": [
    {"question": "Wo soll der Button hin?", "header": "Position",
     "options": [{"label": "Oben", "description": ""}, {"label": "Unten", "description": ""}]},
    {"question": "Welche Farbe?", "header": "Farbe",
     "options": [{"label": "Blau", "description": ""}, {"label": "Grau", "description": ""}]}]}


def main():
    picks, err = ask.validate_answers(Q, {"Position": "Unten", "Farbe": "dunkles Petrol"})
    check(not err, "the answers validate (%s)" % err)
    rec = ask.answered_record(Q, picks)
    check(rec["id"] == "q-1" and len(rec["items"]) == 2, "both questions are kept")
    a, b = rec["items"]
    check(a["question"] == "Wo soll der Button hin?" and a["options"] == ["Oben", "Unten"] and a["chosen"] == ["Unten"],
          "question 1: text, all options, the chosen label (%s)" % a)
    check(b["chosen"] == [] and b["custom"] == ["dunkles Petrol"], "question 2: the owner's own text is kept as custom (%s)" % b)

    # say() with the answered extra: the chat entry carries it, the card timeline gets an `answered` item
    logged, folded = [], []
    copilot.owner_name = lambda: "owner"
    copilot._append_log = lambda owner, entries: logged.extend(entries)
    copilot._find_card = lambda cid: {"id": cid, "run_dir": "RUN"}
    from spine.agent import timeline_store
    timeline_store.append = lambda run_dir, key, item: folded.append((run_dir, item))
    copilot.say("Unten, \"dunkles Petrol\"", cls="you", card="C1", extra={"answered": rec, "by": "owner"})
    check(logged and logged[0].get("answered") == rec and logged[0].get("card") == "C1",
          "the Henry chat entry is bound to the card and carries the answered record")
    check(folded and folded[0][1]["kind"] == "answered" and folded[0][1]["byKind"] == "human"
          and folded[0][1]["answered"]["items"][0]["chosen"] == ["Unten"],
          "the card's timeline gets an `answered` item by the owner, not a Henry note (%s)" % (folded[0][1].get("kind") if folded else None))
    folded.clear()
    copilot.say("Hauptcheckout", cls="you", card="C1", extra={"answered": rec, "by": "henry"})
    check(folded and folded[0][1]["kind"] == "answered" and folded[0][1]["byKind"] == "henry",
          "a question the broker answered is attributed to Henry, not the owner (%s)" % (folded[0][1].get("byKind") if folded else None))
    folded.clear()
    copilot.say("Gate ist rot", cls="pm", card="C1")
    check(folded and folded[0][1]["kind"] == "note" and folded[0][1]["byKind"] == "henry",
          "an ordinary notice still folds as a Henry note")
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("answered question kept: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
