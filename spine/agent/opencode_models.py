# -*- coding: utf-8 -*-
"""What OpenCode can run RIGHT NOW, asked of OpenCode itself.

The hand-kept list (turnopts.OPENCODE_MODELS) went stale within weeks: measured
2026-10-08, four of its fourteen ids are unknown to the CLI (jev-1.13-free,
mimo-v2.5-free and both `opencode/deepseek-*` - DeepSeek is its OWN provider,
`deepseek/deepseek-flash`, connected by DEEPSEEK_API_KEY), and the quality-gate
fallback pointed at one of them. `opencode models` is the runtime's own answer
for the keys it was started with, so the catalog is DERIVED from it and the
hand list is only the seed for a box where the CLI is missing or silent.

  discover(account)  the CLI's list for THAT account's keys (cached, keyed by
                     which providers its keys connect - a replaced key lists the
                     same models). Never raises; None = could not ask.
  catalog(account)   discover() or the seed - what /engines serves.
  known_ids()        every id any account's discovery ever returned + the seed:
                     the model whitelist and engine_for() read this, persisted in
                     runtime_doc so a restart does not forget a picked model.
  fallback(account)  the quality-gate retry model: the cheap DeepSeek one WHEN
                     this account has a DeepSeek key, else "" (no retry) - never
                     a model that cannot run.
  test(account, provider, model)  ONE real minimal request through the CLI, so
                     "key set" becomes "key works": the CLI lists models for a
                     dummy key too, only a request proves it.

  MODEL PROBES (owner 2026-10-09: "ich will sehen, welche Modelle wirklich
  verfuegbar sind"): the CLI also lists models that cannot run (country block,
  deprecated ids). test() per MODEL, remembered per account:

  home: its OWN table `model_probe` (ledger 21), because a probe is per
    ACCOUNT x MODEL (keys and region differ per account) and expires - not
    `user_config` (view prefs, exported), not `runtime_doc` (global, survives
    an account delete), not `user_secret` (one row per PROVIDER, holds keys).

  ONE writer: record(). Callers: probe_model (the button / probe_all thread) and
  note_turn (a REAL turn that failed - event time, no polling). Readers derive
  `avail` {state ok|failed|untested|testing, reason, ms, at}: a result older
  than OK_TTL / FAIL_TTL reads as untested again (a constant, not a setting).
  The `testing` state is the in-process marker of probe_all's thread.
"""
import os
import re
import subprocess
import threading
import time

_TTL_HIT = 600.0
_TTL_MISS = 60.0
_DOC = "opencode_models"
_cache = {}                       # (account, provider-set) -> (expires, [model])
_cli_lock = threading.Lock()      # first starts of two CLIs collide on the sqlite migration (measured)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ID = re.compile(r"^[A-Za-z0-9._~-]+/\S+$")
FALLBACK_PREFERENCE = ("deepseek/deepseek-flash",)

PROVIDER_LABELS = {"opencode": "OpenCode Zen", "deepseek": "DeepSeek", "anthropic": "Anthropic",
                   "openai": "OpenAI", "openrouter": "OpenRouter"}


def _label(mid):
    prov, _, name = mid.partition("/")
    return name.lstrip("~") or mid


def _desc(mid):
    prov = mid.split("/", 1)[0]
    free = mid.endswith("-free") or mid == "opencode/big-pickle"
    return ("Free · " if free else "") + PROVIDER_LABELS.get(prov, prov)


def _env_for(account):
    env = dict(os.environ)
    try:
        from spine.storage import usersecrets
        env.update(usersecrets.env_for(account) if account else {})
    except Exception:                                            # noqa: BLE001
        pass
    return env


def _exe():
    from spine.agent import engines
    return engines.exe_for("opencode")


def _home():
    from spine.agent import opencode_driver
    return opencode_driver._opencode_home()


def parse(out):
    """`opencode models` stdout -> [{id,label,desc}], ids unique, order kept."""
    seen, res = set(), []
    for line in _ANSI.sub("", out or "").splitlines():
        line = line.strip()
        if _ID.match(line) and line not in seen:
            seen.add(line)
            res.append({"id": line, "label": _label(line), "desc": _desc(line)})
    return res


