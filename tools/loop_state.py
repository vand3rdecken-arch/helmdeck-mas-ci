# -*- coding: utf-8 -*-
"""SwarmDeck's build loop as an explicit STATE MACHINE - the same loop control
as the glass harness, states fitted to this repo. Computed from disk, never
from memory of the conversation.

States (agent-actionable first):

    COMPILE  a touched daemon/*.py fails py_compile - fix it
    TYPES    web/ touched and `tsc --noEmit` fails - fix it
    VERIFY   a touched daemon module fails to import (wiring broken) - fix it
    DEBT     daemon/debt.py register malformed (bad status/missing keys) - fix it
    WIP      uncommitted files with RECENT edits (< SWARM_WIP_MINUTES, default 30)
             - someone is mid-work: serve the request, do NOT push a commit
    COMMIT   uncommitted files gone quiet - propose the commit (user gate)
    DONE     nothing actionable

Usage:
    python tools/loop_state.py                  # table + THE next action
    python tools/loop_state.py --stop-hook      # Claude Code Stop hook (blocks once)
    python tools/loop_state.py --session-start  # prints state into fresh context

Never fails (exit 0 always) - a state doctor, not a gate."""
import json, os, subprocess, sys, time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(ROOT, "daemon")
WEB = os.path.join(ROOT, "web")
WIP_MIN = int(os.environ.get("SWARM_WIP_MINUTES", "30"))

CORE_MODULES = ["db", "events", "sessions", "drivers", "processes", "copilot",
                "connectors", "charter", "checkpoints", "auth", "importers",
                "debt", "server"]


def _git(*args):
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def dirty_files():
    out = []
    for line in _git("status", "--porcelain").splitlines():
        if len(line) > 3:
            out.append(line[3:].strip().strip('"'))
    return out


def newest_mtime(paths):
    newest = 0
    for p in paths:
        fp = os.path.join(ROOT, p)
        if os.path.isfile(fp):
            newest = max(newest, os.path.getmtime(fp))
    return newest


def check_compile(touched):
    bad = []
    for p in touched:
        if p.startswith("daemon/") and p.endswith(".py"):
            r = subprocess.run([sys.executable, "-m", "py_compile",
                                os.path.join(ROOT, p)], capture_output=True, text=True)
            if r.returncode != 0:
                bad.append("%s: %s" % (p, (r.stderr or "").strip().splitlines()[-1][:120]))
    return bad


def check_types(touched):
    if not any(p.startswith("web/") for p in touched):
        return []
    if not os.path.isdir(os.path.join(WEB, "node_modules")):
        return []
    npx = "npx.cmd" if os.name == "nt" else "npx"
    env = dict(os.environ)
    env["PATH"] = r"C:\Program Files\nodejs;" + env.get("PATH", "")
    r = subprocess.run([npx, "tsc", "--noEmit", "-p", "tsconfig.json"],
                       cwd=WEB, capture_output=True, text=True, env=env, timeout=180)
    if r.returncode != 0:
        lines = (r.stdout or r.stderr or "").strip().splitlines()
        return [lines[0][:160] if lines else "tsc failed"]
    return []


def check_imports(touched):
    if not any(p.startswith("daemon/") and p.endswith(".py") for p in touched):
        return []
    code = "import " + ",".join(CORE_MODULES)
    r = subprocess.run([sys.executable, "-c", code], cwd=DAEMON,
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return [(r.stderr or "").strip().splitlines()[-1][:160]]
    return []


def check_debt():
    try:
        sys.path.insert(0, DAEMON)
        import importlib
        import debt as _d
        importlib.reload(_d)
        problems = []
        for item in _d.DEBT:
            for k in ("id", "title", "status", "what", "why_it_bites", "trigger", "fix"):
                if k not in item:
                    problems.append("%s missing %s" % (item.get("id", "?"), k))
            if item.get("status") not in ("open", "in_progress", "paid"):
                problems.append("%s has bad status %r" % (item.get("id"), item.get("status")))
        return problems
    except Exception as e:
        return ["debt.py unreadable: %s" % str(e)[:120]]


def transitions():
    """Ordered (STATE, action) list; first entry is THE next action."""
    t = []
    touched = dirty_files()
    if touched:
        bad = check_compile(touched)
        if bad:
            t.append(("COMPILE", "fix: " + " | ".join(bad[:2])))
        tbad = check_types(touched)
        if tbad:
            t.append(("TYPES", "fix web types: " + tbad[0]))
        ibad = check_imports(touched)
        if ibad:
            t.append(("VERIFY", "daemon wiring broken: " + ibad[0]))
    dbad = check_debt()
    if dbad:
        t.append(("DEBT", "repair daemon/debt.py register: " + "; ".join(dbad[:2])))
    if touched and not t:
        quiet = (time.time() - newest_mtime(touched)) > WIP_MIN * 60
        if quiet:
            t.append(("COMMIT", "%d uncommitted file(s) gone quiet - propose a commit "
                      "(don't just stop): %s" % (len(touched), ", ".join(touched[:4]))))
        else:
            t.append(("WIP", "recent uncommitted edits (%d files) - mid-work, serve the "
                      "request, don't force a commit" % len(touched)))
    return t


def print_table():
    t = transitions()
    if not t:
        print("[loop_state] DONE - repo at a resting state (clean tree, checks green).")
        return
    print("[loop_state] states:")
    for st, act in t:
        print("  %-8s %s" % (st, act))
    print("NEXT: %s -> %s" % t[0])


def stop_hook():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if payload.get("stop_hook_active"):
        return
    t = [x for x in transitions() if x[0] != "WIP"]   # WIP never blocks a stop
    if not t:
        return
    st, act = t[0]
    print(json.dumps({
        "decision": "block",
        "reason": "[loop_state] The build loop is not at a resting state: %s - %s. "
                  "Do this now if it needs no user input; if you are genuinely blocked "
                  "on the user (or a check stayed red after ~3 fix attempts), say exactly "
                  "what you need and stop. Full picture: python tools/loop_state.py" % (st, act)
    }))


def session_start():
    print("[loop_state] Session (re)start - build-loop state recomputed from disk:")
    print_table()
    print("Rule: if the next action needs no user input, do it now; stop only at DONE "
          "or a genuine user gate (commit approval, product decisions).")


if __name__ == "__main__":
    if "--stop-hook" in sys.argv:
        stop_hook()
    elif "--session-start" in sys.argv:
        session_start()
    else:
        print_table()
    sys.exit(0)
