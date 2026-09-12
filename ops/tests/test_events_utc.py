# -*- coding: utf-8 -*-
"""Self-sandboxing test for the universal `at_utc` field (phase D2).

Before this, events.emit() stamped only `ts` in host-local time - ambiguous
across machines and twice a year at the DST fold. A real UTC anchor existed
only on auth events (auth._audit) and signature events (routes_sign.py),
added by hand at each call site, so any OTHER event kind (gate, merge, done,
lane, gxp, reconfig, ...) had none at all.

`ts` itself is deliberately left alone: the dashboard, day-boundary rollups
and quota-window math already read it as host-local, and reinterpreting it as
UTC in place would silently shift every "today"/"this week" boundary computed
from it - a correctness change disguised as a timestamp fix.

What this pins down:
  1. every emit(), of any kind, gets an at_utc that parses and ends in Z
  2. `ts` is UNCHANGED - still host-local, same format as before
  3. a caller that already computed its own at_utc (routes_sign.py passing a
     signature's exact signed_at) still wins - the universal default does not
     clobber a more precise value
  4. auth._audit's own at_utc still shows up (now supplied by emit() itself,
     the hand-written computation was removed as redundant) and is a real UTC
     timestamp, not a coincidence of two independent clocks agreeing

Run: py -3.12 ops/tests/test_events_utc.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-eventsutc-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    db.init()

    def rows():
        return events.read_events()          # the table is the record (phase H)

    # ------------------------------------------------------------------ 1 ---
    print("\nevery kind gets a real at_utc")
    for kind in ("gate", "merge", "done", "lane", "gxp", "reconfig", "touch"):
        events.emit(kind, "t-1", ok=True)
    for r in rows():
        au = r.get("at_utc", "")
        ok(au.endswith("Z"), "%s: at_utc ends in Z (got %r)" % (r["kind"], au))
        try:
            time.strptime(au, "%Y-%m-%dT%H:%M:%SZ")
            parsed = True
        except ValueError:
            parsed = False
        ok(parsed, "%s: at_utc actually parses as that format" % r["kind"])

    # ------------------------------------------------------------------ 2 ---
    print("\nts is untouched - still host-local, same format")
    r = rows()[0]
    ok("ts" in r, "ts still present")
    try:
        time.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        ts_ok = True
    except ValueError:
        ts_ok = False
    ok(ts_ok, "ts still in the original host-local format (no 'T', no 'Z')")
    ok("Z" not in r["ts"] and "T" not in r["ts"], "ts was not reinterpreted as UTC")

    # ------------------------------------------------------------------ 3 ---
    print("\na caller-supplied at_utc wins over the default")
    fixed = "2020-01-01T00:00:00Z"
    events.emit("signature", "t-2", op="signed", at_utc=fixed)
    row = [r for r in rows() if r.get("track") == "t-2"][-1]
    ok(row["at_utc"] == fixed, "explicit at_utc was NOT overwritten by the default")

    # ------------------------------------------------------------------ 4 ---
    print("\nauth._audit's at_utc now comes from emit() itself, and is real")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    before = time.gmtime()
    auth.create_user("duy", "a-real-password", "owner")
    auth_row = [r for r in rows() if r.get("kind") == "auth"][-1]
    ok(auth_row["kind"] == "auth" and auth_row["op"] == "user.create",
       "the auth event itself still fires")
    ok(auth_row.get("at_utc", "").endswith("Z"), "and carries at_utc")
    ok(auth_row["at_utc"] >= time.strftime("%Y-%m-%dT%H:%M:%SZ", before),
       "at_utc is a REAL current timestamp, not a leftover/blank value")

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for m in _fails:
            print("  - " + m)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
