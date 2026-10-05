# -*- coding: utf-8 -*-
"""Team-room routes (backlog/team-rooms-member, stage 3). Logic lives in
cells/copilot/chat/rooms.py; this layer only maps the wire to it.

Authorization, in two different shapes on purpose:
  - create / change members: a CAPABILITY (`rooms.manage`, owner + operator),
    declared in GET_CAPS/POST_CAPS below so server.py's one permission gate
    enforces it.
  - list / read / post: MEMBERSHIP, enforced per room inside rooms.py. A room
    the caller is not in answers 404 - the same as an unknown id - so a guest
    cannot even learn that a room exists.

Every id comes from the query/body; the AUTHOR of a post is always the
authenticated account, never a field the client sends.
"""
import json
from urllib.parse import parse_qs, urlparse

from cells.copilot.chat import rooms


def _q(self):
    return parse_qs(urlparse(self.path).query)


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def rooms_get(self, user):
    q = _q(self)
    from spine.auth import permissions
    if (q.get("all") or [""])[0] and permissions.can(user, "rooms.manage"):
        # manager overview: names + members only, never messages
        from spine.storage import db
        return self._send(200, json.dumps([
            {"id": r["id"], "name": r["name"], "members": r["members"]}
            for r in db.room_all()]))
    return self._send(200, json.dumps(rooms.list_for(user["name"])))


def rooms_messages_get(self, user):
    q = _q(self)
    rid = (q.get("room") or [""])[0]
    try:
        msgs = rooms.history(rid, user["name"], after=_int((q.get("after") or ["0"])[0]))
    except PermissionError:
        return self._send(404, json.dumps({"error": "unknown room"}))
    if msgs:       # the member is looking at these: advance THEIR read cursor
        rooms.mark_read(rid, user["name"], msgs[-1]["seq"])
    return self._send(200, json.dumps({"room": rooms.get(rid), "messages": msgs}))


def rooms_new_post(self, user, body):
    try:
        room = rooms.create(body.get("name", ""), user["name"], body.get("members") or [])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(room))


def rooms_members_post(self, user, body):
    try:
        room = rooms.set_members(body.get("room", ""), user["name"],
                                 add=body.get("add") or [], remove=body.get("remove") or [])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(room))


def rooms_post_post(self, user, body):
    rid = body.get("room", "")
    if not rooms.is_member(rid, user["name"]):
        return self._send(404, json.dumps({"error": "unknown room"}))
    try:
        msg = rooms.post(rid, user["name"], body.get("text", ""))
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    # @henry: answer in the background (the reply arrives as the next message,
    # the chat cursor wakes every member's app); the post itself returns at once
    from cells.copilot.chat import room_henry
    room_henry.maybe_answer(msg)
    return self._send(200, json.dumps(msg))


def rooms_card_post(self, user, body):
    """File a card FROM a room (stage 6). Any member may - a guest can file cards
    anyway (/tracks/new) - and it is filed exactly as a guest's card always is:
    backlog (nothing starts), in its own worktree (card_kind pinned to
    new_track: a repo template that asks for the live tree is NOT honoured for
    a card born in a shared room), `client` = the author when a guest. The other
    room members get it shared (summary view, sessions.share); the room gets a
    system line carrying the card id so the app can link it."""
    rid = body.get("room", "")
    if not rooms.is_member(rid, user["name"]):
        return self._send(404, json.dumps({"error": "unknown room"}))
    task = (body.get("task") or "").strip()
    if not task or len(task) > 200:
        return self._send(400, json.dumps({"error": "task required (max 200 characters)"}))
    from cells.engineer.cards import sessions
    from spine.storage import events
    repo = events.settings().get("default_repo")
    if not repo or not sessions.is_git_repo(repo):
        return self._send(400, json.dumps({"error": "no default repo configured for new cards"}))
    client = user["name"] if user["role"] == "client" else ""
    t = sessions.new_track(repo, "req-" + task, task, lane="backlog", client=client,
                           actor=user["name"], description=body.get("description", ""),
                           card_kind="new_track")
    others = [m for m in rooms.members_of(rid) if m != user["name"]]
    if others:
        sessions.share(t["id"], add=others, actor=user["name"])
    rooms.post(rid, user["name"], "legte die Karte an: " + task, by_kind="system",
               extra={"card": t["id"]})
    return self._send(200, json.dumps({"id": t["id"], "geteilt_mit": others}))


def rooms_read_post(self, user, body):
    try:
        rooms.mark_read(body.get("room", ""), user["name"], int(body.get("seq") or 0))
    except (PermissionError, ValueError):
        return self._send(404, json.dumps({"error": "unknown room"}))
    return self._send(200, json.dumps({"ok": True}))


GET_ROUTES = {
    "/rooms": rooms_get,
    "/rooms/messages": rooms_messages_get,
}
POST_ROUTES = {
    "/rooms/new": rooms_new_post,
    "/rooms/members": rooms_members_post,
    "/rooms/post": rooms_post_post,
    "/rooms/read": rooms_read_post,
    "/rooms/card": rooms_card_post,
}
POST_CAPS = {
    "/rooms/new": "rooms.manage",
    "/rooms/members": "rooms.manage",
}
