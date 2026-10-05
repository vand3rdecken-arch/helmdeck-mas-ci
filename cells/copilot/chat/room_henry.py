# -*- coding: utf-8 -*-
"""Henry inside a team room (backlog/team-rooms-member, stage 4).

WHY THIS IS NOT copilot.chat(). chat() is the OWNER's Henry: one resumable
session per person, the board brief (owner facts, cards, prices), hands,
actions. A room is read by several people, so Henry here is a different, much
smaller thing, by construction rather than by instruction:

  - ONE-SHOT and stateless: no --resume, no session pointer. Everything he
    knows is rebuilt from the RECORD each turn - the room's history (every line
    carries its author's name) and the room's memory. Nothing is remembered in a
    hidden per-person transcript another member could not see.
  - NO TOOLS (`--tools ""`), permission mode plan, no MCP, no ambient settings
    layer. He cannot touch the machine even if a message asks him to; the
    refusal is the CLI's, not a sentence in a prompt (owner decree: "invariants
    -> code").
  - HIS OWN BRIEF (harness/agents/room-henry.md), not board-copilot - that one
    carries the owner's machine and money.
  - memory: only the room's notes are read (copilot_memory.room_viewer) and any
    save lands in the room scope. The asker's private notes never ride in -
    everyone in the room reads the answer.
  - he answers ONLY on @henry, to the author of THAT message, by name.

ORDER. One lock per room: two asks at once are answered one after the other,
each turn rebuilding its context from the record at the moment it runs, so the
second answer already includes the first. A new message NEVER interrupts a turn
in progress (the owner chat's last-wins steer would let one member's message
cancel another's answer); a bounded queue stops a flood from burning the plan.
"""
import json
import os
import subprocess
import tempfile
import threading

from cells.copilot.chat import rooms, copilot_memory

HISTORY_LINES = 30
MEMORY_BUDGET = 6000            # chars of room notes handed over in full
TIMEOUT = 180
MAX_QUEUED = 3                  # asks waiting behind the running one
MODEL = "sonnet"                # whitelist alias, same family the cards route to

_HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF = os.path.join(os.path.dirname(_HERE), "harness", "agents", "room-henry.md")
_FALLBACK_BRIEF = ("Du bist Henry in einem Team-Raum. Antworte nur der Person, die dich "
                   "mit @henry gefragt hat, kurz, mit Namen, nur beratend und ohne "
                   "Werkzeuge. Erfinde nichts.")

_locks = {}
_waiting = {}
_guard = threading.Lock()


def brief():
    """Read at CALL time, so an edit applies on the next turn with no restart.
    A missing/unreadable file costs the customisation, never the answer."""
    try:
        with open(BRIEF, encoding="utf-8") as f:
            txt = f.read().strip()
        return txt or _FALLBACK_BRIEF
    except OSError:
        return _FALLBACK_BRIEF


def memory_block(rows):
    """The room's notes IN FULL, newest first, within MEMORY_BUDGET. A room
    holds a handful of notes, so they ride whole: the owner chat's recall (IDF
    over a big corpus) finds nothing in a store this small, and its overview
    points at a `find` tool a room turn does not have."""
    out, used = [], 0
    for name, r in sorted(rows.items(), key=lambda kv: kv[1].get("updated_at") or "",
                          reverse=True):
        body = (r.get("content") or "").strip()
        if used + len(body) > MEMORY_BUDGET:
            break
        used += len(body)
        out.append("=== %s [%s]\n%s" % (name.split("/", 1)[-1],
                                        (r.get("updated_at") or "")[:10], body))
    if not out:
        return ""
    return "\n\nNOTIZEN DIESES RAUMS (alle im Raum lesen sie):\n" + "\n\n".join(out)


def build_prompt(room, history, author, text, rows):
    """The turn, assembled ONLY from the record: members, the room's notes, the
    last HISTORY_LINES messages with their authors, and the question."""
    lines = []
    for m in history[-HISTORY_LINES:]:
        who = "Henry" if m.get("byKind") == "henry" else (m.get("by") or "?")
        lines.append("[%s %s] %s: %s" % (m.get("date", ""), m.get("ts", ""), who,
                                         (m.get("text") or "").replace("\r", "")))
    return ("RAUM: %s\nMITGLIEDER: %s%s\n\nVERLAUF (aelteste zuerst):\n%s\n\n"
            "NEUE NACHRICHT von %s, die dich mit @henry anspricht:\n%s\n\n"
            "Antworte %s direkt."
            % (room["name"], ", ".join(room["members"]), memory_block(rows),
               "\n".join(lines) or "(noch leer)", author, text, author))


