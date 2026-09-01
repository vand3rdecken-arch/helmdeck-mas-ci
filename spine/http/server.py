# -*- coding: utf-8 -*-
"""Local review/index + CONTROL server. The APK is a full-capability client (owner
decision: mobile = same capabilities), so besides pulling it can drive:

  GET  /runs, /runs/<id>/timeline, /runs/<id>/video, /runs/<id>/playbook, /live.jpg
  GET  / (+ /classic, /recorder, /dashboard) -> 302 to the Next app (no UI here)
  POST /control/teach/start   {"title": "..."}      arm a demo recording on the PC
  POST /control/teach/stop                          finalize it (phone stop button)
  POST /control/distill       {"id": "<run-id>"}    demo -> playbook (background)
  POST /control/demo                                scripted browser demo run (background)
  GET  /control/state                               {"teach": <run-id>|null, "busy": [...]}
"""
import json, os, threading
from urllib.parse import unquote, quote, parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from spine.ops.actionlog import read_timeline
from spine.ops.runs import REC, list_runs

_ctl = {"teach": None, "busy": []}   # current TeachSession + background job names
_ctl_lock = threading.Lock()

def _bg(name, fn):
    """Run a control job in the background; the phone polls /control/state.

    THE choke point for every backgrounded card action (steer/answer/dispatch/
    gate - see cells/engineer/routes_track_actions.py's `name` convention
    "track:<verb>:<tid>"). Crash reporting itself lives in spine.ops.bgthread
    (shared with the OTHER bare `threading.Thread` call sites that had the
    same blind spot - see that module's docstring); this wrapper only adds
    the /control/state busy-list bookkeeping on top."""
    from spine.ops import bgthread

    def _tracked():
        try:
            fn()
        finally:
            with _ctl_lock:
                if name in _ctl["busy"]:
                    _ctl["busy"].remove(name)
    with _ctl_lock:
        _ctl["busy"].append(name)
    bgthread.spawn(name, _tracked)


def _active_live():
    for m in list_runs():
        if m.get("status") == "running":
            p = os.path.join(REC, m["id"], "live.jpg")
            if os.path.exists(p):
                return p
    return None

# The daemon serves no UI. The Next app (web/, default http://localhost:3300)
# is the only frontend; the old HTML paths 302 there so stale bookmarks keep
# working. Override the target with settings.web_url when web/ is hosted
# elsewhere.
LEGACY_UI = ("/", "/classic", "/recorder", "/dashboard")

def _web_url():
    from spine.storage import events
    return (events.settings().get("web_url") or "http://localhost:3300").rstrip("/")

from spine.http.apimeta import (_loop_state_mod, _lane_flow, _loop_machine, _config_schema,
                                _profile_schema, CONTROLS, DOORS, SCOPES)
