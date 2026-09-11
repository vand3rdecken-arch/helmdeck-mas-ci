# -*- coding: utf-8 -*-
"""Unit tests for relay_client._push (relay-push-resilience Phase B): the
daemon-side retry helper for POST /tunnel/push. SELF-SANDBOXING: events.SET
and the db are redirected into a tempdir before anything runs - _push logs
via events.log on give-up/recovery, and patching events.SET alone stopped
sandboxing anything since the config-consolidation move to the DB (see
test_pairing_lifecycle.py's header, memory helmdeck-config-consolidation).
`urllib.request.urlopen` is monkeypatched at relay_client's own module
scope (never the stdlib global) and `time.sleep` is a no-op so the retry
backoff (1s, 3s) doesn't slow the suite down.

Run: py -3.12 ops/tests/test_relay_client_push.py
"""
import os, sys, tempfile, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spine.storage import db, events  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="helmdeck-pushtest-")
_old_conn = getattr(db._local, "c", None)
if _old_conn is not None:
    _old_conn.close()
    db._local.c = None
db.ROOT = _TMP
db.DBPATH = os.path.join(_TMP, "helmdeck.db")
events.SET = os.path.join(_TMP, "settings.json")
events.EV = os.path.join(_TMP, "events.jsonl")
db.init()
assert db.DBPATH.startswith(_TMP), "REFUSING TO RUN: db not sandboxed"

from spine.comms import relay_client as rc  # noqa: E402  (after the sandbox redirect)

FAILS = []


def check(name, cond, note=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" - " + note) if note else ""))
    if not cond:
        FAILS.append(name)


rc.time.sleep = lambda *_a, **_k: None   # skip the 1s/3s retry backoff

_log_calls = []


def _fake_log(kind, msg):
    _log_calls.append((kind, msg))


class _FakeResp:
    def __init__(self, status):
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _patch_urlopen(fn):
    rc.urllib.request.urlopen = fn


# events.log is imported LAZILY inside _push_recovered/_push_giveup via
# `from spine.storage import events` - patch the attribute on the real
# module object so every such lazy import resolves to our fake.
import spine.storage.events as _events_mod  # noqa: E402
_events_mod.log = _fake_log


def _reset():
    global _log_calls
    _log_calls = []
    rc._push_fails = 0

# -- 1) URLError, URLError, then 200 -> 3 calls, True, ONE recovery log ----
_reset()
calls = {"n": 0}
def _flaky_then_ok(req, timeout=None):
    calls["n"] += 1
    if calls["n"] < 3:
        raise urllib.error.URLError("connection reset")
    return _FakeResp(200)
_patch_urlopen(_flaky_then_ok)
ok = rc._push("https://relay.example", "room1", "frame-aaaa", "cipher")
check("flaky-then-ok: 3 urlopen calls", calls["n"] == 3, str(calls["n"]))
check("flaky-then-ok: returns True", ok is True)
check("flaky-then-ok: exactly one log call", len(_log_calls) == 1, str(_log_calls))
check("flaky-then-ok: log says delivered after 2 retry(s)",
      _log_calls and "delivered after 2 retry(s)" in _log_calls[0][1], str(_log_calls))

# -- 2) HTTP 400 -> 1 call, False, no retry, ONE rejection log -------------
_reset()
calls = {"n": 0}
def _rejected(req, timeout=None):
    calls["n"] += 1
    raise urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
_patch_urlopen(_rejected)
ok2 = rc._push("https://relay.example", "room1", "frame-bbbb", "cipher")
check("rejected: exactly 1 urlopen call (no retry)", calls["n"] == 1, str(calls["n"]))
check("rejected: returns False", ok2 is False)
check("rejected: exactly one log call", len(_log_calls) == 1, str(_log_calls))
check("rejected: log mentions HTTP 400", _log_calls and "HTTP 400" in _log_calls[0][1], str(_log_calls))

# -- 3) 3x URLError -> False, exactly one "push lost" log ------------------
_reset()
calls = {"n": 0}
def _always_fails(req, timeout=None):
    calls["n"] += 1
    raise urllib.error.URLError("connection reset")
_patch_urlopen(_always_fails)
ok3 = rc._push("https://relay.example", "room1", "frame-cccc", "cipher")
check("exhausted: 3 urlopen calls", calls["n"] == 3, str(calls["n"]))
check("exhausted: returns False", ok3 is False)
check("exhausted: exactly one log call", len(_log_calls) == 1, str(_log_calls))
check("exhausted: log says push lost", _log_calls and "push lost" in _log_calls[0][1], str(_log_calls))

# -- 4) 30 consecutive lost frames -> capped at first-then-every-10th ------
_reset()
_patch_urlopen(_always_fails)
for i in range(30):
    calls["n"] = 0
    rc._push("https://relay.example", "room1", "frame-%04d" % i, "cipher")
check("30 lost frames -> 4 log calls (1st, 10th, 20th, 30th)", len(_log_calls) == 4, str(len(_log_calls)))
give_up_lines = [m for _, m in _log_calls]
check("all 4 are push-lost lines", all("push lost" in m for m in give_up_lines), str(give_up_lines))

print()
print("ALL PASS" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
