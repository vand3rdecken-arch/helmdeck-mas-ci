# -*- coding: utf-8 -*-
"""Board overview stage 1: the completion date of a card and everything that
hangs off it.

Under test (the real paths, no mocks of the code under test):
  1. BOTH accept mutators stamp done_at (repo accept via move_lane, machine
     accept), a re-accept keeps the first stamp, and reopening a card drops it
  2. backfill_done_at reconstructs it ONCE from the latest done event for
     legacy cards (debt done-at-reconstructed-from-events); a card with no
     done event is left alone; a second run is a no-op
  3. sweep_done_archive archives only done cards older than
     policy.done_archive_days, as actor 'policy'; cards without done_at,
     recent cards and open cards stay; 0 = off
  4. the tracks list is bounded: done cards past the 14-day window leave the
     default list and answer on ?archived=1; the pull baseline reports their
     count as older_done

Self-sandboxing: an in-memory board; gate/merge/hooks/events monkeypatched - no
daemon, no git, no network, no LLM. events.emit is patched so nothing can reach
the LIVE db.

Run: py -3.12 ops/tests/test_done_at.py
"""
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()

from cells.copilot.chat import copilot
from spine.comms import notify
from spine.storage import db, events, trackstore
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")   # policy/SoD lookups must never reach the LIVE db
db.init()
from cells.engineer.cards import cardadmin, dispatch, lanemachine, lifecycle, sessions
from cells.engineer.routes import routes_tracks

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


store = {}
EVENTS = []                       # what read_events() serves
EMITTED = []                      # what emit() was asked to write
POLICY = {}

copilot.say = lambda text, cls="pm": None
notify.card_event = lambda t, status: None
notify.push_fcm = lambda *a, **k: None
events.emit = lambda kind, track=None, **kw: EMITTED.append((kind, track, kw))
events.read_events = lambda *a, **k: list(EVENTS)
events.settings = lambda: {"policy": dict(POLICY), "value_per_card": 100}


class FakeDB:
    def tracks_all(self):
        return list(store.values())

    def track_put(self, t):
        store[t["id"]] = t

    def track_get(self, tid):
        return store.get(tid)

    def track_delete(self, tid):
        store.pop(tid, None)


trackstore._db = FakeDB()

RUN = os.path.join(SANDBOX, "run")
WT = os.path.join(SANDBOX, "wt")
os.makedirs(RUN, exist_ok=True)
os.makedirs(WT, exist_ok=True)

lanemachine._autocommit = lambda t: True
lanemachine._repo_hook = lambda t, kind: True
lanemachine._gate = lambda t: (True, [])
lanemachine._merge_to_main = lambda t: (True, "merged", "gemergt")
lanemachine.reclaim_worktree = lambda t, log=None: None
cardadmin.reclaim_worktree = lambda t, log=None: None


def card(tid, **kw):
    t = {"id": tid, "task": "Karte " + tid, "branch": "b-" + tid, "status": "submitted",
         "lane": "review", "repo": SANDBOX, "worktree": WT, "run_dir": RUN,
         "mode": "auto", "turns": 1, "ai_cost": 0.1, "value": 100,
         "priority": "medium", "due": "", "last_reply": ""}
    t.update(kw)
    store[tid] = t
    return t


def ago(days):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))


STAMP = "%Y-%m-%d %H:%M:%S"
print("done_at (board overview stage 1)")

# -- 1. both accept mutators stamp it ---------------------------------------
card("c-repo", last_reply="DELIVERED: fertig.")
before = time.time()
sessions.move_lane("c-repo", "done", actor="owner")
d = store["c-repo"].get("done_at")
check(bool(d) and abs(time.mktime(time.strptime(d, STAMP)) - before) < 30,
      "repo accept stamps done_at (now, local format)")

card("c-mach", machine=True, last_reply="DELIVERED: Task angelegt.")
sessions.move_lane("c-mach", "done", actor="owner")
check(bool(store["c-mach"].get("done_at")), "machine accept stamps done_at too")

three = ago(3)
store["c-repo"]["done_at"] = three
sessions.move_lane("c-repo", "done", actor="owner")       # already landed -> settle
check(store["c-repo"]["done_at"] == three, "a re-accept of a landed card keeps the first stamp")

sessions.move_lane("c-repo", "backlog", actor="owner")
check("done_at" not in store["c-repo"], "reopening a card drops done_at (fresh stamp on next accept)")

