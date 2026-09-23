# -*- coding: utf-8 -*-
"""Restart the HelmDeck daemon WITHOUT killing anyone's turn.

Waits until BOTH witnesses are quiet, then spawns a fresh daemon (its singleton
lock evicts the old one) and health-checks port 8140:

    daemon/state/driver_pids.json   card workers (spine/agent/proctable.py)
    daemon/state/chat_turns.json    Henry's own chat turns (copilot._note_turn)

Why the second file: on 2026-09-13 17:01 an operator restart checked only the
first, found it empty, and killed the owner's running Henry answer mid-tool
("Conversation wieder verloren"). driver_pids never listed the chat process
because it is a warm, persistent port, not a card driver.

    py -3.12 ops/tools/restart_daemon.py [--wait 600] [--force]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, "daemon", "state")


def _load(name):
    try:
        with open(os.path.join(STATE, name), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _alive(pid, spawn):
    """Only a pid that is (a) alive and (b) OUR spawn (proctable's pid-reuse
    guard) counts. A stale entry - the process died without _forget_pid, as
    happened 2026-09-13 18:45 (pid 16404 dead, restart waited 25 min on it) -
    must not block a restart forever."""
    try:
        sys.path.insert(0, ROOT)
        from spine.agent import proctable
        return bool(proctable._is_ours(int(pid), spawn))
    except Exception:                                    # noqa: BLE001
        return True                                      # unknown = assume live (never kill on a guess)


def busy():
    """(cards, chat_users) still running - both empty means safe."""
    cards = [p for p, spawn in _load("driver_pids.json").items() if _alive(p, spawn)]
    return cards, list(_load("chat_turns.json").keys())


def background():
    """Why a session is still busy, by name: daemonctl.background_work (the
    ONE reading of the bg descriptors). A bare pid told the owner nothing -
    2026-09-17 'cards=[18732]' was a 27-run benchmark."""
    try:
        sys.path.insert(0, ROOT)
        from spine.ops import daemonctl
        return daemonctl.background_work()
    except Exception:                                    # noqa: BLE001
        return {}


def healthy():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8140/auth/state", timeout=4) as r:
            return r.status == 200
    except Exception:                                    # noqa: BLE001
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=600, help="seconds to wait for quiet (default 600)")
    ap.add_argument("--force", action="store_true", help="restart even while turns run (kills them)")
    a = ap.parse_args()
    t0 = time.time()
    while not a.force:
        cards, chats = busy()
        bg = background()
        if not cards and not chats and not bg:
            break
        if time.time() - t0 > a.wait:
            print("still busy after %ds - cards=%s chat=%s background=%s; not restarting (use --force)" % (a.wait, cards, chats, bg))
            return 2
        print("waiting: cards=%s chat=%s background=%s" % (cards, chats, bg))
        time.sleep(15)
    old = ""
    try:
        with open(os.path.join(ROOT, "daemon", "daemon.pid"), "r") as f:
            old = f.read().strip()
    except OSError:
        pass
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    out = open(os.path.join(ROOT, "daemon", "restart_stdout.log"), "ab")
    err = open(os.path.join(ROOT, "daemon", "restart_stderr.log"), "ab")
    # --takeover: this tool IS the explicit restart verb, so it may depose the
    # running daemon. A supervisor spawning without it exits 3 instead
    # (spine/http/startup.py, the daemon mutex).
    subprocess.Popen([sys.executable, "-m", "daemon.swarm", "serve", "--takeover"], cwd=ROOT,
                     stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=flags)
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(3)
        if healthy():
            new = ""
            try:
                with open(os.path.join(ROOT, "daemon", "daemon.pid"), "r") as f:
                    new = f.read().strip()
            except OSError:
                pass
            if new and new != old:
                print("restarted: pid %s -> %s, healthy" % (old or "?", new))
                return 0
    print("daemon did not come back healthy within 90s - check daemon/restart_stderr.log")
    return 1


if __name__ == "__main__":
    sys.exit(main())
