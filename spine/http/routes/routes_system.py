# -*- coding: utf-8 -*-
"""System/ops routes - Nth slice of server.py's dispatch-table split (see
routes_auth.py for the pattern/rationale). GET: /presence, /sessions/claude,
/ops/harness/version/<kind>/<name> (path-param, guard stays inline), /history,
/dashboard/data. POST: /presence, /push/register, /debt/<id>/fix (path-param,
guard stays inline), /import/jira|url, /harness, /nightshift/plan, and the
/processes/<id>/step sub-router (path-param, guard stays inline per the
routes_checkpoints.py precedent). Bodies are byte-identical to the inline
blocks they replace.
"""
import json


def presence_get(self, user):
    # who the daemon thinks is here (diagnostic for the notify
    # policy: "why didn't my phone buzz?" has a checkable answer)
    from spine.comms import presence
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    return self._send(200, json.dumps(presence.snapshot()))


def sessions_claude_get(self, user):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from spine.agent import claude_sessions
    return self._send(200, json.dumps(claude_sessions.list_sessions()))


def harness_version_get(self, user, kind, name):
    # /ops/harness/version/<kind>/<name>?id=<vid> - the bytes of one
    # archived version, so the owner can read a prior brief before
    # deciding to roll back to it.
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.registry import harness
    from urllib.parse import parse_qs, urlparse
    vid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
    txt = harness.version_text(kind, name, vid)
    if txt is None:
        return self._send(404, json.dumps({"error": "Version nicht gefunden"}))
    return self._send(200, json.dumps({"id": vid, "text": txt}, ensure_ascii=False))


def history_get(self, user):
    # the git audit trail: main line + every card branch's commits.
    import subprocess
    from cells.engineer import sessions
    from spine.storage import events
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
            bits = line.split("")
            if len(bits) >= 4:
                out.append({"h": bits[0], "msg": bits[1][:100],
                            "author": bits[2], "date": bits[3]})
        return out
    fmt = "--pretty=format:%h%s%an%ad"
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


def dashboard_data_get(self, user):
    from spine.storage import events
    from cells.engineer import sessions
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    m = events.metrics(sessions.list_tracks())
    if user["role"] != "owner":
        m.pop("settings", None)
    return self._send(200, json.dumps(m))


def presence_post(self, user, body):
    # Client heartbeat (Phase 2.1): who is here, is the app in the
    # foreground, and which card is on screen. Drives the 3-tier
    # notify policy in notify.should_push - the daemon stays silent
    # about a card the owner is already looking at. Every role may
    # report its own presence; it is about this connection only.
    from spine.comms import presence
    return self._send(200, json.dumps(presence.record(
        user["name"], body.get("device", "app"),
        focused_card=body.get("focused_card"),
        app_visible=bool(body.get("app_visible", True)),
        activity_at=body.get("last_activity_at"))))


def push_register_post(self, user, body):
    # the phone announces its FCM token (arrives through the E2EE
    # relay like every call); the daemon then pushes sealed data
    # messages to exactly this device
    from spine.storage import events
    tok = (body.get("token") or "").strip()
    if not tok:
        return self._send(400, json.dumps({"error": "token required"}))
    events.save_settings({"push": {"fcm_token": tok}}, actor=user["name"])
    return self._send(200, json.dumps({"registered": True}))


def nightshift_plan_post(self, user, body):
    # alias: run the PM plan now, file its cards
    from cells.pm import pm
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.http.server import _bg
    _bg("pm:plan", lambda: pm.make_plan(actor=user["name"]))
    return self._send(200, json.dumps({"planning": True,
                                       "repos": pm._pm().get("repos") or []}))


def harness_post(self, user, body):
    # Owner edits an agent brief or a settings layer. Validated
    # against ops/harness/schema/*.schema.json BEFORE the write, the
    # replaced file archived so the edit is revertable, and the
    # change appended to the audit log.
    #
    # The rejection is deliberately LOUD (400 with the reason). The
    # read path in harness.py is total and falls back silently by
    # design - a typo may never strand a card - but that same
    # silence at write time would let the owner save a broken brief,
    # see no error, and have every worker quietly keep running the
    # old text. So: forgiving at spawn, strict at save.
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.registry import harness
    from spine.storage import events
    kind = body.get("kind")
    name = body.get("name") or ""
    if kind not in ("agents", "settings"):
        return self._send(400, json.dumps({"error": "kind muss 'agents' oder 'settings' sein"}))
    try:
        vid = body.get("restore")
        if vid:
            res = harness.restore(kind, name, vid, actor=user["name"])
        elif kind == "agents":
            res = harness.write_agent(name, body.get("text") or "", actor=user["name"])
        else:
            res = harness.write_settings(name, body.get("text") or "", actor=user["name"])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
    # `target`, NOT `kind`: emit()'s own first positional parameter is
    # named kind, so passing kind= here raised TypeError AFTER the file
    # had already been written - a changed brief with no audit row and
    # a 500 at the client. Caught by exercising the endpoint, not by
    # reading it.
    events.emit("harness", "-", action=("restore" if body.get("restore") else "write"),
                target=kind, name=name, actor=user["name"],
                path=res.get("path"), sha256=(res.get("sha256") or "")[:16],
                kept_version=res.get("kept_version"), validator=res.get("validator"),
                restored=body.get("restore") or "")
    # the fresh document back, so the editor re-renders the preview
    # (argv, hashes, hook matrix) from the file that is now on disk
    return self._send(200, json.dumps(dict(res, document=harness.document()),
                                      ensure_ascii=False))


def debt_fix_post(self, user, body, did):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from spine.registry import debt
    from cells.engineer import sessions
    from spine.storage import events
    item = next((d for d in debt.DEBT if d["id"] == did), None)
    if not item:
        return self._send(404, json.dumps({"error": "unknown debt id"}))
    repo = events.settings().get("default_repo")
    t = sessions.new_track(repo, "debt-" + item["id"], debt.fix_task(item),
                           lane="backlog", actor=user["name"], priority="high")
    return self._send(200, json.dumps(t))


def import_post(self, user, body, p):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from spine.ops import importers
    try:
        if p.endswith("jira"):
            made = importers.jira_import(body.get("jql", ""), actor=user["name"])
            return self._send(200, json.dumps({"imported": len(made), "ids": made}))
        pr = importers.url_import(body.get("url", ""), client=body.get("client", ""),
                                  due=body.get("due", ""), actor=user["name"])
        return self._send(200, json.dumps(pr))
    except Exception as e:
        return self._send(400, json.dumps({"error": str(e)[:300]}))


def processes_sub_post(self, user, body, pid, step):
    # step == parts[2] of /processes/<pid>/<step>; only "step" is a real
    # action, anything else falls through to the same 404 the original
    # inline try-block produced (kept verbatim, including the try scope).
    from cells.process import processes
    from spine.storage import events
    try:
        if step == "step":
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


GET_ROUTES = {
    "/presence": presence_get,
    "/sessions/claude": sessions_claude_get,
    "/history": history_get,
    "/dashboard/data": dashboard_data_get,
}
POST_ROUTES = {
    "/presence": presence_post,
    "/push/register": push_register_post,
    "/harness": harness_post,
    "/nightshift/plan": nightshift_plan_post,
}
