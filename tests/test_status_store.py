# -*- coding: utf-8 -*-
"""The watertight status store (P3.4) must STAY watertight.

Tracks used to be whole dicts written last-writer-wins from >=4 threads; a stale
snapshot resurrected 'running' and froze a card for 164min (2026-08-07 16:09).
sessions._mutate is now the ONE write path (Paseo's one-owner principle), and
the API derives 'running' at read time (sessions.present, Paseo's
normalizeArchivedStatus). Pins:
  (a) two concurrent _mutate writers -> BOTH changes land (no lost update)
  (b) cancel-vs-steer race, real threads, 50 iterations -> end state is ALWAYS
      needs_you with the session_id intact (invariant I3)
  (c) API read coercion: stored 'running' + no live turn + idle>45s is DELIVERED
      as needs_you; a live turn stays running; the spawn window stays running;
      the STORED value is never touched (invariant I2)
Self-sandboxing: monkeypatched load/save (deep-copy store simulating the DB
round-trip), stubbed events/notify/drivers, tmp run_dir - no daemon, no real DB.
"""
import json, os, random, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)
from spine.storage import db
db.init()                      # role defaults to "tool": NO boot devaluation here
from spine.storage import trackstore
from cells.engineer import sessions
from cells.engineer import lifecycle
from cells.engineer import turnrunner
from spine.agent import drivers
from spine.storage import events
from spine.comms import notify

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- isolate from production: deep-copy store, no audit pollution, no push ----
store = {}


def _load():
    return [json.loads(json.dumps(t)) for t in store.values()]


def _save(t):
    store[t["id"]] = json.loads(json.dumps(t))


sessions._load = _load
sessions._save_track = _save


class FakeDB:
    """cancel_turn/_finish_turn/_mutate call _load/_find/_mutate imported
    directly from trackstore, not through sessions - so the fake backing
    store (with the deep-copy DB-round-trip simulation) has to sit under
    trackstore._db."""
    def tracks_all(self):
        return [json.loads(json.dumps(t)) for t in store.values()]
    def track_put(self, t):
        store[t["id"]] = json.loads(json.dumps(t))
    def track_get(self, tid):
        t = store.get(tid)
        return json.loads(json.dumps(t)) if t else None


trackstore._db = FakeDB()
events.emit = lambda *a, **k: None
notify.card_event = lambda *a, **k: None
notify.clear_dedup = lambda *a, **k: None
turnrunner._ask_repair_on = lambda t: False
turnrunner._record_econ = lambda t, meta: 0.0
lifecycle._promote_live_session = lambda t: False

TMP = tempfile.mkdtemp(prefix="helmdeck-status-store-")


# ---------------------------------------------------------------- (a) no lost update
store.clear()
store["T-A"] = {"id": "T-A", "status": "needs_you", "run_dir": TMP}


def slow_writer(field, value):
    def fn(t):
        t[field] = value
        time.sleep(0.05)       # widen the load->save window a racer would exploit
    sessions._mutate("T-A", fn)


th1 = threading.Thread(target=slow_writer, args=("a", 1))
th2 = threading.Thread(target=slow_writer, args=("b", 2))
th1.start(); th2.start(); th1.join(); th2.join()
check(store["T-A"].get("a") == 1 and store["T-A"].get("b") == 2,
      "(a) two concurrent _mutate writers -> both changes land")

# fn returning False skips the save; a missing track returns None
before = json.dumps(store["T-A"], sort_keys=True)
sessions._mutate("T-A", lambda t: False)
check(json.dumps(store["T-A"], sort_keys=True) == before,
      "(a) fn returning False -> save skipped")
check(sessions._mutate("NOPE", lambda t: None) is None,
      "(a) missing track -> None, nothing created")


# ---------------------------------------------------------------- (b) cancel vs steer
class _StubLog:
    def log(self, *a, **k):
        return {}


drivers.cancel = lambda tid: True          # Stop always "kills" a live turn


def race_once(i):
    store.clear()
    store["RACE"] = {"id": "RACE", "status": "running", "session_id": "S1",
                     "lane": "working", "turns": 3, "run_dir": TMP, "repo": None}
    meta = {"usage": {}, "cost_usd": None, "models": [], "canceled": True}

    def do_cancel():
        time.sleep(random.random() * 0.01)
        sessions.cancel_turn("RACE", actor="test")

    def do_finish():
        time.sleep(random.random() * 0.01)
        sessions._finish_turn("RACE", "S1", "fertig.", meta, _StubLog())

    ths = [threading.Thread(target=do_cancel), threading.Thread(target=do_finish)]
    random.shuffle(ths)
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    final = store["RACE"]
    return final.get("status") == "needs_you" and final.get("session_id") == "S1"


random.seed(7)
ok = all(race_once(i) for i in range(50))
check(ok, "(b) cancel-vs-steer race x50 -> ALWAYS needs_you, session_id intact")


# ---------------------------------------------------------------- (c) read coercion
class Stub:
    def __init__(self, cur):
        self._cur = cur

    def alive(self):
        return True


_real_idle = lifecycle._track_idle_s

t_running = {"id": "COERCE", "status": "running", "run_dir": TMP}

# stored running, NO live turn, idle > 45s -> delivered as needs_you, store untouched
drivers._sessions.pop("COERCE", None)
lifecycle._track_idle_s = lambda t: 999
out = sessions.present(dict(t_running))
check(out.get("status") == "needs_you" and out.get("status_derived") is True,
      "(c) running + no turn + idle>45 -> served as needs_you (derived)")
check(t_running["status"] == "running",
      "(c) coercion is read-only - stored value untouched")

# a genuinely live turn keeps its spinner
drivers._sessions["COERCE"] = Stub(cur={"x": 1})
out = sessions.present(dict(t_running))
check(out.get("status") == "running", "(c) live turn (turn_active) -> stays running")
drivers._sessions.pop("COERCE", None)

# the spawn window (idle <= 45s) is never coerced - no needs_you flicker on start
lifecycle._track_idle_s = lambda t: 3
out = sessions.present(dict(t_running))
check(out.get("status") == "running", "(c) spawn window (idle<=45) -> stays running")

# non-running statuses pass through untouched
lifecycle._track_idle_s = lambda t: 999
same = {"id": "COERCE", "status": "needs_you", "run_dir": TMP}
check(sessions.present(same) is same, "(c) non-running -> passed through as-is")

lifecycle._track_idle_s = _real_idle

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("status-store: all pinned - PASS")
