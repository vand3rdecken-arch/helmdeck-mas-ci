# -*- coding: utf-8 -*-
"""In-flight turn state: the streaming partial, the current tool status, the
thinking tail - and the session id the CLI rotated to mid-turn.

Until state-into-db phase I (2026-09-12) each of these was a small text file
next to the run's media (run_dir/live_partial.txt, live_session.txt; the
board chat's copilot_runs/<user>/live_*.txt), written by the driver's pump
every ~150 ms and re-read by the transcript long-poll every ~350 ms in the
SAME process. A file was the wrong shape twice over:

  * the partial/thinking/status are per-turn scratch - they mean nothing
    after the turn and nothing after a restart - so they live in a process-
    local registry here, keyed by the run id (a card's id) or "copilot:<user>";
  * the session id is NOT scratch: a turn that is hard-killed (restart,
    timeout) leaves the card pointing at the PRE-steer session, and
    lifecycle._promote_live_session needs the rotated id AFTER the crash to
    resume the right conversation. That one is a runtime_doc row
    ("live_session:<key>"), written by exactly one owner - the driver, at the
    moment the CLI announces the id - and cleared when the turn ends. It used
    to be a SECOND owner of the session pointer on disk; now it is the
    driver's observation in the store, and sessions.resume_detached still
    advances the card's own pointer only on proof.

Best-effort everywhere: a live-state write must never break a turn."""
import threading

_lock = threading.Lock()
_buf = {}           # key -> {"partial": str, "thinking": str, "status": str}
_SESSION_PREFIX = "live_session:"


def set_field(key, name, text):
    if not key:
        return
    with _lock:
        _buf.setdefault(key, {})[name] = text or ""


def get_field(key, name, default=""):
    if not key:
        return default
    with _lock:
        return (_buf.get(key) or {}).get(name, default)


def set_partial(key, text):
    set_field(key, "partial", text)


def get_partial(key):
    return get_field(key, "partial", "")


def clear(key):
    """Turn ended: drop every in-flight field AND the rotated session id."""
    if not key:
        return
    with _lock:
        _buf.pop(key, None)
    try:
        from spine.storage import db
        with db.conn() as c:
            c.execute("DELETE FROM runtime_doc WHERE key=?", (_SESSION_PREFIX + key,))
    except Exception:                                            # noqa: BLE001
        pass


def set_session(key, sid):
    """The CLI rotated to `sid` for this run - durable, one owner."""
    if not key or not sid:
        return
    try:
        from spine.storage import db
        db.doc_put(_SESSION_PREFIX + key, {"sid": sid})
    except Exception:                                            # noqa: BLE001
        pass


def get_session(key):
    if not key:
        return None
    try:
        from spine.storage import db
        d = db.doc_get(_SESSION_PREFIX + key) or {}
        return (d.get("sid") or "").strip() or None
    except Exception:                                            # noqa: BLE001
        return None


def _reset_for_tests():
    with _lock:
        _buf.clear()
