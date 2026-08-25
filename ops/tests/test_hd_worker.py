# -*- coding: utf-8 -*-
"""Unit test for ops/tools/hd_worker.py's Phase B resilience (PLAN-hardening.md):
bounded exponential backoff on TRANSIENT failures (connection errors, 5xx),
immediate un-retried raise on a real refusal (4xx). Monkeypatches
urllib.request.urlopen with a scripted sequence of outcomes rather than a
real HTTP server - deterministic, no port binding, no real backoff waits
(base_delay is set tiny for the test so it runs in well under a second).

Run: py -3.12 ops/tests/test_hd_worker.py
"""
import importlib.util
import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def _load_worker():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "hd_worker.py")
    spec = importlib.util.spec_from_file_location("hd_worker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")
    def read(self):
        return self._data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def main():
    hd = _load_worker()
    calls = []

    # -- 1: transient failures then success -----------------------------------
    print("\n_api: transient (connection/5xx) failures retry, then succeed")
    script = [urllib.error.URLError("connection refused"),
             urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b"")),
             _FakeResp({"ok": True})]
    def fake_urlopen(req, timeout=30):
        calls.append(1)
        outcome = script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    orig = hd.urllib.request.urlopen
    hd.urllib.request.urlopen = fake_urlopen
    try:
        result = hd._api("http://x", "/p", "tok", retries=5, base_delay=0.01, max_delay=0.02)
        ok(result == {"ok": True}, "eventually succeeds after 2 transient failures")
        ok(len(calls) == 3, "made exactly 3 attempts (2 failed + 1 success)")
    finally:
        hd.urllib.request.urlopen = orig

    # -- 2: a 4xx is a real refusal, never retried -----------------------------
    print("\n_api: a 4xx is NOT retried")
    calls.clear()
    def fake_urlopen_4xx(req, timeout=30):
        calls.append(1)
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(b'{"error":"nope"}'))
    hd.urllib.request.urlopen = fake_urlopen_4xx
    try:
        try:
            hd._api("http://x", "/p", "tok", retries=5, base_delay=0.01, max_delay=0.02)
            ok(False, "a 4xx should raise")
        except RuntimeError as e:
            ok("403" in str(e), "raises with the real status code")
        ok(len(calls) == 1, "exactly ONE attempt - a refusal is not retried")
    finally:
        hd.urllib.request.urlopen = orig

    # -- 3: retries are bounded, not infinite ----------------------------------
    print("\n_api: retries are bounded")
    calls.clear()
    def fake_urlopen_always_down(req, timeout=30):
        calls.append(1)
        raise urllib.error.URLError("still down")
    hd.urllib.request.urlopen = fake_urlopen_always_down
    try:
        try:
            hd._api("http://x", "/p", "tok", retries=4, base_delay=0.01, max_delay=0.02)
            ok(False, "a persistently-down daemon should eventually raise")
        except RuntimeError:
            ok(True, "raises after exhausting retries rather than hanging forever")
        ok(len(calls) == 4, "made exactly `retries` attempts, no more")
    finally:
        hd.urllib.request.urlopen = orig

    # -- 4: main loop backoff pacing -------------------------------------------
    print("\n_backoff_delay: grows with consecutive failures, stays capped")
    d0 = hd._backoff_delay(0, base=2.0, cap=60.0)
    d5 = hd._backoff_delay(5, base=2.0, cap=60.0)
    d20 = hd._backoff_delay(20, base=2.0, cap=60.0)
    ok(d0 < d5, "backoff grows with more consecutive failures")
    ok(d20 <= 60.0 * 1.0 + 0.01, "backoff never exceeds the cap even after many failures")

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green")


if __name__ == "__main__":
    main()
