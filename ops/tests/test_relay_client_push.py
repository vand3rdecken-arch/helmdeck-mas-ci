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

# -- 5) 400 "truncated body" is TRANSPORT: retried, then delivered ----------
# relay.py's own verdict that the upload never fully arrived (measured
# 2026-09-11 18:28: a 1.96 MB board reply cut at 720 KB). Before: any 4xx was
# "our bug", no retry, the frame - and the phone's board - was simply lost.
class _Body:
    def __init__(self, b): self._b = b
    def read(self): return self._b
    def close(self): pass

class _BodyResp(_FakeResp):
    def __init__(self, status, body):
        _FakeResp.__init__(self, status); self._b = body
    def read(self): return self._b

_reset()
calls = {"n": 0}
def _truncated_then_ok(req, timeout=None):
    calls["n"] += 1
    if calls["n"] == 1:
        raise urllib.error.HTTPError("url", 400, "Bad Request", {}, _Body(b'{"error": "truncated body"}'))
    return _FakeResp(200)
_patch_urlopen(_truncated_then_ok)
ok5 = rc._push("https://relay.example", "room1", "frame-eeee", "cipher")
check("truncated-400 then 200: 2 urlopen calls (retried)", calls["n"] == 2, str(calls["n"]))
check("truncated-400 then 200: delivered", ok5 is True, str(ok5))
check("truncated-400: no 'rejected' log", not any("rejected" in m for _, m in _log_calls), str(_log_calls))

# a plain 400 with another body is still OUR bug - unchanged, no retry
_reset()
calls = {"n": 0}
def _rejected_body(req, timeout=None):
    calls["n"] += 1
    raise urllib.error.HTTPError("url", 400, "Bad Request", {}, _Body(b'{"error": "bad room"}'))
_patch_urlopen(_rejected_body)
ok6 = rc._push("https://relay.example", "room1", "frame-ffff", "cipher")
check("other 400: exactly 1 call, not delivered", calls["n"] == 1 and ok6 is False, "%s %s" % (calls["n"], ok6))

# -- 6) the upload timeout scales with the frame ---------------------------
_reset()
seen = {}
def _capture_timeout(req, timeout=None):
    seen["t"] = timeout
    seen["n"] = len(req.data or b"")
    return _FakeResp(200)
_patch_urlopen(_capture_timeout)
rc._push("https://relay.example", "room1", "frame-small", "x")
small = seen["t"]
rc._push("https://relay.example", "room1", "frame-big", "x" * (2 * 1024 * 1024))
big = seen["t"]
check("small frame keeps the 15 s floor", small == rc.PUSH_TIMEOUT_BASE, str(small))
check("a 2 MB frame gets ~20 s more", big >= rc.PUSH_TIMEOUT_BASE + 20, "%s (bytes %s)" % (big, seen["n"]))

# -- 7) loopback only when PROVEN: same instance id on both /health ---------
def _health_map(mapping):
    def fn(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        for prefix, body in mapping.items():
            if url.startswith(prefix):
                if body is None:
                    raise urllib.error.URLError("down")
                return _BodyResp(200, body)
        raise urllib.error.URLError("unknown " + url)
    return fn
LOCAL = "http://127.0.0.1:%d" % rc.LOCAL_RELAY_PORT
PUB = "https://relay.example"
def _fresh():
    rc._base_cache.update(ts=0.0, public=None, base=None)
_fresh(); _patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: b'{"ok": true, "instance": "abc"}'}))
check("same instance on both -> loopback", rc._resolve_base(PUB) == LOCAL, rc._resolve_base(PUB))
_fresh(); _patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: b'{"ok": true, "instance": "zzz"}'}))
check("different instance -> public URL", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))
_fresh(); _patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: None}))
check("public unreachable -> cannot prove -> public URL (fail-safe)", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))
_fresh(); _patch_urlopen(_health_map({LOCAL: b'{"ok": true}', PUB: b'{"ok": true}'}))
check("older relay without instance id -> public URL", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))
_fresh(); _patch_urlopen(_health_map({LOCAL: None, PUB: b'{"ok": true, "instance": "abc"}'}))
check("no local relay -> public URL", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))
# cached: a second call inside the TTL must not probe again
_fresh(); probes = {"n": 0}
def _counting(req, timeout=None):
    probes["n"] += 1
    return _BodyResp(200, b'{"ok": true, "instance": "abc"}')
_patch_urlopen(_counting)
rc._resolve_base(PUB); rc._resolve_base(PUB)
check("verdict cached within the TTL (2 probes, not 4)", probes["n"] == 2, str(probes["n"]))
# STICKY once proven (owner 2026-09-13/14: the public probe crosses the
# Cloudflare tunnel; when it hiccuped the bridge fell back to the tunnel and
# every phone request went "read timed out" / "push lost frame"). A proven
# loopback survives a FAILED public probe as long as the local relay still
# reports the same instance id - but NOT a public relay that answers with a
# different id, and NOT a relay restart (new local id).
_fresh(); _patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: b'{"ok": true, "instance": "abc"}'}))
rc._resolve_base(PUB)                                     # proves abc
rc._base_cache["ts"] = 0.0                                 # expire the TTL, keep the proof
_patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: None}))
check("public unreachable AFTER a proven match -> stays LOOPBACK", rc._resolve_base(PUB) == LOCAL, rc._resolve_base(PUB))
rc._base_cache["ts"] = 0.0
_patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: b'{"ok": true, "instance": "zzz"}'}))
check("public answers with a DIFFERENT id -> public URL, proof cleared", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))
rc._base_cache["ts"] = 0.0
_patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: None}))
check("...and the cleared proof does not resurrect loopback", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))
_fresh(); _patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "abc"}', PUB: b'{"ok": true, "instance": "abc"}'}))
rc._resolve_base(PUB); rc._base_cache["ts"] = 0.0
_patch_urlopen(_health_map({LOCAL: b'{"ok": true, "instance": "new1"}', PUB: None}))
check("local relay restarted (new id) + public down -> public URL (proof is per instance)", rc._resolve_base(PUB) == PUB, rc._resolve_base(PUB))

print()
print("ALL PASS" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