def discover(account=""):
    exe = _exe()
    if not exe:
        return None
    env = _env_for(account)
    try:
        from spine.storage import usersecrets
        sig = tuple(sorted(usersecrets.env_for(account))) if account else ()
    except Exception:                                            # noqa: BLE001
        sig = ()
    key = (account or "", sig)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return [dict(m) for m in hit[1]]
    models = None
    with _cli_lock:
        # a caller that queued here while another ran the CLI takes its answer
        # instead of running it again (N cold callers = one subprocess, not N
        # back to back - 2026-10-19, /engines piled up behind this lock)
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return [dict(m) for m in hit[1]] if hit[1] else None
        try:
            r = subprocess.run([exe, "models"], cwd=_home(), env=env, capture_output=True, text=True,
                               timeout=45, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                models = parse(r.stdout) or None
        except (OSError, subprocess.SubprocessError):
            models = None
        _cache[key] = (time.time() + (_TTL_HIT if models else _TTL_MISS), models or [])
    if models:
        _remember(models)
    return [dict(m) for m in models] if models else None


def catalog(account=""):
    """discover() or the seed, each model carrying `avail` (what a real request
    proved for THIS account - see the probe section below)."""
    from spine.agent import turnopts
    models = discover(account) or [dict(m) for m in turnopts.OPENCODE_MODELS]
    return annotate(account, models)


def _remember(models):
    try:
        from spine.storage import db
        have = set((db.doc_get(_DOC, {}) or {}).get("ids") or [])
        new = have | {m["id"] for m in models}
        if new != have:
            db.doc_put(_DOC, {"ids": sorted(new)})
    except Exception:                                            # noqa: BLE001
        pass


def known_ids(lower=True):
    """The seed + every id a discovery ever returned (persisted). Lower-cased
    for engine_for(); exact for the model whitelist."""
    from spine.agent import turnopts
    ids = {m["id"] for m in turnopts.OPENCODE_MODELS}
    try:
        from spine.storage import db
        ids |= set((db.doc_get(_DOC, {}) or {}).get("ids") or [])
    except Exception:                                            # noqa: BLE001
        pass
    return {i.lower() for i in ids} if lower else ids


def fallback(account=""):
    """The model a poor free reply is retried on - only one this account can run."""
    have = {m["id"] for m in (discover(account) or [])}
    for cand in FALLBACK_PREFERENCE:
        if cand in have:
            return cand
    return ""


def invalidate():
    _cache.clear()


# -- the real test -------------------------------------------------------------

_CHEAP = re.compile(r"(flash|mini|haiku|lite|lightning|free|pickle)", re.I)


def default_test_model(provider, models):
    mine = [m["id"] for m in models if m["id"].split("/", 1)[0] == provider]
    cheap = [i for i in mine if _CHEAP.search(i)]
    return (cheap or mine or [""])[0]


def classify(returncode, out, timed_out=False):
    """(status, reason) from one CLI request. status in ok|auth|country|missing|timeout|error."""
    o = _ANSI.sub("", out or "")
    low = o.lower()
    if timed_out:
        return "timeout", "no answer in time"
    if returncode == 0 and re.search(r"\bOK\b", o):
        return "ok", ""
    if "not available in your country" in low:
        return "country", "not available in your country"
    if "missing api key" in low or "unauthor" in low or "invalid api key" in low or re.search(r"401", low) or "authentication" in low:
        return "auth", "the key was refused"
    if "model not found" in low or "providermodelnotfounderror" in low:
        return "missing", "the CLI does not know this model"
    if returncode == 0:
        return "ok", "answered without the expected word"
    return "error", re.sub(r"\s+", " ", o).strip()[:160]


def test(account, provider, model=""):
    """ONE minimal request on `provider` with THIS account's key. Returns
    {ok, status, reason, model, ms}. Costs a few tokens on the account's own key
    (nothing for a free model) - which is why it runs on a button, never on a poll."""
    exe = _exe()
    if not exe:
        return {"ok": False, "status": "error", "reason": "OpenCode is not installed", "model": model, "ms": 0}
    models = discover(account) or []
    model = model or default_test_model(provider, models)
    if not model:
        return {"ok": False, "status": "missing", "reason": "no model for this provider is listed (is the key set?)",
                "model": "", "ms": 0}
    t0 = time.time()
    timed_out, rc, out = False, 1, ""
    with _cli_lock:
        try:
            r = subprocess.run([exe, "run", "--model", model, "Antworte nur mit dem Wort OK."],
                               cwd=_home(), env=_env_for(account), capture_output=True, text=True, timeout=80,
                               encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            rc, out = r.returncode, (r.stdout or "") + " " + (r.stderr or "")
        except subprocess.TimeoutExpired:
            timed_out = True
        except (OSError, subprocess.SubprocessError) as e:
            out = str(e)
    status, reason = classify(rc, out, timed_out)
    return {"ok": status == "ok", "status": status, "reason": reason, "model": model,
            "ms": int((time.time() - t0) * 1000)}


# -- per-model probes ----------------------------------------------------------

OK_TTL = 6 * 3600.0          # a proven model is trusted this long
FAIL_TTL = 30 * 60.0         # a failure is re-offered for a retry sooner (keys get fixed, regions change)
_REASONS = {"country": "not available in your country", "auth": "the key was refused",
            "missing": "the CLI does not know this model", "timeout": "no answer in time"}
_run_lock = threading.Lock()
_running = {}                # account -> {"done": n, "total": m, "current": model_id}


def _rows(account):
    from spine.storage import db
    return {r[0]: r for r in db.conn().execute(
        "SELECT model_id,status,reason,ms,tested_at FROM model_probe WHERE user=?", (account or "",)).fetchall()}


def _avail(row, now, testing=False):
    if testing:
        return {"state": "testing"}
    if row:
        ok = row[1] == "ok"
        if now - row[4] < (OK_TTL if ok else FAIL_TTL):
            a = {"state": "ok" if ok else "failed", "ms": row[3], "at": row[4]}
            if not ok:
                a["status"], a["reason"] = row[1], row[2]
            return a
    return {"state": "untested"}


def avail_map(account, ids=None):
    """{model_id: avail} for this account (all probed ones, or `ids`)."""
    now = time.time()
    rows = _rows(account)
    cur = (_running.get(account or "") or {}).get("current")
    return {mid: _avail(rows.get(mid), now, testing=(mid == cur))
            for mid in (ids if ids is not None else rows)}


def annotate(account, models):
    amap = avail_map(account, [m["id"] for m in models])
    for m in models:
        m["avail"] = dict(amap[m["id"]])
    return models


def failed_ids(account):
    return {m for m, a in avail_map(account).items() if a["state"] == "failed"}


def record(account, model_id, result):
    """THE one writer of model_probe. `result` is test()'s shape. bump(): the
    app learns of it from the daemon's event stream and reloads."""
    from spine.storage import db
    status = str(result.get("status") or "error")[:16]
    reason = str(result.get("reason") or _REASONS.get(status, ""))[:200]
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO model_probe(user,model_id,status,reason,ms,tested_at) VALUES(?,?,?,?,?,?)",
                  (account or "", str(model_id)[:200], status, reason, int(result.get("ms") or 0), time.time()))
    db.bump(topic="models")


def drop_user(account):
    """Called from auth.delete_user: rows key on the NAME."""
    from spine.storage import db
    with db.conn() as c:
        return c.execute("DELETE FROM model_probe WHERE user=?", (account or "",)).rowcount


def probe_model(account, model_id):
    """ONE real request on this model (sequential through _cli_lock), persisted.
    Never raises. Returns the avail dict."""
    provider = model_id.split("/", 1)[0]
    try:
        res = test(account, provider, model_id)
    except Exception as e:                                       # noqa: BLE001
        res = {"ok": False, "status": "error", "reason": str(e)[:160], "model": model_id, "ms": 0}
    record(account, model_id, res)
    return avail_map(account, [model_id])[model_id]


def progress(account):
    """{"running", "done", "total"} for the UI's "3/9"."""
    with _run_lock:
        p = _running.get(account or "")
        return {"running": True, "done": p["done"], "total": p["total"]} if p else \
            {"running": False, "done": 0, "total": 0}


def probe_all(account, only_untested=False, models=None):
    """Start a SEQUENTIAL background probe of this account's OpenCode models.
    False if one already runs for the account (idempotent button) or there is
    nothing to probe. The request thread (bound to 8s/20s) returns at once;
    every finished model bumps the version via record()."""
    account = account or ""
    ids = list(models) if models else [m["id"] for m in (discover(account) or [])]
    if only_untested:
        cur = avail_map(account, ids)
        ids = [i for i in ids if cur[i]["state"] == "untested"]
    if not ids:
        return False
    with _run_lock:
        if account in _running:
            return False
        _running[account] = {"done": 0, "total": len(ids), "current": ""}

    def _run():
        from spine.storage import db
        try:
            for mid in ids:
                with _run_lock:
                    _running[account]["current"] = mid
                db.bump(topic="models")
                probe_model(account, mid)
                with _run_lock:
                    _running[account]["done"] += 1
        finally:
            with _run_lock:
                _running.pop(account, None)
            db.bump(topic="models")
    threading.Thread(target=_run, daemon=True, name="model-probe").start()
    return True


def note_turn(account, model_id, error_text):
    """EVENT TIME: a real turn on `model_id` failed. If the error classifies as
    a verdict about the MODEL (country / auth / missing) it lands on the same
    row the button writes; a transient error proves nothing and writes nothing."""
    if not model_id or "/" not in str(model_id):
        return
    status, reason = classify(1, error_text or "")
    if status in ("country", "auth", "missing"):
        record(account, model_id, {"status": status, "reason": reason, "ms": 0})
