# -*- coding: utf-8 -*-
"""SwarmDeck's build loop - the FORWARD work loop a request travels through,
enforced the glass-harness way (states computed from artifacts on disk, Stop
hook blocks resting mid-loop, SessionStart re-orients fresh context).

The loop:

    ALIGN    work started (dirty tree) but no .loop/workorder.md - write it:
             what the request is, and does it fit the repo philosophy
             (CLAUDE.md laws + daemon/charter.py)? Refuse or adjust if not.
    ANALYZE  workorder lacks '## Analysis' - architecture impact + debt delta:
             which modules/laws are touched, does a load-bearing shortcut ship
             (then register it in daemon/debt.py in the same change)?
    EXECUTE  checks are red - build/fix until green: touched daemon/*.py compile,
             web tsc clean, daemon modules import, and DESIGN LINT passes
             (tools/design_lint.py - the enforceable subset of the design skill:
             color-scheme, no inline control sizing, tokens not hex, etc).
    TEST     checks green but workorder lacks '## Verified' - run the real
             thing (e2e/screenshot for UI - JUDGE it, don't just render it),
             AND adversarial-test the specific feature you built (write its
             own break-it cases per .claude/skills/adversarial-test - a
             principle applied per feature, not a canned suite), and record
             what was verified.
    CLEAN    hygiene broken - debt register malformed, or secret files
             (settings.json / users.json / *.db) tracked/staged.
    COMMIT   loop complete and edits gone quiet - propose the commit; on a
             clean tree the workorder is archived to .loop/history/.
    WIP      (overlay, never blocks) recent edits mid-flight - serve the user.
    DONE     clean tree, no open workorder.

Usage:
    python tools/loop_state.py                  # table + THE next action
    python tools/loop_state.py --stop-hook      # Stop hook (blocks once)
    python tools/loop_state.py --session-start  # orientation for fresh context

Never fails (exit 0) - a state doctor, not a gate."""
import json, os, subprocess, sys, time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(ROOT, "daemon")
WEB = os.path.join(ROOT, "web")
LOOPDIR = os.path.join(ROOT, ".loop")
WORKORDER = os.path.join(LOOPDIR, "workorder.md")
WIP_MIN = int(os.environ.get("SWARM_WIP_MINUTES", "30"))

CORE_MODULES = ["db", "events", "sessions", "drivers", "processes", "copilot",
                "connectors", "charter", "checkpoints", "auth", "importers",
                "debt", "server"]
SECRET_NAMES = ("settings.json", "users.json", "swarmdeck.db", "swarmdeck.db-wal",
                "swarmdeck.db-shm", "copilot_log.json",
                "plane_credentials.txt", "sessions.json")

WORKORDER_TEMPLATE = """# Workorder

## Request
<what the user asked for, in one or two sentences>

## Alignment
<does it fit CLAUDE.md laws + the charter? yes / adjusted-because / refused-because>

## Analysis
<architecture impact: modules touched, laws grazed, debt delta (register in
daemon/debt.py if a shortcut ships)>

## Verified
<what was actually run/judged: checks, e2e, screenshots (UI = judged, not
just rendered)>
"""


def _git(*args):
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def dirty_files():
    out = []
    for line in _git("status", "--porcelain").splitlines():
        if len(line) > 3:
            p = line[3:].strip().strip('"')
            if not p.startswith(".loop/"):
                out.append(p)
    return out


def newest_mtime(paths):
    newest = 0
    for p in paths:
        fp = os.path.join(ROOT, p)
        if os.path.isfile(fp):
            newest = max(newest, os.path.getmtime(fp))
    return newest


