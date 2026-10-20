# -*- coding: utf-8 -*-
"""Henry's board verbs as a TOOL he calls INSIDE his turn (ops/tools/henry_act.py).

Why (2026-10-20, a night of empty processes): the ```actions block runs AFTER
his turn on another thread, and the result reaches him a whole turn later. A
two-step job ("file the process, then attach its cards to the id") cannot be
done blind in one turn, and the hands/broker runs - which had Bash but no verb
catalog - wrote the store directly instead. This module is the ONE executor
behind both paths: the same _run_action, the same role gates, the same chat
rows; only the moment differs (now, with the answer back).

home of the credential: daemon MEMORY (a token per spawned Henry process,
valid only while that pid lives), because it is a process credential, not data
at rest - not the db (nothing to protect across a restart: a new daemon
respawns every Henry process and mints fresh ones), not settings.json (a
secret in a file is the failure the data-model law names). The token carries
WHO (account) and WHERE (conversation key, surface); the ROLE and whether this
turn may act are read live from the turn the daemon is running for that key
(set_turn/clear_turn, one owner: copilot._chat), never taken from the caller.
"""
import json
import re
import secrets
import threading
import time

MAX_BATCH = 12            # verbs in one call
MAX_CALLS_PER_TURN = 25   # calls per turn: bounds a loop, not honest work

_lock = threading.Lock()
_tokens = {}              # token -> {account, skey, surface, pid, role}
_turns = {}               # skey -> {role, allow_actions, card, card_run_dir, owner_msg, calls}

_REF = re.compile(r"\$(\d+)\.([a-z_]+)")


def new_token():
    """The secret goes into the child's ENV before it exists (no pid yet);
    register() binds it to the pid right after Popen."""
    return secrets.token_urlsafe(24)


def register(tok, account, skey, surface, pid, role="owner"):
    if not pid:
        return
    with _lock:
        for t in [t for t, e in _tokens.items() if e["pid"] == pid]:
            _tokens.pop(t, None)
        _tokens[tok] = {"account": account, "skey": skey, "surface": surface,
                        "pid": pid, "role": role, "born": time.time()}


def env_for(tok):
    """The two variables the CLI (ops/tools/henry_act.py) reads."""
    return {"HELMDECK_ACT_TOKEN": tok, "HELMDECK_ACT_URL": "http://127.0.0.1:8140"}


def _alive(pid):
    from spine.ops import procwatch
    return procwatch.exists(pid)


def resolve(token):
    with _lock:
        e = _tokens.get(token or "")
    if not e:
        return None
    if not _alive(e["pid"]):
        with _lock:
            _tokens.pop(token, None)
        return None
    return e


def set_turn(skey, role, allow_actions, card=None, card_run_dir=None, owner_msg=""):
    """The turn the daemon is running for this conversation - what a tool call
    from its process is allowed to do. Called at turn start by copilot._chat."""
    with _lock:
        _turns[skey] = {"role": role, "allow_actions": bool(allow_actions), "card": card,
                        "card_run_dir": card_run_dir, "owner_msg": owner_msg or "", "calls": 0}


def clear_turn(skey):
    with _lock:
        _turns.pop(skey, None)


def _ctx(entry):
    """The context a call runs under. A chat process needs a live turn; a judge
    or hands process acts for the account it was spawned for."""
    if entry["surface"] == "chat":
        with _lock:
            t = _turns.get(entry["skey"])
        return t
    return {"role": entry["role"], "allow_actions": True, "card": None, "card_run_dir": None,
            "owner_msg": "", "calls": 0}


def _subst(val, ids):
    """$N.field -> the id the Nth verb of THIS call produced. A reference to a
    verb that produced none raises KeyError (the caller skips that verb)."""
    if isinstance(val, str):
        def rep(m):
            got = (ids.get(int(m.group(1))) or {}).get(m.group(2))
            if got is None:
                raise KeyError(m.group(0))
            return str(got)
        return _REF.sub(rep, val)
    if isinstance(val, list):
        return [_subst(v, ids) for v in val]
    if isinstance(val, dict):
        return {k: _subst(v, ids) for k, v in val.items()}
    return val


