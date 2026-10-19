"""Board events say WHAT moved (2026-10-19, "warum soviele ... vs paseo").

The board version alone made every client refetch every query per tick. Each
writer now names a topic, db.topics_since(v) answers "what moved after v", and
the socket event / long-poll carry it as `t`. Runs the real writers against a
sandbox db."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import db  # noqa: E402

db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-topics-"), "helmdeck.db")
db.init()
from spine.storage import events  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


v0 = db.current_version()
check(db.topics_since(v0) == [], "nothing moved: no topics")

db.track_put({"id": "20261019-220000-direct", "task": "x", "lane": "working"})
check(db.topics_since(v0) == ["tracks"], "a card write is 'tracks' (%s)" % db.topics_since(v0))

v1 = db.current_version()
events.save_settings({"push": {"fcm_token": "a"}}, actor="t")
got = db.topics_since(v1)
check("workspace_config" in got and "tracks" not in got,
      "a settings write is 'workspace_config', not the cards (%s)" % got)
check(set(db.topics_since(v0)) >= {"tracks", "workspace_config"}, "since v0: the union")

v2 = db.current_version()
db.bump()
check(db.topics_since(v2) == [db.TOPIC_ALL], "an unnamed bump means refetch all")

check(db.topics_since(db.current_version() + 50) == [db.TOPIC_ALL],
      "a version from before a restart: refetch all, never []")

v3 = db.current_version()
for i in range(db.TOPIC_RING + 5):
    db.bump(topic="pm")
check(db.topics_since(v3) == [db.TOPIC_ALL], "fell off the ring: refetch all, never a partial answer")
check(db.topics_since(db.current_version() - 3) == ["pm"], "inside the ring: exact")

events.log("relay", "frame waited 9.0s in the relay queue before the bridge pulled it")
check(db.topics_since(db.current_version()) == [], "relay telemetry moves nothing (a8a368d6)")

print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
