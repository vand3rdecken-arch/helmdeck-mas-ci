# -*- coding: utf-8 -*-
"""Headless test for GLANCE COMPLETENESS - the "the glasses said all clear while
the board was on fire" bug class.

/glance is the read-only feed the Ray-Ban Display webapp (glasses/) reads. It
answers ONE question: what is blocked on ME? It answered it by re-deriving
"needs me" from `status == "needs_you"`, which silently dropped EVERY card the
harness parks under another status:

  * bounced by a RED GATE            (sessions._gatefail)
  * bounced on an open merge CONFLICT (sessions._markers / _mergefail)
  * bounced by a failed DISPATCH      (sessions._dispatch_failed)
  * bounced by the ZOMBIE SWEEP       (sessions.sweep_zombies)
  * bounced back by the OWNER         (sessions.move_lane review -> working)
  * SUBMITTED, resting on Review for the accept (sessions._submit)

Six ways for work to stop dead on the owner, none of them on the glasses. The
board's own predicate (sessions.waits_for_owner) and the PM narrative
(pm.activity) each had their own third and fourth answer to the same question.

Under test:
  1. sessions.blocker - the ONE derivation, full truth table incl. the states
     that must stay OFF the feed (running, gating, queued, done, archived, and
     a card waiting on its own background task)
  2. server.glance_payload - every blocked card reaches the wire, with its
     reason, worst news first, and the home-screen count equal to the list
  3. a phantom `running` (turn died) is surfaced at READ time via present()
  4. ANTI-DRIFT: /glance, sessions.waits_for_owner and pm.activity all name the
     SAME set of cards for the same board - one question, one answer

Self-sandboxing: an in-memory board, drivers/events/pm-config seams
monkeypatched - no daemon, no DB, no socket, no network, no LLM."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

import sessions


class FakeDrivers:
    """The liveness oracle. Only `m-running` actually has a turn in flight, so
    every other stored `running` on the board is a phantom."""
    live = {"m-running"}

    @staticmethod
    def turn_active(tid):
        return tid in FakeDrivers.live

    @staticmethod
    def has_session(tid):
        return tid in FakeDrivers.live


sys.modules["drivers"] = FakeDrivers

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# -- the board: one card per state the harness can leave a card in -------------
# Each entry is (card, expected blocker reason or None). This IS the audit: a
# new parked state must be added here, and it must come out of blocker().
BOARD = [
    # --- blocked on the owner -------------------------------------------------
    ({"id": "c-gate", "task": "gate red", "status": "bounced", "lane": "review",
      "gate_report": ["tests/test_x.py:\nassert 1 == 2", "second problem"]},
     "gate"),
    ({"id": "c-conflict", "task": "cannot land", "status": "bounced", "lane": "review",
      "merge_report": "Konfliktmarkierungen sind noch im Worktree offen.",
      "merge_kind": "conflict"},
     "conflict"),
    ({"id": "c-mergeblocked", "task": "merge blocked", "status": "bounced", "lane": "review",
      "merge_report": "main ist nicht auscheckbar", "merge_kind": "blocked"},
     "failed"),
    ({"id": "c-dispatch", "task": "dispatch died", "status": "bounced", "lane": "working",
      "last_reply": "DISPATCH FAILED: no such worktree"},
     "failed"),
    ({"id": "c-zombie", "task": "swept zombie", "status": "bounced", "lane": "working",
      "gate_report": ["Turn mit dem Daemon-Neustart abgebrochen"]},
     "gate"),
    ({"id": "c-ownerbounce", "task": "owner bounced it", "status": "bounced",
      "lane": "working"},
     "failed"),
    ({"id": "c-submitted", "task": "resting on review", "status": "submitted",
      "lane": "review", "review_report": "sauber mergebar"},
     "review"),
    ({"id": "c-question", "task": "asks you", "status": "needs_you", "lane": "working",
      "waiting_on": "you",
      "question": {"id": "q-1", "kind": "choice",
                   "questions": [{"question": "Postgres oder SQLite?",
                                  "header": "DB", "options": []}]}},
     "question"),
    ({"id": "c-delivered", "task": "handed back", "status": "needs_you", "lane": "working",
      "waiting_on": "you", "last_reply": "Fertig - bitte pruefen."},
     "delivered"),
    ({"id": "c-bounced-asking", "task": "bounced while asking", "status": "bounced",
      "lane": "working",
      "question": {"id": "q-2", "kind": "choice",
                   "questions": [{"question": "Welchen Branch nehme ich?",
                                  "header": "Branch", "options": []}]}},
     "question"),
    # a stored `running` whose turn DIED - no test of `status` can see this one,
    # which is exactly why the derivation presents before it decides
    ({"id": "c-phantom", "task": "turn died", "status": "running", "lane": "working"},
     "delivered"),
    # --- NOT the owner's move -------------------------------------------------
    # (m-running is held live by FakeDrivers below)
    ({"id": "m-running", "task": "working now", "status": "running", "lane": "working"}, None),
    ({"id": "m-gating", "task": "gate is running", "status": "gating", "lane": "review"}, None),
    ({"id": "m-queued", "task": "not started", "status": "queued", "lane": "backlog"}, None),
    ({"id": "m-accepted", "task": "landed", "status": "accepted", "lane": "done"}, None),
    ({"id": "m-background", "task": "waiting on its own task", "status": "needs_you",
      "lane": "working", "waiting_on": "background", "background": {"n": 1, "names": ["build"]}},
     None),
    ({"id": "m-archived", "task": "archived bounce", "status": "bounced", "lane": "review",
      "archived": True, "gate_report": ["red"]},
     None),
]

TRACKS = [dict(c) for c, _ in BOARD]
BLOCKED_IDS = {c["id"] for c, r in BOARD if r}


# -- 1. the one derivation ----------------------------------------------------
def reason_of(card):
    """What the surfaces see: present() then blocker(), i.e. owner_blockers."""
    got = sessions.owner_blockers([dict(card)])
    return got[0][1]["reason"] if got else None


def test_blocker_truth_table():
    print("owner_blockers - every state the harness can park a card in:")
    for card, want in BOARD:
        got = reason_of(card)
        check(got == want, "%-18s -> %s" % (card["id"], want or "not the owner's move"))
    check(sessions.owner_blockers([]) == [], "an empty board is handled")
    check(sessions.owner_blockers(None) == [], "None is handled")
    check(sessions.blocker(None) is None and sessions.blocker({}) is None,
          "blocker() handles None / an empty card")

    print("blocker() itself is PURE - liveness is present()'s job, not its own:")
    phantom = {"id": "c-phantom", "task": "turn died", "status": "running"}
    check(sessions.blocker(phantom) is None,
          "blocker() on a stored `running` says nothing (it cannot know the turn died)")
    check(reason_of(phantom) == "delivered",
          "...and owner_blockers pairs it with present(), which can")

    print("blocker reasons are the published vocabulary:")
    for _card, want in BOARD:
        if want:
            check(want in sessions.BLOCKER_REASONS, "%s in BLOCKER_REASONS" % want)

    print("the detail carries WHY, on one line:")
    gate = sessions.blocker(dict(TRACKS[0]))
    check("assert 1 == 2" in gate["detail"],
          "a gate bounce names the failing ASSERTION, not just the file")
    check("\n" not in gate["detail"] and len(gate["detail"]) <= 160,
          "the detail is one short line (600x600 display)")
    q = sessions.blocker({"id": "q", "status": "needs_you",
                          "question": {"id": "q-1", "kind": "choice",
                                       "questions": [{"question": "Postgres oder SQLite?",
                                                      "header": "DB", "options": []}]}})
    check("Postgres" in (q["detail"] or ""), "an asking card carries the question itself")
    check("Branch" in (sessions.blocker(dict(
        [c for c, _ in BOARD if c["id"] == "c-bounced-asking"][0]))["detail"] or ""),
        "a bounce that is still ASKING reports the question, not a bare 'failed'")

    print("waits_for_owner is the same derivation, not a second one:")
    for card, want in BOARD:
        check(sessions.waits_for_owner(dict(card)) == bool(want),
              "waits_for_owner(%s) == %s" % (card["id"], bool(want)))


# -- 2. the wire --------------------------------------------------------------
METRICS = {"capacity": {"wip": 2, "wip_limit": 3, "headroom": 1},
           "totals": {"margin": 1234.5}, "settings": {"currency": "EUR"},
           "sows": [{"name": "Acme", "margin": 400.0}]}


def test_glance_payload():
    import server
    print("server.glance_payload - what actually reaches the glasses:")
    pay = server.glance_payload([dict(t) for t in TRACKS], METRICS)
    got = {c["id"] for c in pay["needs_you"]}

    missing = sorted(BLOCKED_IDS - got)
    extra = sorted(got - BLOCKED_IDS)
    check(not missing, "no blocked card is dropped (missing: %s)" % (missing or "none"))
    check(not extra, "nothing that is NOT the owner's move leaks in (extra: %s)" % (extra or "none"))

    print("the regression that started this - each of these used to be invisible:")
    for tid, reason in (("c-gate", "gate"), ("c-conflict", "conflict"),
                        ("c-dispatch", "failed"), ("c-ownerbounce", "failed"),
                        ("c-submitted", "review")):
        c = [x for x in pay["needs_you"] if x["id"] == tid]
        check(bool(c) and c[0]["reason"] == reason,
              "%-14s is on the feed as '%s'" % (tid, reason))

    print("the payload is self-consistent:")
    check(pay["econ"]["needs_you"] == len(pay["needs_you"]),
          "the home-screen number equals the list it opens")
    check(all(c.get("detail") is not None and "reason" in c for c in pay["needs_you"]),
          "every entry carries a reason and a detail")
    check(all(len(c["task"]) <= 70 for c in pay["needs_you"]), "titles stay glasses-sized")

    print("worst news first (the glasses show one screen):")
    order = [c["reason"] for c in pay["needs_you"]]
    ranks = [server.GLANCE_RANK[r] for r in order]
    check(ranks == sorted(ranks), "sorted by blocker severity: %s" % order)
    check(order[0] in ("gate", "conflict", "failed"), "a stuck card is on the first screen")

    print("back-compat with glasses builds older than the reason vocabulary:")
    asking = [c for c in pay["needs_you"] if c["id"] == "c-question"][0]
    check(asking["asking"] is True, "an asking card still sets the old `asking` flag")
    check(all(c["asking"] is False for c in pay["needs_you"] if c["reason"] != "question"),
          "nothing else claims to be asking")
    check(pay["econ"]["wip_limit"] == 3 and pay["sows"][0]["name"] == "Acme",
          "the econ/SoW half is unchanged")

    print("empty board:")
    empty = server.glance_payload([], METRICS)
    check(empty["needs_you"] == [] and empty["econ"]["needs_you"] == 0,
          "an idle board really is 'all clear'")


def test_phantom_running_is_surfaced():
    """A card whose turn DIED still says `running` in the store until the
    reconciler heals it. present() derives the truth at read time - so the feed
    must show it, or the owner sees a spinner on the glasses forever."""
    import server
    print("liveness decides, not the stored status:")
    dead = {"id": "c-phantom", "task": "turn died", "status": "running", "lane": "working"}
    alive = {"id": "m-running", "task": "working now", "status": "running", "lane": "working"}
    pay = server.glance_payload([dead, alive], METRICS)
    got = [(c["id"], c["reason"]) for c in pay["needs_you"]]
    check(got == [("c-phantom", "delivered")],
          "the phantom is surfaced, the live turn is not: %s" % got)


# -- 3. anti-drift ------------------------------------------------------------
def test_surfaces_agree():
    """The bug was never one endpoint - it was three surfaces each deriving
    "blocked on you" from raw status on their own. Pin them together."""
    import pm, server
    print("every surface names the same cards for the same board:")

    sessions.list_tracks = lambda: [dict(t) for t in TRACKS]
    pm._pm = lambda: {"loop_enabled": False, "autonomy": "ask"}
    pm._loopstate = lambda: {}
    pm._state = lambda: ("OFF", "Proaktiv ist aus.")
    pm._read_activity = lambda n=20: []

    act = pm.activity()
    pay = server.glance_payload([dict(t) for t in TRACKS], METRICS)

    by_task = {(t.get("task") or "")[:70]: t["id"] for t in TRACKS}
    pm_ids = {by_task[x] for x in (act["needs_you"] + act["blockers"])}
    glance_ids = {c["id"] for c in pay["needs_you"]}
    predicate_ids = {t["id"] for t in TRACKS if sessions.waits_for_owner(dict(t))}

    check(pm_ids == glance_ids,
          "pm.activity == /glance (diff: %s)" % (sorted(pm_ids ^ glance_ids) or "none"))
    check(predicate_ids == glance_ids,
          "waits_for_owner == /glance (diff: %s)" % (sorted(predicate_ids ^ glance_ids) or "none"))
    check(glance_ids == BLOCKED_IDS, "...and all three equal the audited set")

    print("the PM still splits stuck work from work awaiting a decision:")
    stuck = ("c-gate", "c-conflict", "c-mergeblocked", "c-dispatch",
             "c-zombie", "c-ownerbounce")
    check(set(act["blockers"]) == {(t.get("task") or "")[:70] for t in TRACKS
                                   if t["id"] in stuck},
          "blockers = the STUCK cards, never double-counted under needs_you")
    check(not (set(act["blockers"]) & set(act["needs_you"])),
          "no card appears in both buckets")
    check("wartet auf dich: turn died" in act["now"],
          "a card whose turn died reads 'wartet auf dich', not 'arbeitet gerade an'")
    check(not any(x.startswith("arbeitet gerade an: turn died") for x in act["now"]),
          "...and the PM no longer claims dead work is in flight")


test_blocker_truth_table()
test_glance_payload()
test_phantom_running_is_surfaced()
test_surfaces_agree()

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("glance completeness: PASS")
