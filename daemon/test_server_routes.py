# -*- coding: utf-8 -*-
"""Route-level smoke test for server.py's H handler (Route 1: prerequisite for
splitting the do_GET/do_POST dispatch into modules — this pins the OBSERVABLE
behavior of a representative route slice so a future refactor can be verified
against real HTTP responses, not just import-time compile checks).

Self-sandboxing: db/auth/events are ALL redirected to a temp dir BEFORE any of
them touch disk, so this never reads or writes the real helmdeck.db/users.json/
settings.json/events.jsonl/processes.json. The server binds to 127.0.0.1:0
(OS-assigned ephemeral port) in a background thread — it never touches :8140,
so it cannot collide with (or evict) a live daemon. `serve()` itself is NEVER
called (it takes the singleton port lock and would evict a running daemon).

TRAPS MEASURED THE HARD WAY (both real, both recovered, both now guarded
here): (1) db.ROOT - db.init() reads/migrates ROOT/tracks.json and ROOT/
events.jsonl (renaming them to *.imported); patching only db.DBPATH still let
init() touch the REAL daemon/events.jsonl. (2) events.EV - events.emit() (the
append-only audit sink) writes through events.py's OWN independent ROOT/EV
globals, never covered by db.ROOT or events.SET; any route that calls
events.emit() (most of them do, for the audit trail) appended real lines to
the production events.jsonl even with db fully sandboxed. Both are now patched
below BEFORE any module touches disk. If a THIRD module turns up with its own
hardcoded ROOT-based path (grep for `os.path.join(ROOT,` in any module a new
route imports), sandbox it here too before running - this class of bug will
keep recurring until every module's storage goes through db.py.

Run: py -3.12 test_server_routes.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-route-test-")

    # Stub the ACTUAL agent spawn before anything imports sessions/drivers -
    # the tracks-cluster tests below dispatch/steer real cards through the
    # real sessions.py/lanemachine.py/turnrunner.py state machine (Route 14:
    # the gate/dispatch "crown jewel"), but must never shell out to a real
    # `claude` CLI process. drivers.run is the ONE seam turnrunner._turn
    # calls through (see turnrunner.py:133) - stubbing it here, before
    # `import server` below pulls in sessions (which imports drivers),
    # keeps every dispatched/steered turn instant, deterministic, and
    # network-free while still exercising the real state transitions
    # around it (worktree creation, lane writes, gate, merge).
    import drivers
    def _fake_driver_run(cfg, t, prompt):
        return ("sid-" + t["id"], "ok", {})
    drivers.run = _fake_driver_run

    # sandbox EVERYTHING with disk state, before any of it is touched. db.ROOT
    # is the critical one: db.init() reads/MIGRATES ROOT/tracks.json and
    # ROOT/events.jsonl (renaming them to *.imported) using that same global -
    # patching only DBPATH still lets init() touch the REAL daemon/events.jsonl
    # (measured the hard way: a first draft of this test renamed the live
    # events.jsonl to .imported before this guard existed - recovered by
    # renaming it back, no data lost, but never again: ROOT must be sandboxed).
    import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    import events
    events.SET = os.path.join(tmp, "settings.json")
    events.EV = os.path.join(tmp, "events.jsonl")   # the append-only audit sink

    # connectors.py and checkpoints.py each compute their own directory
    # globals from __file__ (independent of db.ROOT - see
    # test_checkpoints_db_migration.py) - sandbox both before any route
    # touches them, so a connector list/rollback/run or checkpoint list/
    # diff/restore route never reads or writes the real daemon/connectors/
    # or daemon/checkpoints/ directories.
    import connectors
    connectors.CDIR = os.path.join(tmp, "connectors")
    os.makedirs(connectors.CDIR, exist_ok=True)
    connectors.VDIR = os.path.join(connectors.CDIR, "_versions")
    os.makedirs(connectors.VDIR, exist_ok=True)
    import checkpoints
    checkpoints.ROOT = tmp
    checkpoints.CPDIR = os.path.join(tmp, "checkpoints")
    os.makedirs(checkpoints.CPDIR, exist_ok=True)

    # runs.REC (a card's run_dir root - screenshots/live.jpg/actionlog) is a
    # THIRD independent __file__-derived global, same class of bug as
    # connectors/checkpoints above - and unlike those two, nothing caught it
    # before this test started filing real tracks: dispatch.py, cardadmin.py
    # and sessions.py each did `from runs import REC` at import time, so they
    # hold their OWN bound copy of the real daemon/recordings path - patching
    # runs.REC alone does not reach them. MEASURED THE HARD WAY while writing
    # the tracks-cluster tests below: a first draft (no REC patch) filed real
    # cards straight into the live daemon/recordings/ folder (git-ignored, so
    # no tracked data was harmed, but a real-file violation of this test's own
    # sandboxing rule) before this guard existed. Every module holding its own
    # REC copy must be patched here, before any card is filed.
    import runs, dispatch as _dispatch_mod, cardadmin as _cardadmin_mod
    REC = os.path.join(tmp, "recordings")
    os.makedirs(REC, exist_ok=True)
    runs.REC = REC
    _dispatch_mod.REC = REC
    _cardadmin_mod.REC = REC
    import sessions as _sessions_mod
    _sessions_mod.REC = REC

    db.init(role="tool")   # NOT role="daemon" - this process owns no driver sessions

    # a real owner user + session, so authenticated routes are exercised too
    auth.create_user("routetest-owner", "s4ndb0x-pw", "owner")
    sid = auth.login("routetest-owner", "s4ndb0x-pw")
    ok(bool(sid), "sandbox owner created + logged in")

    import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        def req(method, path, body=None, cookie=None, expect=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            headers = {"Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = "sd_session=%s" % cookie
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            data = r.read()
            conn.close()
            try:
                parsed = json.loads(data) if data else None
            except ValueError:
                parsed = None
            if expect is not None:
                ok(r.status == expect, "%s %s -> %d (want %d)" % (method, path, r.status, expect))
            return r.status, parsed

        # -- public route: no auth needed, no cookie -------------------------
        status, body = req("GET", "/auth/state", expect=200)
        ok(isinstance(body, dict) and "setup_needed" in body, "/auth/state shape: setup_needed present")
        ok(body.get("user") is None, "/auth/state: anonymous request has no user")

        # -- unauthenticated request to an owner-only route is refused -------
        req("GET", "/policy", expect=403)

        # -- authenticated routes, real session cookie ------------------------
        status, body = req("GET", "/me", cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("name") == "routetest-owner",
           "/me returns the logged-in owner")

        status, body = req("GET", "/tracks", cookie=sid, expect=200)
        ok(isinstance(body, list) and body == [], "/tracks: empty list on a fresh sandboxed DB")

        status, body = req("GET", "/dashboard/data", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "capacity" in body, "/dashboard/data shape: capacity present")

        # -- settings/automation group (routes_settings.py) --------------------
        status, body = req("GET", "/settings", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/settings shape: a dict (the raw settings blob)")

        status, body = req("GET", "/nightshift", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/nightshift shape: a dict (pm.status() alias)")

        status, body = req("GET", "/usage", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/usage shape: a dict (usage.snapshot())")

        status, body = req("GET", "/automation", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "config_schema" in body and "loop_states" in body,
           "/automation shape: config_schema+loop_states present")

        status, body = req("POST", "/settings", {"value_per_card": 123}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/settings POST accepted a patch, returned the saved settings")
        status, body = req("GET", "/settings", cookie=sid, expect=200)
        ok(body.get("value_per_card") == 123, "/settings POST actually persisted the patch")

        # -- glasses group (routes_glance.py) - token-gated, no session needed ---
        status, body = req("GET", "/glance", expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance with no token configured: refused")

        status, body = req("GET", "/glance/voice/doesnotexist.mp3", expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance/voice with no token configured: refused")

        status, body = req("POST", "/glance/talk", {"message": "hi"}, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance/talk with no token configured: refused")

        status, body = req("POST", "/glance/answer", {"id": "x"}, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance/answer with no token configured: refused")

        # set a real glance_token, then exercise the token-checked (not the
        # feature-flag-checked) half of each route - proves the dispatch-table
        # move preserved the token comparison exactly.
        req("POST", "/settings", {"glance_token": "test-tok-123"}, cookie=sid, expect=200)
        status, body = req("GET", "/glance?token=wrong", expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance with wrong token: refused")
        status, body = req("GET", "/glance?token=test-tok-123", expect=200)
        ok(isinstance(body, dict) and "needs_you" in body and "econ" in body,
           "/glance with correct token: real glance_payload shape (needs_you+econ)")
        status, body = req("POST", "/glance/talk", {"token": "test-tok-123", "message": "hi"}, expect=403)
        ok(body.get("error", "").startswith("talking to the board agent"),
           "/glance/talk with correct token but glance_talk unset: feature-flag refusal (not a token error)")
        status, body = req("POST", "/glance/answer", {"token": "test-tok-123", "id": "x"}, expect=403)
        ok(body.get("error", "").startswith("deciding from the glasses"),
           "/glance/answer with correct token but glance_decide unset: feature-flag refusal")

        # rejected relay url (plain http, not localhost) - real validation path
        status, body = req("POST", "/settings", {"relay": {"url": "http://evil.example.com"}},
                           cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/settings POST rejects an insecure relay url")

        # -- info/introspection group (routes_info.py) --------------------------
        status, body = req("GET", "/debt", cookie=sid, expect=200)
        ok(isinstance(body, list), "/debt shape: a list (debt.list_debt())")

        status, body = req("GET", "/charter", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "core" in body, "/charter shape: core present")

        status, body = req("GET", "/loop/map", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "laws" in body and "charter" in body and body.get("harness"),
           "/loop/map (routes_info version) shape: laws+charter+harness present")

        status, body = req("GET", "/models", cookie=sid, expect=200)
        ok(isinstance(body, list), "/models shape: a list (turnopts.list_models())")

        status, body = req("GET", "/harness", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/harness shape: a dict (harness.document())")

        status, body = req("GET", "/harness/schema", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "agent" in body and "settings" in body,
           "/harness/schema shape: agent+settings schemas present")

        status, body = req("GET", "/loop/map", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "runtime" in body and "build" in body,
           "/loop/map shape: runtime+build present (apimeta._lane_flow + _loop_machine)")

        # -- pm group (routes_pm.py) ---------------------------------------------
        status, body = req("GET", "/pm/economics", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "goal" in body and "economics" in body,
           "/pm/economics shape: goal+economics present")

        status, body = req("GET", "/pm/plan", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "plan" in body and "activity" in body,
           "/pm/plan shape: plan+activity present")

        # /pm/config is pure (settings write, no LLM) - exercise the real
        # round-trip, same as /settings above.
        status, body = req("POST", "/pm/config", {"loop_enabled": False, "idle_minutes": 42},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict), "/pm/config POST accepted, returned pm._pm()")
        status, body = req("GET", "/pm/plan", cookie=sid, expect=200)
        ok((body.get("config") or {}).get("idle_minutes") == 42,
           "/pm/config POST actually persisted (idle_minutes round-trips via /pm/plan)")

        # /pm/consolidate, /pm/report, /pm/reconcile all run a MODEL TURN in
        # their happy path - never invoke that in a sandboxed test (cost,
        # network, non-determinism). Verify the OWNER-ONLY / role gate instead,
        # via a second client-role user, proving the guard survived the move
        # without ever reaching pm.brief()/pm.consolidation_proposal().
        auth.create_user("routetest-client", "s4ndb0x-pw2", "client")
        csid = auth.login("routetest-client", "s4ndb0x-pw2")
        status, body = req("POST", "/pm/consolidate", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/pm/consolidate refuses a client (owner only)")
        status, body = req("POST", "/pm/report", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/pm/report refuses a client (owner/operator only)")
        status, body = req("POST", "/pm/reconcile", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/pm/reconcile refuses a client (owner/operator only)")

        # -- misc group (routes_misc.py) -----------------------------------------
        status, body = req("GET", "/processes", cookie=sid, expect=200)
        ok(isinstance(body, list), "/processes shape: a list (fresh sandboxed DB, syncs first)")

        status, body = req("POST", "/processes/new", {"request": "a smoke-test process"},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("id"), "/processes/new POST creates a real process")
        status, body = req("GET", "/processes", cookie=sid, expect=200)
        ok(len(body) == 1, "/processes/new POST actually persisted (visible on the next GET)")

        status, body = req("POST", "/processes/new", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/processes/new POST rejects a missing 'request'")

        status, body = req("GET", "/policy", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "policies" in body, "/policy shape: policies present (owner authorized)")

        # -- a POST route: filing a real card through the live HTTP path -----
        status, body = req("POST", "/tracks/new",
                           {"repo": tmp, "task": "route-smoke-test card", "lane": "backlog"},
                           cookie=sid)
        # tmp is not a git repo, so this should be REJECTED, not silently accepted
        # (test_dispatch_visibility.py pins the same "no silent backlog fallback" law)
        ok(status in (400, 200), "/tracks/new against a non-repo path returns a real status: %d" % status)
        if status == 200:
            ok(isinstance(body, dict) and body.get("error"), "/tracks/new non-repo: error surfaced in the 200 body")

        # -- copilot/chat group (routes_copilot.py) - never invoke the real -----
        # model turn (cost, network, non-determinism); verify role gates and
        # the pure history/live/cancel reads instead.
        status, body = req("GET", "/chat/history", cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/chat/history refuses a client")
        status, body = req("GET", "/chat/history", cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("messages") == [],
           "/chat/history shape: messages present, empty on a fresh sandboxed DB")

        status, body = req("GET", "/chat/live", cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/chat/live refuses a client")
        status, body = req("GET", "/chat/live", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/chat/live shape: a dict")

        status, body = req("POST", "/chat/cancel", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/chat/cancel refuses a client")
        status, body = req("POST", "/chat/cancel", {}, cookie=sid, expect=200)
        ok(isinstance(body, dict) and "cancelled" in body, "/chat/cancel: owner allowed, nothing running")

        status, body = req("POST", "/chat", {"text": "hi"}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/chat refuses a client")
        status, body = req("POST", "/chat", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/chat POST rejects missing text (never reaches copilot.chat)")

        # -- projects group (routes_projects.py) ---------------------------------
        status, body = req("GET", "/projects", cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/projects GET refuses a client")
        status, body = req("GET", "/projects", cookie=sid, expect=200)
        ok(body == [], "/projects: empty list, sandboxed DB has no projects yet")

        status, body = req("POST", "/projects", {"name": "Acme", "billing": "fixed", "fixed_price": 5000},
                           cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/projects POST refuses a non-owner")
        status, body = req("POST", "/projects", {"name": "Acme", "billing": "fixed", "fixed_price": 5000},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("id"), "/projects POST creates a real project")
        pid = body["id"]
        status, body = req("GET", "/projects", cookie=sid, expect=200)
        ok(len(body) == 1 and body[0]["id"] == pid, "/projects POST actually persisted")

        status, body = req("POST", "/projects/%s/update" % pid, {"name": "Acme Corp"},
                           cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/projects/.../update refuses a non-owner")
        status, body = req("POST", "/projects/%s/update" % pid, {"name": "Acme Corp"},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("name") == "Acme Corp", "/projects/.../update persisted")

        status, body = req("POST", "/projects/doesnotexist/update", {"name": "x"},
                           cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/projects/.../update: unknown id -> 400")

        status, body = req("POST", "/projects/%s/delete" % pid, {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/projects/.../delete refuses a non-owner")
        status, body = req("POST", "/projects/%s/delete" % pid, {}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/projects/.../delete: owner allowed")
        status, body = req("GET", "/projects", cookie=sid, expect=200)
        ok(body == [], "/projects/.../delete actually removed it")

        # -- connectors group (routes_connectors.py) -----------------------------
        status, body = req("GET", "/connectors", cookie=sid, expect=200)
        ok(body == [], "/connectors: empty list, sandboxed CDIR has no connector files")

        status, body = req("POST", "/connectors/doesnotexist/rollback", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/connectors/.../rollback refuses a client")
        status, body = req("POST", "/connectors/doesnotexist/rollback", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/connectors/.../rollback: no such connector -> 400")

        status, body = req("POST", "/connectors/doesnotexist/run", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/connectors/.../run refuses a client")
        status, body = req("POST", "/connectors/doesnotexist/run", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/connectors/.../run: no such connector -> 400")

        # -- checkpoints group (routes_checkpoints.py) ---------------------------
        status, body = req("GET", "/checkpoints", cookie=sid, expect=200)
        ok(body == [], "/checkpoints: empty list, sandboxed CPDIR has no checkpoints yet")

        status, body = req("GET", "/checkpoints/doesnotexist/diff", cookie=sid, expect=404)
        ok(isinstance(body, dict) and body.get("error"), "/checkpoints/.../diff: no such checkpoint -> 404")

        status, body = req("POST", "/checkpoints/doesnotexist/restore", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/checkpoints/.../restore refuses a non-owner")
        status, body = req("POST", "/checkpoints/doesnotexist/restore", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/checkpoints/.../restore: no such checkpoint -> 400")

        # a real checkpoint round-trip, straight through the sandboxed CPDIR
        import checkpoints as _cp
        real_cid = _cp.create(actor="routetest", reason="smoke")
        status, body = req("GET", "/checkpoints", cookie=sid, expect=200)
        ok(len(body) == 1 and body[0]["id"] == real_cid, "/checkpoints lists the real sandboxed checkpoint")
        status, body = req("GET", "/checkpoints/%s/diff" % real_cid, cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("id") == real_cid, "/checkpoints/.../diff on a real id: 200")
        status, body = req("POST", "/checkpoints/%s/restore" % real_cid, {}, cookie=sid, expect=200)
        ok(body.get("restored") == real_cid, "/checkpoints/.../restore on a real id: 200, restores it")

        # -- control/teach group (routes_control.py) ----------------------------
        status, body = req("GET", "/control/state", cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("teach") is None and body.get("busy") == [],
           "/control/state shape: idle (no teach session, nothing busy)")

        status, body = req("POST", "/control/teach/stop", {}, cookie=sid, expect=404)
        ok(isinstance(body, dict) and body.get("error"), "/control/teach/stop with nothing recording: 404")

        status, body = req("POST", "/control/distill", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/control/distill with no id: rejected")

        # -- relay group (routes_relay.py) - owner-only guard, no real pairing ---
        status, body = req("POST", "/relay/pair", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/relay/pair refuses a client (owner only)")
        status, body = req("POST", "/relay/unpair", {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/relay/unpair refuses a client (owner only)")
        # owner + no relay configured -> relay_client.unpair() is a harmless no-op
        status, body = req("POST", "/relay/unpair", {}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/relay/unpair (owner, nothing paired) returns a dict")

        # -- tracks cluster (routes_tracks.py + routes_track_actions.py) -------
        # the CROWN JEWEL group: real HTTP round trips through sessions.py's
        # data layer and lanemachine.py's gate/merge state machine, not just
        # role-gate assertions. Uses a REAL git repo (in the sandboxed tmp
        # dir) so /tracks/new, gate-pass, and gate-blocked are all exercised
        # against real git state - never a live agent turn (lane="backlog"
        # + direct worktree construction below, so no claude driver spawns).
        import subprocess as _sp
        repo_dir = os.path.join(tmp, "gate-repo")
        os.makedirs(repo_dir, exist_ok=True)
        def git(*args):
            r = _sp.run(["git", "-C", repo_dir] + list(args), capture_output=True,
                        text=True, timeout=20)
            ok(r.returncode == 0, "git %s: %s" % (" ".join(args), r.stderr[:200]))
        git("init")
        git("config", "user.email", "routetest@example.com")
        git("config", "user.name", "routetest")
        with open(os.path.join(repo_dir, "README.md"), "w") as f:
            f.write("gate smoke\n")
        git("add", "README.md")
        git("commit", "-m", "initial")

        # -- /tracks: empty list still holds after the earlier non-repo probe ---
        status, body = req("GET", "/tracks", cookie=sid, expect=200)
        base_count = len(body)

        # -- /tracks/new: real repo, backlog lane (instant, no agent turn) ------
        status, body = req("POST", "/tracks/new",
                           {"repo": repo_dir, "task": "gate smoke card", "lane": "backlog"},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("id"), "/tracks/new (real repo, backlog): creates a real card")
        tid = body["id"]
        branch = body["branch"]

        status, body = req("GET", "/tracks", cookie=sid, expect=200)
        ok(len(body) == base_count + 1 and any(t["id"] == tid for t in body),
           "/tracks: the new backlog card is now listed")

        status, body = req("POST", "/tracks/new", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/new: missing task/repo -> 400")

        # -- /tracks/<id>/update, /archive, /attach round trips ------------------
        status, body = req("POST", "/tracks/%s/update" % tid, {"priority": "high"},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("priority") == "high",
           "/tracks/<id>/update: real field change persisted")

        status, body = req("POST", "/tracks/%s/archive" % tid, {"on": True}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/archive refuses a client")
        status, body = req("POST", "/tracks/%s/archive" % tid, {"on": True}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/tracks/<id>/archive: owner allowed")
        req("POST", "/tracks/%s/archive" % tid, {"on": False}, cookie=sid, expect=200)  # unarchive for the rest

        import base64 as _b64
        att_b64 = _b64.b64encode(b"attachment smoke").decode()
        status, body = req("POST", "/tracks/%s/attach" % tid,
                           {"attachments": [{"name": "note.txt", "data": att_b64}]},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict), "/tracks/<id>/attach: accepted")
        status, body = req("GET", "/tracks/%s/attachments" % tid, cookie=sid, expect=200)
        ok(isinstance(body, list) and any(a["name"] == "0_note.txt" for a in body),
           "/tracks/<id>/attachments: real file listed")
        status, body = req("GET", "/tracks/%s/attachment/0_note.txt" % tid, cookie=sid, expect=200)
        ok(body is None or True, "/tracks/<id>/attachment/<name>: 200 (binary body, not JSON-parsed here)")
        status, body = req("POST", "/tracks/%s/attach/remove" % tid, {"name": "0_note.txt"},
                           cookie=sid, expect=200)
        ok(isinstance(body, dict), "/tracks/<id>/attach/remove: accepted")
        status, body = req("GET", "/tracks/%s/attachments" % tid, cookie=sid, expect=200)
        ok(body == [], "/tracks/<id>/attach/remove: actually removed it")

        # -- /tracks/<id>/turns, /history, /transcript, /checkpoints: real reads
        status, body = req("GET", "/tracks/%s/turns" % tid, cookie=sid, expect=200)
        ok(isinstance(body, list), "/tracks/<id>/turns shape: a list")
        status, body = req("GET", "/tracks/%s/history" % tid, cookie=sid, expect=200)
        ok(isinstance(body, list), "/tracks/<id>/history shape: a list (a backlog card has no branch commits yet)")
        status, body = req("GET", "/tracks/%s/transcript" % tid, cookie=sid, expect=200)
        ok(isinstance(body, list), "/tracks/<id>/transcript shape: a list (no session yet)")
        status, body = req("GET", "/tracks/%s/checkpoints" % tid, cookie=sid, expect=200)
        ok(isinstance(body, list), "/tracks/<id>/checkpoints shape: a list")
        status, body = req("GET", "/tracks/%s/live" % tid, cookie=sid, expect=404)
        ok(isinstance(body, bytes) or body is None, "/tracks/<id>/live: 404, no live.jpg yet")

        # -- ownership: a client who does NOT own this card is refused ----------
        status, body = req("GET", "/tracks/%s/history" % tid, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/history refuses a non-owning client")

        # -- /tracks/<id>/cancel: no live turn to cancel, still a clean 200 -----
        status, body = req("POST", "/tracks/%s/cancel" % tid, {}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/tracks/<id>/cancel: no active turn, returns a dict")

        # -- /tracks/<id>/answer: no pending question -> 409 ---------------------
        status, body = req("POST", "/tracks/%s/answer" % tid, {"answers": {}}, cookie=sid, expect=409)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/answer: no pending question -> 409")

        # -- /tracks/<id>/steer: role gate (never actually runs a turn: missing --
        # text short-circuits before sessions.steer is reached)
        status, body = req("POST", "/tracks/%s/steer" % tid, {"text": "hi"}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/steer refuses a non-owning client")
        status, body = req("POST", "/tracks/%s/steer" % tid, {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/steer: missing text -> 400 (never reaches sessions.steer)")

        # -- GATE, BLOCKED: never dispatched -> lanemachine._gate's own "never --
        # dispatched" problem, not a fabricated one. /lane backgrounds the gate
        # (started:true) - poll the board until the card settles.
        import time as _time
        def _await_gate_settle(tid, deadline_s=15):
            """Poll /tracks until this card's status is a TERMINAL post-gate
            value. The background mutate to status='gating' is itself async
            (the HTTP response only means the thread was STARTED), so a naive
            "status != gating" poll can catch a STALE terminal status left
            over from an EARLIER /lane call before the new gate run has even
            begun mutating - a false "already settled" read (measured the
            hard way while writing this test: the second gate-passing probe
            below reuses the same card the gate-blocked probe just bounced,
            so 'bounced' is both a valid outcome AND a stale leftover).
            Require the card to visibly pass through status='gating' at
            least once before accepting a terminal status, so a stale read
            can never be mistaken for a completed run."""
            deadline = _time.time() + deadline_s
            seen_gating = False
            card = None
            while _time.time() < deadline:
                _, tracks_now = req("GET", "/tracks", cookie=sid)
                card = next((c for c in tracks_now if c["id"] == tid), None)
                st = (card or {}).get("status")
                if st == "gating":
                    seen_gating = True
                elif seen_gating and st in ("bounced", "submitted", "accepted"):
                    break
                _time.sleep(0.15)
            return card

        status, body = req("POST", "/tracks/%s/lane" % tid, {"lane": "review"}, cookie=sid, expect=200)
        ok(body.get("gating") is True, "/tracks/<id>/lane -> review: backgrounded (gating:true)")
        card = _await_gate_settle(tid)
        ok(card is not None and card.get("status") == "bounced" and card.get("lane") == "review",
           "GATE BLOCKED (never dispatched): card bounces back to Review, not silently accepted "
           "(got status=%r lane=%r)" % ((card or {}).get("status"), (card or {}).get("lane")))
        ok(card is not None and any("never dispatched" in p for p in (card.get("gate_report") or [])),
           "GATE BLOCKED: gate_report explains WHY (never dispatched), not just that it failed")

        # -- GATE, PASSING: a SEPARATE fresh backlog card (the first card is now
        # lane="review"/bounced - a ->working move on a card ALREADY on Review is
        # a human BOUNCE-BACK in lanemachine.move_lane, not a fresh dispatch, so
        # it would never create a worktree; measured hitting exactly that: the
        # first draft reused `tid` here and the worktree never appeared).
        # Dispatch this one for real (lane="working") through the SAME HTTP path
        # production uses. drivers.run is stubbed at the top of this test
        # (instant, deterministic, no real claude CLI/network), but
        # dispatch._start_inner still runs for real: _ensure_worktree creates a
        # genuine git worktree+branch and _finish_turn writes the real track
        # state - all inside the SAME background thread the daemon uses, so
        # there is no cross-thread staleness between "set up preconditions" and
        # "gate reads them".
        status, body = req("POST", "/tracks/new",
                           {"repo": repo_dir, "task": "gate pass smoke card", "lane": "backlog"},
                           cookie=sid, expect=200)
        tid2 = body["id"]

        status, body = req("POST", "/tracks/%s/lane" % tid2, {"lane": "working"}, cookie=sid, expect=200)
        ok(body.get("started") == tid2, "/tracks/<id>/lane -> working (fresh backlog card): backgrounded (started)")
        deadline = _time.time() + 15
        card2 = None
        while _time.time() < deadline:
            _, tracks_now = req("GET", "/tracks", cookie=sid)
            card2 = next((c for c in tracks_now if c["id"] == tid2), None)
            if card2 and card2.get("worktree"):
                break
            _time.sleep(0.15)
        ok(card2 is not None and card2.get("lane") == "working" and card2.get("worktree"),
           "dispatch: fresh card carries a real worktree after ->working (got lane=%r worktree=%r)"
           % ((card2 or {}).get("lane"), bool((card2 or {}).get("worktree"))))

        status, body = req("POST", "/tracks/%s/lane" % tid2, {"lane": "review"}, cookie=sid, expect=200)
        ok(body.get("gating") is True, "/tracks/<id>/lane -> review (fresh dispatched worktree): backgrounded")
        card2 = _await_gate_settle(tid2)
        ok(card2 is not None and card2.get("lane") == "review" and card2.get("status") != "bounced",
           "GATE PASSING (real clean worktree, no helmdeck.gate file): card advances past the gate "
           "instead of bouncing (got status=%r lane=%r)" % ((card2 or {}).get("status"), (card2 or {}).get("lane")))

        # -- /tracks/reorder ------------------------------------------------------
        status, body = req("POST", "/tracks/reorder", {"ids": [tid]}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/reorder refuses a client")
        status, body = req("POST", "/tracks/reorder", {"ids": [tid]}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/tracks/reorder: owner allowed")

        # -- /tracks/<id>/fork, /fork-chat, /rewind: unreachable target -> a real
        # RuntimeError from sessions.py surfaces as 400, not a crash ------------
        status, body = req("POST", "/tracks/doesnotexist/fork", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/fork: unknown id -> 400 (RuntimeError caught)")
        status, body = req("POST", "/tracks/doesnotexist/fork-chat", {}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/fork-chat: unknown id -> 400")
        status, body = req("POST", "/tracks/doesnotexist/rewind", {"commit": "HEAD"}, cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/rewind: unknown id -> 400")

        # -- /tracks/<id>/delete: owner-only guard, then a real delete -----------
        status, body = req("POST", "/tracks/%s/delete" % tid, {}, cookie=csid, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/tracks/<id>/delete refuses a non-owner")
        status, body = req("POST", "/tracks/%s/delete" % tid, {}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/tracks/<id>/delete: owner allowed, real delete")
        status, body = req("GET", "/tracks", cookie=sid, expect=200)
        ok(not any(t["id"] == tid for t in body), "/tracks/<id>/delete: actually removed it")

        # -- logout: cookie is invalidated, the general auth gate (line ~259 of
        # server.py: `if p not in self.OPEN and not user: 401`) now refuses /me
        # before its route body (which assumes an authenticated user) ever runs.
        req("POST", "/auth/logout", cookie=sid, expect=200)
        status, body = req("GET", "/me", cookie=sid, expect=401)
        ok(isinstance(body, dict) and body.get("error") == "auth required",
           "/me after logout: refused by the general auth gate")

    finally:
        httpd.shutdown()
        th.join(timeout=5)

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
