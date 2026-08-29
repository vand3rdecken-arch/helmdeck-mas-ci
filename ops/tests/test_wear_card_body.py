# -*- coding: utf-8 -*-
"""Headless test for THE WATCH CARD'S BODY (GET /wear/board -> `body`).

The defect this pins (owner, 2026-08-29, photographed on the watch): opening a
card on the Wear app showed its title, a "Zurueck" button and "Henry fragen" -
and nothing else. Literally nothing else: BoardCard carried only id/task/reason,
CardScreen rendered only the title, and the pipeline rows (`In Arbeit` /
`Backlog`, the bucket the tapped card was in) carried no text at all.

glance_payload's `detail` was already on the wire and thrown away; the card's own
last reply was never sent. This adds `body` - the watch's OWN field, so the
glasses' shared `detail` keeps its shape and its 160-char lens cap.

What is pinned here:
 1. the <helmdeck-ask> block never reaches the wrist as raw JSON (the exact
    screenful the owner photographed earlier the same day)
 2. ```fenced blocks are dropped, prose either side of them is kept
 3. markdown markers are flattened - a watch renders '**' literally
 4. paragraph breaks survive; whitespace INSIDE a line is collapsed
 5. the cap is enforced (payload bound, not just a UI one)
 6. a never-run card falls back to its description, so `yours` is not blank
 7. pipeline rows carry body AND status
 8. the needs_you/yours enrichment matches cards BY ID (the loop that would
    silently attach the wrong text if it drifted)
 9. None/empty input is safe

Self-sandboxing: temp events/settings/db, no model call, no network.
Run: py -3.12 ops/tests/test_wear_card_body.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-wearbody-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.http.routes import routes_wear as W

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- 1. the ask block never reaches the wrist -------------------------------
ASK = ('Kurz gesagt: fertig.\n'
       '<helmdeck-ask>\n'
       '{"questions": [{"question": "Weiter?", "header": "Naechstes", '
       '"options": [{"label": "Ja", "description": "weiter"}]}]}\n'
       '</helmdeck-ask>')
out = W._wear_text(ASK)
check("helmdeck-ask" not in out and '"label"' not in out,
      "the <helmdeck-ask> block is stripped - no raw JSON on the watch")
check(out.startswith("Kurz gesagt: fertig."),
      "and the prose in front of it survives intact")

# -- 2. fenced blocks ------------------------------------------------------
FENCED = "vorher\n```actions\n{\"do\": \"merge\"}\n```\nnachher"
out = W._wear_text(FENCED)
check("do" not in out.replace("vorher", "").replace("nachher", "")
      and "vorher" in out and "nachher" in out,
      "a ```fenced block is dropped and the prose on BOTH sides is kept")

# an UNCLOSED fence must not swallow the rest of the reply
out = W._wear_text("sichtbar\n```\nrest ohne Ende")
check("sichtbar" in out, "an unclosed fence still keeps the prose before it")

# -- 3. markdown markers ---------------------------------------------------
MD = "## DELIVERED\n**fett** und `code`\n- erster Punkt\n- zweiter Punkt"
out = W._wear_text(MD)
check("#" not in out and "*" not in out and "`" not in out,
      "heading/emphasis/code markers are flattened - a watch shows them literally")
check("DELIVERED" in out and "fett" in out and "erster Punkt" in out,
      "and the words themselves are untouched")

# -- 4. structure ----------------------------------------------------------
out = W._wear_text("Absatz eins.\n\n\n\nAbsatz zwei.")
check(out == "Absatz eins.\n\nAbsatz zwei.",
      "blank runs collapse to ONE break - paragraphs stay, gaps do not")
out = W._wear_text("viele      Spalten\tund   Tabs")
check(out == "viele Spalten und Tabs",
      "whitespace inside a line is collapsed (a 240dp line has no columns)")

# -- 5. the cap, and WHERE it cuts -----------------------------------------
out = W._wear_text("x" * 5000)
check(len(out) <= W.WEAR_BODY_MAX + 4,
      "the body is capped at WEAR_BODY_MAX (%d) - it rides sealed through the "
      "relay, once per listed card" % W.WEAR_BODY_MAX)

# The owner's report: "Message abgeschnitten". A raw slice ended mid-word and
# read as a broken message rather than as a bounded screen.
# Both fixtures are sized FROM the cap, never with a hardcoded repeat count.
# They used to be "wort " * 400 (1999 chars), which comfortably overflowed the
# 1200-char cap of the day and then silently stopped overflowing when it rose to
# 2000 - the check went green-to-red for a reason that had nothing to do with the
# behaviour it guards. Deriving the length means a future cap change cannot
# quietly turn these into tests of the un-cut path.
long_words = ("wort " * (W.WEAR_BODY_MAX // 5 + 50)).strip()
out = W._wear_text(long_words)
check(len(long_words) > W.WEAR_BODY_MAX,
      "the overflow fixture really does exceed the cap it is testing")
check(out.endswith(" ..."), "a cut body SAYS it was cut")
check(not out.replace(" ...", "").endswith("wor"),
      "and it never ends mid-word")
sentences = ("Erster Satz. " * (W.WEAR_BODY_MAX // 13 + 20)).strip()
out = W._wear_text(sentences)
check(out.endswith(". ..."),
      "a sentence end is preferred over a bare word boundary")
check(W._wear_clip("kurz", 100) == "kurz",
      "text that fits is returned untouched - no ellipsis on a complete message")
check(W._wear_clip("a" * 50, 10) == "a" * 10 + "...",
      "one unbroken 50-char token still yields something, cut hard and marked")

# -- 5b. the cap must not cut a REAL reply ----------------------------------
# Owner, 2026-08-29, photographing a card on the watch: the report stopped after
# ~10 lines on " ...". The cap was 1200 while the card itself can hold 2000 -
# so the watch was cutting text that existed, on the one screen he opens to read
# it. These two checks pin that the wire cap is >= the STORAGE cap and that a
# maximal stored reply therefore arrives whole.
STORED_MAX = 2000            # turnrunner._settle_reply_apply: cleaned[:2000]
check(W.WEAR_BODY_MAX >= STORED_MAX,
      "WEAR_BODY_MAX (%d) is at least the %d chars a card can actually STORE "
      "(cells/engineer/turnrunner.py:247) - below that the watch cuts real text"
      % (W.WEAR_BODY_MAX, STORED_MAX))
# A reply of exactly the stored maximum, in real words rather than one long
# token, so _wear_clip's word/sentence search is genuinely exercised.
full = (("Der Turn ist fertig und hier steht der Bericht. " * 60)[:STORED_MAX]).strip()
out = W._wear_text(full)
check(not out.endswith("..."),
      "a MAXIMAL stored reply (%d chars) reaches the wrist WITHOUT an ellipsis - "
      "the exact screen the owner photographed" % len(full))
check(out == full,
      "and it arrives byte-for-byte complete, not merely un-marked")

# -- 6. fallback for a card that never ran ---------------------------------
check(W._wear_body({"last_reply": "gelaufen", "description": "beschrieben"})
      == "gelaufen", "a card that has run shows its last reply")
check(W._wear_body({"description": "beschrieben"}) == "beschrieben",
      "a card that never ran falls back to its description (the `yours` bucket)")
check(W._wear_body({}) == "" and W._wear_body(None) == "",
      "an empty card yields an empty body, not a crash")
check(W._wear_text(None) == "" and W._wear_text("") == "",
      "None/empty text is safe")

# -- 7. pipeline rows carry body AND status --------------------------------
# `branch` is present because events.metrics() indexes it directly (it is a
# real card field, not test scaffolding) - the route calls metrics() before
# glance_payload and a fixture without it fails there, not here.
TRACKS = [
    {"id": "run-1", "task": "laufende Karte", "status": "running", "branch": "b1",
     "last_reply": "**Zwischenstand** aus dem letzten Turn."},
    {"id": "q-1", "task": "wartende Karte", "status": "queued", "branch": "b2",
     "description": "noch nie gelaufen"},
    {"id": "skip-1", "task": "schon gelistet", "status": "running", "branch": "b3",
     "last_reply": "darf nicht doppelt erscheinen"},
    {"id": "arch-1", "task": "archiviert", "status": "running", "branch": "b4",
     "archived": True},
]
from cells.engineer import sessions as _sessions
# present() is what makes `running` HONEST - it demotes a card whose turn died
# to needs_you, and a headless test has no live turn, so every fixture below
# would otherwise be demoted and the working bucket would be empty for the wrong
# reason. Verified, not assumed: present() on a bare running dict returns
# status='needs_you', status_derived=True. Identity here isolates the field
# plumbing under test; that present() is CALLED at all is asserted separately.
_real_present = _sessions.present
_sessions.present = lambda t: t
try:
    pipe = W._wear_pipeline(TRACKS, {"skip-1"})
finally:
    _sessions.present = _real_present
work = pipe["working"]
check(len(work) == 1 and work[0]["id"] == "run-1",
      "a card already listed elsewhere is skipped, an archived one is dropped")
check(work[0].get("status") == "running",
      "a pipeline row carries its status, so the card screen can colour it")
check(work[0].get("body") == "Zwischenstand aus dem letzten Turn.",
      "a RUNNING card's row carries its last reply - the exact case the owner "
      "tapped into and found empty")
back = pipe["backlog"]
check(len(back) == 1 and back[0].get("body") == "noch nie gelaufen",
      "a queued card's row carries its description")

# ...and that present() really is on the path: WITHOUT the stub, the same
# phantom-running fixture must NOT be reported as "in Arbeit". This is the half
# the identity stub above deliberately switches off, so it is asserted here
# rather than left to a comment.
live = W._wear_pipeline([TRACKS[0]], set())
check(live["working"] == [] and live["working_total"] == 0,
      "a card whose turn is dead is not called 'in Arbeit' - _wear_pipeline "
      "runs present() first, exactly as its docstring claims")

# -- 8. the enrichment matches BY ID ---------------------------------------
# Drive the real route with a stub transport: this is the loop that would
# silently attach the WRONG card's text if it ever drifted to positional
# matching, and no pure-function test can reach it.
from cells.engineer import sessions
from spine.ops import glances

sent = {}


class _Stub:
    path = "/wear/board"

    def _send(self, code, payload):
        sent["code"] = code
        sent["body"] = json.loads(payload)


_real_list = sessions.list_tracks
sessions.list_tracks = lambda: TRACKS
_real_payload = glances.glance_payload
glances.glance_payload = lambda tracks, m: {
    # deliberately in a DIFFERENT order than TRACKS: positional matching would
    # hand q-1's text to run-1 and the test would catch it
    "needs_you": [{"id": "q-1", "task": "wartende Karte", "detail": "warum"},
                  # markdown, exactly as blockers._blocker_text hands it over -
                  # it collapses whitespace and slices, nothing more
                  {"id": "run-1", "task": "laufende Karte",
                   "detail": "## DELIVERED **fett** und `code`"}],
    "yours": [{"id": "skip-1", "task": "schon gelistet"}],
    "econ": {}, "ts": 0,
}
try:
    W.wear_board_get(_Stub(), {"role": "owner", "name": "owner"})
finally:
    sessions.list_tracks = _real_list
    glances.glance_payload = _real_payload

body = sent.get("body") or {}
ny = {c["id"]: c for c in body.get("needs_you") or []}
check(sent.get("code") == 200, "the route answers 200")
check(ny.get("q-1", {}).get("body") == "noch nie gelaufen"
      and ny.get("run-1", {}).get("body") == "Zwischenstand aus dem letzten Turn.",
      "each needs_you row gets ITS OWN card's text - matched by id, not position")
check(ny.get("q-1", {}).get("detail") == "warum",
      "a `detail` with nothing to clean comes through unchanged")
check((body.get("yours") or [{}])[0].get("body") == "darf nicht doppelt erscheinen",
      "the `yours` bucket is enriched too")
# The exact thing the owner photographed: raw '## DELIVERED **fett**' on a
# 240dp round screen, because `detail` is shaped for a badge and a lens and
# hands markdown straight through.
d = ny.get("run-1", {}).get("detail") or ""
check("#" not in d and "*" not in d and "`" not in d,
      "the watch's copy of `detail` is FLATTENED - no markdown reaches the wrist")
check(d == "DELIVERED fett und code",
      "and the words survive the flattening intact")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL WEAR CARD BODY CHECKS PASSED")