def _argv():
    from cells.copilot.chat import copilot
    return [copilot.CLAUDE, "-p", "--output-format", "json", "--permission-mode", "plan",
            "--tools", "", "--model", MODEL, "--setting-sources", ""] + copilot._lean_mcp_args()


def _empty_cwd():
    """An EMPTY directory outside the repo: the CLI auto-loads CLAUDE.md and its
    per-project auto-memory from the cwd, and the repo's own (HelmDeck's laws,
    the owner's notes) must never reach a room turn."""
    d = os.path.join(tempfile.gettempdir(), "helmdeck-room-henry")
    os.makedirs(d, exist_ok=True)
    return d


def run_claude(system, prompt, timeout=TIMEOUT):
    """The ONE place this module spawns the CLI: (reply text, raw json).
    stdin carries the turn; the brief goes as a FILE (Windows' command-line cap,
    see copilot._brief_file)."""
    from cells.copilot.chat import copilot
    from spine.agent import drivers
    from spine.agent.spawnenv import tool_path
    argv = _argv() + ["--system-prompt-file", copilot._brief_file(system)]
    p = subprocess.Popen(drivers._cmd_line(argv), cwd=_empty_cwd(), stdin=subprocess.PIPE,
                         env=tool_path(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        out, err = p.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    if not (out or "").strip():
        raise RuntimeError("no model output: " + (err or "").strip()[:200])
    raw = json.loads(out)
    try:                                   # the plan calibration's share of it
        from spine.turn import econ
        econ.record_spend("room", list((raw.get("modelUsage") or {}).keys()),
                          raw.get("usage"), raw.get("total_cost_usd"))
    except Exception:                                            # noqa: BLE001
        pass
    return (raw.get("result") or "").strip(), raw


def _lock_for(rid):
    with _guard:
        return _locks.setdefault(rid, threading.Lock())


def answer(rid, author, text, runner=None):
    """One Henry turn in room `rid`, in answer to `author`'s message. Blocks on
    the room's lock (the queue), reads the record at THAT moment, stores the
    reply (or an honest failure note) and returns the stored message, or None
    when the queue is full. `runner(system, prompt) -> (text, raw)` is the seam
    the tests use; production uses run_claude."""
    runner = runner or run_claude
    with _guard:
        if _waiting.get(rid, 0) >= MAX_QUEUED:
            return None
        _waiting[rid] = _waiting.get(rid, 0) + 1
    try:
        with _lock_for(rid):
            room = rooms.get(rid)
            if not room:
                return None
            viewer = copilot_memory.room_viewer(rid)
            rows = copilot_memory.all_notes(viewer)
            prompt = build_prompt(room, rooms.history(rid, author), author, text, rows)
            try:
                reply, _raw = runner(brief(), prompt)
            except Exception as e:                               # noqa: BLE001
                return rooms.post(rid, "Henry", "Ich konnte gerade nicht antworten (%s)."
                                  % str(e)[:120], by_kind="henry", extra={"to": author, "error": True})
            reply, muts = copilot_memory.parse(reply)
            if muts:
                copilot_memory.apply(muts, actor="henry", source="room:%s" % rid,
                                     scope=copilot_memory.scope_for(viewer, room=rid),
                                     viewer=viewer)
            if not reply:
                reply = "(keine Antwort)"
            return rooms.post(rid, "Henry", reply, by_kind="henry", extra={"to": author})
    finally:
        with _guard:
            _waiting[rid] = max(0, _waiting.get(rid, 1) - 1)


def maybe_answer(msg, background=True, runner=None):
    """Called by the route after a HUMAN message landed. Starts Henry only when
    the message mentions him AND the room allows it; Henry's own messages never
    reach here, so he can never trigger himself."""
    if msg.get("byKind") != "human" or not msg.get("henry"):
        return False
    room = rooms.get(msg["room_id"]) if msg.get("room_id") else None
    if not room or not room.get("henry_on_mention", True):
        return False
    args = (msg["room_id"], msg["by"], msg["text"], runner)
    if background:
        threading.Thread(target=answer, args=args, daemon=True,
                         name="room-henry:%s" % msg["room_id"]).start()
    else:
        answer(*args)
    return True
