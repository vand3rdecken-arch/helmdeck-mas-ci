# -*- coding: utf-8 -*-
"""HENRY'S OWN BACKGROUND AGENTS - the CLI-native ones (Agent/Task with
run_in_background, or any run_in_background tool) that his warm chat process
launches itself.

Owner 2026-09-16 18:51 ("Arbeitet aber keine visuelle Rueckmeldung"): Henry
launched an Explore sub-agent at 18:42 ("dauert ein, zwei Minuten"), it was
still working nine minutes later (19 tool steps in its transcript) - and the
chat showed NOTHING. The chat's background line (BackgroundTasks, variant
"henry") knew only broker follow-ups and hands runs; a CLI Agent lived
nowhere. The card side has had this since 2026-08-24 (drivers._scan_bg +
sessions.bg_upsert); this is the same fold for the chat process, kept
in-memory like hands._tasks because a chat bg task has no track to persist
on and dies with the process anyway.

ONE OWNER, EVENT TIME (CLAUDE.md law): every mutation here comes from the
process's own stream - a tool_use is a CANDIDATE, its tool_result ("Async
agent launched") confirms it, the CLI's system/task_notification (between
turns it is the ONLY shape the pump sees - drivers.py, measured 2026-08-24)
or an in-turn <task-notification> text closes it, and copilot._persist_drop
reconciles: a killed process takes its sub-agents with it, so every open
task is closed as failed WITH that reason (Paseo finishAll parity) - never
left "running" forever with nothing behind it."""
import re
import threading
import time

_lock = threading.Lock()
_tasks = {}          # skey -> {uid: BgTask dict (+ "user")}
_cand = {}           # skey -> {uid: (title, detail)}
_closed = {}         # skey -> [uid] closed since the last take_closed() - the auto-continue cue
_re_done = re.compile(r"<tool-use-id>(.*?)</tool-use-id>", re.S)
_re_status = re.compile(r"<status>(.*?)</status>", re.S)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    return ""


def _emit(action, skey, uid, **kw):
    try:
        from spine.storage import events
        events.emit("henry_bg", "-", action=action, skey=skey, id=uid, **kw)
    except Exception:                                    # noqa: BLE001
        pass


def _desc(t):
    """The BgTask descriptor the chat renders (tasks() and the db row)."""
    return dict({k: t[k] for k in ("title", "status", "since", "updated", "detail", "result")},
                kind="agent", steps=[dict(s) for s in t.get("steps", [])])


def _persist(skey, uid):
    """Write the run's descriptor to helmdeck.db (db.chat_runs) at launch and
    at its end - the tile outlives the hour window and a daemon restart
    (owner 2026-09-25). Best-effort: the registry never fails on the db."""
    with _lock:
        t = (_tasks.get(skey) or {}).get(uid)
        doc, user = (_desc(t), t.get("user")) if t else (None, None)
    if doc is None:
        return
    try:
        from spine.storage import db
        db.chat_run_put("bg:" + uid, user, doc)
    except Exception as e:                               # noqa: BLE001
        print("henry_bg: run persist failed - %s" % str(e)[:160], flush=True)


def fold(skey, ev, user=None):
    """Fold ONE stream event of Henry's chat process. Cheap no-op for the
    vast majority of events; never raises (best-effort registry, never the
    turn - the caller wraps it anyway)."""
    typ = ev.get("type")
    if typ == "system":
        if ev.get("subtype") != "task_notification":
            return
        uid = str(ev.get("tool_use_id") or "")
        st = ev.get("status") or "completed"
        _close(skey, uid, st, str(ev.get("summary") or ""))
        return
    if typ not in ("assistant", "user"):
        return
    c = (ev.get("message") or {}).get("content")
    if not isinstance(c, list):
        return
    parent = ev.get("parent_tool_use_id")
    if parent:
        # A SUB-AGENT's own frame (the CLI streams them with the Agent call's
        # id as parent - measured 2026-09-16): its tool calls are the steps
        # the run tile shows. Folded here, at event time, never re-read.
        _sub_steps(skey, parent, c)
        return
    launched = None
    for p in c:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "tool_use":
            inp = p.get("input") if isinstance(p.get("input"), dict) else {}
            if inp.get("run_in_background") or p.get("name") in ("Task", "Agent"):
                title = str(inp.get("description") or p.get("name") or "task")[:80]
                detail = str(inp.get("prompt") or inp.get("command") or inp.get("description") or "")[:600]
                with _lock:
                    _cand.setdefault(skey, {})[p.get("id")] = (title, detail)
        elif p.get("type") == "tool_result":
            uid = p.get("tool_use_id")
            with _lock:
                hit = (_cand.get(skey) or {}).pop(uid, None)
            if not hit:
                continue
            txt = _text_of(p.get("content"))
            if "Async agent launched" in txt or "run_in_background" in txt \
                    or "background" in txt[:200].lower():
                title, detail = hit
                now = time.time()
                with _lock:
                    _tasks.setdefault(skey, {})[uid] = {
                        "title": title, "status": "running", "since": now, "updated": now,
                        "detail": detail, "result": "", "user": user, "steps": []}
                _emit("launched", skey, uid, title=title)
                _persist(skey, uid)
                launched = uid
        elif p.get("type") == "text" and isinstance(p.get("text"), str) \
                and p["text"].lstrip().startswith("<task-notification>"):
            hit = _re_done.search(p["text"])
            if hit:
                sm = _re_status.search(p["text"])
                _close(skey, hit.group(1).strip(), (sm.group(1).strip() if sm else "completed"),
                       _text_of(p["text"]))
    return launched


