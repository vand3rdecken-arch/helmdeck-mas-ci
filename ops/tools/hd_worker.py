# -*- coding: utf-8 -*-
"""SKETCH, not a hardened service (ops/docs/backlog/remote-device-execution,
"Explicitly NOT done this round"). Runs ON A TEAM MEMBER'S OWN PC: long-polls
the central daemon's device queue, runs a card's turn in a LOCAL clone with
full local capability (this is the member's own trusted machine - no
worktree/tool sandboxing here, that only matters on shared infrastructure,
see ops/tools/card_tool_guard.py's own docstring for that distinction),
commits, bundles the branch, and submits it back. The central daemon's gate/
merge/GxP pipeline is untouched by any of this - it only ever sees a branch
that has landed in its own repo, exactly like a local worktree card's.

No retry/offline/reconnect handling, no packaging or install story, no
config file - a deliberately small reference implementation of the protocol,
proven end to end by ops/tests/test_remote_device.py against the daemon
side. Hardening this into a real background service is follow-up work.

Usage:
    python ops/tools/hd_worker.py --daemon https://host:8140 --device <id> \
        --token sdk_xxx --repo C:/path/to/local/clone
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _api(daemon, path, token, method="GET", body=None):
    url = daemon.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %s on %s: %s" % (e.code, path, body[:300]))


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
    integration against, not a replacement for it."""
    prompt = task + (("\n\n" + description) if description else "")
    r = subprocess.run(
        ["claude", "-p", "--permission-mode", "acceptEdits"],
        cwd=repo, input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0:
        raise RuntimeError("claude turn failed: %s" % (r.stderr or r.stdout)[:400])
    return r.stdout


def process_one(daemon, device_id, token, repo_root):
    task = _api(daemon, "/devices/%s/queue" % device_id, token)
    if not task:
        return False
    branch = task["branch"]
    print("claimed card %s: %s" % (task["id"], task["task"]))

    if _git(repo_root, "remote"):
        _git(repo_root, "fetch", "-q", "origin")
    base = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo_root, "checkout", "-q", "-b", branch, base)
    try:
        _run_turn_locally(repo_root, branch, task["task"], task.get("description", ""))
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
        result = _api(daemon, "/devices/%s/submit" % device_id, token, method="POST",
                      body={"track": task["id"], "bundle_b64": b64})
        print("submitted -> lane=%s" % result.get("lane"))
    finally:
        _git(repo_root, "checkout", "-q", base)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", required=True)
    ap.add_argument("--device", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--repo", required=True, help="local clone of the target repo")
    ap.add_argument("--once", action="store_true", help="process one task and exit")
    a = ap.parse_args()

    if not os.path.isdir(os.path.join(a.repo, ".git")):
        print("error: --repo is not a git checkout: %s" % a.repo, file=sys.stderr)
        sys.exit(1)

    while True:
        try:
            did_work = process_one(a.daemon, a.device, a.token, a.repo)
        except RuntimeError as e:
            print("error: %s" % e, file=sys.stderr)
            did_work = False
        if a.once:
            break
        if not did_work:
            time.sleep(2)


if __name__ == "__main__":
    main()
