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


def _client_safe(steps, user):
    """A `client`-role user must never see Henry's card-scoped chat: it
    carries board-wide context (other cards, capacity, prices) a client has
    no business reading. `/chat` itself is already owner/operator-only
    (routes_copilot.py), so this filter is the only place a client could
    otherwise see Henry - applied to every transcript read, not just steps
    already on disk (byKind steps land here from cells/copilot/copilot.py's
    card-scoped fold)."""
    if user.get("role") != "client":
        return steps
    return [s for s in steps if s.get("byKind") != "henry" and s.get("to") != "henry"]


# The LIST is a summary, the card GET is the full record (Slack/Linear/GitHub:
# list = summary rows, detail = one fetch by id). The list used to carry every
# card's whole record - 3.0 MB for 422 cards, ~4.2 MB once sealed for the relay,
# past the Worker's 4 MiB frame cap (MAX_BODY) - so the phone's refresh got 413
# and kept a stale list, and any card newer than that cache rendered as an empty
# "Card" screen forever (2026-09-29). Fields only the card screen reads stay out.
_LIST_REPLY_MAX = 400          # the board previews two lines of last_reply


def _summary(t):
    s = {k: v for k, v in t.items() if k != "bg_tasks"}
    if len(s.get("last_reply") or "") > _LIST_REPLY_MAX:
        s["last_reply"] = s["last_reply"][:_LIST_REPLY_MAX]
    return s


def _visible(t, user):
    from spine.auth import auth
    # clients: own cards, plus cards another person SHARED with them (summary
    # only - see _view)
    return t and not t.get("board_hidden") and auth.sees_card(user, t)


def _view(t, user):
    """What `user` gets of card `t`: the whole record for a card they own (or
    any owner/operator), the whitelisted summary for a card merely shared with
    them (auth.shared_view). Applied to every list row and the card GET."""
    from spine.auth import auth
    return _summary(t) if auth.owns_card(user, t) else auth.shared_view(t)


def tracks_list_get(self, user):
    from urllib.parse import parse_qs, urlparse
    from cells.engineer.cards import sessions
    from spine.storage import db
    # present(): stored 'running' is never believed on the way OUT -
    # only a live turn (drivers.turn_active) may render a spinner.
    # board_hidden (owner decree 2026-09-14): a landing's own ship-decide
    # research card - see lanemachine.request_ship_decision's docstring.
    q = parse_qs(urlparse(self.path).query, keep_blank_values=True)   # `?cookie=` = first pull
    if "cookie" not in q:                     # legacy full list (old apps, tools)
        arch = q.get("archived", [""])[0] == "1"   # the Archive filter's own list
        ts = [sessions.present(t) for t in sessions.list_tracks()
              if _visible(t, user) and (not arch or t.get("archived"))]
        return self._send(200, json.dumps([_view(t, user) for t in ts]))
    # PULL, Replicache-style (rocicorp/mono packages/replicache/src/puller.ts
    # PullResponseOKV1 + patch-operation.ts): the client sends the opaque
    # `cookie` it got last time; the reply is {cookie, patch:[put|del|clear]}.
    # The view is the NON-archived board, so a card that got archived or
    # deleted is a `del`. A cookie from another daemon process (epoch), a
    # malformed one or the empty one gets `clear` + every card = re-baseline.
    try:
        epoch, since = (int(x) for x in q["cookie"][0].split("."))
    except ValueError:
        epoch, since = 0, 0
    full = epoch != db.TRACK_EPOCH
    v, ids = db.tracks_changed_since(0 if full else since)
    rows = sessions.list_tracks() if full else [db.track_get(i) for i in ids]
    patch = [{"op": "clear"}] if full else []
    for i, t in zip(ids if not full else [None] * len(rows), rows):
        if t is None:
            patch.append({"op": "del", "key": i})
        elif _visible(t, user) and not t.get("archived"):
            patch.append({"op": "put", "key": t["id"], "value": _view(sessions.present(t), user)})
        else:
            patch.append({"op": "del", "key": t["id"]})
    return self._send(200, json.dumps({"cookie": "%d.%d" % (db.TRACK_EPOCH, v), "patch": patch}))


