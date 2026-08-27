# -*- coding: utf-8 -*-
"""Reference worker implementation (ops/docs/backlog/remote-device-execution,
PLAN-hardening.md Phases A-C shipped daemon-side + this file's own Phase B,
Phase D usage/cost capture + revoke-detection + config file below). Runs ON
A TEAM MEMBER'S OWN PC: long-polls the central daemon's device queue, runs
a card's turn in a LOCAL clone with full local capability (this is the
member's own trusted machine - no worktree/tool sandboxing here, that only
matters on shared infrastructure, see ops/tools/card_tool_guard.py's own
docstring for that distinction), commits, bundles the branch, and submits
it back - along with the turn's usage/cost (captured from its own
--output-format json call), folded through the SAME spine.turn.econ
function a local card's turn uses. The central daemon's gate/merge/GxP
pipeline is untouched by any of this - it only ever sees a branch that has
landed in its own repo, exactly like a local worktree card's.

Still open (debt remote-worker-not-hardened): no live transcript streaming
to the board mid-turn (Phase H), no board-UI surfacing of a stuck/
reassignable device card (Phase G - the API + daemon-side event exist;
POST /devices/reassign and GET /devices/mine already work).

Install (Phase F): `pip install ops/tools/` exposes an `hd-worker` console
script (pyproject.toml there scopes it to this one module). Login autostart
(Windows): `hd-worker --install-autostart --config <path>` (HKCU Run key,
same mechanism as the daemon tray; token stays in the config file, not the
Run-key value). Remove with --uninstall-autostart. mac/Linux: point a
launchd/systemd unit at `hd-worker --config <path>` by hand.

Usage (either form; a --config value only fills in what a flag omits):
    python ops/tools/hd_worker.py --daemon https://host:8140 --device <id> \
        --token sdk_xxx --repo C:/path/to/local/clone
    hd-worker --config C:/path/to/worker-config.json
        # {"daemon": "...", "device": "...", "token": "sdk_xxx", "repo": "..."}
"""
import argparse
import base64
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


def _api(daemon, path, token, method="GET", body=None,
        retries=5, base_delay=1.0, max_delay=30.0):
    """HTTP call with bounded exponential backoff + jitter - but ONLY on
    transient failures (connection errors, 5xx): a daemon restart or a
    dropped wifi packet should not turn into a lost turn. A 4xx is a real
    refusal (bad token, wrong device, malformed body) and is raised
    immediately, unretried - retrying a request the server has already
    explicitly rejected wastes time and never succeeds differently.
    `retries` is bounded (never an infinite retry loop) so a persistently
    broken call still surfaces to the caller instead of hanging forever."""
    url = daemon.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            if e.code < 500:
                body_txt = e.read().decode("utf-8", "replace")
                raise RuntimeError("HTTP %s on %s: %s" % (e.code, path, body_txt[:300]))
            last_err = RuntimeError("HTTP %s on %s (server error)" % (e.code, path))
        except (urllib.error.URLError, OSError) as e:
            last_err = RuntimeError("connection error on %s: %s" % (path, e))
        if attempt < retries - 1:
            # Jitter REDUCES the capped delay (random.uniform(0.5, 1.0)),
            # never multiplies it past max_delay - a jitter factor that can
            # exceed 1.0 would make the "cap" not actually cap anything.
            delay = min(max_delay, base_delay * (2 ** attempt)) * random.uniform(0.5, 1.0)
            time.sleep(delay)
    raise last_err


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


class TurnInterrupted(RuntimeError):
    """The card stopped being this device's mid-turn (reassigned/reclaimed/
    revoked - the daemon's device_card_status said so). The local turn was
    killed and the card must NOT be committed/bundled/submitted: another
    device (or the reclaim sweep) now owns it. Distinct from a failure - the
    worker just loops back to poll for its next real task."""


