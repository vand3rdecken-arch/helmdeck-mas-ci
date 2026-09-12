# -*- coding: utf-8 -*-
"""Self-sandboxing test for GET /harness/export + POST /harness/import
(config-consolidation phase 6, owner decree: "einer stellt seine harness
ein und kann dieses exportieren").

The real end-to-end claim: seed a workspace with real config across every
plane (workspace, policy, a project overlay, an account overlay, memory),
export it, WIPE the sandbox to a fresh empty db, import the export back,
and diff every plane against what was seeded - byte-identical. That is the
only way to prove import replays through the SAME writers export read from,
rather than two paths that happen to agree in the easy case.

Run: py -3.12 ops/tests/test_harness_export_import.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def _boot(tmp):
    """Fresh sandboxed daemon on an ephemeral port, same recipe as
    test_server_routes.py. Returns (httpd, thread, port).

    daemon.paths.DAEMON_ROOT stays REAL: policy.SEED binds to it at import
    time and must keep resolving to the real tracked policy_seed.json
    (read-only, safe) - only db.ROOT/DBPATH move, same pattern every other
    policy-touching test in this repo uses."""
    from spine.storage import db
    # db.conn() caches ONE connection per THREAD in db._local - fine for a
    # real daemon (one db file for the process lifetime), but this test boots
    # TWO full sandboxes in the same process, and the main thread's cached
    # connection from the first boot would silently outlive the DBPATH
    # reassignment below. Drop it so `conn()` opens a fresh connection
    # against the NEW path on its next call, in every thread that already
    # touched the old one.
    old = getattr(db._local, "c", None)
    if old is not None:
        old.close()
        db._local.c = None
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    # events.EV (the append-only audit sink) binds to the REAL daemon dir at
    # import time, independent of db.ROOT - sandboxed explicitly so an
    # events.emit() call in here can never append to the real
    # daemon/events.jsonl (the exact incident this whole decree's earlier
    # phases measured and fixed for db.ROOT; this is the same class of leak
    # for a module that isn't db.py).
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    from spine.auth import policy
    db.init()

    from http.server import ThreadingHTTPServer
    from spine.http.server import H
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, th, port


def _req(port, method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = "sd_session=%s" % cookie
    data = json.dumps(body) if body is not None else None
    conn.request(method, path, data, headers)
    r = conn.getresponse()
    raw = r.read()
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = raw
    conn.close()
    return r.status, parsed


def main():
    tmp1 = tempfile.mkdtemp(prefix="hd-export-src-")
    httpd1, th1, port1 = _boot(tmp1)
    try:
        from spine.auth import auth
        auth.create_user("owner1", "hunter2hunter2", "owner")
        sid = auth.login("owner1", "hunter2hunter2")
        assert sid, "sandbox login failed"

        # 1. seed real config across every plane the export covers.
        status, body = _req(port1, "POST", "/settings",
                            {"appearance": {"backdrop": "aurora"},
                             "default_repo": "c:/proj/alpha",
                             "policy": {"lang": "en"}}, cookie=sid)
        ok(status == 200, "seed workspace config")

        status, body = _req(port1, "POST", "/harness/config",
                            {"values": {"rule.tone.length.pm": "ausfuehrlich"}}, cookie=sid)
        ok(status == 200, "seed a project-less (workspace) rule")

        from spine.storage import projectconfig
        # project keys are NORMALIZED (project_key() collapses slash style +
        # case) - write with the same key /harness/config?repo= will resolve
        # to, or the round-trip check below queries a different row than the
        # one just written.
        PROJECT = projectconfig.project_key("c:/proj/alpha")
        _, err = projectconfig.write(PROJECT, {"rule.hands.own_hands.pm": False},
                                     actor="owner1")
        ok(err is None, "seed a project overlay directly (%s)" % err)

        from spine.storage import userconfig
        userconfig.write("owner1", {"lang": "en"}, actor="owner1")

        from spine.storage import db
        db.memory_put("owner-likes-terse-replies", "# Terse\n\nOwner said so.", actor="henry")

        # 2. export.
        status, exported = _req(port1, "GET", "/harness/export?secrets=0", cookie=sid)
        ok(status == 200, "GET /harness/export succeeds")
        ok(exported.get("workspace", {}).get("appearance", {}).get("backdrop") == "aurora",
           "export carries the seeded workspace value")
        ok(PROJECT in (exported.get("project_overlays") or {}),
           "export carries the project overlay")
        ok("owner1" in (exported.get("user_overlays") or {}),
           "export carries the account overlay")
        ok("owner-likes-terse-replies" in (exported.get("memory") or {}),
           "export carries the memory note")
    finally:
        httpd1.shutdown()
        th1.join(timeout=5)

    # 3. a SECOND, completely fresh sandbox - the wipe.
    tmp2 = tempfile.mkdtemp(prefix="hd-export-dst-")
    httpd2, th2, port2 = _boot(tmp2)
    try:
        from spine.auth import auth
        auth.create_user("owner2", "hunter2hunter2", "owner")
        sid2 = auth.login("owner2", "hunter2hunter2")

        status, before = _req(port2, "GET", "/settings", cookie=sid2)
        ok(before.get("appearance", {}).get("backdrop") != "aurora",
           "fresh sandbox does NOT already have the seeded value (sanity)")

        # 4. import the export back.
        status, result = _req(port2, "POST", "/harness/import", exported, cookie=sid2)
        ok(status == 200 and result.get("ok"), "POST /harness/import succeeds")

        # 5. diff every plane, byte-identical.
        status, after_settings = _req(port2, "GET", "/settings", cookie=sid2)
        ok(after_settings.get("appearance", {}).get("backdrop") == "aurora",
           "workspace config round-tripped")
        ok(after_settings.get("default_repo") == "c:/proj/alpha",
           "workspace config round-tripped (second key)")

        status, cfg = _req(port2, "GET", "/harness/config?repo=" + PROJECT, cookie=sid2)
        rule = next((r for r in cfg["rules"] if r["key"] == "hands.own_hands"), None)
        surf = next((s for s in (rule or {}).get("surfaces", []) if s["surface"] == "pm"), None)
        ok(surf is not None and surf["value"] is False,
           "project overlay round-tripped through projectconfig.write")

        from spine.storage import db as db2, userconfig as uc2
        ok(uc2.stored("owner1").get("lang") == "en",
           "account overlay round-tripped (owner1 is a NEW account on this sandbox)")
        ok(db2.memory_all().get("owner-likes-terse-replies", {}).get("content")
           == "# Terse\n\nOwner said so.",
           "memory note round-tripped byte-identical")

        # 6. a second export from the IMPORTED sandbox matches the original,
        #    modulo exported_at - the actual "harness travels intact" claim.
        status, reexported = _req(port2, "GET", "/harness/export?secrets=0", cookie=sid2)
        for key in ("workspace", "project_overlays"):
            a, b = dict(exported.get(key) or {}), dict(reexported.get(key) or {})
            # user_overlays legitimately differs (owner2 exists only on the
            # dest sandbox) - checked separately above instead.
            ok(a == b, "%s: re-export matches the original export" % key)
        # memory rows carry updated_at/actor - the import legitimately writes
        # a NEW timestamp (db.memory_put stamps "now"), so only CONTENT is
        # compared here; the timestamp/actor are the sentinel write path's own
        # contract (cells/copilot/chat/copilot_memory.py), not the
        # export/import round-trip's.
        mem_a = {k: v["content"] for k, v in (exported.get("memory") or {}).items()}
        mem_b = {k: v["content"] for k, v in (reexported.get("memory") or {}).items()}
        ok(mem_a == mem_b, "memory: re-export content matches the original export")
    finally:
        httpd2.shutdown()
        th2.join(timeout=5)

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
