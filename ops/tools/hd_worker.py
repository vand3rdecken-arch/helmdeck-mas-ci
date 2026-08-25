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

Still open (debt remote-worker-not-hardened, Phase D remainder): no
packaged install/autostart registration (a config file exists now - see
--config below - but nothing installs a Task Scheduler entry/service for
you), no live transcript streaming to the board mid-turn, no board-UI
surfacing of a stuck/reassignable device card (the API + daemon-side event
exist; POST /devices/reassign and GET /devices/mine already work, no
surfaces/app screen renders them yet).

Usage (either form; a --config value only fills in what a flag omits):
    python ops/tools/hd_worker.py --daemon https://host:8140 --device <id> \
        --token sdk_xxx --repo C:/path/to/local/clone
    python ops/tools/hd_worker.py --config C:/path/to/worker-config.json
        # {"daemon": "...", "device": "...", "token": "sdk_xxx", "repo": "..."}
"""
import argparse
import base64
import json
import os
import random
import subprocess
import sys
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


def _run_turn_locally(repo, branch, task, description):
    """Runs the card's turn in the member's OWN local clone, full local
    capability - the same claude CLI invocation shape drivers.py uses
    centrally, minus the worktree/card.json sandboxing that only makes
    sense on shared infrastructure. Deliberately simple (-p, acceptEdits,
    no streaming/resume) - a reference point to build the real driver
    integration against, not a replacement for it.

    --output-format json (not plain text) for exactly one reason: the
    result event's total_cost_usd/usage/modelUsage are the SAME economics
    fields spine/agent/drivers.py's _ClaudeSession parses off a local
    card's result event (drivers.py:1194 - "usage": d.get("usage"),
    "cost_usd": d.get("total_cost_usd"), "models": list((d.get("modelUsage")
    or {}).keys())). Reusing that exact shape (not inventing a new one)
    means spine.turn.econ._record_econ, the daemon's real economics
    function, can fold a device turn's spend in unmodified - no fork of
    the pricing/context-window logic. Returns (reply_text, usage_meta).
    On any parse failure, usage_meta is None - the turn still counts as
    successful (the branch still gets submitted), it just carries no
    cost/usage data. A cost-reporting parse failure must never block real
    work from landing."""
    prompt = task + (("\n\n" + description) if description else "")
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
        usage_meta = {"usage": d.get("usage") or {}, "cost_usd": d.get("total_cost_usd"),
                     "models": list((d.get("modelUsage") or {}).keys())}
    except (ValueError, AttributeError):
        pass   # not JSON, or a shape we don't recognize - reply stays the raw stdout
    return reply, usage_meta


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
    try:
        _reply, usage_meta = _run_turn_locally(
            repo_root, branch, task["task"], task.get("description", ""))
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
    an autostart registration (Task Scheduler / a service) points at,
    rather than baking a long argv into the scheduled task itself."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
    a = ap.parse_args()

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