def _tree_kill(proc):
    """Kill the claude subprocess AND its children - a bare proc.kill() on
    Windows would orphan whatever claude spawned (a build, a test runner)
    still holding file locks in the worktree. Mirrors drivers.py's taskkill
    /T shape for the daemon-side sessions."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                          capture_output=True)
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def _usage_from_result(res):
    """The three economics fields, pulled off a stream-json/json `result`
    event - the SAME shape spine/agent/drivers.py parses off a local card's
    result event, so spine.turn.econ._record_econ folds a device turn's
    spend unmodified. None when there is no result event."""
    if not isinstance(res, dict):
        return None
    return {"usage": res.get("usage") or {}, "cost_usd": res.get("total_cost_usd"),
            "models": list((res.get("modelUsage") or {}).keys())}


def _run_turn_locally(repo, branch, task, description, still_mine=None,
                     on_stream=None, poll_interval=5.0):
    """Runs the card's turn in the member's OWN local clone, full local
    capability - the same claude CLI invocation drivers.py uses centrally,
    minus the worktree/card.json sandboxing that only matters on shared
    infrastructure. Returns (reply_text, usage_meta).

    Two paths:
    - SIMPLE (still_mine is None AND on_stream is None): one blocking
      `--output-format json` call. Used by tests and any caller that wants
      neither interrupt-checking nor live streaming.
    - STREAMING (still_mine and/or on_stream given): `--output-format
      stream-json`, read line-by-line in a reader thread (a PIPE that fills
      would deadlock proc.wait() alone), so we can BOTH forward each event
      to on_stream AS IT ARRIVES (Phase H live transcript) and check
      still_mine every poll_interval to abort a reassigned/revoked card
      (Phase E). Both callbacks are best-effort: a streaming or status-poll
      error never fails the turn, whose real result still lands via
      submit_remote_result.

    on_stream(events) (Phase H): called with each batch of raw Claude stream
    events while the turn runs; process_one POSTs them to /devices/<id>/
    stream, where the daemon folds them through the SAME
    drivers.fold_timeline_event a local card uses - so a device turn shows
    on the board live, identical to a local one."""
    prompt = task + (("\n\n" + description) if description else "")
    if still_mine is None and on_stream is None:
        r = subprocess.run(
            ["claude", "-p", "--permission-mode", "acceptEdits", "--output-format", "json"],
            cwd=repo, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800)
        if r.returncode != 0:
            raise RuntimeError("claude turn failed: %s" % (r.stderr or r.stdout)[:400])
        usage_meta = None
        reply = r.stdout
        try:
            d = json.loads(r.stdout)
            reply = d.get("result", r.stdout)
            usage_meta = _usage_from_result(d)
        except (ValueError, AttributeError):
            pass
        return reply, usage_meta

    argv = ["claude", "-p", "--permission-mode", "acceptEdits",
            "--output-format", "stream-json", "--verbose"]
    proc = subprocess.Popen(argv, cwd=repo, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace")
    try:
        proc.stdin.write(prompt); proc.stdin.close()
    except (OSError, ValueError):
        pass
    buf = []
    buf_lock = threading.Lock()
    result_holder = {}

    def _read():
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                with buf_lock:
                    buf.append(ev)
                if ev.get("type") == "result":
                    result_holder["ev"] = ev
        except Exception:
            pass

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()

    def _flush():
        with buf_lock:
            batch = buf[:]
            buf.clear()
        if batch and on_stream:
            try:
                on_stream(batch)
            except Exception:
                pass   # streaming is best-effort - never fail the turn on it

    waited = 0.0
    while True:
        reader.join(timeout=poll_interval)
        _flush()
        if not reader.is_alive():
            break
        waited += poll_interval
        if still_mine and not still_mine():
            _tree_kill(proc)
            raise TurnInterrupted(
                "card reassigned/reclaimed mid-turn - killed the local "
                "turn, not submitting")
        if waited >= 1800:
            _tree_kill(proc)
            raise RuntimeError("claude turn exceeded 1800s - killed")

    proc.wait()
    err = proc.stderr.read() if proc.stderr else ""
    res = result_holder.get("ev")
    if res is None and proc.returncode not in (0, None):
        raise RuntimeError("claude turn failed: %s" % (err or "")[:400])
    reply = (res or {}).get("result", "")
    return reply, _usage_from_result(res)


class DeviceRevoked(RuntimeError):
    """The daemon no longer recognizes this device/token (revoked, or the
    device record itself was deleted). Distinct from a transient failure -
    retrying with backoff would just spin forever on something that will
    never recover without a human re-registering the device."""


def process_one(daemon, device_id, token, repo_root):
    try:
        task = _api(daemon, "/devices/%s/queue" % device_id, token)
    except RuntimeError as e:
        # 404 on THIS device's own queue is the daemon's only real "signal"
        # a poll-based worker can act on for revoke() - there is no separate
        # push channel, so the worker learns it on its next scheduled poll
        # (same ~20s cadence the long-poll already uses) rather than
        # instantly, but it DOES learn it and stop, instead of retrying an
        # auth failure forever under the transient-failure backoff.
        if "HTTP 404" in str(e):
            raise DeviceRevoked(
                "device %s is unknown to the daemon (revoked, or never "
                "registered) - stopping" % device_id)
        raise
    if not task:
        return False
    branch = task["branch"]
    print("claimed card %s: %s" % (task["id"], task["task"]))

    if _git(repo_root, "remote"):
        _git(repo_root, "fetch", "-q", "origin")
    base = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo_root, "checkout", "-q", "-b", branch, base)

    def _still_mine():
        # Phase E: cheap "is this card still mine?" the turn watcher calls
        # every few seconds. A device-not-found (404) means the token was
        # revoked - also "not mine". Any OTHER transient error: assume still
        # mine (do NOT kill a running turn just because one status poll
        # blipped - fail toward keeping real work alive, the sweep is the
        # backstop if we're actually wrong).
        try:
            st = _api(daemon, "/devices/%s/card/%s" % (device_id, task["id"]),
                     token, retries=2, base_delay=0.5, max_delay=2.0)
            return bool(st.get("assigned"))
        except RuntimeError as e:
            return "HTTP 404" not in str(e)

    def _on_stream(events):
        # Phase H: forward this batch of live turn events to the daemon,
        # which folds them into the card's timeline so the board shows the
        # device turn AS IT HAPPENS. Best-effort - streaming failing must
        # never fail the turn (its real result lands via /submit).
        try:
            _api(daemon, "/devices/%s/stream" % device_id, token, method="POST",
                 body={"track": task["id"], "events": events},
                 retries=2, base_delay=0.5, max_delay=2.0)
        except RuntimeError:
            pass

    try:
        _reply, usage_meta = _run_turn_locally(
            repo_root, branch, task["task"], task.get("description", ""),
            still_mine=_still_mine, on_stream=_on_stream)
        if _git(repo_root, "status", "--porcelain"):
            _git(repo_root, "add", "-A")
            _git(repo_root, "commit", "-q", "-m",
                 "device work: %s (%s)" % (task["task"][:60], task["id"]))
        bundle_path = os.path.join(repo_root, ".hd-submission.bundle")
        subprocess.run(["git", "-C", repo_root, "bundle", "create", bundle_path, branch],
                       check=True, capture_output=True)
        with open(bundle_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        os.remove(bundle_path)
        body = {"track": task["id"], "bundle_b64": b64}
        if usage_meta:
            body["usage_meta"] = usage_meta
        result = _api(daemon, "/devices/%s/submit" % device_id, token, method="POST",
                      body=body)
        print("submitted -> lane=%s" % result.get("lane"))
    except TurnInterrupted as e:
        print("card %s: %s" % (task["id"], e))
        return False   # not a failure - just loop back and poll for real work
    finally:
        _git(repo_root, "checkout", "-q", base)
    return True


def _backoff_delay(consecutive_failures, base=2.0, cap=60.0):
    # Same jitter shape as _api's retry delay - uniform(0.5, 1.0) REDUCES
    # the capped value, never multiplies past `cap`.
    return min(cap, base * (2 ** min(consecutive_failures, 6))) * random.uniform(0.5, 1.0)


def _load_config(path):
    """--config <path>: daemon/device/token/repo from a JSON file instead
    of argv. Two real reasons, not just convenience: a device token on the
    command line sits in shell history and in `ps`/Task Manager's argument
    column for every other process on the box to read; a config file (with
    normal OS file permissions) does not. Second, it is the natural place
    an autostart registration points at, rather than baking a long argv
    (token included) into the Run-key value itself."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------- autostart (Phase F)