def tracks_get(self, user, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not t or not auth.sees_card(user, t):
        return self._send(404, json.dumps({"error": "no such card"}))
    if not auth.owns_card(user, t):          # shared with them: summary only
        return self._send(200, json.dumps(auth.shared_view(sessions.present(t))))
    return self._send(200, json.dumps(sessions.present(t)))


def tracks_live_get(self, user, tid):
    # the card's own glance feed: newest frame while its agent's
    # turn is being screen-recorded (fresh = written in last 20s)
    import time as _t
    from cells.engineer.cards import sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not auth.owns_card(user, t):
        return self._send(403, b"not your card", "text/plain")
    fp = os.path.join(t["run_dir"], "live.jpg") if t else ""
    if fp and os.path.exists(fp) and _t.time() - os.path.getmtime(fp) < 20:
        with open(fp, "rb") as f:
            return self._send(200, f.read(), "image/jpeg")
    return self._send(404, b"no live frame", "text/plain")


def tracks_turns_get(self, user, tid):
    # per-card AI usage: every turn's model, tokens, cost
    from spine.storage import events
    from cells.engineer.cards import sessions
    from spine.auth import auth
    if not auth.owns_card(user, sessions.get_track(tid)):
        return self._send(403, json.dumps({"error": "not your card"}))
    turns = [e for e in events.read_events()
             if e.get("kind") == "turn" and e.get("track") == tid]
    return self._send(200, json.dumps(turns))


def tracks_history_get(self, user, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    if not auth.owns_card(user, sessions.get_track(tid)):
        return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(sessions.history(tid)))


def tracks_transcript_get(self, user, tid):
    # the Paseo-style agent view: every turn's text + tool calls.
    # Card 2 cutover: served from the event-time timeline_store (folded live
    # by the driver's own pump), not re-parsed from Claude Code's private
    # .jsonl - see claude_sessions.read_transcript_store's docstring.
    from cells.engineer.cards import sessions
    from spine.agent import claude_sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not auth.owns_card(user, t):
        return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(_client_safe(claude_sessions.read_transcript_store(t), user)))


def tracks_transcript_live_get(self, user, tid):
    # PUSH over the sealed relay: hold the request until the
    # transcript changes (or ~22s), then return the fresh steps + a
    # version token. The phone loops this - real streaming latency
    # without SSE (which can't be relayed). Reuses the e2ee/relay
    # path untouched. 22s < relay REPLY_TIMEOUT (120) and the daemon
    # bridge's _local timeout (115), so the reply always lands.
    import time as _t
    from cells.engineer.cards import sessions
    from spine.agent import claude_sessions
    from spine.auth import auth
    from urllib.parse import parse_qs, urlparse
    t = sessions.get_track(tid)
    if not t:
        return self._send(404, json.dumps({"error": "no such card"}))
    if not auth.owns_card(user, t):
        return self._send(403, json.dumps({"error": "not your card"}))
    q = parse_qs(urlparse(self.path).query)
    want = (q.get("v") or [""])[0]
    deadline = _t.time() + 22
    cur = claude_sessions.transcript_store_version(t)
    while str(cur) == want and _t.time() < deadline:
        _t.sleep(0.35)
        cur = claude_sessions.transcript_store_version(t)
    # DELTA (perf): the client sends how many steps it already holds
    # (`have`); return only the TAIL - new steps plus a small overlap so
    # a late tool_result or the end-of-turn abandoned-relabel landing on a
    # recent step is still picked up. The compute is cheap (~16ms for a
    # full build); the cost was the RELAY payload - a full transcript is
    # 100-227KB re-sent on every token/tool tick. The tail is a few KB.
    # `have` absent/0 -> full transcript (old client + the loop's first
    # call), so this is backward compatible.
    steps = _client_safe(claude_sessions.read_transcript_store(t), user)
    try:
        have = int((q.get("have") or ["0"])[0])
    except ValueError:
        have = 0
    total = len(steps)
    base = max(0, min(have, total) - 12) if have > 0 else 0
    return self._send(200, json.dumps(
        {"v": str(cur), "base": base, "total": total, "steps": steps[base:]}))


def tracks_checkpoints_get(self, user, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not auth.owns_card(user, t):
        return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(sessions.list_checkpoints(tid)))


