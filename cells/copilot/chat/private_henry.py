# -*- coding: utf-8 -*-
"""A PRIVATE Henry for a restricted role (operator) - backlog/team-rooms-member.

The owner's Henry (copilot.chat) knows the whole board, loads the owner's memory
into every turn and has hands. An operator works only on cards that are theirs or
assigned to them (auth.owns_card), so they get THIS one instead: same isolation as
the room Henry (room_henry.py), but one person and a personal history.

  - ONE-SHOT and stateless like the room Henry: no --resume, no session pointer.
    Each turn is rebuilt from the RECORD: the person's own conversation (the same
    `chat` table the owner's Henry uses, keyed by account - so an admin reads it
    only through chat_grants, with consent), THEIR cards (owns_card / sees_card,
    title + status + result, never repo or paths) and THEIR notes
    (copilot_memory person scope).
  - NO TOOLS, plan mode, no MCP, no ambient settings, empty cwd (room_henry.run_claude).
    He advises; he does not act.
  - One lock per person: messages are answered in order, never interrupting each
    other; a bounded queue stops a flood from burning the plan.
"""
import threading

from cells.copilot.chat import copilot_memory, room_henry
from spine.storage import db

PRIVATE_ROLES = ("operator",)         # who gets a private Henry (the owner has the full one)
HISTORY_ENTRIES = 24
CARD_LIMIT = 15
MAX_QUEUED = 3

BRIEF = room_henry.BRIEF.replace("room-henry.md", "private-henry.md")
_FALLBACK = ("Du bist Henry und hilfst einer Person bei ihrer Arbeit. Antworte kurz, nur "
             "beratend und ohne Werkzeuge. Du kennst nur den Verlauf, die Karten dieser "
             "Person und deine Notizen ueber sie. Erfinde nichts.")

_locks = {}
_waiting = {}
_guard = threading.Lock()


def allowed(user):
    return bool(user) and user.get("role") in PRIVATE_ROLES


def brief():
    try:
        with open(BRIEF, encoding="utf-8") as f:
            return f.read().strip() or _FALLBACK
    except OSError:
        return _FALLBACK


def cards_for(user):
    """The cards this person may see, newest first, as the SUMMARY a prompt needs.
    Own/assigned cards and shared ones alike are reduced to the same whitelisted
    fields (auth.SHARED_FIELDS minus the people) - a repo path or session id never
    enters a prompt."""
    from cells.engineer.cards import sessions
    from spine.auth import auth
    rows = [t for t in sessions.list_tracks()
            if not t.get("board_hidden") and not t.get("archived") and auth.sees_card(user, t)]
    rows.sort(key=lambda t: t.get("updated") or "", reverse=True)
    out = []
    for t in rows[:CARD_LIMIT]:
        out.append({"id": t.get("id"), "task": (t.get("task") or "")[:120], "lane": t.get("lane"),
                    "status": t.get("status"), "result": (t.get("last_reply") or "")[:240],
                    "mine": auth.owns_card(user, t)})
    return out


def memory_block(rows, budget=4000):
    out, used = [], 0
    for name, r in sorted(rows.items(), key=lambda kv: kv[1].get("updated_at") or "", reverse=True):
        body = (r.get("content") or "").strip()
        if used + len(body) > budget:
            break
        used += len(body)
        out.append("=== %s\n%s" % (name, body))
    return ("\n\nNOTIZEN UEBER DIESE PERSON:\n" + "\n\n".join(out)) if out else ""


def build_prompt(user, cards, history, text, rows):
    lines = []
    for e in history[-HISTORY_ENTRIES:]:
        who = "Henry" if e.get("role") == "assistant" else user["name"]
        lines.append("%s: %s" % (who, (e.get("text") or "").replace("\r", "")))
    cl = ["- [%s] %s (%s/%s)%s%s" % (c["id"], c["task"], c["lane"], c["status"],
                                    "" if c["mine"] else " [nur geteilt]",
                                    (" - Ergebnis: " + c["result"]) if c["result"] else "")
          for c in cards]
    return ("PERSON: %s\n\nIHRE KARTEN (mehr siehst du nicht):\n%s%s\n\nVERLAUF:\n%s\n\n"
            "NEUE NACHRICHT von %s:\n%s"
            % (user["name"], "\n".join(cl) or "(keine)", memory_block(rows),
               "\n".join(lines) or "(noch leer)", user["name"], text))


def _entry(role, text, by, extra=None):
    import time
    e = {"role": role, "kind": "text", "text": text, "by": by,
         "byKind": "human" if role == "user" else "henry",
         "date": time.strftime("%Y-%m-%d"), "ts": time.strftime("%H:%M")}
    if extra:
        e.update(extra)
    return e


def history(user):
    return db.chat_tail(user["name"], 80)


def answer(user, text, runner=None):
    """One turn for `user`, in answer to `text` (already appended to their chat).
    Blocks on the person's lock (the queue); returns the stored reply or None when
    the queue is full."""
    runner = runner or room_henry.run_claude
    name = user["name"]
    with _guard:
        if _waiting.get(name, 0) >= MAX_QUEUED:
            return None
        _waiting[name] = _waiting.get(name, 0) + 1
    try:
        with _guard:
            lock = _locks.setdefault(name, threading.Lock())
        with lock:
            tail = db.chat_tail(name, HISTORY_ENTRIES + 4)
            idx = max((i for i, e in enumerate(tail) if e.get("role") == "user" and e.get("text") == text),
                      default=len(tail))
            viewer = copilot_memory.viewer_for(name, user["role"]) or {"account": name, "rooms": (), "cards": ()}
            rows = copilot_memory.all_notes(viewer)
            prompt = build_prompt(user, cards_for(user), tail[:idx], text, rows)
            try:
                reply, _raw = runner(brief(), prompt)
            except Exception as e:                               # noqa: BLE001
                reply, err = "Ich konnte gerade nicht antworten (%s)." % str(e)[:120], True
            else:
                err = False
                reply, muts = copilot_memory.parse(reply)
                if muts:
                    copilot_memory.apply(muts, actor="henry", source="private:%s" % name,
                                         scope=copilot_memory.scope_for(viewer), viewer=viewer)
                reply = reply or "(keine Antwort)"
            e = _entry("assistant", reply, "Henry", {"error": True} if err else None)
            db.chat_append(name, [e])
            db.bump_chat()
            return e
    finally:
        with _guard:
            _waiting[name] = max(0, _waiting.get(name, 1) - 1)


def post(user, text, background=True, runner=None):
    """Append the person's message at once, then answer (in the background). The
    message shows immediately; Henry's reply arrives as the next entry."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty message")
    if len(text) > 8000:
        raise ValueError("message too long (max 8000)")
    e = _entry("user", text, user["name"])
    db.chat_append(user["name"], [e])
    db.bump_chat()
    if background:
        threading.Thread(target=answer, args=(user, text, runner), daemon=True,
                         name="private-henry:%s" % user["name"]).start()
    else:
        answer(user, text, runner)
    return e