def _ids_of(a):
    """The ids a verb produced, as RECORDED on the action by its own handler
    (copilot_actions._tag / new_process) - never parsed back out of prose."""
    out = {}
    for src, name in (("_card", "card"), ("_process", "process"), ("_hands", "hands"),
                      ("_run", "run"), ("_template", "template")):
        if a.get(src):
            out[name] = a[src]
    if out:
        out["id"] = out.get("card") or out.get("process") or out.get("template") \
            or out.get("hands") or out.get("run")
    return out


def run(entry, payload):
    """(http status, body dict). Executes the verbs in order, in this call."""
    ctx = _ctx(entry)
    if ctx is None:
        return 409, {"error": "no running turn for this conversation - the tool works "
                              "inside a turn; between turns use the ```actions block"}
    if not ctx["allow_actions"]:
        return 403, {"error": "advisory surface: board actions are not run here"}
    acts = payload.get("actions") if isinstance(payload, dict) and "actions" in payload else payload
    if isinstance(acts, dict):
        acts = [acts]
    if not isinstance(acts, list) or not acts or not all(isinstance(a, dict) for a in acts):
        return 400, {"error": "send one verb {\"type\": ...} or a list of them"}
    if len(acts) > MAX_BATCH:
        return 400, {"error": "at most %d verbs per call (got %d)" % (MAX_BATCH, len(acts))}
    with _lock:
        ctx["calls"] = ctx.get("calls", 0) + 1
        n_calls = ctx["calls"]
    if n_calls > MAX_CALLS_PER_TURN:
        return 429, {"error": "%d calls in this turn - hand the rest off (card / agent) and "
                              "end the turn" % MAX_CALLS_PER_TURN}
    from cells.copilot.chat import copilot, copilot_actions
    account, role = entry["account"], ctx["role"]
    card, run_dir = ctx.get("card"), ctx.get("card_run_dir")
    ids, results = {}, []
    for i, a in enumerate(acts, 1):
        try:
            a = _subst(a, ids)
        except KeyError as e:
            res = "skipped: %s - an earlier verb of this call produced no such id" % e
            results.append({"n": i, "type": a.get("type"), "result": res, "ids": {}})
            continue
        if card:
            if a.get("type") == "hands" and not a.get("card"):
                a["card"] = card
            if a.get("type") in ("file_card", "direct_task") and not a.get("_origin_card"):
                a["_origin_card"] = card
        try:
            res = copilot_actions._run_action(a, account, role, owner_msg=ctx.get("owner_msg") or "")
        except Exception as e:                               # noqa: BLE001
            res = "action failed: %s" % str(e)[:200]
        got = _ids_of(a)
        ids[i] = got
        results.append({"n": i, "type": a.get("type"), "result": res, "ids": got})
        # the owner's screen: the same row the post-turn path writes
        try:
            if run_dir:
                from spine.agent import timeline_store as _ts
                import uuid
                _ts.append(run_dir, "s:" + uuid.uuid4().hex,
                           {"kind": "note", "text": res, "byKind": "henry",
                            "ts": time.strftime("%H:%M:%S"), "ta": time.time()})
            else:
                copilot._append_log(account, [dict(
                    {"cls": "act", "text": res},
                    **({"card": a.get("_card"), "cardName": a.get("_card_name")} if a.get("_card") else {}),
                    **({"hands": a["_hands"]} if a.get("_hands") else {}),
                    **({"run": a["_run"]} if a.get("_run") else {}))])
        except Exception:                                    # noqa: BLE001
            pass
    return 200, {"results": results}


def act_post(handler, body):
    """POST /henry/act - before the session gate (like /mcp): authorized ONLY by
    the process token in X-Henry-Act-Token, from this machine."""
    ip = (handler.client_address or ("",))[0]
    if ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return handler._send(403, json.dumps({"error": "local only"}))
    entry = resolve(handler.headers.get("X-Henry-Act-Token") or "")
    if not entry:
        return handler._send(401, json.dumps({"error": "no valid act token (this process was not "
                                                       "spawned by the daemon, or it ended)"}))
    status, doc = run(entry, body)
    return handler._send(status, json.dumps(doc, ensure_ascii=False))
