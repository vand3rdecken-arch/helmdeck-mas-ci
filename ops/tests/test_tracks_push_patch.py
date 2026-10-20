# -*- coding: utf-8 -*-
"""The card patch that rides a pushed event (2026-10-20).

A board event now carries the /tracks patch itself (relay_client.
_EventPublisher._tracks_patch), so a card write costs the phone no request -
Paseo's agent_update carries the agent the same way. This proves, against the
REAL publisher and the REAL routes_tracks.tracks_patch:
  - the pushed patch is byte-identical to what that account's own pull returns;
  - a device registered to a CLIENT account never receives another account's
    card - the push is scoped exactly like the pull (the security half);
  - an unknown device key, an unknown account, a baseline or an oversized
    patch rides nothing (the app's pull covers it).

SELF-SANDBOXING like test_boards_http.py. Run: py -3.12 ops/tests/test_tracks_push_patch.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-tpush-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import db, events            # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET), ("users", auth.USERS)):
    assert path.startswith(_SANDBOX), "REFUSING TO RUN: %s points at %s" % (label, path)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


db.init()
auth.create_user("boss", "hunter2hunter2", "owner")
auth.create_user("ada", "hunter2hunter2", "client")
events.save_settings({"push": {"devices": {
    "PUB-BOSS": {"token": "t1", "label": "Android", "account": "boss"},
    "PUB-ADA": {"token": "t2", "label": "iPhone", "account": "ada"},
    "PUB-GONE": {"token": "t3", "label": "old", "account": "nobody"},
}}}, actor="test")

from cells.engineer.routes import routes_tracks   # noqa: E402
from spine.comms import relay_client as rc         # noqa: E402

pub = rc._EventPublisher.__new__(rc._EventPublisher)   # only the patch half - no socket, no thread

v0 = db.current_version()
db.track_put({"id": "20261020-090000-direct", "task": "boss card", "lane": "working", "client": "boss"})
db.track_put({"id": "20261020-090100-direct", "task": "ada card", "lane": "working", "client": "ada"})
frm = "%d.%d" % (db.TRACK_EPOCH, v0)

for who, key in (("boss", "PUB-BOSS"), ("ada", "PUB-ADA")):
    u = auth.get_user(who)
    pulled = routes_tracks.tracks_patch({"name": u["name"], "role": u["role"]}, frm)
    pushed = pub._tracks_patch(key, v0)
    check(pushed is not None, "%s: the event carries a patch" % who)
    if pushed:
        check(pushed["from"] == frm, "%s: it says where it starts (%s)" % (who, pushed["from"]))
        check(pushed["patch"] == pulled["patch"] and pushed["cookie"] == pulled["cookie"],
              "%s: pushed patch == that account's own pull" % who)

ada = pub._tracks_patch("PUB-ADA", v0) or {"patch": []}
puts = [op["key"] for op in ada["patch"] if op["op"] == "put"]
check("20261020-090000-direct" not in puts, "a CLIENT's device never receives the owner's card (%s)" % puts)
check("20261020-090100-direct" in puts, "but does receive its own")
boss = pub._tracks_patch("PUB-BOSS", v0) or {"patch": []}
check({op["key"] for op in boss["patch"] if op["op"] == "put"} >= {"20261020-090000-direct", "20261020-090100-direct"},
      "the owner's device receives both")

check(pub._tracks_patch("PUB-UNKNOWN", v0) is None, "an unregistered device key: no payload")
check(pub._tracks_patch("PUB-GONE", v0) is None, "a device of a deleted account: no payload")
# The publisher always asks from the CURRENT epoch, so a baseline cannot come
# out of it today - the guard is for the day tracks_patch answers `clear` for
# another reason (e.g. a pruned change log). Drive the guard itself.
_real = routes_tracks.tracks_patch
routes_tracks.tracks_patch = lambda user, cookie: {"cookie": "x.9", "patch": [{"op": "clear"}]}
check(pub._tracks_patch("PUB-BOSS", v0) is None, "a baseline (clear) never rides an event")
routes_tracks.tracks_patch = _real

rc._EventPublisher.TRACKS_PUSH_MAX = 200
check(pub._tracks_patch("PUB-BOSS", v0) is None, "a patch over the size bound: no payload, the pull covers it")

print("RESULT:", "PASS" if not _fails else "FAIL (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