from spine.ops.glances import glance_payload, _glance_question
from spine.http.routes import routes_auth
from spine.http.routes import routes_policy
from spine.http.routes import routes_settings
from spine.http.routes import routes_glance
from spine.http.routes import routes_info
from cells.pm import routes_pm
from spine.http.routes import routes_misc
from spine.http.routes import routes_control
from spine.http.routes import routes_relay
from spine.http.routes import routes_wear
from cells.connectors import routes_connectors
from spine.http.routes import routes_audit
from spine.http.routes import routes_checkpoints
from spine.http.routes import routes_sign
from spine.http.routes import routes_projects
from cells.copilot import routes_copilot
from cells.engineer import routes_tracks
from cells.engineer import routes_track_actions
from spine.http.routes import routes_runs
from spine.http.routes import routes_system
from spine.http.routes import routes_cells
from spine.http.routes import routes_devices
from spine.http.routes import routes_gxp

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    # Legacy UI paths redirect before auth (no data behind them); the auth
    # endpoints are public; every data/control route needs a logged-in
    # session (cookie) or a per-user device token.
    OPEN = ("/auth/state", "/auth/login", "/auth/logout",
            "/auth/setup", "/auth/register", "/glance",
            # W2b device-code pairing (relay_client.py's own header has the
            # rationale): the claiming device has no session yet by
            # definition, so this must be reachable before auth - same class
            # as /glance, self-gated by its own single-use code instead of a
            # token/cookie.
            "/relay/pair/claim")

    def _sid(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sd_session":
                return v
        return None

    def _user(self):
        from spine.auth import auth
        tok = ""
        h = self.headers.get("Authorization") or ""
        if h.startswith("Bearer "):
            tok = h[7:].strip()
        if not tok and "token=" in self.path:
            tok = self.path.split("token=")[1].split("&")[0]
        u = auth.resolve(sid=self._sid(), token=tok or None)
        if u and self.command == "POST" and self.path.split("?")[0] != "/presence":
            # presence signal for the idle-time worker. POSTs only: a GET can
            # be the board's auto-refresh in a forgotten browser tab, but a
            # POST is a human doing something - steering, filing, configuring.
            #
            # /presence is EXCLUDED deliberately: it is a 15s heartbeat, so
            # counting it here would mean an app merely left open makes the
            # board look permanently busy and the PM/night loop would never
            # find its idle window again. Heartbeats say "he is here", which is
            # a different question from "he is working" - see presence.py.
            from cells.pm import pm
            pm.touch()
        return u

    def _send_cookie(self, code, body, sid=None, clear=False):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # Missing before today: every OTHER route answers via _send(), which
        # sets these; _send_cookie() (auth login/setup/register/logout) never
        # did. The OPTIONS preflight (do_OPTIONS) always set CORS correctly,
        # masking this - but the browser blocks JS from READING the actual
        # POST response body without this header on the response itself, so
        # fetch() throws a network-looking TypeError. curl doesn't enforce
        # CORS, so this was invisible there - only a real browser reproduces
        # it. Found live: /auth/login worked perfectly via curl (200, real
        # token) but failed in the browser with what looked like a connection
        # error.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        if sid:
            self.send_header("Set-Cookie",
                "sd_session=%s; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000" % sid)
        if clear:
            self.send_header("Set-Cookie", "sd_session=; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))

    def do_OPTIONS(self):
        # CORS preflight: a cross-origin fetch carrying an Authorization header
        # (the Expo web build hitting the daemon from a different port) sends an
        # OPTIONS preflight first. Auth is still enforced on the real request -
        # this only tells the browser the request is permitted.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p in LEGACY_UI:
                web = _web_url()
                self.send_response(302)
                self.send_header("Location", web + "/")
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    ("<!doctype html><meta charset=utf-8><title>HelmDeck</title>"
                     "<p>HelmDeck lives at <a href=\"%s/\">%s</a>.</p>"
                     % (web, web)).encode("utf-8"))
                return
            user = self._user()
            # Dispatch-table routes (the server.py decomposition seam): checked
            # BEFORE the inline if-chain below, so a route's move here is a
            # pure relocation - every other route is byte-identical to before.
            if p in routes_auth.GET_ROUTES:
                return routes_auth.GET_ROUTES[p](self, user)
            if p in routes_policy.GET_ROUTES:
                return routes_policy.GET_ROUTES[p](self, user)
            for _prefix, _handler in routes_glance.GET_PREFIX_ROUTES:
                if p.startswith(_prefix):
                    return _handler(self, user)
            if p in routes_glance.GET_ROUTES:
                return routes_glance.GET_ROUTES[p](self, user)
            if p in routes_relay.GET_ROUTES:
                return routes_relay.GET_ROUTES[p](self, user)
            if p not in self.OPEN and not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            # Cell gate: a path owned by a DISABLED agentic system 404s cleanly
            # (the tab is gone on the app; the route reports absent). One derived
            # check, no per-route edits. No-op while all cells default enabled.
            from spine.registry import cells
            if cells.path_disabled(p):
                return self._send(404, json.dumps({"error": "cell disabled"}))
            # Permission gate (ops/docs/backlog/rbac-gxp card 2): same position
            # as the cell gate above, same "one derived check" shape. No-op for
            # any route not yet migrated onto GET_CAPS/PATTERNS - its own inline
            # check (below) remains the only enforcement until it's migrated
            # (spine/auth/permissions.py's module docstring + debt.py).
            from spine.auth import permissions
            _parts = p.strip("/").split("/")
            _cap = permissions.cap_for("GET", p, _parts)
            if _cap:
                _denial = permissions.require(user, _cap)
                if _denial:
                    return self._send(*_denial)
            if p == "/users":
                from spine.auth import auth
                # `id` + `tail`, never the token itself. This used to ship every
                # device token in full to the panel on every load, while the UI
                # only ever displayed the last six characters - the other 186
                # bits were on the wire for nothing. Revoke goes by id now.
                return self._send(200, json.dumps([
                    {"name": u["name"], "role": u["role"], "created": u.get("created"),
                     "tokens": [{"label": t.get("label"), "id": t.get("id"),
                                 "tail": t.get("tail", ""), "created": t.get("created"),
                                 # card 5 debt (rbac-audit-hardening-partial):
                                 # access-review signal, computed live, never
                                 # a stored flag - see auth._token_stale.
                                 "last_used": t.get("last_used"),
                                 "expires": t.get("expires"),
                                 "stale": auth._token_stale(t)}
                                for t in u.get("tokens", [])]}
                    for u in auth.list_users()]))
            if p in routes_runs.GET_ROUTES:
                return routes_runs.GET_ROUTES[p](self, user)
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "runs":
                if routes_runs.runs_item_get(self, user, parts[1], parts[2]):
                    return
            if p in routes_control.GET_ROUTES:
                return routes_control.GET_ROUTES[p](self, user)
            # --- orchestrator: branches/sessions (the Paseo half) ---
            if p in routes_tracks.GET_ROUTES:
                return routes_tracks.GET_ROUTES[p](self, user)
            if p in routes_projects.GET_ROUTES:
                return routes_projects.GET_ROUTES[p](self, user)
            # --- company instrumentation: settings + CEO dashboard ---
            if p in routes_copilot.GET_ROUTES:
                return routes_copilot.GET_ROUTES[p](self, user)
            # --- Wear OS watch: board summary (README.md §4.7) ---
            if p in routes_wear.GET_ROUTES:
                return routes_wear.GET_ROUTES[p](self, user)
            if p == "/stream/wait":
                # PUSH over the sealed relay (SSE can't tunnel): a HANGING GET,
                # not a poll. Blocks until something the client subscribes to
                # moves, or ~22s, then answers. The client re-arms immediately,
                # so an idle fleet holds one open request each and sends nothing.
                # 22s < relay REPLY_TIMEOUT (120) and bridge _local (115).
                #
                # TWO cursors: `v` = board data, `c` = chat transcript. The chat
                # one exists because the transcript is a JSON file, not a table,
                # so no db writer ever moved `v` for a Henry answer and every
                # surface had quietly fallen back to a fixed interval.
                from spine.storage import db
                _q = parse_qs(urlparse(self.path).query)

                def _cursor(name):
                    try:
                        return int((_q.get(name) or ["0"])[0])
                    except ValueError:
                        return 0

                # STRICTLY OPT-IN, and this is not a style choice. If `c` is
                # absent we must answer exactly as before: an older bundle sends
                # only `v`, so it would be compared against chat_last=0 - and
                # from the first chat message on, _chat_version > 0 would be
                # permanently true and every one of its requests would return
                # instantly. The stream loop re-calls on success, so a stale
                # client would spin hot forever against the daemon. Absent `c`
                # therefore means "board only", byte-identical to the old reply.
                if "c" not in _q:
                    return self._send(200, json.dumps(
                        {"v": db.wait_version(_cursor("v"), timeout=22)}))
                v, c = db.wait_any(_cursor("v"), _cursor("c"), timeout=22)
                return self._send(200, json.dumps({"v": v, "c": c}))
            if p == "/stream":
                # SSE: push a version tick whenever board data changes - pays
                # the polling debt. Client refetches on tick.
                from spine.storage import db
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                last = db.current_version()
                try:
                    self.wfile.write(("data: %d" % last).encode() + b"\n\n")
                    self.wfile.flush()
                    while True:
                        v = db.wait_version(last, timeout=25)
                        self.wfile.write(("data: %d" % v).encode() + b"\n\n")
                        self.wfile.flush()
                        last = v
                except (ConnectionAbortedError, BrokenPipeError, OSError):
                    return
            if p.startswith("/tracks/") and p.endswith("/stream"):
                tid = p[len("/tracks/"):-len("/stream")]
                return routes_track_actions.tracks_stream_get(self, user, tid)
            if p in routes_system.GET_ROUTES:
                return routes_system.GET_ROUTES[p](self, user)
            if p in routes_devices.GET_ROUTES:
                return routes_devices.GET_ROUTES[p](self, user)
            if p in routes_gxp.GET_ROUTES:
                return routes_gxp.GET_ROUTES[p](self, user)
            if len(parts) == 3 and parts[0] == "devices" and parts[2] == "queue":
                return routes_devices.devices_queue_get(self, user, parts[1])
            if len(parts) == 4 and parts[0] == "devices" and parts[2] == "card":
                return routes_devices.devices_card_status_get(self, user, parts[1], parts[3])
            if p in routes_info.GET_ROUTES:
                return routes_info.GET_ROUTES[p](self, user)
            if p in routes_pm.GET_ROUTES:
                return routes_pm.GET_ROUTES[p](self, user)
            if len(parts) == 4 and parts[0] == "harness" and parts[1] == "version":
                return routes_system.harness_version_get(self, user, parts[2], parts[3])
            if p.startswith("/sign/subject/"):
                return routes_sign.sign_subject_get(
                    self, user, p[len("/sign/subject/"):])
            if p in routes_audit.GET_ROUTES:
                return routes_audit.GET_ROUTES[p](self, user)
            if p in routes_checkpoints.GET_ROUTES:
                return routes_checkpoints.GET_ROUTES[p](self, user)
            if p.startswith("/checkpoints/") and p.endswith("/diff"):
                cid = p[len("/checkpoints/"):-len("/diff")]
                return routes_checkpoints.checkpoints_diff_get(self, user, cid)
            if len(parts) == 3 and parts[0] == "cells" and parts[2] == "source":
                return routes_cells.cell_source_get(self, user, parts[1])
            if p in routes_connectors.GET_ROUTES:
                return routes_connectors.GET_ROUTES[p](self, user)
            if p in routes_misc.GET_ROUTES:
                return routes_misc.GET_ROUTES[p](self, user)
            if p in routes_settings.GET_ROUTES:
                return routes_settings.GET_ROUTES[p](self, user)
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "live":
                return routes_tracks.tracks_live_get(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "turns":
                return routes_tracks.tracks_turns_get(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "history":
                return routes_tracks.tracks_history_get(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "transcript":
                return routes_tracks.tracks_transcript_get(self, user, parts[1])
            if len(parts) == 4 and parts[0] == "tracks" and parts[2] == "transcript" and parts[3] == "live":
                return routes_tracks.tracks_transcript_live_get(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "checkpoints":
                return routes_tracks.tracks_checkpoints_get(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "attachments":
                return routes_tracks.tracks_attachments_get(self, user, parts[1])
            if len(parts) == 4 and parts[0] == "tracks" and parts[2] == "attachment":
                return routes_tracks.tracks_attachment_get(self, user, parts[1], parts[3])
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass

    def do_PUT(self):
        """PUT is a CLOSED table - the third method this server answers, added
        for accounts-boards-prd phase 1's `PUT /me/config`.

        Deliberately not folded into do_POST: do_POST carries a blanket "clients
        can file and comment only" denial partway down its chain, and a
        self-scoped profile write is precisely the thing a client role MUST be
        able to do. Bolting an exception onto that denial list would have made
        the rule read as a list of accidents; a separate verb for a separate
        kind of write keeps both statements true.

        There is no fall-through: a path with no PUT_ROUTES entry 404s. The
        auth, cell and capability gates below are the same three do_GET/do_POST
        run, in the same order, so a put route is never accidentally the one
        door that skips one."""
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        try:
            user = self._user()
            if not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            from spine.registry import cells
            if cells.path_disabled(p):
                return self._send(404, json.dumps({"error": "cell disabled"}))
            from spine.auth import permissions
            _cap = permissions.cap_for("PUT", p, p.strip("/").split("/"))
            if _cap:
                _denial = permissions.require(user, _cap)
                if _denial:
                    return self._send(*_denial)
            if p in routes_misc.PUT_ROUTES:
                return routes_misc.PUT_ROUTES[p](self, user, body)
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

    def do_DELETE(self):
        """DELETE is a CLOSED table, the fourth method this server answers,
        added for accounts-boards-prd phase 2's `DELETE /me/boards`.

        Why a fourth verb rather than the house's usual POST /<thing>/delete
        (users, projects): those are OWNER-ONLY routes, and do_POST denies a
        `client` role everything outside a short allowlist. Deleting a board
        you created is precisely a thing the weakest role must be able to do -
        the same argument do_PUT's docstring makes, and bolting a second
        exception onto that denial list would have turned a rule into a list of
        accidents. A delete is also not a write with a flag: folding it into
        PUT would mean a malformed board body could ever be read as "remove
        it".

        Exact-match only, no fall-through, no body: the resource is named in
        the query string (`?id=`), so a delete route is never the one door that
        quietly grew a pattern. The auth, cell and capability gates below are
        the same three the other three verbs run, in the same order."""
        parsed = urlparse(self.path)
        p = parsed.path
        try:
            user = self._user()
            if not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            from spine.registry import cells
            if cells.path_disabled(p):
                return self._send(404, json.dumps({"error": "cell disabled"}))
            from spine.auth import permissions
            _cap = permissions.cap_for("DELETE", p, p.strip("/").split("/"))
            if _cap:
                _denial = permissions.require(user, _cap)
                if _denial:
                    return self._send(*_denial)
            if p in routes_misc.DELETE_ROUTES:
                return routes_misc.DELETE_ROUTES[p](self, user, parse_qs(parsed.query))
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        try:
            from spine.auth import auth
            user = self._user()
            # Dispatch-table routes (see do_GET) - checked before the inline
            # if-chain, so this is a pure relocation of the 4 auth POST routes.
            if p in routes_auth.POST_ROUTES:
                return routes_auth.POST_ROUTES[p](self, user, body)
            if p in routes_policy.POST_ROUTES:
                return routes_policy.POST_ROUTES[p](self, user, body)
            if p in routes_glance.POST_ROUTES:
                return routes_glance.POST_ROUTES[p](self, user, body)
            if not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            # Cell gate (see do_GET): a POST path owned by a DISABLED agentic
            # system 404s cleanly. No-op while all cells default enabled.
            from spine.registry import cells
            if cells.path_disabled(p):
                return self._send(404, json.dumps({"error": "cell disabled"}))
            # Permission gate (see do_GET's twin block for the full rationale).
            from spine.auth import permissions
            parts = p.strip("/").split("/")
            _cap = permissions.cap_for("POST", p, parts)
            if _cap:
                _denial = permissions.require(user, _cap)
                if _denial:
                    return self._send(*_denial)
            # ---- user management (owner only, cap users.manage) ----
            if parts[0] == "users":
                try:
                    # actor= is what makes these auditable: auth.py records WHO
                    # changed WHOSE account, and only this layer knows the caller.
                    if len(parts) == 1:
                        return self._send(200, json.dumps(auth.create_user(
                            body.get("name", ""), body.get("password", ""),
                            body.get("role", "operator"), actor=user["name"])))
                    name, action = parts[1], parts[2] if len(parts) > 2 else ""
                    if action == "password":
                        auth.set_password(name, body.get("password", ""), actor=user["name"])
                    elif action == "role":
                        auth.set_role(name, body.get("role", ""), actor=user["name"])
                    elif action == "tokens":
                        return self._send(200, json.dumps(
                            {"token": auth.issue_token(name, body.get("label", ""),
                                                       actor=user["name"])}))
                    elif action == "revoke":
                        auth.revoke_token(name, body.get("token", ""), actor=user["name"])
                    elif action == "delete":
                        auth.delete_user(name, actor=user["name"])
                    else:
                        return self._send(404, json.dumps({"error": "?"}))
                    return self._send(200, json.dumps({"ok": True}))
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            # answering a question is a steer in typed form (it runs the same
            # turn), so a client may answer on their OWN card exactly as they
            # may steer it - the per-card ownership check still runs below.
            if user["role"] == "client" and p not in ("/tracks/new", "/processes/new", "/presence") \
               and not (p.startswith("/tracks/") and (p.endswith("/steer") or p.endswith("/cancel")
                                                      or p.endswith("/answer"))):
                return self._send(403, json.dumps({"error": "clients can file and comment only"}))
            if p in routes_copilot.POST_ROUTES:
                return routes_copilot.POST_ROUTES[p](self, user, body)
            if p in routes_wear.POST_ROUTES:
                return routes_wear.POST_ROUTES[p](self, user, body)
            if p in routes_tracks.POST_ROUTES:
                return routes_tracks.POST_ROUTES[p](self, user, body)
            if p in routes_relay.POST_ROUTES:
                return routes_relay.POST_ROUTES[p](self, user, body)
            if p == "/sessions/claude/adopt":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                from cells.engineer import sessions
                try:
                    return self._send(200, json.dumps(sessions.adopt_session(
                        body.get("session_id", ""), body.get("cwd", ""),
                        mode=body.get("mode", "continue"), first=body.get("first", ""),
                        actor=user["name"])))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if p == "/sign":
                return routes_sign.sign_post(self, user, body)
            if p == "/sign/batch":
                return routes_sign.sign_batch_post(self, user, body)
            if p in routes_pm.POST_ROUTES:
                return routes_pm.POST_ROUTES[p](self, user, body)
            if p in routes_devices.POST_ROUTES:
                return routes_devices.POST_ROUTES[p](self, user, body)
            if p in routes_gxp.POST_ROUTES:
                return routes_gxp.POST_ROUTES[p](self, user, body)
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "devices" and parts[2] == "revoke":
                return routes_devices.devices_revoke_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "devices" and parts[2] == "submit":
                return routes_devices.devices_submit_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "devices" and parts[2] == "stream":
                return routes_devices.devices_stream_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "checkpoints" and parts[2] == "restore":
                return routes_checkpoints.checkpoints_restore_post(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "connectors" and parts[2] == "rollback":
                return routes_connectors.connectors_rollback_post(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "connectors" and parts[2] == "run":
                return routes_connectors.connectors_run_post(self, user, parts[1])
            if len(parts) == 3 and parts[0] == "debt" and parts[2] == "fix":
                return routes_system.debt_fix_post(self, user, body, parts[1])
            if p in ("/import/jira", "/import/url"):
                return routes_system.import_post(self, user, body, p)
            # ---- processes: propose -> adjust -> accept into cards ----
            if p in routes_misc.POST_ROUTES:
                return routes_misc.POST_ROUTES[p](self, user, body)
            parts = p.strip("/").split("/")
            if parts[0] == "processes" and len(parts) >= 3:
                return routes_system.processes_sub_post(self, user, body, parts[1], parts[2])
            if p in routes_control.POST_ROUTES:
                return routes_control.POST_ROUTES[p](self, user, body)
            if p in routes_settings.POST_ROUTES:
                return routes_settings.POST_ROUTES[p](self, user, body)
            if p in routes_system.POST_ROUTES:
                return routes_system.POST_ROUTES[p](self, user, body)
            # --- orchestrator control ---
            if p in routes_projects.POST_ROUTES:
                return routes_projects.POST_ROUTES[p](self, user, body)
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "projects" and parts[2] == "update":
                return routes_projects.projects_update_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "projects" and parts[2] == "delete":
                return routes_projects.projects_delete_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "archive":
                return routes_tracks.tracks_archive_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "fork":
                return routes_tracks.tracks_fork_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "fork-chat":
                return routes_tracks.tracks_forkchat_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "delete":
                return routes_tracks.tracks_delete_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "update":
                return routes_tracks.tracks_update_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "rewind":
                return routes_tracks.tracks_rewind_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "attach":
                return routes_tracks.tracks_attach_post(self, user, body, parts[1])
            if len(parts) == 4 and parts[0] == "tracks" and parts[2] == "attach" \
                    and parts[3] == "remove":
                return routes_tracks.tracks_attach_remove_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "steer":
                return routes_track_actions.tracks_steer_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "answer":
                return routes_track_actions.tracks_answer_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "cancel":
                return routes_track_actions.tracks_cancel_post(self, user, body, parts[1])
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "lane":
                return routes_track_actions.tracks_lane_post(self, user, body, parts[1])
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

from spine.http.startup import _tls_config, _hydrate_windows_path, _hydrate_registry_env, _take_singleton_lock


def serve(port=8140):
    _hydrate_windows_path()      # bash-launched daemons lack Windows dirs on PATH -> gate/py/cmd fail
    _hydrate_registry_env()      # + JAVA_HOME/ANDROID_HOME/user-PATH from the registry (build env)
    _take_singleton_lock(port)   # evict a prior daemon so the relay poll never races a restart
    from spine.storage import db
    # role="daemon": loading the store AS THE DAEMON structurally devalues any
    # persisted 'running'/'gating' (db._devalue_persisted_running - the old
    # serve()-side sweep_zombies call, now part of the load path itself).
    db.init(role="daemon")
    # The default board, minted from policy.lane_labels the first time (PRD
    # phase 2: "migration at daemon start"). Idempotent - a board that exists
    # is neither re-seeded nor re-labelled, so this is a no-op on every boot
    # after the first. Best-effort: a board store that will not open must not
    # stop the daemon from serving, and /me degrades to "no boards".
    try:
        from spine.storage import boards
        boards.ensure_default()
    except Exception as e:
        print("BOARDS: default board not seeded: %s" % e)
    import atexit
    from spine.agent import drivers
    reaped = drivers.reap_orphans()   # tree-kill agent processes a prior daemon left behind
    if reaped:
        print("DRIVERS: reaped %d orphan agent process tree(s) from a previous run." % reaped)
    # SINGLETON eviction's taskkill /T does not reliably cascade to a
    # grandchild ffmpeg subprocess, so a screen recorder can outlive the
    # daemon that started it - reap those too (wincap.py's own reap_orphans).
    from spine.media import wincap
    rreaped = wincap.reap_orphans()
    if rreaped:
        print("WINCAP: reaped %d orphan screen recorder(s) from a previous run." % rreaped)
    drivers.start_idle_sweeper()      # reap idle worker sessions (Paseo idle TTL)
    atexit.register(drivers.shutdown_all)   # clean stop: don't orphan worker trees
    from cells.engineer import sessions
    reclaimed = sessions.sweep_worktrees()  # WORKTREE RECLAMATION backstop: merged+clean card trees left
    if reclaimed:                            # by pre-reclaim builds (the "System too full" pile-up). Paseo
        print("SESSIONS: reclaimed %d merged worktree(s)" % reclaimed)  # stays clean by having none at all.
    reclaimed_claims = sessions.sweep_stale_device_claims()  # a card claimed by a remote
    if reclaimed_claims:                     # device that then went quiet before this boot -
        print("SESSIONS: reclaimed %d stale device claim(s): %s"  # same backstop-at-boot
             % (len(reclaimed_claims), ", ".join(reclaimed_claims)))  # shape as worktrees above.
    # start_zombie_reconciler()/start_background_watcher() moved OFF this flat
    # boot path (daemon/debt.py order 33, Phase 3): both are CONTINUOUS pollers
    # over Engineer-cell state (card `status`, session liveness, background-
    # task completion), so they now launch through cells.start_enabled() below
    # via sessions.start_engineer_lifecycle() - gated by engineerEnabled like
    # every other cell's poller. The one-shot boot passes below stay flat.
    sessions.apply_board_directives()    # one-shot board-data patches shipped as repo data
    stamped = sessions.backfill_outcomes()  # one-shot: stamp reviewed outcomes onto pre-outcome
    if stamped:                             # done cards (pays debt legacy-outcome-on-read)
        print("SESSIONS: backfilled outcome on %d legacy done card(s)" % stamped)
    from spine.auth import auth
    from spine.storage import events
    if auth.migrate_legacy(events.settings().get("users")):
        print("AUTH: legacy token-users migrated to users.json; old tokens still work as device tokens.")
        print("      Set real passwords via the Users panel (owner).")
    if not auth.list_users():
        print("AUTH: no users yet - the web app will show the create-owner setup screen.")
    from spine.comms import relay_client
    from spine.registry import cells
    # Cell lifecycle: launch each ENABLED agentic system's poller through the
    # registry (process chain poller, connectors scheduler, pm proactive loop).
    # Replaces the flat start_*() calls - all cells default enabled, so this is
    # behaviourally identical until an owner disables one via policy.swap.
    cells.start_enabled()
    relay_client.start(port)   # reverse tunnel for mobile (spine, not a cell) - idle until settings.relay is set
    # Transport (pays debt [single-secret-transport]): with TLS material
    # present, network traffic goes through the https listener and the plain
    # listener retreats to LOOPBACK ONLY - local tooling (relay bridge,
    # cloudflared, Electron shell) keeps http://localhost, but credentials and
    # cookies never cross the LAN unencrypted. No TLS material = today's
    # behaviour, unchanged. A BROKEN TLS config also stays loopback-only:
    # failing loud beats silently downgrading to cleartext on the network.
    cert, key, tls_port = _tls_config()
    bind = "127.0.0.1" if cert else "0.0.0.0"
    if cert:
        import ssl
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(cert, key)
            tls_srv = ThreadingHTTPServer(("0.0.0.0", tls_port), H)
            tls_srv.socket = ctx.wrap_socket(tls_srv.socket, server_side=True,
                                             do_handshake_on_connect=False)
            threading.Thread(target=tls_srv.serve_forever, daemon=True).start()
            print("TLS: https://0.0.0.0:%d (cert %s); plain http is loopback-only" % (tls_port, cert), flush=True)
        except Exception as e:
            print("TLS ERROR: %s\n    https listener NOT started; plain http stays "
                  "LOOPBACK-ONLY (no cleartext on the network). Fix the cert/key "
                  "(ops/tools/make_tls_cert.py) or remove them to serve http again." % e,
                  flush=True)
    print("HelmDeck review server on http://localhost:%d  (APK pulls /runs, /live.jpg)" % port)
    try:
        ThreadingHTTPServer((bind, port), H).serve_forever()
    finally:
        drivers.shutdown_all()   # tree-kill live worker sessions on stop (Ctrl-C included)

if __name__ == "__main__":
    serve()
