# -*- coding: utf-8 -*-
"""Headless test for the CARD OUTCOME seam - the "the plan forgot the answer"
bug class.

The board snapshot only surfaced last_reply while a card was needs_you; once
accepted, its result text vanished from the PM's view. The PM plan/triage reads
that same snapshot, so an owner decision a card's final reply had long answered
(e.g. the tester-origin question) kept resurfacing as "open".

Under test (all three seams):
  1. sessions.extract_outcome distills a 1-2 line result from a final reply
     (DELIVERED convention preferred, hand-off boilerplate stripped)
  2. BOTH accept paths persist it at event time: move_lane -> done (repo card)
     and _accept_machine -> done (machine card)
  3. copilot._snapshot shows outcome= for finished cards (STORED outcome only -
     never derived per read) while keeping last_reply= for needs_you - and
     nothing for a quietly working card
  4. sessions.backfill_outcomes stamps legacy pre-outcome done cards exactly
     once at daemon start: reviewed overrides beat the heuristic, junk replies
     stamp '' (key presence = migrated), non-done and already-stamped cards
     are untouched, and a second run is a no-op
     (pays debt legacy-outcome-on-read)

Self-sandboxing: an in-memory board, gate/merge/hooks/notify monkeypatched -
no daemon, no git, no network, no LLM."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()

import copilot, notify, sessions

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# -- in-memory board + captured channels --------------------------------------
store = {}

copilot.say = lambda text, cls="pm": None
notify.card_event = lambda t, status: None
notify.push_fcm = lambda *a, **k: None
sessions._load = lambda: list(store.values())
sessions.list_tracks = lambda: list(store.values())
sessions._save_track = lambda t: store.__setitem__(t["id"], t)

RUN = os.path.join(SANDBOX, "run")
WT = os.path.join(SANDBOX, "wt")
os.makedirs(RUN, exist_ok=True)
os.makedirs(WT, exist_ok=True)


class FakeEvents:
    """events without the append-only store; metrics/settings for _snapshot."""
    @staticmethod
    def emit(*a, **k):
        pass

    @staticmethod
    def read_events():
        return []

    @staticmethod
    def _completion_mode(te, turns):
        return "auto"

    @staticmethod
    def metrics(tracks):
        return {"capacity": {"wip": 0, "wip_limit": 3, "headroom": 3}}

    @staticmethod
    def settings():
        return {"policy": {}, "value_per_card": 100}


class FakeProcesses:
    @staticmethod
    def list_processes():
        return []


sys.modules["events"] = FakeEvents
sys.modules["processes"] = FakeProcesses

# The slow/dangerous seams: never run a real gate, merge, hook or git in a test.
sessions._autocommit = lambda t: True
sessions._repo_hook = lambda t, kind: True
sessions._gate = lambda t: (True, [])
sessions._merge_to_main = lambda t: (True, "merged", "2 commits nach main gemergt")
sessions.reclaim_worktree = lambda t, log=None: None


def card(tid, **kw):
    t = {"id": tid, "task": "Karte " + tid, "branch": "b-" + tid, "status": "submitted",
         "lane": "review", "repo": SANDBOX, "worktree": WT, "run_dir": RUN,
         "mode": "auto", "turns": 3, "ai_cost": 0.5, "value": 100,
         "priority": "medium", "due": "", "last_reply": ""}
    t.update(kw)
    store[tid] = t
    return t


DELIVERED_REPLY = ("Analyse abgeschlossen, Details unten.\n\n"
                   "DELIVERED: Tester-Herkunft geklaert - 29 organische "
                   "Reddit-Adressen + 12 gekaufte.\n\n"
                   "Ready for Review - move the card to Review; accepting it deploys.")

print("card outcome (snapshot memory for finished cards)")

# -- 1. extract_outcome distills the DELIVERED summary -------------------------
o = sessions.extract_outcome(DELIVERED_REPLY)
check("29 organische" in o and "12 gekaufte" in o,
      "DELIVERED summary is extracted (the answered decision survives)")
check("Ready for Review" not in o and "DELIVERED" not in o,
      "hand-off boilerplate + anchor word are stripped")
check("Analyse abgeschlossen" not in o,
      "prose BEFORE the DELIVERED anchor is not the outcome")

o = sessions.extract_outcome("Fix eingebaut und getestet.\nAlle Tests gruen.\n"
                             "Naechster Schritt waere Doku.\nUnd noch mehr.")
check(o == "Fix eingebaut und getestet. Alle Tests gruen.",
      "no DELIVERED anchor -> first 2 lines of the reply")
check(sessions.extract_outcome("") == "" and sessions.extract_outcome(None) == "",
      "empty / missing reply -> empty outcome (never crashes)")
check(len(sessions.extract_outcome("DELIVERED: " + "x" * 999)) <= 240,
      "outcome is clipped to a short sentence, not a transcript")

# -- 2a. repo accept (move_lane -> done) persists the outcome -------------------
card("c-repo", last_reply=DELIVERED_REPLY)
out = sessions.move_lane("c-repo", "done", actor="owner")
check(out.get("status") == "accepted" and out.get("lane") == "done",
      "green Done lands the repo card")
check("29 organische" in store["c-repo"].get("outcome", ""),
      "accept PERSISTS the outcome on the card (event time, not read time)")

# -- 2b. machine accept persists it too ----------------------------------------
card("c-mach", machine=True, last_reply="DELIVERED: Autostart-Task angelegt, Tray laeuft.")
out = sessions.move_lane("c-mach", "done", actor="owner")
check(out.get("status") == "accepted" and out.get("lane") == "done",
      "machine Done accepts without gate/merge")
check("Autostart-Task angelegt" in store["c-mach"].get("outcome", ""),
      "machine accept persists the outcome too (both accept mutators)")

# -- 2c. accepting an ALREADY LANDED card is a no-op, never a re-gate ----------
# Live incident (card 20260812-164257): lane='done' is written only AFTER the
# deploy hook, so a card that had already merged+deployed still read
# lane=review for ~22s. A second Done in that window started a concurrent
# cycle whose gate hit the just-reclaimed worktree and BOUNCED a card that had
# shipped. A repeat accept must settle the card, not re-run gate/merge.
_gate_calls = []
_merge_calls = []
_real_gate, _real_merge = sessions._gate, sessions._merge_to_main
sessions._gate = lambda t: (_gate_calls.append(t["id"]), (True, []))[1]
sessions._merge_to_main = lambda t: (_merge_calls.append(t["id"]),
                                     (True, "merged", "gemergt"))[1]

out = sessions.move_lane("c-repo", "done", actor="owner")   # c-repo is accepted already
check(_gate_calls == [] and _merge_calls == [],
      "re-accepting a landed card runs NO gate and NO merge (got gate=%r merge=%r)"
      % (_gate_calls, _merge_calls))
check(out.get("status") == "accepted" and out.get("lane") == "done",
      "the re-accept settles the card in Done instead of bouncing it")
check(not out.get("gate_report") and not out.get("merge_failed"),
      "a landed card is never handed a gate punch list by a second accept")
check("29 organische" in store["c-repo"].get("outcome", ""),
      "the outcome recorded at the real accept survives the re-accept")
sessions._gate, sessions._merge_to_main = _real_gate, _real_merge
sessions._gate = lambda t: (True, [])
sessions._merge_to_main = lambda t: (True, "merged", "2 commits nach main gemergt")

# -- 3. the snapshot carries the result of FINISHED cards -----------------------
card("c-open", lane="working", status="needs_you", last_reply="Welche DB soll ich nehmen?")
card("c-work", lane="working", status="running", last_reply="Ich arbeite noch.")
# legacy: accepted BEFORE the outcome field existed - only last_reply survives
card("c-old", lane="done", status="accepted",
     last_reply="DELIVERED: OTA-Pipeline repariert, push_update.sh gruen.")

snap = copilot._snapshot()
line = {tid: next(l for l in snap.splitlines() if ("id=%s " % tid) in l)
        for tid in ("c-repo", "c-mach", "c-open", "c-work", "c-old")}

check("outcome=" in line["c-repo"] and "29 organische" in line["c-repo"],
      "snapshot: an accepted card SHOWS its outcome (PM triage reads this)")
check("outcome=" in line["c-mach"],
      "snapshot: an accepted machine card shows its outcome")
check("outcome=" not in line["c-old"],
      "snapshot: NO read-time derivation - an unstamped legacy card stays "
      "silent until the one-shot backfill runs (Paseo law)")
check("last_reply=" in line["c-open"] and "Welche DB" in line["c-open"],
      "snapshot: needs_you still carries its open question")
check("last_reply=" not in line["c-work"] and "outcome=" not in line["c-work"],
      "snapshot: a quietly working card stays quiet (no reply spam)")

# -- 4. the one-shot backfill (debt legacy-outcome-on-read) ---------------------
# the chatfork shape that PROVED the heuristic wrong: the reply opens with an
# off-topic aside, the actual answer comes later - reviewed override must win
CHATFORK = "20260811-153456-chatfork"
card(CHATFORK, lane="done", status="accepted",
     last_reply="## DELIVERED\n\nVerstanden fuer naechstes Mal - habe das als "
                "dauerhafte Erinnerung gespeichert.\n\nUnd die Sache ist "
                "geloest: Kailash hat die Gruppen-Adresse geliefert.")
# a junk final reply (cancelled turn) reviewed to '' - stamped but never shown
CANCELLED = "20260808-053628-req-fix-dashboard-zu-berf"
card(CANCELLED, lane="done", status="accepted", last_reply="(turn cancelled by you)")
# unreviewed legacy card: heuristic value is stamped ONCE
card("c-leg", lane="done", status="accepted",
     last_reply="DELIVERED: Relay-Neustart automatisiert, Tray-Supervisor aktiv.")
# not done / already stamped: backfill must not touch these
card("c-back", lane="backlog", status="resting", last_reply="DELIVERED: nix.")
store["c-repo"]["outcome_before"] = store["c-repo"]["outcome"]

n = sessions.backfill_outcomes()
check(n == 4, "backfill stamps exactly the unstamped done cards (got %d)" % n)
check("appclosedtesting@googlegroups.com" in store[CHATFORK]["outcome"]
      and "Erinnerung" not in store[CHATFORK]["outcome"],
      "chatfork: reviewed outcome (Kailash's tester group) beats the "
      "aside-first heuristic miss")
check(store[CANCELLED]["outcome"] == "",
      "junk reply: reviewed to '' - key present, no nonsense sentence")
check("Relay-Neustart automatisiert" in store["c-leg"]["outcome"],
      "unreviewed legacy card: heuristic value stamped at migration time")
check("outcome" not in store["c-back"],
      "non-done card is left alone")
check(store["c-repo"]["outcome"] == store["c-repo"]["outcome_before"],
      "event-time outcome from a real accept is never overwritten")
check(sessions.backfill_outcomes() == 0,
      "second run is a no-op (key presence = migrated, incl. '' stamps)")

snap = copilot._snapshot()
line = {tid: next(l for l in snap.splitlines() if ("id=%s " % tid) in l)
        for tid in (CHATFORK, CANCELLED, "c-old", "c-leg")}
check("outcome=" in line[CHATFORK] and "appclosedtesting" in line[CHATFORK],
      "snapshot after backfill: chatfork shows the REAL result "
      "(the done-when of the fix card)")
check("outcome=" not in line[CANCELLED],
      "snapshot after backfill: ''-stamped junk card shows no outcome line")
check("outcome=" in line["c-old"] and "OTA-Pipeline repariert" in line["c-old"],
      "snapshot after backfill: legacy card now shows its stamped outcome")
check("outcome=" in line["c-leg"],
      "snapshot after backfill: heuristic-stamped legacy card shows it too")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all card-outcome checks passed")