# -- 2. backfill from the done event ----------------------------------------
card("c-leg", lane="done", status="accepted")
card("c-noev", lane="done", status="accepted")
card("c-new", lane="done", status="accepted", done_at=ago(1))
card("c-open", lane="working", status="running")
EVENTS[:] = [{"kind": "done", "track": "c-leg", "ts": "2026-01-02 03:04:05"},
             {"kind": "done", "track": "c-leg", "ts": "2026-02-03 04:05:06"},   # reopened + re-accepted
             {"kind": "note", "track": "c-noev", "ts": "2026-02-03 04:05:06"},
             {"kind": "done", "track": "c-new", "ts": "2020-01-01 00:00:00"},
             {"kind": "done", "track": "c-open", "ts": "2026-02-03 04:05:06"}]
keep_new = store["c-new"]["done_at"]
n = sessions.backfill_done_at()
check(store["c-leg"].get("done_at") == "2026-02-03 04:05:06", "legacy card gets the LATEST done event's ts")
check("done_at" not in store["c-noev"], "a done card without a done event is left alone")
check(store["c-new"]["done_at"] == keep_new, "a card that already has done_at is never overwritten")
check("done_at" not in store["c-open"], "an open card is not touched")
check(n == 1, "exactly the one reconstructable card was stamped (got %r)" % n)
check(sessions.backfill_done_at() == 0, "backfill is idempotent")

# -- 3. auto-archive sweep ---------------------------------------------------
store.clear()
card("a-old", lane="done", status="accepted", done_at=ago(90))
card("a-mid", lane="done", status="accepted", done_at=ago(30))
card("a-nodate", lane="done", status="accepted")
card("a-open", lane="working", status="running", done_at=ago(90))
card("a-arch", lane="done", status="accepted", done_at=ago(90), archived=True)
EMITTED.clear()

POLICY.clear()
check(lifecycle.sweep_done_archive() == [] and not EMITTED, "no policy value -> the sweep is off (0 = never)")
POLICY["done_archive_days"] = 0
check(lifecycle.sweep_done_archive() == [], "done_archive_days 0 = off")
POLICY["done_archive_days"] = 60
got = lifecycle.sweep_done_archive()
check(got == ["a-old"], "only the done card older than N days is archived (got %r)" % got)
check(store["a-old"].get("archived") is True, "the card carries archived=true")
check(not store["a-mid"].get("archived") and not store["a-nodate"].get("archived")
      and not store["a-open"].get("archived"),
      "younger, undated and open cards stay")
check(any(k == "archive" and tr == "a-old" and kw.get("actor") == "policy" for k, tr, kw in EMITTED),
      "the audit event names actor 'policy'")
check(lifecycle.sweep_done_archive() == [], "a second sweep finds nothing (archived cards are skipped)")
POLICY["done_archive_days"] = "x"
check(lifecycle.sweep_done_archive() == [], "a junk policy value is ignored, not a crash")
cardadmin.archive_track("a-old", on=False, actor="owner")
check(store["a-old"].get("archived") is False, "reversible: the owner's unarchive works as before")

# -- 4. bounded tracks list ---------------------------------------------------
store.clear()
card("r-open", lane="working", status="running")
card("r-recent", lane="done", status="accepted", done_at=ago(2))
card("r-old", lane="done", status="accepted", done_at=ago(40))
card("r-undated", lane="done", status="accepted")
card("r-arch", lane="working", archived=True)

routes_tracks._visible = lambda t, user: True
routes_tracks._view = lambda t, user: t
sessions.list_tracks = lambda: list(store.values())
sessions.present = lambda t: t
db.tracks_changed_since = lambda since: (7, [])


class H:
    def __init__(self, path):
        self.path = path
        self.code, self.body = None, None

    def _send(self, code, body):
        self.code, self.body = code, json.loads(body)


def ids_of(h):
    return sorted(t["id"] for t in h.body)


h = H("/tracks")
routes_tracks.tracks_list_get(h, "owner")
check("r-old" not in ids_of(h) and {"r-open", "r-recent", "r-undated"} <= set(ids_of(h)),
      "default list: open + recent done + undated done, NOT the old done card (got %r)" % ids_of(h))
h = H("/tracks?archived=1")
routes_tracks.tracks_list_get(h, "owner")
check(ids_of(h) == ["r-arch", "r-old"], "?archived=1 serves archived + old done (got %r)" % ids_of(h))

h = H("/tracks?cookie=")
routes_tracks.tracks_list_get(h, "owner")
put = sorted(p["key"] for p in h.body["patch"] if p["op"] == "put")
check("r-old" not in put and "r-recent" in put, "pull baseline puts the bounded board (got %r)" % put)
check(h.body.get("older_done") == 1, "pull baseline reports older_done (got %r)" % h.body.get("older_done"))

print()
print("FAILED: %d" % len(_fails) if _fails else "all ok")
sys.exit(1 if _fails else 0)
