# -*- coding: utf-8 -*-
"""Reference-class forecast (cells/copilot/planning/duration_forecast).

Pinned on a SANDBOX db (db.DBPATH first - the live db is never touched):
 1. agent/hands runs: since..updated of completed runs only, window respected
 2. cards: pure agent time = start marker -> turn; the wait between a turn end
    and the owner's answer is NOT counted; classes split by machine/direct/fast
 3. below MIN_N the line says "zu wenig Daten" instead of a percentile
Run: py -3.12 ops/tests/test_duration_forecast.py
"""
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from spine.storage import db
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-durfc-"), "helmdeck.db")
db.init()
from cells.copilot.planning import duration_forecast as df

NOW = 1_800_000_000.0


def utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def run(rid, kind, secs, ago=3600, status="completed"):
    u = NOW - ago
    db.chat_run_put(rid, "owner", {"kind": kind, "status": status, "since": u - secs, "updated": u})


def ev(c, track, kind, t, **data):
    data["at_utc"] = utc(t)
    c.execute("INSERT INTO events(ts,kind,track,data) VALUES(?,?,?,?)",
              (utc(t), kind, track, json.dumps(data)))


def card(c, tid, t0, turn1, answer_gap, turn2, **flags):
    c.execute("INSERT INTO tracks(id,data) VALUES(?,?)", (tid, json.dumps(dict(flags, id=tid))))
    ev(c, tid, "lane", t0, frm="backlog", to="working")
    ev(c, tid, "turn", t0 + turn1)
    ev(c, tid, "answer", t0 + turn1 + answer_gap, actor="owner")
    ev(c, tid, "turn", t0 + turn1 + answer_gap + turn2)


with db.conn() as c:
    for i in range(6):
        run("agent-%d" % i, "agent", 60 * (i + 1))           # 1..6 min
    run("agent-old", "agent", 99999, ago=40 * 86400)         # outside the window
    run("agent-fail", "agent", 99999, status="failed")       # not completed
    run("hands-0", "hands", 100)                             # n=1 -> too few
    for i in range(5):
        card(c, "m%d" % i, NOW - 7200, 300, 7200, 120, machine=True)   # 7 min agent, 2h wait
    c.execute("INSERT INTO tracks(id,data) VALUES('ex',?)", (json.dumps({"example": True, "machine": True}),))
    ev(c, "ex", "lane", NOW - 7000, frm="backlog", to="working")
    ev(c, "ex", "turn", NOW - 100)

st = df.stats(db.conn(), NOW)
assert st["agent"]["n"] == 6 and st["agent"]["p50"] == 240, st["agent"]   # nearest rank of 60..360
assert st["agent"]["p80"] == 300, st["agent"]
assert st["hands"] == {"n": 1, "p50": None, "p80": None}, st["hands"]
assert st["machine"]["n"] == 5 and st["machine"]["p50"] == 420, st["machine"]   # wait excluded
assert st["direct"]["n"] == 0 and st["file_card"]["n"] == 0
line = df.duration_line(db.conn(), NOW)
assert "agent P50 4.0 / P80 5.0 min (n=6)" in line, line
assert "hands zu wenig Daten (n=1)" in line and "machine_task P50 7.0" in line, line
print("OK", line)