_STEPS_KEPT = 30


def _sub_steps(skey, parent, content):
    with _lock:
        t = (_tasks.get(skey) or {}).get(parent)
        if t is None:
            return
        steps = t.setdefault("steps", [])
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "tool_use":
                inp = p.get("input") if isinstance(p.get("input"), dict) else {}
                try:
                    from spine.agent import claude_transcript_fmt as _fmt
                    lbl, sub = _fmt._tool_label(p.get("name"), inp)
                except Exception:                            # noqa: BLE001
                    lbl, sub = p.get("name") or "tool", ""
                steps.append({"id": p.get("id") or "", "label": lbl or p.get("name") or "tool",
                              "text": (sub or "")[:140], "status": "running", "ta": time.time()})
                del steps[:-_STEPS_KEPT]
                t["updated"] = time.time()
            elif p.get("type") == "tool_result":
                for s in steps:
                    if s["id"] and s["id"] == p.get("tool_use_id"):
                        s["status"] = "failed" if p.get("is_error") else "completed"


def _close(skey, uid, status, result):
    if status not in ("completed", "failed", "canceled"):
        status = "completed"
    with _lock:
        t = (_tasks.get(skey) or {}).get(uid)
        if not t or t["status"] != "running":
            return
        t["status"], t["result"], t["updated"] = status, (result or "")[:400], time.time()
        _closed.setdefault(skey, []).append(uid)
    _emit(status, skey, uid, result=(result or "")[:200])
    _persist(skey, uid)


def take_closed(skey):
    """Pop the tasks closed since the last call - descriptors, not ids. The
    ping reader calls this after its fold: a non-empty answer means a
    hand-back landed BETWEEN turns, i.e. nobody is going to react to it
    unless the harness starts a turn (copilot._bg_continue). Popped, so one
    hand-back drives exactly one continue."""
    with _lock:
        uids = _closed.pop(skey, [])
        per = _tasks.get(skey) or {}
        return [dict(per[u], uid=u) for u in uids if u in per]


def finish_all(skey, why):
    """The process behind `skey` is gone (copilot._persist_drop): its
    sub-agents died with it. Close every open task as failed with the reason,
    so the line never shows a runner nobody is running."""
    closed = []
    with _lock:
        _cand.pop(skey, None)
        for uid, t in (_tasks.get(skey) or {}).items():
            if t["status"] == "running":
                t["status"], t["result"], t["updated"] = "failed", ("FAILED - " + why)[:400], time.time()
                closed.append(uid)
    if closed:
        _emit("finish_all", skey, "-", why=why[:120], closed=len(closed))
    for uid in closed:
        _persist(skey, uid)
    return len(closed)


def tasks(user=None, closed_within_s=3600):
    """BgTask-shaped descriptors for the chat's background line (the same
    shape hands.tasks() returns). Running ones always; closed ones for an hour
    so the owner sees the hand-back, not just the disappearance."""
    now = time.time()
    out = {}
    with _lock:
        for skey, per in _tasks.items():
            for uid, t in per.items():
                if user is not None and t.get("user") not in (None, user):
                    continue
                if t["status"] != "running" and now - t["updated"] > closed_within_s:
                    continue
                out["bg:" + uid] = _desc(t)
    return out


def running_ids(skey):
    with _lock:
        return [u for u, t in (_tasks.get(skey) or {}).items() if t["status"] == "running"]