# HKCU Run key, the SAME mechanism surfaces/desktop/tray.py already uses for
# the daemon tray (winreg, never shelling to powershell - that binary is not
# on the owner's PATH, memory: paseo-architecture-learnings). Windows-first
# (the owner's box); on mac/Linux this no-ops and the module docstring points
# at the manual launchd/systemd recipe. The registered command runs the
# worker with --config so the TOKEN stays in the config file, never in the
# Run-key value a curious process could read.
try:
    import winreg
except ImportError:
    winreg = None

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "HelmDeckDeviceWorker"


def _autostart_cmd(config_path):
    """The exact string the Run key stores: pythonw (no console window) +
    this script + --config. pythonw next to the interpreter if present, else
    the interpreter itself - same resolution tray.py uses."""
    exe = sys.executable or "python"
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    launcher = pyw if os.path.exists(pyw) else exe
    return '"%s" "%s" --config "%s"' % (launcher, os.path.abspath(__file__),
                                        os.path.abspath(config_path))


def _autostart_status(name=_RUN_NAME):
    """The registered command, or None. Read-only."""
    if not winreg:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _set_autostart(on, config_path=None, name=_RUN_NAME):
    """Register (on=True, needs config_path) or remove (on=False) the Run
    key. Returns True on success. `name` is a parameter purely so a test can
    round-trip against a throwaway value under the same key without touching
    the real one."""
    if not winreg:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, _autostart_cmd(config_path))
            else:
                try:
                    winreg.DeleteValue(k, name)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def _resolve_config(daemon, device, token, repo, cfg):
    """Merge argv (each may be None) over a config dict - a flag always
    wins when both are given. Returns (daemon, device, token, repo,
    missing) where `missing` names whichever required value neither
    source supplied, so the caller can report exactly what's absent
    instead of argparse's generic 'required' error (which can't know
    about the config-file fallback)."""
    daemon = daemon or cfg.get("daemon")
    device = device or cfg.get("device")
    token = token or cfg.get("token")
    repo = repo or cfg.get("repo")
    missing = [n for n, v in (("--daemon/config daemon", daemon),
                              ("--device/config device", device),
                              ("--token/config token", token),
                              ("--repo/config repo", repo)) if not v]
    return daemon, device, token, repo, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="JSON file with daemon/device/token/repo "
                                     "- overridden by any of the flags below if both given")
    ap.add_argument("--daemon")
    ap.add_argument("--device")
    ap.add_argument("--token")
    ap.add_argument("--repo", help="local clone of the target repo")
    ap.add_argument("--once", action="store_true", help="process one task and exit")
    ap.add_argument("--install-autostart", action="store_true",
                    help="register a Windows login autostart (HKCU Run) for --config, then exit")
    ap.add_argument("--uninstall-autostart", action="store_true",
                    help="remove the login autostart, then exit")
    a = ap.parse_args()

    # Autostart management acts and exits - it never enters the poll loop.
    if a.install_autostart or a.uninstall_autostart:
        if not winreg:
            print("error: autostart is Windows-only (HKCU Run key). On mac/Linux "
                  "register a launchd/systemd unit pointing at --config manually.",
                  file=sys.stderr)
            sys.exit(1)
        if a.uninstall_autostart:
            ok_ = _set_autostart(False)
            print("autostart removed." if ok_ else "error: could not remove autostart",
                  file=sys.stderr if not ok_ else sys.stdout)
            sys.exit(0 if ok_ else 1)
        if not a.config:
            print("error: --install-autostart needs --config <path> (the Run key "
                  "stores a --config invocation so the token stays in the file)",
                  file=sys.stderr)
            sys.exit(1)
        ok_ = _set_autostart(True, a.config)
        print("autostart registered: %s" % _autostart_status() if ok_
              else "error: could not register autostart",
              file=sys.stdout if ok_ else sys.stderr)
        sys.exit(0 if ok_ else 1)

    cfg = _load_config(a.config) if a.config else {}
    daemon, device, token, repo, missing = _resolve_config(
        a.daemon, a.device, a.token, a.repo, cfg)
    if missing:
        print("error: missing required value(s): %s" % ", ".join(missing), file=sys.stderr)
        sys.exit(1)
    a.daemon, a.device, a.token, a.repo = daemon, device, token, repo

    if not os.path.isdir(os.path.join(a.repo, ".git")):
        print("error: --repo is not a git checkout: %s" % a.repo, file=sys.stderr)
        sys.exit(1)

    # "no work available" (a normal, expected poll result) and "can't reach
    # the daemon at all" get DIFFERENT pacing - hammering a healthy-but-idle
    # daemon every 2s is fine, hammering a genuinely down one every 2s just
    # adds load to whatever is already struggling. consecutive_failures only
    # counts the latter (an _api RuntimeError after its own internal retries
    # were exhausted); a clean "no task claimed" resets it.
    consecutive_failures = 0
    reachable = True
    try:
        while True:
            try:
                did_work = process_one(a.daemon, a.device, a.token, a.repo)
                consecutive_failures = 0
                if not reachable:
                    print("daemon reachable again.")
                    reachable = True
            except DeviceRevoked as e:
                # NOT a transient failure - retrying forever would just spin
                # on an auth error that a human has to fix by re-registering
                # the device. Exit distinctly, non-zero, so a process
                # supervisor (Phase D packaging) can tell "stopped because
                # revoked" apart from "crashed, please restart".
                print("error: %s" % e, file=sys.stderr)
                sys.exit(2)
            except RuntimeError as e:
                consecutive_failures += 1
                did_work = False
                if reachable:   # log the transition, not every failed attempt
                    print("error: %s (retrying with backoff)" % e, file=sys.stderr)
                    reachable = False
            if a.once:
                break
            if consecutive_failures:
                time.sleep(_backoff_delay(consecutive_failures))
            elif not did_work:
                time.sleep(2)
    except KeyboardInterrupt:
        print("\nshutting down - if a task was claimed mid-turn, it stays "
              "'working' until the daemon's stale-claim sweep reclaims it "
              "for re-processing (or you rerun this worker).")
        sys.exit(0)


if __name__ == "__main__":
    main()
