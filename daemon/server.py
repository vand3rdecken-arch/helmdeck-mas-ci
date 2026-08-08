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
from urllib.parse import unquote, parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from actionlog import read_timeline
from runs import REC, list_runs

_ctl = {"teach": None, "busy": []}   # current TeachSession + background job names
_ctl_lock = threading.Lock()

def _bg(name, fn):
    """Run a control job in the background; the phone polls /control/state."""
    def wrap():
        try: fn()
        finally:
            with _ctl_lock:
                if name in _ctl["busy"]:
                    _ctl["busy"].remove(name)
    with _ctl_lock:
        _ctl["busy"].append(name)
    threading.Thread(target=wrap, daemon=True).start()

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
    import events
    return (events.settings().get("web_url") or "http://localhost:3300").rstrip("/")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    # Legacy UI paths redirect before auth (no data behind them); the auth
    # endpoints are public; every data/control route needs a logged-in
    # session (cookie) or a per-user device token.
    OPEN = ("/auth/state", "/auth/login", "/auth/logout",
            "/auth/setup", "/auth/register", "/glance")

    def _sid(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sd_session":
                return v
        return None

    def _user(self):
        import auth
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
            import pm
            pm.touch()
        return u

    def _send_cookie(self, code, body, sid=None, clear=False):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
            if p == "/auth/state":
                import auth, events
                reg = events.settings().get("registration") or {}
                return self._send(200, json.dumps(
                    {"setup_needed": not auth.list_users(), "user": user,
                     "registration": bool(reg.get("open") or reg.get("invite_code")),
                     "registration_open": bool(reg.get("open"))}))
            if p == "/glance":
                # read-only glance surface for the Meta Ray-Ban Display webapp
                # (glasses/). Token-gated, cross-origin (CORS on via _send). No
                # write access, no session-cookie coupling - additive, not a
                # weakening of auth. Off unless settings.glance_token is set.
                import events, sessions
                tok = events.settings().get("glance_token") or ""
                given = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
                if not tok or given != tok:
                    return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
                m = events.metrics(sessions.list_tracks())
                # The glance surface is "what wants ME". A card waiting on its own
                # background task does not, so it stays off the glasses; a card
                # asking a question does, and says so.
                ny = [{"id": t["id"], "task": (t.get("task") or "")[:70],
                       "client": t.get("client", ""), "status": t.get("status"),
                       "asking": bool(t.get("question"))}
                      for t in map(sessions.present, sessions.list_tracks())
                      if t.get("status") == "needs_you" and not t.get("archived")
                      and t.get("waiting_on") != "background"]
                return self._send(200, json.dumps({
                    "needs_you": ny,
                    "econ": {"needs_you": len(ny), "wip": m["capacity"]["wip"],
                             "wip_limit": m["capacity"]["wip_limit"],
                             "headroom": m["capacity"]["headroom"],
                             "margin": m["totals"]["margin"],
                             "currency": m["settings"].get("currency", "EUR")},
                    "sows": [{"name": (s["name"] or "")[:40], "margin": s["margin"]}
                             for s in m.get("sows", [])[:5]]}))
            if p not in self.OPEN and not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            if p == "/users":
                import auth
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps([
                    {"name": u["name"], "role": u["role"], "created": u.get("created"),
                     "tokens": [{"label": t["label"], "token": t["token"],
                                 "created": t.get("created")} for t in u.get("tokens", [])]}
                    for u in auth.list_users()]))
            if p == "/runs":
                runs = list_runs()
                for m in runs:
                    m["steps"] = len(read_timeline(os.path.join(REC, m["id"])))
                return self._send(200, json.dumps(runs))
            if p == "/live.jpg":
                lp = _active_live()
                if not lp:
                    return self._send(404, b"no active run", "text/plain")
                with open(lp, "rb") as f:
                    return self._send(200, f.read(), "image/jpeg")
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "runs":
                rid, what = parts[1], parts[2]
                d = os.path.join(REC, os.path.basename(rid))
                if what == "timeline":
                    return self._send(200, json.dumps(read_timeline(d)))
                if what == "playbook":
                    fp = os.path.join(d, "playbook.md")
                    if os.path.exists(fp):
                        with open(fp, "rb") as f:
                            return self._send(200, f.read(), "text/markdown; charset=utf-8")
                    return self._send(404, b"not distilled", "text/plain")
                if what == "video":
                    for name, ct in (("screen.mp4", "video/mp4"), ("browser.webm", "video/webm")):
                        fp = os.path.join(d, name)
                        if os.path.exists(fp):
                            with open(fp, "rb") as f:
                                return self._send(200, f.read(), ct)
                    return self._send(404, b"no video", "text/plain")
                if what == "videochunk":
                    # Ranged, base64-in-JSON slices of the recording. The mobile
                    # app reaches the daemon through an end-to-end encrypted
                    # relay that carries TEXT frames, so a raw binary stream
                    # cannot pass; slicing keeps recordings watchable on the
                    # phone without weakening the tunnel or loading a whole
                    # video into memory.
                    import base64 as _b64, transcode
                    q = parse_qs(urlparse(self.path).query)
                    try:
                        off = max(0, int((q.get("offset") or ["0"])[0]))
                        ln = int((q.get("len") or ["262144"])[0])
                    except ValueError:
                        return self._send(400, json.dumps({"error": "bad offset/len"}))
                    ln = max(1, min(ln, 1_048_576))          # 1 MiB ceiling per slice
                    # A phone or a 600x600 glasses display cannot use a full
                    # desktop capture; serving a small rendition cuts the bytes
                    # that have to cross the relay by roughly an order of
                    # magnitude. Made once on THIS machine, then cached.
                    profile = (q.get("profile") or ["mobile"])[0]
                    for name, ct in (("screen.mp4", "video/mp4"), ("browser.webm", "video/webm")):
                        fp = os.path.join(d, name)
                        if not os.path.exists(fp):
                            continue
                        fp = transcode.variant(fp, profile)
                        if fp.endswith(".mp4"):
                            ct = "video/mp4"
                        size = os.path.getsize(fp)
                        with open(fp, "rb") as f:
                            f.seek(off)
                            blob = f.read(ln)
                        return self._send(200, json.dumps({
                            "size": size, "mime": ct, "offset": off,
                            "profile": profile, "scaled": transcode.available(),
                            "eof": off + len(blob) >= size,
                            "data": _b64.b64encode(blob).decode()}))
                    return self._send(404, json.dumps({"error": "no video"}))
            if p == "/control/state":
                with _ctl_lock:
                    s = _ctl["teach"]
                    return self._send(200, json.dumps(
                        {"teach": s.rid if s and not s.stopped.is_set() else None,
                         "busy": list(_ctl["busy"])}))
            # --- orchestrator: branches/sessions (the Paseo half) ---
            if p == "/tracks":
                import sessions
                # present(): stored 'running' is never believed on the way OUT -
                # only a live turn (drivers.turn_active) may render a spinner.
                ts = [sessions.present(t) for t in sessions.list_tracks()]
                if user["role"] == "client":   # clients see only their own cards
                    ts = [t for t in ts if t.get("client") == user["name"]]
                return self._send(200, json.dumps(ts))
            if p == "/projects":
                import projects
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                return self._send(200, json.dumps(projects.list_projects()))
            # --- company instrumentation: settings + CEO dashboard ---
            if p == "/chat/history":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import copilot
                return self._send(200, json.dumps(copilot.history(user["name"])))
            if p == "/stream/wait":
                # Board PUSH over the sealed relay (SSE can't tunnel): long-poll
                # the data version. Blocks until it passes `v` or ~22s, then
                # returns {v}. The phone loops it and invalidates on change -
                # live board updates in relay mode, no fixed poll. 22s < relay
                # REPLY_TIMEOUT (120) and bridge _local (115).
                import db
                want = (parse_qs(urlparse(self.path).query).get("v") or ["0"])[0]
                try:
                    last = int(want)
                except ValueError:
                    last = 0
                return self._send(200, json.dumps({"v": db.wait_version(last, timeout=22)}))
            if p == "/stream":
                # SSE: push a version tick whenever board data changes - pays
                # the polling debt. Client refetches on tick.
                import db
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
                # per-card SSE: push the live turn transcript as the agent works.
                # Claude Code writes the session .jsonl live, so we watch it and
                # emit the parsed transcript whenever it grows - real streaming,
                # no client poll, same shape as the board /stream above.
                import sessions, claude_sessions, time as _t
                tid = p[len("/tracks/"):-len("/stream")]
                t = sessions.get_track(tid)
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, json.dumps({"error": "not your card"}))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                # Tick whenever the session .jsonl grows, the driver's
                # live_partial.txt grows (token streaming within a block, before
                # it's flushed to the .jsonl), OR the flight recorder gets a
                # lifecycle note. ONE token for both live paths - SSE and the
                # relay long-poll must agree on what "changed" means, or the
                # web feed silently misses what the phone gets. session_id is
                # resolved fresh inside so streaming starts on turn 1 (sidecar)
                # too. The client refetches the transcript on each tick.
                def combined():
                    return claude_sessions.transcript_version(t)

                def tick(v):
                    self.wfile.write(("data: %d" % v).encode() + b"\n\n")
                    self.wfile.flush()
                try:
                    last = combined()
                    tick(last)
                    idle = 0
                    while True:
                        _t.sleep(0.3)
                        size = combined()
                        if size != last:
                            last = size
                            tick(size)
                            idle = 0
                        elif (idle := idle + 1) >= 45:   # ~13.5s keep-alive
                            self.wfile.write(b": ping\n\n"); self.wfile.flush(); idle = 0
                except (ConnectionAbortedError, BrokenPipeError, OSError):
                    return
            if p == "/presence":
                # who the daemon thinks is here (diagnostic for the notify
                # policy: "why didn't my phone buzz?" has a checkable answer)
                import presence
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps(presence.snapshot()))
            if p == "/debt":
                import debt
                return self._send(200, json.dumps(debt.list_debt()))
            if p == "/charter":
                import charter, events
                return self._send(200, json.dumps(
                    {"core": charter.CHARTER,
                     "house_rules": (events.settings().get("policy") or {}).get("house_rules", "")}))
            if p == "/loop/map":
                # the machine, made legible: the lane/gate flow + the build loop +
                # the fixed harness laws behind them (charter is code, shown read-only).
                import charter, events
                ll = (events.settings().get("policy") or {}).get("lane_labels") or {}
                lab = lambda k, d: ll.get(k, d)
                return self._send(200, json.dumps({
                    "runtime": {
                        "title": "Wie Arbeit fließt",
                        "lanes": [
                            {"key": "backlog", "label": lab("backlog", "Backlog"), "kind": "policy",
                             "instruction": "Karten warten. Ab der Priorität in policy.auto_dispatch_priority "
                                            "starten sie sich selbst — aber nur im WIP-Rahmen (capacity.wip_limit)."},
                            {"key": "working", "label": lab("working", "In Arbeit"), "kind": "fixed",
                             "instruction": "Ein Agent arbeitet in einem ISOLIERTEN git-worktree (Harness-Gesetz: "
                                            "worktree-Isolation). Jeder Turn ist gemessen (Kosten/Token → Audit)."},
                            {"key": "review", "label": lab("review", "Review"), "kind": "fixed",
                             "instruction": "Beim Eintritt läuft der Quality-Gate (gate-before-review, FIX). "
                                            "Rot → die Karte wird zurückgebounced mit sichtbarem Grund."},
                            {"key": "done", "label": lab("done", "Fertig"), "kind": "policy",
                             "instruction": "Merge + Deploy. Nichts merged sich selbst — außer policy.auto_accept_green "
                                            "ist an. Der Prozess-Chain rückt einen Schritt vor."},
                        ],
                        "gate": {"label": "Quality Gate", "kind": "fixed", "between": ["working", "review"],
                                 "instruction": "Gate-before-review ist ein fixes Harness-Gesetz: kein Review ohne "
                                                "bestandenen Gate. Das Ergebnis geht append-only ins Audit-Log."},
                    },
                    "build": {
                        "title": "Wie Änderungen gebaut werden",
                        "states": [
                            {"key": "ALIGN", "instruction": "Arbeit begonnen, aber kein Workorder — Request + passt es zu den Gesetzen/Charter?"},
                            {"key": "ANALYZE", "instruction": "Architektur-Impact + Debt-Delta (Abkürzungen in debt.py registrieren)."},
                            {"key": "EXECUTE", "instruction": "Checks rot → bauen/fixen bis grün (compile, types, design-lint)."},
                            {"key": "TEST", "instruction": "Grün heißt nicht fertig: das echte Ding prüfen (UI = beurteilt, nicht nur gerendert) + adversarial testen."},
                            {"key": "CLEAN", "instruction": "Hygiene: Debt-Register wohlgeformt, keine Secrets getrackt."},
                            {"key": "COMMIT", "instruction": "Loop komplett & ruhig → Commit vorschlagen; Workorder archiviert."},
                        ],
                    },
                    "laws": [
                        {"key": "auth", "text": "Auth ist fix — nie geschwächt."},
                        {"key": "audit", "text": "Append-only Audit/Events — Geschichte wird nie überschrieben."},
                        {"key": "gate", "text": "Gate-before-review — Qualität vor jeder Abnahme."},
                        {"key": "economics", "text": "Gemessene Ökonomie — jeder Turn hat Kosten/Value."},
                        {"key": "worktree", "text": "Worktree-Isolation — jeder Agent in eigenem Checkout."},
                        {"key": "drivers", "text": "Driver-Kommandos sind fix — was Agents ausführen ist nicht frei konfigurierbar."},
                        {"key": "charter", "text": "Charter-Kern ist Code — nicht per Chat editierbar."},
                    ],
                    "charter": charter.CHARTER,
                }))
            if p == "/models":
                import turnopts
                return self._send(200, json.dumps(turnopts.list_models()))
            if p == "/pm/economics":
                # cheap, no-LLM economics snapshot + the stored MVP goal
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import pm
                return self._send(200, json.dumps({"goal": pm.get_goal(), "economics": pm.economics()}))
            if p == "/pm/plan":
                # the last PM briefing (cached artifact) + live economics - no LLM,
                # so the Dashboard shows instantly; /pm/report refreshes it.
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import pm
                return self._send(200, json.dumps({"goal": pm.get_goal(),
                    "economics": pm.economics(), "plan": pm.live_plan(),
                    "config": pm._pm(), "activity": pm.activity()}))
            if p == "/sessions/claude":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import claude_sessions
                return self._send(200, json.dumps(claude_sessions.list_sessions()))
            if p == "/checkpoints":
                import checkpoints
                return self._send(200, json.dumps(checkpoints.list_checkpoints()))
            if p.startswith("/checkpoints/") and p.endswith("/diff"):
                import checkpoints
                cid = p[len("/checkpoints/"):-len("/diff")]
                try:
                    return self._send(200, json.dumps(checkpoints.diff(cid)))
                except (RuntimeError, ValueError) as e:
                    return self._send(404, json.dumps({"error": str(e)}))
            if p == "/history":
                # the git audit trail: main line + every card branch's commits.
                import subprocess, sessions, events
                repo = events.settings().get("default_repo")
                if not repo:
                    return self._send(200, json.dumps({"main": [], "branches": []}))
                def git(*args):
                    r = subprocess.run(["git", "-C", repo, *args],
                                       capture_output=True, text=True, timeout=20)
                    return r.stdout.strip() if r.returncode == 0 else ""
                def parse(log):
                    out = []
                    for line in log.splitlines():
                        bits = line.split("")
                        if len(bits) >= 4:
                            out.append({"h": bits[0], "msg": bits[1][:100],
                                        "author": bits[2], "date": bits[3]})
                    return out
                fmt = "--pretty=format:%h%s%an%ad"
                head = git("rev-parse", "--abbrev-ref", "HEAD") or "main"
                main = parse(git("log", "-n", "40", "--date=short", fmt, head))
                tmap = {}
                for t in sessions.list_tracks():
                    tmap.setdefault(t["branch"], t)
                branches = []
                for br in git("branch", "--format=%(refname:short)").splitlines():
                    br = br.strip()
                    if not br or br == head:
                        continue
                    commits = parse(git("log", "--date=short", fmt, "-n", "20",
                                        "%s..%s" % (head, br)))
                    t = tmap.get(br)
                    branches.append({
                        "name": br, "commits": commits,
                        "track": t["id"] if t else None,
                        "task": t["task"][:70] if t else "",
                        "lane": t.get("lane") if t else None,
                        "client": t.get("client") if t else "",
                    })
                branches.sort(key=lambda b: (b["track"] is None, b["name"]))
                return self._send(200, json.dumps(
                    {"head": head, "main": main, "branches": branches[:40]}))
            if p == "/connectors":
                import connectors
                return self._send(200, json.dumps(connectors.list_connectors()))
            if p == "/processes":
                import processes
                try:
                    processes.sync()
                except Exception:
                    pass
                return self._send(200, json.dumps(processes.list_processes(
                    client=user["name"] if user["role"] == "client" else None)))
            if p == "/me":
                # Carries the PUBLIC UI policy, not just the identity: the
                # workspace language (and the lane labels the board renders) has
                # to reach EVERY role, or the app is German for an operator and
                # English for the owner - exactly the split this replaced.
                # /dashboard/data can't serve it: it strips settings for
                # non-owners and 403s clients. Whitelisted, never the whole
                # settings blob - that stays owner-only.
                import events
                pol = events.settings().get("policy") or {}
                return self._send(200, json.dumps({
                    "name": user["name"], "role": user["role"],
                    "ui": {"lang": pol.get("lang", "de"),
                           "lane_labels": pol.get("lane_labels") or {}},
                }))
            if p == "/settings":
                import events
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps(events.settings()))
            if p == "/nightshift":   # kept as an alias; the PM loop is the system now
                import pm
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps(pm.status()))
            if p == "/usage":
                # Claude subscription usage (5h + weekly rate-limit windows) with pacing,
                # from the same source as Paseo's usage tab. Owner-only: it's the owner's
                # account. Cached in usage.py so a poll doesn't hammer the endpoint.
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import usage
                return self._send(200, json.dumps(usage.snapshot()))
            if p == "/automation":
                # everything about the auto-working machinery in one place: the
                # night shift (is it on, repos, limits, tonight's plan), the policy
                # (auto-dispatch/accept), and the build-loop state machine + where
                # it currently sits - so the UI can expose "what is the harness doing".
                import events, pm, os as _os, sys as _sys
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                s = events.settings(); pol = s.get("policy") or {}
                loop_states = [
                    ["ALIGN", "Arbeit begonnen - Workorder schreiben (passt es zu Gesetzen + Charter?)"],
                    ["ANALYZE", "Architektur-Impact + Debt-Delta klaeren, bevor gebaut wird"],
                    ["EXECUTE", "Checks rot - bauen/fixen bis gruen (py_compile, tsc, design-lint)"],
                    ["TEST", "verifizieren statt nur rendern - adversarial testen"],
                    ["CLEAN", "aufraeumen, Debt-Register gepflegt halten"],
                    ["BUILD", "stale Artefakte neu bauen (Installer / APK / glasses)"],
                    ["COMMIT", "Loop fertig + ruhig - Commit vorschlagen"],
                    ["DONE", "sauberer Baum, kein offener Workorder"],
                ]
                current = []
                try:
                    _sys.path.insert(0, _os.path.join(
                        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
                    import loop_state
                    current = [{"state": st, "action": ac} for st, ac in (loop_state.transitions() or [])]
                except Exception as e:
                    current = [{"state": "?", "action": "loop_state: %s" % str(e)[:120]}]
                # Declarative config schema: the SINGLE source of truth for every
                # editable knob ("policy is data"). The app renders each control
                # generically and writes it back with saveSettings(nest(path,value)),
                # so a new knob = one entry here, not hand-wiring in two screens. The
                # fixed harness/laws are NOT here - they live read-only in /loop/map.
                ns = s.get("nightshift") or {}
                config_schema = [
                    {"group": "policy", "path": "policy.auto_accept_green", "control": "toggle",
                     "labelKey": "cfg.autoAccept", "value": bool(pol.get("auto_accept_green"))},
                    {"group": "policy", "path": "policy.auto_dispatch_modes", "control": "multi",
                     "labelKey": "cfg.autoModes", "options": ["do", "prepare", "cowork"],
                     "value": pol.get("auto_dispatch_modes") or []},
                    {"group": "policy", "path": "policy.auto_dispatch_priority", "control": "single",
                     "labelKey": "cfg.autoPrio", "options": ["never", "urgent", "high"],
                     "value": pol.get("auto_dispatch_priority") or "never"},
                    {"group": "policy", "path": "policy.chat_configure_roles", "control": "multi",
                     "labelKey": "cfg.chatRoles", "options": ["owner", "operator"],
                     "value": pol.get("chat_configure_roles") or ["owner"]},
                    {"group": "policy", "path": "policy.lane_labels", "control": "labels",
                     "labelKey": "cfg.laneLabels", "keys": ["backlog", "working", "review", "done"],
                     "value": pol.get("lane_labels") or {}},
                    {"group": "night", "path": "nightshift.enabled", "control": "toggle",
                     "labelKey": "cfg.nightEnabled", "value": bool(ns.get("enabled"))},
                    {"group": "night", "path": "nightshift.window", "control": "text",
                     "labelKey": "cfg.nightWindow", "placeholder": "always", "value": ns.get("window") or ""},
                    {"group": "night", "path": "nightshift.max_cards", "control": "number",
                     "labelKey": "cfg.nightMax", "value": ns.get("max_cards", 3)},
                    {"group": "night", "path": "nightshift.idle_minutes", "control": "number",
                     "labelKey": "cfg.nightIdle", "value": ns.get("idle_minutes", 20)},
                ]
                return self._send(200, json.dumps({
                    "nightshift": pm.status(),   # alias key: the PM loop's status
                    "policy": {k: pol.get(k) for k in ("auto_dispatch_modes", "auto_dispatch_priority",
                              "auto_accept_green", "chat_admin_roles", "chat_configure_roles")},
                    "config_schema": config_schema,
                    "repos": (s.get("pm") or {}).get("repos") or [],
                    "default_repo": s.get("default_repo"),
                    "loop_states": [{"state": st, "desc": d} for st, d in loop_states],
                    "loop_current": current,
                }))
            if p == "/dashboard/data":
                import events, sessions
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                m = events.metrics(sessions.list_tracks())
                if user["role"] != "owner":
                    m.pop("settings", None)
                return self._send(200, json.dumps(m))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "live":
                # the card's own glance feed: newest frame while its agent's
                # turn is being screen-recorded (fresh = written in last 20s)
                import sessions, time as _t
                t = sessions.get_track(parts[1])
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, b"not your card", "text/plain")
                fp = os.path.join(t["run_dir"], "live.jpg") if t else ""
                if fp and os.path.exists(fp) and _t.time() - os.path.getmtime(fp) < 20:
                    with open(fp, "rb") as f:
                        return self._send(200, f.read(), "image/jpeg")
                return self._send(404, b"no live frame", "text/plain")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "turns":
                # per-card AI usage: every turn's model, tokens, cost
                import events, sessions
                if user["role"] == "client":
                    t = sessions.get_track(parts[1])
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                turns = [e for e in events.read_events()
                         if e.get("kind") == "turn" and e.get("track") == parts[1]]
                return self._send(200, json.dumps(turns))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "history":
                import sessions
                if user["role"] == "client":
                    t = sessions.get_track(parts[1])
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                return self._send(200, json.dumps(sessions.history(parts[1])))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "transcript":
                # the Paseo-style agent view: every turn's text + tool calls,
                # read straight from the session's Claude Code transcript
                import sessions, claude_sessions
                t = sessions.get_track(parts[1])
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, json.dumps({"error": "not your card"}))
                return self._send(200, json.dumps(claude_sessions.read_transcript_live(t)))
            if len(parts) == 4 and parts[0] == "tracks" and parts[2] == "transcript" and parts[3] == "live":
                # PUSH over the sealed relay: hold the request until the
                # transcript changes (or ~22s), then return the fresh steps + a
                # version token. The phone loops this - real streaming latency
                # without SSE (which can't be relayed). Reuses the e2ee/relay
                # path untouched. 22s < relay REPLY_TIMEOUT (120) and the daemon
                # bridge's _local timeout (115), so the reply always lands.
                import sessions, claude_sessions, time as _t
                t = sessions.get_track(parts[1])
                if not t:
                    return self._send(404, json.dumps({"error": "no such card"}))
                if user["role"] == "client" and t.get("client") != user["name"]:
                    return self._send(403, json.dumps({"error": "not your card"}))
                q = parse_qs(urlparse(self.path).query)
                want = (q.get("v") or [""])[0]
                deadline = _t.time() + 22
                cur = claude_sessions.transcript_version(t)
                while str(cur) == want and _t.time() < deadline:
                    _t.sleep(0.35)
                    cur = claude_sessions.transcript_version(t)
                # DELTA (perf): the client sends how many steps it already holds
                # (`have`); return only the TAIL - new steps plus a small overlap so
                # a late tool_result or the end-of-turn abandoned-relabel landing on a
                # recent step is still picked up. The compute is cheap (~16ms for a
                # full build); the cost was the RELAY payload - a full transcript is
                # 100-227KB re-sent on every token/tool tick. The tail is a few KB.
                # `have` absent/0 -> full transcript (old client + the loop's first
                # call), so this is backward compatible.
                steps = claude_sessions.read_transcript_live(t)
                try:
                    have = int((q.get("have") or ["0"])[0])
                except ValueError:
                    have = 0
                total = len(steps)
                base = max(0, min(have, total) - 12) if have > 0 else 0
                return self._send(200, json.dumps(
                    {"v": str(cur), "base": base, "total": total, "steps": steps[base:]}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "checkpoints":
                import sessions
                t = sessions.get_track(parts[1])
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, json.dumps({"error": "not your card"}))
                return self._send(200, json.dumps(sessions.list_checkpoints(parts[1])))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "attachments":
                import sessions
                t = sessions.get_track(parts[1])
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, json.dumps({"error": "not your card"}))
                out = []
                for fp in (t or {}).get("attachments") or []:
                    try:
                        out.append({"name": os.path.basename(fp),
                                    "size": os.path.getsize(fp) if os.path.exists(fp) else 0})
                    except OSError:
                        pass
                return self._send(200, json.dumps(out))
            if len(parts) == 4 and parts[0] == "tracks" and parts[2] == "attachment":
                import sessions, mimetypes
                t = sessions.get_track(parts[1])
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, b"not your card", "text/plain")
                name = unquote(parts[3])
                # only serve a file the card actually references (no path escape)
                match = next((fp for fp in (t or {}).get("attachments") or []
                             if os.path.basename(fp) == name), None)
                if not match or not os.path.exists(match):
                    return self._send(404, b"no such attachment", "text/plain")
                ctype = mimetypes.guess_type(match)[0] or "application/octet-stream"
                with open(match, "rb") as f:
                    return self._send(200, f.read(), ctype)
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        try:
            import auth
            user = self._user()
            # ---- auth endpoints (public) ----
            if p == "/auth/setup":
                if auth.list_users():
                    return self._send(403, json.dumps({"error": "already set up"}))
                try:
                    auth.create_user(body.get("name", ""), body.get("password", ""), "owner")
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
                sid = auth.login(body["name"], body["password"])
                return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)
            if p == "/auth/register":
                import events, secrets as _s
                reg = events.settings().get("registration") or {}
                code = (body.get("invite") or "").strip()
                if not reg.get("open"):
                    want = reg.get("invite_code") or ""
                    if not want or not code or not _s.compare_digest(code, want):
                        return self._send(403, json.dumps({"error": "valid invite code required"}))
                try:
                    auth.create_user(body.get("name", ""), body.get("password", ""),
                                     reg.get("default_role", "client"))
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
                sid = auth.login(body["name"], body["password"])
                return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)
            if p == "/auth/login":
                sid = auth.login(body.get("name", ""), body.get("password", ""))
                if not sid:
                    return self._send(401, json.dumps({"error": "wrong name or password"}))
                return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)
            if p == "/auth/logout":
                if self._sid():
                    auth.logout(self._sid())
                return self._send_cookie(200, json.dumps({"ok": True}), clear=True)
            if not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            # ---- user management (owner only) ----
            parts = p.strip("/").split("/")
            if parts[0] == "users":
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    if len(parts) == 1:
                        return self._send(200, json.dumps(auth.create_user(
                            body.get("name", ""), body.get("password", ""),
                            body.get("role", "operator"))))
                    name, action = parts[1], parts[2] if len(parts) > 2 else ""
                    if action == "password":
                        auth.set_password(name, body.get("password", ""))
                    elif action == "role":
                        auth.set_role(name, body.get("role", ""))
                    elif action == "tokens":
                        return self._send(200, json.dumps(
                            {"token": auth.issue_token(name, body.get("label", ""))}))
                    elif action == "revoke":
                        auth.revoke_token(name, body.get("token", ""))
                    elif action == "delete":
                        auth.delete_user(name)
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
            if p == "/chat/cancel":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import copilot
                return self._send(200, json.dumps({"cancelled": copilot.cancel(user["name"])}))
            if p == "/tracks/reorder":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import sessions
                ids = body.get("ids") or []
                return self._send(200, json.dumps(sessions.reorder(ids, actor=user["name"])))
            if p == "/relay/pair":
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import relay_client, auth
                try:
                    pay = relay_client.pairing_payload()
                except ValueError as e:   # plain-http relay url: refuse to mint
                    return self._send(400, json.dumps({"error": str(e)}))
                # a fresh device token so the phone authenticates through the
                # encrypted tunnel (carried as Bearer inside the sealed request).
                # Invites bring the teammate's OWN token - minting an owner
                # token there would leave a dangling owner credential per invite.
                if not body.get("invite"):
                    pay["device_token"] = auth.issue_token(user["name"], "phone (relay)")
                return self._send(200, json.dumps(pay))
            if p == "/relay/unpair":
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import relay_client
                return self._send(200, json.dumps(relay_client.unpair()))
            if p == "/sessions/claude/adopt":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import sessions
                try:
                    return self._send(200, json.dumps(sessions.adopt_session(
                        body.get("session_id", ""), body.get("cwd", ""),
                        mode=body.get("mode", "continue"), first=body.get("first", ""),
                        actor=user["name"])))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if p == "/pm/config":
                # owner sets the proactive-loop policy (on/off, autonomy ladder,
                # repos allowlist, timing/caps). Whitelisted keys only.
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import pm, events
                allowed = ("loop_enabled", "autonomy", "repos", "window", "idle_minutes",
                           "replan_minutes", "max_dispatch_per_day", "goal", "plan",
                           "monthly_eur", "quota_turns_per_day")
                merged = dict(events.settings().get("pm") or {})
                for k in allowed:
                    if k in body:
                        merged[k] = body[k]
                if merged.get("autonomy") not in ("notify", "ask", "act"):
                    merged["autonomy"] = "act"
                events.save_settings({"pm": merged})
                return self._send(200, json.dumps(pm._pm()))
            if p == "/pm/consolidate":
                # Phase 3: propose (read-only) or apply (non-destructive) the
                # roll-up of many small cards into 2-5 stream cards per repo.
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import pm
                try:
                    if body.get("mode") == "apply":
                        return self._send(200, json.dumps(pm.apply_consolidation(
                            body.get("repos") or [], actor=user["name"])))
                    return self._send(200, json.dumps(pm.consolidation_proposal(
                        model=body.get("model", ""))))
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)[:300]}))
            if p == "/pm/report":
                # Proactive PM/CTO briefing: tasks-to-goal, prioritized next,
                # token/cost projection grounded in real spend. One model turn.
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import pm
                try:
                    return self._send(200, json.dumps(pm.brief(
                        goal=body.get("goal"), model=body.get("model", ""))))
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)[:300]}))
            if p == "/chat":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import copilot
                text = body.get("text", "").strip()
                if not text:
                    return self._send(400, json.dumps({"error": "text required"}))
                try:
                    return self._send(200, json.dumps(copilot.chat(
                        user["name"], text, role=user["role"], model=body.get("model", ""),
                        thinking=body.get("thinking", ""), attachments=body.get("attachments"),
                        card=body.get("card"))))
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)[:300]}))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "checkpoints" and parts[2] == "restore":
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import checkpoints
                try:
                    checkpoints.restore(parts[1], actor=user["name"])
                    return self._send(200, json.dumps({"restored": parts[1]}))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            if len(parts) == 3 and parts[0] == "connectors" and parts[2] == "rollback":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import connectors, events
                try:
                    prev = connectors.rollback(parts[1])
                    events.emit("connector", "-", action="rollback", name=parts[1], actor=user["name"])
                    return self._send(200, json.dumps({"restored": prev}))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            if len(parts) == 3 and parts[0] == "connectors" and parts[2] == "run":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import connectors
                try:
                    made = connectors.run_connector(parts[1], actor=user["name"])
                    return self._send(200, json.dumps({"cards": len(made)}))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            if len(parts) == 3 and parts[0] == "debt" and parts[2] == "fix":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import debt, sessions, events
                item = next((d for d in debt.DEBT if d["id"] == parts[1]), None)
                if not item:
                    return self._send(404, json.dumps({"error": "unknown debt id"}))
                repo = events.settings().get("default_repo")
                t = sessions.new_track(repo, "debt-" + item["id"], debt.fix_task(item),
                                       lane="backlog", actor=user["name"], priority="high")
                return self._send(200, json.dumps(t))
            if p in ("/import/jira", "/import/url"):
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import importers
                try:
                    if p.endswith("jira"):
                        made = importers.jira_import(body.get("jql", ""), actor=user["name"])
                        return self._send(200, json.dumps({"imported": len(made), "ids": made}))
                    pr = importers.url_import(body.get("url", ""), client=body.get("client", ""),
                                              due=body.get("due", ""), actor=user["name"])
                    return self._send(200, json.dumps(pr))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            # ---- processes: propose -> adjust -> accept into cards ----
            if p == "/processes/new":
                import processes
                req = body.get("request")
                if not req:
                    return self._send(400, json.dumps({"error": "request required"}))
                client = user["name"] if user["role"] == "client" else body.get("client", "")
                return self._send(200, json.dumps(processes.create(
                    req, client=client, due=body.get("due", ""), actor=user["name"])))
            parts = p.strip("/").split("/")
            if parts[0] == "processes" and len(parts) >= 3:
                import processes, events
                pid = parts[1]
                try:
                    if parts[2] == "step":
                        act = body.get("action")
                        idx = int(body.get("idx", -1))
                        if act == "accept":
                            repo = body.get("repo") or events.settings().get("default_repo")
                            if not repo:
                                return self._send(400, json.dumps({"error": "no default_repo preset"}))
                            return self._send(200, json.dumps(
                                processes.accept_step(pid, idx, repo, actor=user["name"])))
                        if act == "update":
                            return self._send(200, json.dumps(
                                processes.update_step(pid, idx, body.get("patch") or {})))
                        if act == "remove":
                            return self._send(200, json.dumps(processes.remove_step(pid, idx)))
                        if act == "add":
                            return self._send(200, json.dumps(processes.add_step(
                                pid, body.get("title", "new step"), body.get("mode", "do"))))
                        if act == "accept_all":
                            repo = body.get("repo") or events.settings().get("default_repo")
                            pr = processes.get(pid)
                            for i in range(len(pr["steps"])):
                                if not pr["steps"][i].get("track"):
                                    pr = processes.accept_step(pid, i, repo, actor=user["name"])
                            return self._send(200, json.dumps(pr))
                    return self._send(404, json.dumps({"error": "?"}))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if p == "/control/teach/start":
                from teach import TeachSession
                with _ctl_lock:
                    if _ctl["teach"] and not _ctl["teach"].stopped.is_set():
                        return self._send(409, json.dumps({"error": "already recording",
                                                           "id": _ctl["teach"].rid}))
                    s = TeachSession(body.get("title") or "unnamed task").start()
                    _ctl["teach"] = s
                return self._send(200, json.dumps({"id": s.rid}))
            if p == "/control/teach/stop":
                with _ctl_lock:
                    s = _ctl["teach"]
                if not s:
                    return self._send(404, json.dumps({"error": "not recording"}))
                rid = s.stop()
                return self._send(200, json.dumps({"id": rid}))
            if p == "/control/distill":
                rid = os.path.basename(body.get("id") or "")
                if not rid:
                    return self._send(400, json.dumps({"error": "id required"}))
                from distill import distill
                _bg("distill:" + rid, lambda: distill(rid))
                return self._send(200, json.dumps({"started": rid}))
            if p == "/control/demo":
                import swarm
                _bg("demo", swarm.browser_demo)
                return self._send(200, json.dumps({"started": "browser-demo"}))
            if p == "/settings":
                import events
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                rel = body.get("relay")
                if isinstance(rel, dict) and rel.get("url"):
                    import relay_client
                    if relay_client.insecure_url(rel["url"]):
                        return self._send(400, json.dumps({"error":
                            "relay url must be https:// (or http://localhost for "
                            "local testing) - pairing links carry a device token "
                            "and must not cross the network unencrypted"}))
                return self._send(200, json.dumps(events.save_settings(body, actor=user["name"])))
            if p == "/presence":
                # Client heartbeat (Phase 2.1): who is here, is the app in the
                # foreground, and which card is on screen. Drives the 3-tier
                # notify policy in notify.should_push - the daemon stays silent
                # about a card the owner is already looking at. Every role may
                # report its own presence; it is about this connection only.
                import presence
                return self._send(200, json.dumps(presence.record(
                    user["name"], body.get("device", "app"),
                    focused_card=body.get("focused_card"),
                    app_visible=bool(body.get("app_visible", True)),
                    activity_at=body.get("last_activity_at"))))
            if p == "/push/register":
                # the phone announces its FCM token (arrives through the E2EE
                # relay like every call); the daemon then pushes sealed data
                # messages to exactly this device
                import events
                tok = (body.get("token") or "").strip()
                if not tok:
                    return self._send(400, json.dumps({"error": "token required"}))
                events.save_settings({"push": {"fcm_token": tok}}, actor=user["name"])
                return self._send(200, json.dumps({"registered": True}))
            if p == "/nightshift/plan":   # alias: run the PM plan now, file its cards
                import pm
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                _bg("pm:plan", lambda: pm.make_plan(actor=user["name"]))
                return self._send(200, json.dumps({"planning": True,
                                                   "repos": pm._pm().get("repos") or []}))
            # --- orchestrator control ---
            if p == "/tracks/new":
                import sessions, events
                repo = body.get("repo") or events.settings().get("default_repo")
                branch = body.get("branch"); task = body.get("task")
                if task and not branch:   # preset flow: task alone is enough
                    # ASCII-ONLY slug. isalnum() alone is Unicode-true, so a task
                    # like "Dashboard zu überfüllt" put umlauts into the git ref;
                    # on Windows (cp1252 consoles, mojibake in tracks.json) that
                    # produced a branch git never created - the card then hit
                    # WinError 267 (worktree cwd invalid) on every steer.
                    _de = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
                    _t = task.lower().translate(_de)
                    branch = "req-" + "".join(
                        ch if (ch.isascii() and ch.isalnum()) else "-" for ch in _t)[:24]
                if not (repo and branch and task):
                    return self._send(400, json.dumps({"error": "task required (+ repo unless default_repo is set in settings)"}))
                if not sessions.is_git_repo(repo):
                    return self._send(400, json.dumps(
                        {"error": "repo is not a git repository: " + repo}))
                lane = body.get("lane", "working")
                client = user["name"] if user["role"] == "client" else body.get("client", "")
                driver = body.get("driver", "claude")
                if user["role"] == "client":
                    driver = "claude"   # clients don't pick desktop-driving agents
                model = body.get("model", "")
                attachments = body.get("attachments")
                if lane == "backlog":   # filing a request is instant, no session
                    return self._send(200, json.dumps(sessions.new_track(
                        repo, branch, task, body.get("perm", sessions.DEFAULT_PERM),
                        lane="backlog", client=client, value=body.get("value"),
                        driver=driver, actor=user["name"],
                        priority=body.get("priority", "medium"),
                        due=body.get("due", ""), model=model, attachments=attachments,
                        project_id=body.get("project_id"),
                        description=body.get("description", ""),
                        billing=body.get("billing", "fixed"), rate=body.get("rate"))))
                def go():
                    sessions.new_track(repo, branch, task,
                                       body.get("perm", sessions.DEFAULT_PERM),
                                       lane="working", client=client,
                                       value=body.get("value"),
                                       driver=driver, actor=user["name"],
                                       priority=body.get("priority", "medium"),
                                       due=body.get("due", ""), model=model, attachments=attachments,
                                       project_id=body.get("project_id"),
                                       description=body.get("description", ""),
                                       billing=body.get("billing", "fixed"), rate=body.get("rate"))
                _bg("track:new:" + branch, go)
                return self._send(200, json.dumps({"started": branch}))
            if p == "/projects":
                import projects
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    return self._send(200, json.dumps(projects.new_project(
                        body.get("name"), body.get("billing"), client=body.get("client", ""),
                        fixed_price=body.get("fixed_price"), rate=body.get("rate"),
                        actor=user["name"])))
                except (ValueError, TypeError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "projects" and parts[2] == "update":
                import projects
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    return self._send(200, json.dumps(
                        projects.update_project(parts[1], body, actor=user["name"])))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "projects" and parts[2] == "delete":
                import projects
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    return self._send(200, json.dumps(
                        projects.delete_project(parts[1], actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "archive":
                import sessions
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                try:
                    return self._send(200, json.dumps(sessions.archive_track(
                        parts[1], on=bool(body.get("on", True)), actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "fork":
                import sessions
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                try:
                    return self._send(200, json.dumps(sessions.fork_track(
                        parts[1], from_ref=body.get("ref", ""), actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "delete":
                import sessions
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    return self._send(200, json.dumps(sessions.delete_track(
                        parts[1], actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "update":
                import sessions
                if user["role"] == "client":
                    t = sessions.get_track(parts[1])
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                    body.pop("autopilot", None)   # autopilot opt-in is owner/operator only
                try:
                    return self._send(200, json.dumps(
                        sessions.update_track(parts[1], body, actor=user["name"])))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "rewind":
                import sessions
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                try:
                    return self._send(200, json.dumps(
                        sessions.rewind_files(parts[1], body.get("commit", ""), actor=user["name"])))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "attach":
                import sessions
                tid = parts[1]
                if user["role"] == "client":
                    t = sessions.get_track(tid)
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                try:
                    return self._send(200, json.dumps(
                        sessions.add_attachments(tid, body.get("attachments"), actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 4 and parts[0] == "tracks" and parts[2] == "attach" \
                    and parts[3] == "remove":
                import sessions
                tid = parts[1]
                if user["role"] == "client":
                    t = sessions.get_track(tid)
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                try:
                    return self._send(200, json.dumps(
                        sessions.remove_attachment(tid, body.get("name", ""), actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "steer":
                import sessions
                tid = parts[1]
                text = body.get("text")
                if not text:
                    return self._send(400, json.dumps({"error": "text required"}))
                if user["role"] == "client":
                    t = sessions.get_track(tid)
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                actor = user["name"]
                model = body.get("model", "")
                thinking = body.get("thinking", "")          # level string, "" = off
                attachments = body.get("attachments")
                # clients steer their own card but can't escalate the permission mode
                mode = body.get("mode") if user["role"] != "client" else None
                _bg("track:steer:" + tid, lambda: sessions.steer(
                    tid, text, actor=actor, model=model, thinking=thinking,
                    attachments=attachments, mode=mode))
                return self._send(200, json.dumps({"started": tid}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "answer":
                # Phase 2.4: the owner picks an option on the worker's pending
                # question. Backgrounded like /steer - it RUNS a turn (the
                # worker continues with the decision), so holding the request
                # would block the phone for the length of that turn.
                import sessions
                tid = parts[1]
                if user["role"] == "client":
                    t = sessions.get_track(tid)
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                t = sessions.get_track(tid)
                if not t or not t.get("question"):
                    return self._send(409, json.dumps({"error": "no pending question"}))
                # validate BEFORE backgrounding, so a bad/stale answer reports
                # the reason instead of failing invisibly on a worker thread
                import ask
                rid = body.get("request_id", "")
                if rid and rid != (t["question"] or {}).get("id"):
                    return self._send(409, json.dumps(
                        {"error": "this question was already answered or replaced"}))
                picks, err = ask.validate_answers(t["question"], body.get("answers") or {})
                if err:
                    return self._send(400, json.dumps({"error": err}))
                actor = user["name"]
                answers = body.get("answers") or {}
                _bg("track:answer:" + tid, lambda: sessions.answer_question(
                    tid, answers, request_id=rid, actor=actor))
                return self._send(200, json.dumps({"started": tid, "answered": True}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "cancel":
                import sessions
                tid = parts[1]
                if user["role"] == "client":
                    t = sessions.get_track(tid)
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                return self._send(200, json.dumps(sessions.cancel_turn(tid, actor=user["name"])))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "lane":
                import sessions
                tid = parts[1]
                lane = body.get("lane")
                actor = user["name"]
                if lane == "working":
                    _bg("track:dispatch:" + tid,
                        lambda: sessions.move_lane(tid, "working", actor=actor))
                    return self._send(200, json.dumps({"started": tid}))
                if lane in ("review", "done"):
                    # Gate (subprocess, up to 600s) + merge + deploy hook. Held
                    # inline this blocked the HTTP request for minutes, which is
                    # what made an accept feel like invisible background work.
                    # Background it like ->working; the card carries status
                    # "gating" and every outcome is reported on the card, in the
                    # chat (sessions._say_card) and by push.
                    _bg("track:gate:" + tid,
                        lambda: sessions.move_lane(tid, lane, actor=actor))
                    return self._send(200, json.dumps({"started": tid, "gating": True}))
                return self._send(200, json.dumps(sessions.move_lane(tid, lane, actor=actor)))
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

def _tls_config():
    """Resolve the daemon's TLS material: env (HELMDECK_TLS_CERT/KEY) beats
    settings.tls {cert,key,port} beats auto-detected daemon/certs/tls.crt+key
    (what tools/make_tls_cert.py writes). Returns (cert, key, port) or
    (None, None, port) when TLS is not configured."""
    import events
    t = events.settings().get("tls") or {}
    cert = os.environ.get("HELMDECK_TLS_CERT") or t.get("cert") or ""
    key = os.environ.get("HELMDECK_TLS_KEY") or t.get("key") or ""
    if not (cert and key):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs")
        c, k = os.path.join(base, "tls.crt"), os.path.join(base, "tls.key")
        if os.path.isfile(c) and os.path.isfile(k):
            cert, key = c, k
    tls_port = int(os.environ.get("HELMDECK_TLS_PORT") or t.get("port") or 8443)
    return (cert, key, tls_port) if (cert and key) else (None, None, tls_port)


def _hydrate_windows_path():
    """A daemon launched from Git-bash inherits a MinGW-only PATH that LACKS the
    standard Windows dirs, so `py`, `cmd`, `powershell` and friends are not found.
    The merge gate (`py ... run_gate.py`, run via cmd.exe) then fails with "'py' is
    not recognized" even though the gate itself passes - the card looks like it has
    a code bug when the daemon simply can't invoke the gate. Ensure the core Windows
    dirs + this interpreter's dir are on PATH so anything the daemon (or a driver it
    spawns, which inherits os.environ) shells out to resolves, regardless of how the
    daemon was launched. Append (don't prepend) so a driver's own toolchain still
    wins. Paseo adoption Phase 4.4. No-op off Windows / when already present."""
    if os.name != "nt":
        return
    import sys
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    want = [os.path.join(root, "System32"), root,
            os.path.join(root, "System32", "WindowsPowerShell", "v1.0"),
            os.path.dirname(sys.executable)]
    parts = os.environ.get("PATH", "").split(os.pathsep)
    have = {p.lower() for p in parts if p}
    add = [d for d in want if d and d.lower() not in have and os.path.isdir(d)]
    if add:
        os.environ["PATH"] = os.pathsep.join(parts + add)
        print("PATH: hydrated with Windows dirs (%s) - gate/tools now resolve" %
              ", ".join(os.path.basename(d) or d for d in add), flush=True)


def _hydrate_registry_env():
    """Windows counterpart of Paseo's inheritLoginShellEnv (Paseo captures the
    LOGIN-SHELL env on mac/linux and explicitly SKIPS win32 - login-shell-env.ts
    throws reason:'win32'). On Windows the durable place users and installers
    declare JAVA_HOME, ANDROID_HOME and PATH additions is the REGISTRY
    environment (machine + user). A daemon launched from git-bash or a GUI can
    miss those (var set after login; launcher stripped the env) - and then
    every gradle/adb build inside a card dies on 'JAVA_HOME is not set' even
    though the same build works in the owner's own terminal. Merge at start:
    variables only when absent (a genuinely inherited value wins), PATH
    entries APPENDED (the inherited toolchain order wins). Read via winreg
    (stdlib) - NEVER by shelling to powershell, which is not guaranteed to be
    on PATH (this very dev box lacks it). Paseo adoption Phase 4.4."""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return

    def read_key(root, subkey):
        vals = {}
        try:
            with winreg.OpenKey(root, subkey) as k:
                i = 0
                while True:
                    try:
                        name, val, typ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if typ in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(val, str):
                        vals[name] = val
        except OSError:
            pass
        return vals

    machine = read_key(winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
    user = read_key(winreg.HKEY_CURRENT_USER, "Environment")
    merged = dict(machine)
    merged.update(user)                      # user overrides machine, like Windows does
    added = []
    # 1) plain variables first, so PATH entries like %JAVA_HOME%\bin expand next
    for name, val in merged.items():
        if name.upper() == "PATH":
            continue
        if name not in os.environ:          # os.environ is case-insensitive on nt
            os.environ[name] = os.path.expandvars(val)
            added.append(name)
    # 2) PATH: append registry entries the launcher dropped
    have = {p.lower().rstrip("\\") for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    extra = []
    for src in (machine, user):
        for key, val in src.items():
            if key.upper() != "PATH":
                continue
            for p in val.split(os.pathsep):
                p = os.path.expandvars(p.strip())
                if p and p.lower().rstrip("\\") not in have and os.path.isdir(p):
                    extra.append(p)
                    have.add(p.lower().rstrip("\\"))
    if extra:
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(extra)
        added.append("PATH+%d" % len(extra))
    if added:
        print("ENV: hydrated from registry (%s) - build env present regardless of launcher"
              % ", ".join(sorted(added)), flush=True)


def _take_singleton_lock(port):
    """One daemon per machine. A restart used to race the old instance: the new
    process couldn't bind the port until the old one died, and in that gap the
    RELAY reverse-tunnel poll dropped - the phone showed "paired but takes very
    long" until a poll re-established. So on start we cleanly evict a prior
    daemon (pidfile + tree-kill) and wait for the port to actually free before
    binding, making restart deterministic instead of a bind race."""
    import socket, subprocess, time, signal
    pidfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon.pid")

    def _kill(pid, why):
        if not pid or pid == os.getpid():
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print("SINGLETON: evicted %s pid %d - taking over relay/port %d." % (why, pid, port), flush=True)
        except Exception:
            pass   # already gone

    def _pids_on_port():
        """Every PID LISTENING on the port. The pidfile alone is NOT enough: Python's
        HTTPServer sets SO_REUSEADDR, so on Windows several daemons can silently
        double-bind the same port and stale ones (old code, no reconciler) keep
        serving. Kill ALL of them so exactly one daemon owns the port - the leak
        Paseo avoids by never using SO_REUSEADDR (a 2nd server fails EADDRINUSE)."""
        found = set()
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                p = line.split()
                if len(p) >= 5 and p[0].upper() == "TCP" and p[3].upper() == "LISTENING" \
                        and p[1].endswith(":%d" % port):
                    try:
                        found.add(int(p[4]))
                    except ValueError:
                        pass
        except Exception:
            pass
        found.discard(os.getpid())
        return found

    try:
        old = int(open(pidfile).read().strip())
    except Exception:
        old = None
    _kill(old, "prior daemon (pidfile)")
    for pid in _pids_on_port():          # + any stale daemon double-bound to the port
        _kill(pid, "stale daemon on port")
    # wait for the port to free (old listener socket releasing), up to ~5s
    for _ in range(50):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            break
        except OSError:
            s.close()
            time.sleep(0.1)
    try:
        open(pidfile, "w").write(str(os.getpid()))
        import atexit
        atexit.register(lambda: os.path.exists(pidfile) and os.remove(pidfile))
    except Exception:
        pass


def serve(port=8140):
    _hydrate_windows_path()      # bash-launched daemons lack Windows dirs on PATH -> gate/py/cmd fail
    _hydrate_registry_env()      # + JAVA_HOME/ANDROID_HOME/user-PATH from the registry (build env)
    _take_singleton_lock(port)   # evict a prior daemon so the relay poll never races a restart
    import db
    # role="daemon": loading the store AS THE DAEMON structurally devalues any
    # persisted 'running'/'gating' (db._devalue_persisted_running - the old
    # serve()-side sweep_zombies call, now part of the load path itself).
    db.init(role="daemon")
    import drivers, atexit
    reaped = drivers.reap_orphans()   # tree-kill agent processes a prior daemon left behind
    if reaped:
        print("DRIVERS: reaped %d orphan agent process tree(s) from a previous run." % reaped)
    drivers.start_idle_sweeper()      # reap idle worker sessions (Paseo idle TTL)
    atexit.register(drivers.shutdown_all)   # clean stop: don't orphan worker trees
    import sessions
    reclaimed = sessions.sweep_worktrees()  # WORKTREE RECLAMATION backstop: merged+clean card trees left
    if reclaimed:                            # by pre-reclaim builds (the "System too full" pile-up). Paseo
        print("SESSIONS: reclaimed %d merged worktree(s)" % reclaimed)  # stays clean by having none at all.
    sessions.start_zombie_reconciler()   # + CONTINUOUS reconcile (Paseo 15s-sweep parity): catch a card
                                         # stuck at status=running with no session BETWEEN restarts, live
    sessions.apply_board_directives()    # one-shot board-data patches shipped as repo data
    sessions.start_background_watcher()  # auto-continue cards whose background task finished
    import auth, events
    if auth.migrate_legacy(events.settings().get("users")):
        print("AUTH: legacy token-users migrated to users.json; old tokens still work as device tokens.")
        print("      Set real passwords via the Users panel (owner).")
    if not auth.list_users():
        print("AUTH: no users yet - the web app will show the create-owner setup screen.")
    import processes, connectors, relay_client
    processes.start_chain_poller()
    connectors.start_scheduler()
    relay_client.start(port)   # reverse tunnel for mobile - idle until settings.relay is set
    import pm
    pm.start_loop()            # the single proactive loop - no-op until settings.pm.loop_enabled
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
                  "(tools/make_tls_cert.py) or remove them to serve http again." % e,
                  flush=True)
    print("HelmDeck review server on http://localhost:%d  (APK pulls /runs, /live.jpg)" % port)
    try:
        ThreadingHTTPServer((bind, port), H).serve_forever()
    finally:
        drivers.shutdown_all()   # tree-kill live worker sessions on stop (Ctrl-C included)

if __name__ == "__main__":
    serve()
