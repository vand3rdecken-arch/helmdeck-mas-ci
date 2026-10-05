# -*- coding: utf-8 -*-
"""Team rooms - the Slack-channel shape (backlog/team-rooms-member, stage 3).

A ROOM is a conversation with a member list. Humans and Henry are in it; every
member reads the whole history and every message carries its author. A room is
one more THREAD kind next to the card threads and the inbox, not a second chat
system (owner decree "Threads = Karten", "never two chat UIs").

ONE OWNER PER FACT (CLAUDE.md, no monkey patches):
  - the member list is a RECORDED fact, mutated only by set_members()/create();
    "may this account read this room" is derived from it at every call -
    is_member() - never from a cached flag or a role.
  - a message's author is written at post time from the authenticated account,
    never taken from the request body.

Authorization is MEMBERSHIP (per resource, like auth.owns_card for cards), not a
capability: the caps only decide who may CREATE a room or change its members
(`rooms.manage`, owner + operator). A client/guest reads and posts in the
rooms they are a member of and nowhere else - the Slack-guest model.

Henry's replies in a room (@henry only) are stage 4; this module records the
messages and extracts the mentions so the later stages have one parser.
"""
import re
import secrets
import time

from spine.storage import db

NAME_MAX = 60
TEXT_MAX = 8000
HENRY = "henry"
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_.\-]+)")


def _now_parts():
    return time.strftime("%Y-%m-%d"), time.strftime("%H:%M")


def _accounts():
    from spine.auth import auth
    return {u["name"]: u for u in auth.list_users()}


def _emit(rid, **fields):
    try:
        from spine.storage import events
        events.emit("room", rid, **fields)
    except Exception:                                            # noqa: BLE001
        pass          # the audit mirror must never break the room itself


def get(rid):
    return db.room_get(rid)


def is_member(rid, user):
    r = db.room_get(rid)
    return bool(r) and user in (r.get("members") or [])


def members_of(rid):
    r = db.room_get(rid)
    return list(r.get("members") or []) if r else []


def rooms_of(user):
    """Ids of the rooms `user` is a member of (derived from the records)."""
    return [r["id"] for r in db.room_all() if user in (r.get("members") or [])]


def list_for(user):
    """The rooms `user` may see, newest activity first, each with a preview."""
    out = []
    for r in db.room_all():
        if user not in (r.get("members") or []):
            continue
        tail = db.room_messages(r["id"], limit=1)
        last = tail[-1] if tail else {}
        out.append({"id": r["id"], "name": r["name"], "members": r["members"],
                    "henry_on_mention": r.get("henry_on_mention", True),
                    "created_by": r.get("created_by"),
                    "last_seq": last.get("seq", 0),
                    "preview": (last.get("text") or "")[:140].replace("\n", " "),
                    "last_by": last.get("by", ""),
                    "last_at": "%s %s" % (last.get("date", ""), last.get("ts", "")),
                    })
    out.sort(key=lambda x: x["last_at"], reverse=True)
    return out


def _clean_members(names):
    known = _accounts()
    out = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        if n not in known:
            raise ValueError("unknown account: %s" % n)
        if n not in out:
            out.append(n)
    return out


def create(name, creator, members=()):
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX:
        raise ValueError("room name must be 1-%d characters" % NAME_MAX)
    mem = _clean_members(list(members) + [creator])
    room = {"id": "r" + secrets.token_hex(4), "name": name, "members": mem,
            "created_by": creator, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "henry_on_mention": True}
    db.room_put(room)
    _emit(room["id"], op="create", actor=creator, name=name, members=mem)
    return room


def set_members(rid, actor, add=(), remove=()):
    r = db.room_get(rid)
    if not r:
        raise ValueError("unknown room")
    mem = list(r.get("members") or [])
    for n in _clean_members(add):
        if n not in mem:
            mem.append(n)
    for n in (remove or []):
        if n in mem:
            mem.remove(n)
    if not mem:
        raise ValueError("a room needs at least one member")
    r["members"] = mem
    db.room_put(r)
    _emit(rid, op="members", actor=actor, add=list(add or []), remove=list(remove or []))
    return r


def parse_mentions(text, members):
    """-> (mentioned member accounts, henry_mentioned). Case-insensitive on the
    account name; an @name that is not a member is simply not a mention (nobody
    outside the room is ever addressed or notified through it)."""
    by_lower = {m.lower(): m for m in members}
    mentioned, henry = [], False
    for tok in _MENTION.findall(text or ""):
        low = tok.lower().rstrip(".")
        if low == HENRY:
            henry = True
        elif low in by_lower and by_lower[low] not in mentioned:
            mentioned.append(by_lower[low])
    return mentioned, henry


def post(rid, author, text, by_kind="human", extra=None):
    """Append one message. `author` is the AUTHENTICATED account (the route
    passes user["name"]); membership is enforced here, in the one writer, so no
    route can forget it. Returns the stored message incl. mentions."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty message")
    if len(text) > TEXT_MAX:
        raise ValueError("message too long (max %d)" % TEXT_MAX)
    r = db.room_get(rid)
    if not r:
        raise ValueError("unknown room")
    if by_kind == "human" and author not in (r.get("members") or []):
        raise PermissionError("not a member of this room")
    mentioned, henry = parse_mentions(text, r.get("members") or [])
    date, hhmm = _now_parts()
    entry = {"role": "user" if by_kind == "human" else "assistant", "kind": "text",
             "text": text, "by": author, "byKind": by_kind, "date": date, "ts": hhmm,
             "mentions": mentioned, "henry": bool(henry)}
    if extra:
        entry.update(extra)
    return db.room_message_add(rid, entry)


def history(rid, user, after=0):
    """The room's messages for a MEMBER. Raises PermissionError otherwise."""
    if not is_member(rid, user):
        raise PermissionError("not a member of this room")
    return db.room_messages(rid, after=after)
