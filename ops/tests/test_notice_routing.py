# -*- coding: utf-8 -*-
"""THE NOTICE DECREE, pinned (owner 2026-08-30, quoting the PM's daily
"Ziel vs. Budget" block back at the board):

    "Diese Karte sollte in der Form nicht mehr im Chat sein. Zu viel info..
     bzw ich weiss nicht was ich dazu machen soll."

Two rules came out of it and both are checked here, because both are the kind
that rot silently - a notice re-lengthens one format string at a time, and a
re-route is invisible until the owner complains again:

  1. LENGTH - spine.comms.notice.short() clips anything owner-visible to two
     short sentences. Section 1. Includes the case that ALREADY bit once: the
     first splitter treated the decimal point in "~6.0%" as a sentence end and
     cut the line after "hat ~6.", keeping the number and throwing away the
     ask.
  2. ROUTING - a notice with no owner DECISION does not reach his chat at all.
     Section 2 walks every proactive PM notice and asserts which of the three
     channels it landed in (chat / dashboard feed / Henry).
  3. The notices that DO stay must be answerable, not just short: section 3
     proves _ask_owner's buttons are real - the entry is the class the chat's
     question channel reads, and the payload survives the same validation the
     tapped answer goes through.

Self-sandboxing: pm's _say/_ask_owner/_to_henry/_activity/_save_loopstate,
get_goal/latest_plan and usage's snapshot/weekly_pacing_flag are patched -
nothing touches disk, chat, FCM or the real board.

Run: py -3.12 ops/tests/test_notice_routing.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from spine.comms import notice
from spine.ops import ask
from cells.pm import pm

FAILS = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        FAILS.append(name)


# =============================================================================
print("1. the length law")

check("two sentences pass through untouched",
      notice.short("Fertig: die Karte wartet auf dich. Abnehmen?")
      == "Fertig: die Karte wartet auf dich. Abnehmen?")

five = ("Ziel: in den Store. Budget: 90% verbraucht. Zielpfad: 8 Turns offen. "
        "Risiko: Kontingent vor dem Reset leer. Machbarkeit: unbekannt.")
clipped = notice.short(five)
check("the complained-about five-sentence block is cut to two",
      clipped == "Ziel: in den Store. Budget: 90% verbraucht.")

# THE REGRESSION: a decimal point is not a sentence end. The naive splitter cut
# this after "hat ~6." - the number kept, the question thrown away.
money = ("„Karte X“ hat ~6.0% vom Wochenkontingent statt der zugeteilten ~5.0% "
         "verbraucht. Weiterlaufen lassen?")
check("decimal points are not sentence ends", notice.short(money) == money)
check("the ask survives the clip", "Weiterlaufen lassen?" in notice.short(money))

# ...and the same for a German date, which puts a period-then-SPACE inside a
# timestamp: "So 30.08. 20:00" cut the line at the date on the first fix.
dated = "Das Kontingent ist ~So 30.08. 20:00 leer. Nicht-Ziel-Arbeit zurückstellen?"
check("a German timestamp is not a sentence end", notice.short(dated) == dated)

# a real two-sentence notice that ENDS in an abbreviation still terminates
check("an abbreviation does not end the sentence early",
      notice.short("Es fehlt z. B. der Keystore. Sag kurz Bescheid. Und noch was.")
      == "Es fehlt z. B. der Keystore. Sag kurz Bescheid.")

check("a bulleted wall collapses to one line",
      "\n" not in notice.short("Dreieck schief:\n• Budget voraus\n• Timeline über"))
check("an over-long single sentence is cut on a word boundary and SAYS so",
      notice.short("wort " * 200).endswith(" …")
      and len(notice.short("wort " * 200)) <= notice.MAX_CHARS + 2)
check("empty stays empty", notice.short("") == "" and notice.short(None) == "")


# =============================================================================
print("2. routing: chat only when the owner has a move")

CHAT, FEED, HENRY, ASKS = [], [], [], []
pm._say = lambda text: CHAT.append(text)
pm._activity = lambda kind, msg, card=None: FEED.append({"kind": kind, "msg": msg})
pm._to_henry = lambda kind, detail, card=None, feed="": HENRY.append(
    {"kind": kind, "detail": detail, "feed": feed})
pm._ask_owner = lambda text, options, header="", card="", title="": ASKS.append(
    {"text": text, "options": options})
pm._save_loopstate = lambda s: None
pm.get_goal = lambda: "In den Google Play Store deployen"

PLAN = [{}]
pm.latest_plan = lambda: PLAN[0]

from spine.ops import usage
FLAG = [None]
SNAP = [{}]
usage.weekly_pacing_flag = lambda: FLAG[0]
usage.snapshot = lambda: SNAP[0]


def reset():
    del CHAT[:], FEED[:], HENRY[:], ASKS[:]


# -- the quota check-in: pure projection, Henry's own mandate ------------------
reset()
FLAG[0] = {"usedPct": 90, "elapsed_pct": 60, "projected_pct": 150,
           "resetsAt": "2026-08-30T22:00:00Z", "exhaust_before_reset": True,
           "exhaust_at": "2026-08-30T20:00:00Z"}
pm._usage_checkin({})
check("quota pacing goes to Henry", len(HENRY) == 1 and HENRY[0]["kind"] == "quota-pacing")
check("quota pacing never reaches the chat", not CHAT and not ASKS)

# -- the triangle tilt: a bullet list of drifts, no move ----------------------
reset()
pm._triangle_watch({})
check("triangle tilt goes to Henry", len(HENRY) == 1 and HENRY[0]["kind"] == "triangle-tilt")
check("triangle tilt never reaches the chat", not CHAT and not ASKS)

# -- the plan gate: the fix is the harness's own move -------------------------
reset()
FLAG[0] = None
PLAN[0] = {"plan_status": "ready", "goal": "x",
           "triage": {"budget": "blocked", "timeline": "ok", "scope": "ok"},
           "gate": "Budget-Ecke unbelegt.", "verify": {"issues": ["keine Evidenz"]}}
pm._plan_gate_notice({})
check("red plan gate goes to Henry", len(HENRY) == 1 and HENRY[0]["kind"] == "plan-gate-red")
check("red plan gate never reaches the chat", not CHAT and not ASKS)

# -- the stakeholder update: THE message the owner quoted ---------------------
# on track -> the dashboard, silently. This is the exact regression.
reset()
PLAN[0] = {"budget": {"est_turns_to_goal": 8, "eta_days": 1, "pace_turns_per_day": 17.5}}
SNAP[0] = {"status": "ok", "windows": [{"id": "weekly", "usedPct": 40,
                                        "resetsAt": "2026-08-30T22:00:00Z",
                                        "pacing": {"projected_pct": 70}}]}
pm._stakeholder_update({})
check("'Ziel vs. Budget' on track is DASHBOARD ONLY",
      not CHAT and not ASKS and any("Ziel vs. Budget" in f["msg"] for f in FEED))

# at risk -> ONE question with buttons, because only he can trade goal vs quota
reset()
SNAP[0] = {"status": "ok", "windows": [{"id": "weekly", "usedPct": 90,
                                        "resetsAt": "2026-08-30T22:00:00Z",
                                        "pacing": {"projected_pct": 150, "flag": True,
                                                   "exhaust_at": "2026-08-30T20:00:00Z"}}]}
pm._stakeholder_update({})
check("at risk ASKS the owner instead of reporting at him", len(ASKS) == 1 and not CHAT)
check("the at-risk ask offers a real trade",
      ASKS and len(ASKS[0]["options"]) == 2)
check("the at-risk ask obeys the length law untouched",
      ASKS and notice.short(ASKS[0]["text"]) == ASKS[0]["text"])
check("the full report still reaches the dashboard",
      any("Ziel vs. Budget" in f["msg"] for f in FEED))

# -- missing key info: STAYS in the chat, but as ONE question -----------------
reset()
PLAN[0] = {"open_questions": ["Ist der Play-Console-Account angelegt?",
                              "Liegt der Upload-Keystore bereit?",
                              "Gibt es eine Datenschutz-URL?"]}
pm._needs_from_owner({})
check("missing key info stays in the chat", len(CHAT) == 1)
check("it asks ONE question, not a form of five",
      CHAT and CHAT[0].count("?") <= 2 and "•" not in CHAT[0])
check("it says how many are still queued", CHAT and "2 weitere" in CHAT[0])
check("it obeys the length law untouched", CHAT and notice.short(CHAT[0]) == CHAT[0])


# =============================================================================
print("3. the notices that stay are ANSWERABLE, not just short")

SAID = []
from cells.copilot import copilot
copilot.say = lambda text, cls="pm", card=None, extra=None: SAID.append(
    {"text": text, "cls": cls, "card": card, "extra": extra or {}})
# MUST be stubbed: _ask_owner now asks the chat whether a question is already
# open, and the real one reads the owner's live log - an unsandboxed run would
# defer every ask and test nothing. (That it failed exactly this way on the
# first run is the guard proving itself against real data.)
copilot.chat_question_open = lambda: None

from cells.pm import pm_comm
pm_comm._escalation_tid = lambda: ""
ok = pm_comm._ask_owner("Karte X ist über Budget. Weiterlaufen lassen?",
                        [{"label": "Stoppen", "description": "anhalten"},
                         {"label": "Weiterlaufen", "description": "Budget erhöhen"}],
                        header="Über Budget", card="t1")
check("_ask_owner reports success", ok is True)
# the exact string the live 12:47 question got wrong: a raw slice produced
# "...Die automatischen PM-M", cut mid-word
_raw = "UX-FIX (Owner-Beschwerde 2026-08-30): Die automatischen PM-Meldungen"
_lab = notice.label(_raw)
check("the card is named on a WORD boundary, not mid-word",
      _lab.endswith("…") and _raw.startswith(_lab[:-1])
      and not _raw[len(_lab) - 1:len(_lab)].strip())
check("a short name is left alone", notice.label("Wear-OS-Bug") == "Wear-OS-Bug")
check("an empty task falls back to the id", notice.label("", fallback="t1") == "t1")
check("one chat entry written", len(SAID) == 1)
# cls "bot" is what BOTH ends of the question channel key on - copilot.
# open_question (which routes_copilot._answer_text checks the tapped request_id
# against) and the app's openChatQuestion. "pm" would render dead buttons.
check("posted in the class the question channel reads", SAID and SAID[0]["cls"] == "bot")
q = SAID[0]["extra"].get("question") if SAID else None
check("a typed question rides along", bool(q) and bool(q.get("id")))
check("the options survived as real buttons",
      q and len(q["questions"][0]["options"]) == 2)
check("the header is bounded", q and len(q["questions"][0]["header"]) <= ask.MAX_HEADER_LEN)
# the round trip the owner's tap actually takes
picks, err = ask.validate_answers(q, {q["questions"][0]["header"]: "Stoppen"})
check("a tapped answer validates", not err and picks and picks[0]["labels"] == ["Stoppen"])
bad, err2 = ask.validate_answers(q, {})
check("an empty answer is refused, not silently accepted", bad is None and err2)

# a question that cannot be built must DEGRADE to a line, never to silence
del SAID[:]
ESCALATED = []
pm_comm._escalate = lambda text, tid="", title="": ESCALATED.append(text)
ok2 = pm_comm._ask_owner("Nur eine Option ist keine Wahl.",
                         [{"label": "Nur die eine"}], card="t1")
check("an unusable option list does not produce a dead panel", ok2 is False)
check("...and falls back to speaking, not to silence", len(ESCALATED) == 1)


# =============================================================================
print("4. ONE open question at a time (the 12:47 dead-panel regression)")

# Measured live 2026-08-30 12:47: the first PM tick after the rework posted
# three asks back to back. The chat answers only the NEWEST, so the two earlier
# and MORE URGENT budget questions were dead panels the instant the third
# landed. A dedup latch does not prevent this - it stops the same notice
# repeating, not two different ones firing in one tick.
del SAID[:]
HANDOVER = []
pm_comm._to_henry = lambda kind, detail, card=None, feed="": HANDOVER.append(
    {"kind": kind, "detail": detail, "feed": feed})

PENDING = [None]
copilot.chat_question_open = lambda: PENDING[0]

OPTS = [{"label": "Stoppen", "description": "anhalten"},
        {"label": "Weiterlaufen", "description": "weiter"}]

first = pm_comm._ask_owner("Karte A ist über Budget. Weiterlaufen lassen?", OPTS, card="a")
check("with nothing pending, the first ask goes through", first is True and len(SAID) == 1)

# now one IS open - exactly the 12:47 state
PENDING[0] = SAID[0]["extra"]["question"]
second = pm_comm._ask_owner("Karte B ist über Budget. Weiterlaufen lassen?", OPTS, card="b")
check("a second ask is refused while one is open", second is False)
check("only ONE chat entry exists - no dead panel", len(SAID) == 1)
check("the refused ask is handed to Henry, not dropped",
      len(HANDOVER) == 1 and HANDOVER[0]["kind"] == "owner-ask-deferred")
check("Henry gets the question AND its options",
      HANDOVER and "Karte B" in HANDOVER[0]["detail"]
      and "Stoppen" in HANDOVER[0]["detail"])
check("the deferral is visible on the dashboard too", HANDOVER and HANDOVER[0]["feed"])

# the owner answers -> open_question settles itself -> the slot re-arms.
# No stored flag to clear: that is why the guard reads the log.
PENDING[0] = None
third = pm_comm._ask_owner("Karte C ist über Budget. Weiterlaufen lassen?", OPTS, card="c")
check("once answered, the next ask goes through again",
      third is True and len(SAID) == 2)


print("")
if FAILS:
    print("FAILED: %d check(s): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("ALL NOTICE-ROUTING CHECKS PASSED")
