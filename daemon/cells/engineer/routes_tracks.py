# -*- coding: utf-8 -*-
"""Track CRUD/read routes - 14th slice of server.py's dispatch-table split
(see routes_auth.py for the pattern/rationale). GET /tracks (board list),
GET /tracks/<id>/live (per-card glance frame), /turns, /history, /transcript
(+/live long-poll), /checkpoints, /attachments (+/attachment/<name>), and
POST /tracks/reorder, /tracks/new, /<id>/archive, /fork, /fork-chat, /delete,
/update, /rewind, /attach (+/attach/remove).

The gate/dispatch-critical actions (steer, answer, cancel, lane, the live
transcript SSE stream) are deliberately kept in routes_track_actions.py
instead - see that module's docstring for why they were split out.

Path-param routes (parts[0]=="tracks", variable tail) keep their guard
inline in server.py (same precedent as routes_checkpoints.py's
diff/restore) - only the route BODY moves here, verbatim. Bodies are
byte-identical to the inline blocks they replace.
"""
import json, os
from urllib.parse import unquote


def tracks_list_get(self, user):
    import sessions
    # present(): stored 'running' is never believed on the way OUT -
    # only a live turn (drivers.turn_active) may render a spinner.
    ts = [sessions.present(t) for t in sessions.list_tracks()]
    if user["role"] == "client":   # clients see only their own cards
        ts = [t for t in ts if t.get("client") == user["name"]]
    return self._send(200, json.dumps(ts))


def tracks_live_get(self, user, tid):
    # the card's own glance feed: newest frame while its agent's
    # turn is being screen-recorded (fresh = written in last 20s)
    import sessions, time as _t
    t = sessions.get_track(tid)
    if user["role"] == "client" and (not t or t.get("client") != user["name"]):
        return self._send(403, b"not your card", "text/plain")
    fp = os.path.join(t["run_dir"], "live.jpg") if t else ""
    if fp and os.path.exists(fp) and _t.time() - os.path.getmtime(fp) < 20:
        with open(fp, "rb") as f:
            return self._send(200, f.read(), "image/jpeg")
    return self._send(404, b"no live frame", "text/plain")


def tracks_turns_get(self, user, tid):
    # per-card AI usage: every turn's model, tokens, cost
    import events, sessions
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    turns = [e for e in events.read_events()
             if e.get("kind") == "turn" and e.get("track") == tid]
    return self._send(200, json.dumps(turns))


def tracks_history_get(self, user, tid):
    import sessions
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(sessions.history(tid)))


def tracks_transcript_get(self, user, tid):
    # the Paseo-style agent view: every turn's text + tool calls,
    # read straight from the session's Claude Code transcript
    import sessions, claude_sessions
    t = sessions.get_track(tid)
    if user["role"] == "client" and (not t or t.get("client") != user["name"]):
        return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(claude_sessions.read_transcript_live(t)))


def tracks_transcript_live_get(self, user, tid):
    # PUSH over the sealed relay: hold the request until the
    # transcript changes (or ~22s), then return the fresh steps + a
    # version token. The phone loops this - real streaming latency
    # without SSE (which can't be relayed). Reuses the e2ee/relay
    # path untouched. 22s < relay REPLY_TIMEOUT (120) and the daemon
    # bridge's _local timeout (115), so the reply always lands.
    import sessions, claude_sessions, time as _t
    from urllib.parse import parse_qs, urlparse
    t = sessions.get_track(tid)
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


def tracks_checkpoints_get(self, user, tid):
    import sessions
    t = sessions.get_track(tid)
    if user["role"] == "client" and (not t or t.get("client") != user["name"]):
        return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(sessions.list_checkpoints(tid)))


def tracks_attachments_get(self, user, tid):
    import sessions
    t = sessions.get_track(tid)
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


def tracks_attachment_get(self, user, tid, name):
    import sessions, mimetypes
    t = sessions.get_track(tid)
    if user["role"] == "client" and (not t or t.get("client") != user["name"]):
        return self._send(403, b"not your card", "text/plain")
    name = unquote(name)
    # only serve a file the card actually references (no path escape)
    match = next((fp for fp in (t or {}).get("attachments") or []
                 if os.path.basename(fp) == name), None)
    if not match or not os.path.exists(match):
        return self._send(404, b"no such attachment", "text/plain")
    ctype = mimetypes.guess_type(match)[0] or "application/octet-stream"
    with open(match, "rb") as f:
        return self._send(200, f.read(), ctype)


def tracks_reorder_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    import sessions
    ids = body.get("ids") or []
    return self._send(200, json.dumps(sessions.reorder(ids, actor=user["name"])))


def tracks_new_post(self, user, body):
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
    import server
    server._bg("track:new:" + branch, go)
    return self._send(200, json.dumps({"started": branch}))


def tracks_archive_post(self, user, body, tid):
    import sessions
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    try:
        return self._send(200, json.dumps(sessions.archive_track(
            tid, on=bool(body.get("on", True)), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_fork_post(self, user, body, tid):
    import sessions
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    try:
        return self._send(200, json.dumps(sessions.fork_track(
            tid, from_ref=body.get("ref", ""), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_forkchat_post(self, user, body, tid):
    # split a crowded card's CONVERSATION into a new card (keeps
    # context, unlike /fork which forks code at a ref with a fresh
    # session - see sessions.fork_conversation).
    import sessions
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    try:
        return self._send(200, json.dumps(sessions.fork_conversation(
            tid, first=body.get("first", ""), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_delete_post(self, user, body, tid):
    import sessions
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    try:
        return self._send(200, json.dumps(sessions.delete_track(
            tid, actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_update_post(self, user, body, tid):
    import sessions, events
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
        body.pop("autopilot", None)   # autopilot opt-in is owner/operator only
        body.pop("driver", None)      # capability grant (GUI/desktop control) - admin only
    elif "driver" in body:
        admin_roles = (events.settings().get("policy") or {}).get(
            "chat_admin_roles", ["owner", "operator"])
        if user["role"] not in admin_roles:
            return self._send(403, json.dumps(
                {"error": "changing a card's driver requires: " + ", ".join(admin_roles)}))
    try:
        return self._send(200, json.dumps(
            sessions.update_track(tid, body, actor=user["name"])))
    except (RuntimeError, ValueError) as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_rewind_post(self, user, body, tid):
    import sessions
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    try:
        return self._send(200, json.dumps(
            sessions.rewind_files(tid, body.get("commit", ""), actor=user["name"])))
    except (RuntimeError, ValueError) as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_attach_post(self, user, body, tid):
    import sessions
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    try:
        return self._send(200, json.dumps(
            sessions.add_attachments(tid, body.get("attachments"), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_attach_remove_post(self, user, body, tid):
    import sessions
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    try:
        return self._send(200, json.dumps(
            sessions.remove_attachment(tid, body.get("name", ""), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


GET_ROUTES = {
    "/tracks": tracks_list_get,
}
POST_ROUTES = {
    "/tracks/reorder": tracks_reorder_post,
    "/tracks/new": tracks_new_post,
}