def workorder():
    try:
        with open(WORKORDER, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def section_filled(text, header):
    """True if the section under `header` has real content (not the template stub)."""
    if header not in text:
        return False
    body = text.split(header, 1)[1].split("\n## ", 1)[0]
    body = body.replace("\n", " ").strip()
    return len(body) > 10 and not body.startswith("<")


def checks_red(touched):
    problems = []
    for p in touched:
        if p.startswith("daemon/") and p.endswith(".py"):
            r = subprocess.run([sys.executable, "-m", "py_compile",
                                os.path.join(ROOT, p)], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("%s: %s" % (p, (r.stderr or "").strip().splitlines()[-1][:100]))
    if any(p.startswith("web/") for p in touched) and \
       os.path.isdir(os.path.join(WEB, "node_modules")):
        try:
            npx = r"C:\Program Files\nodejs\npx.cmd"
            if not os.path.exists(npx):
                npx = "npx.cmd" if os.name == "nt" else "npx"
            env = dict(os.environ)
            env["PATH"] = r"C:\Program Files\nodejs;" + env.get("PATH", "")
            r = subprocess.run([npx, "tsc", "--noEmit", "-p", "tsconfig.json"],
                               cwd=WEB, capture_output=True, text=True, env=env, timeout=180)
            if r.returncode != 0:
                first = (r.stdout or r.stderr or "").strip().splitlines()
                problems.append("web types: " + (first[0][:120] if first else "tsc failed"))
        except (OSError, subprocess.SubprocessError):
            pass   # a state doctor must never crash; types are re-checked in session
    if not problems and any(p.startswith("daemon/") and p.endswith(".py") for p in touched):
        r = subprocess.run([sys.executable, "-c", "import " + ",".join(CORE_MODULES)],
                           cwd=DAEMON, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            problems.append("daemon wiring: " + (r.stderr or "").strip().splitlines()[-1][:120])
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import design_lint
        problems += ["design: " + v for v in design_lint.lint(touched)]
    except Exception:
        pass   # never crash the doctor
    return problems


def hygiene_problems():
    problems = []
    tracked = _git("ls-files").splitlines()
    for t in tracked:
        base = os.path.basename(t)
        if (base in SECRET_NAMES or base.endswith(".env")) and not t.startswith(".claude/"):
            problems.append("secret file tracked: " + t)
    try:
        sys.path.insert(0, DAEMON)
        import importlib, debt as _d
        importlib.reload(_d)
        for item in _d.DEBT:
            if item.get("status") not in ("open", "in_progress", "paid"):
                problems.append("debt register: %s bad status" % item.get("id"))
            for k in ("id", "title", "status", "what", "why_it_bites", "trigger", "fix"):
                if k not in item:
                    problems.append("debt register: %s missing %s" % (item.get("id", "?"), k))
    except Exception as e:
        problems.append("debt.py unreadable: %s" % str(e)[:100])
    return problems


def archive_workorder():
    wo = workorder()
    if wo is None:
        return
    hist = os.path.join(LOOPDIR, "history")
    os.makedirs(hist, exist_ok=True)
    dst = os.path.join(hist, time.strftime("%Y%m%d-%H%M%S") + ".md")
    os.replace(WORKORDER, dst)


# each shippable artifact vs ONLY the source that feeds it - so a web change
# doesn't flag the APK (whose Kotlin is untouched) as stale, and vice versa.
ARTIFACT_SRC = {
    "desktop/release/SwarmDeck-Setup-0.2.0-x64.exe": ("daemon", "web/app", "web/components", "web/lib"),
    # the shippable Android artifact is the SIGNED release build (debug is only
    # a local convenience build and is never distributed)
    "apk/app/build/outputs/apk/release/app-release.apk": ("apk/app/src",),
    "glasses/dist/swarmdeck-glasses.zip": ("glasses/index.html", "glasses/styles.css", "glasses/app.js"),
}
_SKIP = ("node_modules", ".next", "__pycache__", os.sep + "build", os.sep + "dist")
# only SOURCE files count - not the running daemon's data (events.jsonl,
# swarmdeck.db, settings.json, ...), which would otherwise flag every artifact
# stale on each turn.
_CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".kt", ".kts")


def _src_mtime(srcs):
    paths = []
    for s in srcs:
        sp = os.path.join(ROOT, s)
        if os.path.isdir(sp):
            for root, _, files in os.walk(sp):
                if any(x in root for x in _SKIP):
                    continue
                paths.extend(os.path.join(root, f) for f in files if f.endswith(_CODE_EXT))
        elif os.path.exists(sp):
            paths.append(sp)
    return newest_mtime(paths)


def build_stale():
    """True if a shippable artifact is missing or older than ITS OWN source - so
    the loop nudges `build_all` before it rests. Only checked once work has gone
    quiet, so it never runs on every keystroke."""
    for art, srcs in ARTIFACT_SRC.items():
        ap = os.path.join(ROOT, art)
        if not os.path.exists(ap):
            return True
        if _src_mtime(srcs) > os.path.getmtime(ap):
            return True
    return False


def transitions():
    """Ordered (STATE, action); first is THE next action."""
    touched = dirty_files()
    wo = workorder()

    if not touched:
        if wo is not None:            # loop finished by a commit - close the book
            archive_workorder()
        return []

    t = []
    if wo is None:
        os.makedirs(LOOPDIR, exist_ok=True)
        t.append(("ALIGN", "work in flight without a workorder - create .loop/workorder.md "
                  "(template written) and fill '## Request' + '## Alignment': does this fit "
                  "CLAUDE.md laws + the charter? Refuse or adjust if not."))
        try:
            if not os.path.exists(WORKORDER):
                with open(WORKORDER, "w", encoding="utf-8") as f:
                    f.write(WORKORDER_TEMPLATE)
        except OSError:
            pass
        return t
    if not (section_filled(wo, "## Request") and section_filled(wo, "## Alignment")):
        t.append(("ALIGN", "fill '## Request' + '## Alignment' in .loop/workorder.md - "
                  "the request vs repo philosophy (CLAUDE.md laws, charter)."))
        return t
    if not section_filled(wo, "## Analysis"):
        t.append(("ANALYZE", "fill '## Analysis' in .loop/workorder.md - architecture "
                  "impact + debt delta (register shortcuts in daemon/debt.py)."))
        return t

    ui_work = any(p.startswith("web/") for p in touched)
    design = (" DESIGN MODE: apply .claude/skills/impeccable (read its SKILL.md "
              "before writing UI; tokens + laws in web/app/globals.css win on "
              "conflict)." if ui_work and os.path.isdir(
                  os.path.join(ROOT, ".claude", "skills", "impeccable")) else "")
    red = checks_red(touched)
    if red:
        t.append(("EXECUTE", "checks red - build/fix: " + " | ".join(red[:2]) + design))
        return t

    if not section_filled(wo, "## Verified"):
        adv = (" Then adversarial-test THIS feature (not a generic walk): apply "
               ".claude/skills/adversarial-test - list how a careless/hostile user "
               "breaks the thing you just built, try each, record pass/fail in Verified.")
        t.append(("TEST", "checks green but nothing verified - run the real thing "
                  "(e2e; UI = screenshot and JUDGE) and fill '## Verified'." + design + adv))
        return t

    hyg = hygiene_problems()
    if hyg:
        t.append(("CLEAN", " | ".join(hyg[:2])))
        return t

    quiet = (time.time() - newest_mtime(touched)) > WIP_MIN * 60
    if quiet and build_stale():
        t.append(("BUILD", "work verified & quiet, but shippable artifacts are stale - run "
                  "`bash tools/build_all.sh` to rebuild installer + APK + glasses from "
                  "current source (or `win`/`apk`/`glasses` for one), THEN propose the commit."))
        return t
    if quiet:
        t.append(("COMMIT", "loop complete, %d file(s) quiet - propose the commit "
                  "(workorder archives on clean tree): %s"
                  % (len(touched), ", ".join(touched[:4]))))
    else:
        t.append(("WIP", "loop complete, edits still fresh (%d files) - serve the user; "
                  "propose the commit when work goes quiet" % len(touched)))
    return t


def print_table():
    t = transitions()
    if not t:
        print("[loop_state] DONE - clean tree, no open workorder. Loop: "
              "ALIGN > ANALYZE > EXECUTE > TEST > CLEAN > BUILD > COMMIT.")
        return
    print("[loop_state] loop position:")
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
    t = [x for x in transitions() if x[0] != "WIP"]
    if not t:
        return
    st, act = t[0]
    print(json.dumps({
        "decision": "block",
        "reason": "[loop_state] The build loop is not at a resting state: %s - %s "
                  "Do this now if it needs no user input; if you are genuinely blocked "
                  "on the user (or a check stayed red after ~3 fix attempts), say exactly "
                  "what you need and stop. Full picture: python tools/loop_state.py" % (st, act)
    }))


def session_start():
    print("[loop_state] Session (re)start - loop position recomputed from disk:")
    print_table()
    print("Rule: ALIGN before code, ANALYZE before building, TEST means judged not "
          "rendered, COMMIT closes the loop. If the next action needs no user input, "
          "do it now.")


if __name__ == "__main__":
    if "--stop-hook" in sys.argv:
        stop_hook()
    elif "--session-start" in sys.argv:
        session_start()
    else:
        print_table()
    sys.exit(0)
