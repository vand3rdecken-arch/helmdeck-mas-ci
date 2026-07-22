# -*- coding: utf-8 -*-
"""User-built integrations - connectors the swarm writes for you.

Anyone with chat access can say "build an integration that pulls X into the
board". The copilot files a CONNECTOR CARD: an agent writes connectors/<name>.py
in its worktree against the contract below, the review gate checks it, and a
human accepts it - only then is the file INSTALLED here (daemon/connectors/)
and runnable. Chat never injects running code directly; integration code walks
the same trust loop as every other deliverable.

Contract for a connector module:

    NAME = "hn-top"           # kebab-case, matches filename
    DESCRIPTION = "..."
    def run():
        # fetch/derive work items; NO side effects on the board here
        return [{"task": "...", "client": "", "priority": "medium",
                 "due": "", "value": 0}]        # each item -> a backlog card

Scheduling: settings.connectors {name: {"every_minutes": N}} - the poller
runs due connectors and files whatever they return."""
import importlib.util, json, os, shutil, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
CDIR = os.path.join(ROOT, "connectors")
STATE = os.path.join(CDIR, "_state.json")
os.makedirs(CDIR, exist_ok=True)

CONTRACT = """Create the file connectors/%(name)s.py (create the connectors/ folder at the
repo root if missing). It must define:
  NAME = "%(name)s"
  DESCRIPTION = "<one line>"
  def run():  # stdlib only (urllib, json, re, csv...), no pip installs
      # %(spec)s
      return items   # list of dicts: {"task": str, "client": str,
                     #  "priority": "urgent|high|medium|low", "due": "YYYY-MM-DD"|"",
                     #  "value": number}  - each becomes a backlog card
Keep it under ~120 lines, defensive (timeouts, missing fields), cap output at
20 items. Test it by running `python -c "import sys; sys.path.insert(0,'connectors'); import %(pyname)s as m; print(len(m.run()))"`
from the repo root, then COMMIT everything."""

def build_task(name, spec):
    pyname = name.replace("-", "_")
    return ("INTEGRATION BUILD: " + spec + "\n\n" +
            CONTRACT % {"name": pyname, "spec": spec, "pyname": pyname})

VDIR = os.path.join(CDIR, "_versions")
os.makedirs(VDIR, exist_ok=True)

def _archive(name):
    """Safeguard the current version before any overwrite - rollback fuel."""
    cur = os.path.join(CDIR, name + ".py")
    if os.path.exists(cur):
        shutil.copy2(cur, os.path.join(VDIR, "%s.%s.py" % (name, time.strftime("%Y%m%d-%H%M%S"))))

def versions(name):
    pre = name + "."
    return sorted(f for f in os.listdir(VDIR) if f.startswith(pre) and f.endswith(".py"))

def rollback(name):
    """Restore the previous version (current one is archived too, so a
    rollback is itself reversible)."""
    vs = versions(name)
    if not vs:
        raise RuntimeError("no previous version of " + name)
    _archive(name)
    prev = vs[-1]
    shutil.copy2(os.path.join(VDIR, prev), os.path.join(CDIR, name + ".py"))
    os.remove(os.path.join(VDIR, prev))
    return prev

def install_from_worktree(track):
    """Called on accept of a connector card: copy its connectors/*.py live.
    The existing version (if any) is archived first - originals are never lost."""
    src = os.path.join(track.get("worktree") or "", "connectors")
    if not os.path.isdir(src):
        return []
    import charter
    installed, blocked = [], []
    for f in os.listdir(src):
        if f.endswith(".py") and not f.startswith("_"):
            with open(os.path.join(src, f), encoding="utf-8", errors="replace") as fh:
                code = fh.read()
            hits = charter.screen_source(code)
            if hits:
                blocked.append("%s (%s)" % (f, "; ".join(hits)))
                continue
            _archive(f[:-3])
            shutil.copy2(os.path.join(src, f), os.path.join(CDIR, f))
            installed.append(f)
    if blocked:
        raise RuntimeError("CHARTER BLOCKED: " + " | ".join(blocked))
    return installed

def list_connectors():
    out = []
    for f in sorted(os.listdir(CDIR)):
        if not f.endswith(".py") or f.startswith("_"):
            continue
        name = f[:-3]
        desc = ""
        try:
            mod = _load(name)
            desc = getattr(mod, "DESCRIPTION", "")
        except Exception as e:
            desc = "load error: %s" % str(e)[:80]
        out.append({"name": name, "description": desc, "last_run": _state().get(name),
                    "versions": len(versions(name))})
    return out

def _run_sandboxed(name, timeout=90):
    """Run the connector in a SEPARATE python process: it cannot touch the
    daemon's memory/board state, and a hang/crash cannot take the daemon down.
    Only its JSON stdout comes back."""
    code = ("import json,sys;sys.path.insert(0,%r);"
            "import %s as m;print(json.dumps(m.run()))" % (CDIR, name))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=timeout, cwd=CDIR)
    if r.returncode != 0:
        raise RuntimeError("connector failed: " + (r.stderr or "").strip()[-300:])
    line = (r.stdout or "").strip().splitlines()
    items = json.loads(line[-1]) if line else []
    if not isinstance(items, list):
        raise RuntimeError("connector must return a list")
    return items

def _load(name):
    fp = os.path.join(CDIR, name + ".py")
    spec = importlib.util.spec_from_file_location("connector_" + name, fp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _save_state(d):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f)

def run_connector(name, actor="owner"):
    """Execute an installed connector; its items become backlog cards."""
    import events, sessions
    repo = events.settings().get("default_repo")
    if not repo:
        raise RuntimeError("no default_repo preset")
    items = _run_sandboxed(name)
    made = []
    for i, it in enumerate(items[:20]):
        if not it.get("task"):
            continue
        t = sessions.new_track(
            repo, "conn-%s-%d" % (name[:14], i), str(it["task"])[:500],
            lane="backlog", client=str(it.get("client") or ""),
            actor="connector:" + name,
            priority=it.get("priority") if it.get("priority") in
                ("urgent", "high", "medium", "low") else "medium",
            due=str(it.get("due") or ""), value=it.get("value") or None)
        made.append(t["id"])
    st = _state(); st[name] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_state(st)
    events.emit("import", "-", source="connector:" + name, count=len(made), actor=actor)
    return made

def start_scheduler(interval=60):
    def loop():
        last = {}
        while True:
            try:
                import events
                sched = events.settings().get("connectors") or {}
                now = time.time()
                for name, cfg in sched.items():
                    mins = (cfg or {}).get("every_minutes")
                    if not mins:
                        continue
                    if now - last.get(name, 0) >= mins * 60:
                        last[name] = now
                        try:
                            run_connector(name, actor="schedule")
                        except Exception as e:
                            print("connector %s failed: %s" % (name, e))
            except Exception as e:
                print("connector scheduler error:", e)
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True).start()
