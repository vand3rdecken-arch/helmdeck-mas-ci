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
import tempfile
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

    # -- 5: _run_turn_locally parses --output-format json into usage_meta -----
    print("\n_run_turn_locally: usage_meta parsed from --output-format json")
    class _FakeCompleted:
        def __init__(self, returncode, stdout, stderr=""):
            self.returncode = returncode; self.stdout = stdout; self.stderr = stderr
    orig_run = hd.subprocess.run
    good_json = json.dumps({
        "result": "did the thing", "total_cost_usd": 0.0234,
        "usage": {"input_tokens": 500, "output_tokens": 200},
        "modelUsage": {"claude-sonnet-5": {}},
    })
    hd.subprocess.run = lambda *a, **kw: _FakeCompleted(0, good_json)
    try:
        reply, meta = hd._run_turn_locally("C:/fake/repo", "br", "task", "")
        ok(reply == "did the thing", "reply text extracted from the JSON result field")
        ok(meta is not None and meta["cost_usd"] == 0.0234,
           "cost_usd captured from total_cost_usd")
        ok(meta["usage"] == {"input_tokens": 500, "output_tokens": 200},
           "usage dict captured verbatim")
        ok(meta["models"] == ["claude-sonnet-5"],
           "models list derived from modelUsage KEYS - same shape drivers.py itself parses")
    finally:
        hd.subprocess.run = orig_run

    # a non-JSON / unrecognized stdout must not crash the turn - it just
    # carries no usage_meta (cost reporting is best-effort, never a blocker).
    hd.subprocess.run = lambda *a, **kw: _FakeCompleted(0, "not json at all")
    try:
        reply, meta = hd._run_turn_locally("C:/fake/repo", "br", "task", "")
        ok(reply == "not json at all" and meta is None,
           "unparseable stdout falls back to raw text, usage_meta=None, no crash")
    finally:
        hd.subprocess.run = orig_run

    hd.subprocess.run = lambda *a, **kw: _FakeCompleted(1, "", "boom")
    try:
        try:
            hd._run_turn_locally("C:/fake/repo", "br", "task", "")
            ok(False, "a non-zero claude exit should raise")
        except RuntimeError:
            ok(True, "a failed claude turn still raises (unrelated to JSON parsing)")
    finally:
        hd.subprocess.run = orig_run

    # -- 6: DeviceRevoked - a 404 on the device's OWN queue stops the worker --
    print("\nDeviceRevoked: 404 on /devices/<id>/queue is not a transient failure")
    def fake_api_404(daemon, path, token, method="GET", body=None):
        raise RuntimeError("HTTP 404 on %s: not found" % path)
    orig_api = hd._api
    hd._api = fake_api_404
    try:
        try:
            hd.process_one("http://x", "dev1", "tok", "C:/fake/repo")
            ok(False, "process_one should raise DeviceRevoked on a 404 queue poll")
        except hd.DeviceRevoked as e:
            ok("dev1" in str(e), "DeviceRevoked names the device")
        except RuntimeError:
            ok(False, "raised plain RuntimeError instead of the more specific DeviceRevoked")
    finally:
        hd._api = orig_api

    # a 5xx/connection error on the SAME call must NOT be mistaken for revoke.
    def fake_api_500(daemon, path, token, method="GET", body=None):
        raise RuntimeError("HTTP 502 on %s: bad gateway" % path)
    hd._api = fake_api_500
    try:
        try:
            hd.process_one("http://x", "dev1", "tok", "C:/fake/repo")
            ok(False, "should raise")
        except hd.DeviceRevoked:
            ok(False, "a transient 5xx must NOT be classified as DeviceRevoked")
        except RuntimeError:
            ok(True, "a transient failure stays a plain RuntimeError (retryable)")
    finally:
        hd._api = orig_api

    # -- 7: config-file merge (argv wins on overlap) ---------------------------
    print("\n_resolve_config / _load_config")
    cfg_path = os.path.join(tempfile.mkdtemp(prefix="hd-worker-cfg-"), "worker.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"daemon": "https://cfg-daemon", "device": "cfg-dev",
                  "token": "cfg-tok", "repo": "C:/cfg-repo"}, f)
    loaded = hd._load_config(cfg_path)
    ok(loaded["daemon"] == "https://cfg-daemon", "_load_config reads the JSON file")

    d, dev, tok, r, missing = hd._resolve_config(None, None, None, None, loaded)
    ok((d, dev, tok, r) == ("https://cfg-daemon", "cfg-dev", "cfg-tok", "C:/cfg-repo"),
       "with no argv, every value comes from the config file")
    ok(missing == [], "nothing missing when the config supplies everything")

    d, dev, tok, r, missing = hd._resolve_config(
        "https://argv-daemon", None, None, None, loaded)
    ok(d == "https://argv-daemon" and dev == "cfg-dev",
       "an explicit argv value WINS over the config file for that field only")

    d, dev, tok, r, missing = hd._resolve_config(None, None, None, None, {})
    ok(len(missing) == 4, "with neither argv nor config, all 4 required values are missing")
    ok("--daemon/config daemon" in missing[0] or any("--daemon" in m for m in missing),
       "missing list names WHICH values are absent, not just that something is")

    # -- 8: _run_turn_locally interrupt (Phase E) ------------------------------
    print("\n_run_turn_locally: still_mine=False mid-turn kills the subprocess")
    # a fake long-running child: a python one-liner that sleeps. still_mine
    # flips to False after the first poll, so the watcher must kill it and
    # raise TurnInterrupted well before the sleep would finish.
    import subprocess as _sp
    polls = {"n": 0}
    def still_mine_flip():
        polls["n"] += 1
        return polls["n"] < 1   # False from the very first check
    orig_popen = hd.subprocess.Popen
    killed = {"done": False}
    class _FakeProc:
        def __init__(self):
            self.pid = -1
            self.returncode = None
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self._waits = 0
        def wait(self, timeout=None):
            self._waits += 1
            raise _sp.TimeoutExpired("claude", timeout)   # never finishes on its own
    fake = _FakeProc()
    hd.subprocess.Popen = lambda *a, **kw: fake
    orig_treekill = hd._tree_kill
    hd._tree_kill = lambda proc: killed.__setitem__("done", True)
    try:
        try:
            hd._run_turn_locally("C:/fake/repo", "br", "task", "",
                                still_mine=still_mine_flip, poll_interval=0.01)
            ok(False, "a still_mine that goes False should raise TurnInterrupted")
        except hd.TurnInterrupted:
            ok(True, "TurnInterrupted raised when the card stops being ours mid-turn")
        ok(killed["done"], "the local subprocess was tree-killed on interrupt")
    finally:
        hd.subprocess.Popen = orig_popen
        hd._tree_kill = orig_treekill

    # still_mine that stays True: the turn runs to completion (proc.wait
    # returns normally on the 2nd poll), usage parsed from stdout.
    print("\n_run_turn_locally: still_mine=True runs to completion")
    good = json.dumps({"result": "ok", "total_cost_usd": 0.01,
                      "usage": {"input_tokens": 10}, "modelUsage": {"m": {}}})
    class _FinishingProc:
        def __init__(self):
            self.pid = -2; self.returncode = 0
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(good); self.stderr = io.StringIO("")
            self._n = 0
        def wait(self, timeout=None):
            self._n += 1
            if self._n < 2:
                raise _sp.TimeoutExpired("claude", timeout)
            return 0   # finishes on the 2nd poll
    fp = _FinishingProc()
    hd.subprocess.Popen = lambda *a, **kw: fp
    try:
        reply, meta = hd._run_turn_locally("C:/fake/repo", "br", "task", "",
                                          still_mine=lambda: True, poll_interval=0.01)
        ok(reply == "ok" and meta and meta["cost_usd"] == 0.01,
           "an uninterrupted turn completes and its usage is parsed as usual")
    finally:
        hd.subprocess.Popen = orig_popen

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green")


if __name__ == "__main__":
    main()