def tracks_attachments_get(self, user, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not auth.owns_card(user, t):
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
    import mimetypes
    from cells.engineer.cards import sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not auth.owns_card(user, t):
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


def _structural_denial(user, tid):
    """The floor for a STRUCTURAL verb addressed by card id (archive, fork,
    rewind, ...): a guest never, an operator only on a card that is theirs or
    assigned to them, the owner always. These routes used to test only
    `role == "client"`, so an operator reached any card by id."""
    from cells.engineer.cards import sessions
    from spine.auth import auth
    if user["role"] == "client":
        return (403, json.dumps({"error": "owner/operator only"}))
    if not auth.owns_card(user, sessions.get_track(tid)):
        return (403, json.dumps({"error": "not your card"}))
    return None


def tracks_share_post(self, user, body):
    """Share a card with other accounts (summary view) or withdraw the share.
    `cards.admin` holders only (owner, operator): a guest can neither widen nor
    narrow who sees a card. The write is sessions.share - the one owner."""
    from spine.auth import auth, permissions
    from cells.engineer.cards import sessions
    denial = permissions.require(user, "cards.admin")
    if denial:
        return self._send(*denial)
    # an operator widens access only to a card that is theirs or assigned to them
    if not auth.owns_card(user, sessions.get_track(body.get("id", ""))):
        return self._send(404, json.dumps({"error": "no such card"}))
    try:
        t = sessions.share(body.get("id", ""), add=body.get("add") or [],
                           remove=body.get("remove") or [], actor=user["name"])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    if t is None:
        return self._send(404, json.dumps({"error": "no such card"}))
    return self._send(200, json.dumps({"id": t["id"], "geteilt_mit": t.get("geteilt_mit") or []}))


def tracks_assign_post(self, user, body):
    """Assign a card to operators (full access) or take the assignment back.
    OWNER ONLY: who works on what is the owner's call; an operator can neither
    widen their own reach nor hand a card to a colleague."""
    from cells.engineer.cards import sessions
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    try:
        t = sessions.assign(body.get("id", ""), add=body.get("add") or [],
                            remove=body.get("remove") or [], actor=user["name"])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    if t is None:
        return self._send(404, json.dumps({"error": "no such card"}))
    return self._send(200, json.dumps({"id": t["id"], "zugewiesen_an": t.get("zugewiesen_an") or []}))


def tracks_reorder_post(self, user, body):
    from spine.auth import auth
    if auth.is_restricted(user):     # manual order is a whole-board act
        return self._send(403, json.dumps({"error": "owner only"}))
    from cells.engineer.cards import sessions
    ids = body.get("ids") or []
    return self._send(200, json.dumps(sessions.reorder(ids, actor=user["name"])))


def tracks_new_post(self, user, body):
    from cells.engineer.cards import sessions
    from spine.storage import events
    # SoD counterpart (card 3, ops/docs/backlog/rbac-gxp): quality/auditor are
    # approve/read-only roles - they may never be the one who files/dispatches
    # a card, independent of whether policy.sod_accept is even on (that knob
    # only governs the ACCEPT side, in lanemachine._sod_block_reason - this is
    # the dispatch side, which is unconditional for these two roles).
    if user["role"] in ("quality", "auditor"):
        return self._send(403, json.dumps(
            {"error": "role '%s' may not dispatch cards" % user["role"]}))
    # RESTRICTED roles (client, operator) file a card INTO the workspace's default
    # repo with default settings - the SERVER decides the environment, not the
    # sender (Copilot's coding agent works the same way: the task is asked inside
    # a repo, the asker cannot aim it at another one). Before this a guest could
    # name any git repo on this machine in `repo`, pick the agent's permission
    # mode in `perm`, and set billing fields; the worktree guard confines the
    # agent to ITS repo, but which repo was the sender's choice.
    from spine.auth import auth
    restricted = auth.is_restricted(user)
    repo = events.settings().get("default_repo") if restricted else (
        body.get("repo") or events.settings().get("default_repo"))
    perm = sessions.DEFAULT_PERM if restricted else body.get("perm", sessions.DEFAULT_PERM)
    value = None if restricted else body.get("value")
    project_id = None if restricted else body.get("project_id")
    billing = "fixed" if restricted else body.get("billing", "fixed")
    rate = None if restricted else body.get("rate")
    branch = body.get("branch"); task = body.get("task")
    if task and not branch:   # preset flow: task alone is enough
        # Only the human STEM. new_track owns the actual branch name
        # (trackstore._card_branch): it de-umlauts, slugs ASCII-only - an
        # umlaut in a git ref cost every steer a WinError 267 - appends the
        # card id, and proves the result free. Deriving it here instead is how
        # two cards with the same opening sentence ended up sharing a worktree.
        branch = "req-" + task
    if not (repo and branch and task):
        return self._send(400, json.dumps({"error": "task required (+ repo unless default_repo is set in settings)"}))
    if not sessions.is_git_repo(repo):
        return self._send(400, json.dumps(
            {"error": "repo is not a git repository: " + repo}))
    # a GUEST's card waits in the backlog until an admin moves it (nothing starts
    # an agent on the owner's machine on a guest's say-so alone); an operator
    # works their own cards, so theirs may start at once
    lane = "backlog" if user["role"] == "client" else body.get("lane", "working")
    client = user["name"] if restricted else body.get("client", "")
    driver = "claude" if restricted else body.get("driver", "claude")   # no desktop-driving agents
    # A card on an engine the daemon cannot run would only dispatch into a
    # spawn failure - refuse at filing (spine/agent/engines.check_selectable).
    from spine.agent import engines
    bad = engines.check_selectable(driver)
    if bad:
        return self._send(400, json.dumps({"error": bad}))
    model = body.get("model", "")
    attachments = body.get("attachments")
    if lane == "backlog":   # filing a request is instant, no session
        return self._send(200, json.dumps(sessions.new_track(
            repo, branch, task, perm,
            lane="backlog", client=client, value=value,
            driver=driver, actor=user["name"],
            priority=body.get("priority", "medium"),
            due=body.get("due", ""), model=model, attachments=attachments,
            project_id=project_id,
            description=body.get("description", ""),
            billing=billing, rate=rate)))
    def go():
        sessions.new_track(repo, branch, task,
                           perm,
                           lane="working", client=client,
                           value=value,
                           driver=driver, actor=user["name"],
                           priority=body.get("priority", "medium"),
                           due=body.get("due", ""), model=model, attachments=attachments,
                           project_id=project_id,
                           description=body.get("description", ""),
                           billing=billing, rate=rate)
    from spine.http import server
    # `branch` is only the human STEM here (new_track derives the real name and
    # the card id on the background thread, so neither is knowable yet). Echo a
    # short label, not the stem: for the preset flow the stem is the whole task
    # text, and it would otherwise land verbatim in the response AND in the
    # busy list that /control/state publishes.
    label = (task or branch)[:60]
    server._bg("track:new:" + label, go)
    return self._send(200, json.dumps({"started": label}))


def tracks_archive_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    denial = _structural_denial(user, tid)
    if denial:
        return self._send(*denial)
    try:
        return self._send(200, json.dumps(sessions.archive_track(
            tid, on=bool(body.get("on", True)), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_fork_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    denial = _structural_denial(user, tid)
    if denial:
        return self._send(*denial)
    try:
        return self._send(200, json.dumps(sessions.fork_track(
            tid, from_ref=body.get("ref", ""), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_forkchat_post(self, user, body, tid):
    # split a crowded card's CONVERSATION into a new card (keeps
    # context, unlike /fork which forks code at a ref with a fresh
    # session - see sessions.fork_conversation).
    from cells.engineer.cards import sessions
    denial = _structural_denial(user, tid)
    if denial:
        return self._send(*denial)
    try:
        return self._send(200, json.dumps(sessions.fork_conversation(
            tid, first=body.get("first", ""), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_delete_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    # Same role floor as the chat "delete" verb (policy.chat_admin_roles,
    # default owner+operator) - this endpoint used to hardcode owner-only,
    # so an operator could delete via chat but got a 403 on the identical
    # REST call. One gate, one policy knob, both paths agree now.
    if not auth.is_admin(user):
        return self._send(403, json.dumps(
            {"error": "role '%s' may not delete cards (policy.chat_admin_roles)"
             % user["role"]}))
    if not auth.owns_card(user, sessions.get_track(tid)):
        return self._send(403, json.dumps({"error": "not your card"}))
    try:
        return self._send(200, json.dumps(sessions.delete_track(
            tid, actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_update_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    if not auth.owns_card(user, sessions.get_track(tid)):
        return self._send(403, json.dumps({"error": "not your card"}))
    if user["role"] == "client":
        body.pop("autopilot", None)   # autopilot opt-in is owner/operator only
        body.pop("driver", None)      # capability grant (GUI/desktop control) - admin only
    elif "driver" in body:
        if not auth.is_admin(user):
            return self._send(403, json.dumps(
                {"error": "changing a card's driver requires: " + ", ".join(auth.chat_admin_roles())}))
    try:
        return self._send(200, json.dumps(
            sessions.update_track(tid, body, actor=user["name"])))
    except (RuntimeError, ValueError) as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_rewind_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    denial = _structural_denial(user, tid)
    if denial:
        return self._send(*denial)
    try:
        return self._send(200, json.dumps(
            sessions.rewind_files(tid, body.get("commit", ""), actor=user["name"])))
    except (RuntimeError, ValueError) as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_attach_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    if not auth.owns_card(user, sessions.get_track(tid)):
        return self._send(403, json.dumps({"error": "not your card"}))
    try:
        return self._send(200, json.dumps(
            sessions.add_attachments(tid, body.get("attachments"), actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


def tracks_attach_remove_post(self, user, body, tid):
    from cells.engineer.cards import sessions
    from spine.auth import auth
    if not auth.owns_card(user, sessions.get_track(tid)):
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
    "/tracks/share": tracks_share_post,
    "/tracks/assign": tracks_assign_post,
    "/tracks/new": tracks_new_post,
}
