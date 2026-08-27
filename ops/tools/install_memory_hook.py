# -*- coding: utf-8 -*-
"""Install (or verify) the memory auto-commit Stop hook into ~/.claude.

WHAT THIS DEPLOYS AND WHY IT IS TWO FILES
-----------------------------------------
The hook has to live in ~/.claude/hooks/ - it must run for EVERY project,
including ones in other repos and ones that do not exist yet, so it cannot be
loaded from inside any single project. But a script that exists only there is
itself untracked, unreviewed and undiffable, which is precisely the problem the
hook is being installed to solve. So:

    ops/tools/memory_autocommit.py        canonical - versioned, reviewed, gated
    ~/.claude/hooks/memory_autocommit.py   deployed copy, byte-identical

and this installer keeps them equal. `--check` reports drift without changing
anything, so the gate can assert the deployed copy has not been edited out from
under the repo (or simply gone stale after a pull).

WHY `Stop` AND NOT `SessionEnd`
-------------------------------
Stop fires after every turn, so a note written mid-session is captured within
the same session. SessionEnd fires once and is missed entirely if the process
dies - which is exactly the case where you most want the snapshot to already
exist. The cost of Stop is that it runs often, so the hook is written to be
near-free when there is nothing to commit (one `git status --porcelain` per
memory directory).

WHERE IT WILL AND WILL NOT RUN
------------------------------
~/.claude/settings.json is the operator's PERSONAL layer. HelmDeck's own card
and copilot spawns drop that layer (`--setting-sources project` / `""`), so this
hook never runs inside a card - correctly, because a card cannot write to a
memory directory at all (ops/harness/settings/card.json denies Write/Edit there,
measured against the real CLI). Interactive sessions are the only writers, and
they are exactly what this covers.

Usage:
    py -3.12 ops/tools/install_memory_hook.py            # install / update
    py -3.12 ops/tools/install_memory_hook.py --check    # report drift, change nothing
    py -3.12 ops/tools/install_memory_hook.py --uninstall
"""
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "ops", "tools", "memory_autocommit.py")

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
HOOKS = os.path.join(CLAUDE, "hooks")
DST = os.path.join(HOOKS, "memory_autocommit.py")
SETTINGS = os.path.join(CLAUDE, "settings.json")

# Matches the form the operator's existing hooks already use
# (`python "$HOME/.claude/hooks/no_push_worktime.py"`) rather than inventing a
# second convention on the same machine.
COMMAND = 'python "$HOME/.claude/hooks/memory_autocommit.py"'
MARKER = "memory_autocommit.py"          # how we recognise OUR entry, idempotently
EVENT = "Stop"
STATUS = "Snapshotting project memory"


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _backup(path):
    """Keep the file we are about to replace. settings.json is the operator's
    own config and carries his model pin, permissions and other hooks; an
    installer that mangles it must be undoable without git, because this
    directory has none."""
    cur = _read(path)
    if cur is None:
        return ""
    dst = "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
    try:
        with open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(cur)
        return dst
    except OSError:
        return ""


def script_state():
    """'ok' | 'missing' | 'drift' - is the deployed copy the canonical one?"""
    src, dst = _read(SRC), _read(DST)
    if src is None:
        return "no-source"
    if dst is None:
        return "missing"
    return "ok" if src == dst else "drift"


def hook_entries(settings):
    """Our entries under hooks.Stop, however many (should be 0 or 1)."""
    got = []
    for grp in ((settings.get("hooks") or {}).get(EVENT) or []):
        if not isinstance(grp, dict):
            continue
        for h in grp.get("hooks") or []:
            if isinstance(h, dict) and MARKER in str(h.get("command") or ""):
                got.append(h)
    return got


def load_settings():
    raw = _read(SETTINGS)
    if raw is None:
        return {}, None
    try:
        return json.loads(raw), None
    except ValueError as e:
        return None, "settings.json is not valid JSON: %s" % str(e)[:160]


def check():
    """Report, change nothing. Returns True when fully installed and current."""
    ok = True
    st = script_state()
    print("script : %s -> %s" % (SRC, DST))
    if st == "ok":
        print("         OK (deployed copy is byte-identical to the repo's)")
    elif st == "missing":
        print("         NOT INSTALLED"); ok = False
    elif st == "drift":
        print("         DRIFT - the deployed copy differs from ops/tools/memory_autocommit.py")
        print("         re-run without --check to redeploy"); ok = False
    else:
        print("         SOURCE MISSING (%s)" % SRC); ok = False

    settings, err = load_settings()
    print("hook   : %s (%s)" % (SETTINGS, EVENT))
    if err:
        print("         %s" % err)
        return False
    entries = hook_entries(settings)
    if len(entries) == 1:
        print("         OK (1 entry): %s" % entries[0].get("command"))
    elif not entries:
        print("         NOT WIRED"); ok = False
    else:
        print("         %d DUPLICATE entries - would run the hook %d times per turn"
              % (len(entries), len(entries))); ok = False
    return ok


def install():
    if _read(SRC) is None:
        print("cannot install: %s is missing" % SRC)
        return 1

    os.makedirs(HOOKS, exist_ok=True)
    before = script_state()
    shutil.copyfile(SRC, DST)
    print("script : %s (%s)" % (DST, "updated" if before == "drift" else
                                ("installed" if before == "missing" else "already current")))

    settings, err = load_settings()
    if err:
        # Refuse rather than guess. Rewriting a file we cannot parse would risk
        # destroying the operator's model pin, permissions and other hooks.
        print("REFUSING to touch settings.json: %s" % err)
        print("fix the JSON, then re-run.")
        return 1

    entries = hook_entries(settings)
    if len(entries) == 1:
        # already wired - refresh the command/statusMessage in place, no duplicate
        entries[0]["command"] = COMMAND
        entries[0]["type"] = "command"
        entries[0]["statusMessage"] = STATUS
        changed = True
        note = "already wired (refreshed in place)"
    elif len(entries) > 1:
        print("REFUSING: %d duplicate entries found - remove them by hand first "
              "so nothing is silently deleted." % len(entries))
        return 1
    else:
        hooks = settings.setdefault("hooks", {})
        stop = hooks.setdefault(EVENT, [])
        stop.append({"hooks": [{"type": "command", "command": COMMAND,
                                "statusMessage": STATUS}]})
        changed = True
        note = "wired"

    if changed:
        bak = _backup(SETTINGS)
        _atomic_write(SETTINGS, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        print("hook   : %s in %s%s" % (note, SETTINGS,
                                       (" (backup: %s)" % os.path.basename(bak)) if bak else ""))
    print("\nActive from the NEXT session (hooks are read at session start).")
    return 0


def uninstall():
    settings, err = load_settings()
    if err:
        print("cannot parse settings.json: %s" % err)
        return 1
    stop = (settings.get("hooks") or {}).get(EVENT) or []
    kept = []
    removed = 0
    for grp in stop:
        if not isinstance(grp, dict):
            kept.append(grp); continue
        hs = [h for h in (grp.get("hooks") or [])
              if not (isinstance(h, dict) and MARKER in str(h.get("command") or ""))]
        removed += len(grp.get("hooks") or []) - len(hs)
        if hs:
            grp["hooks"] = hs
            kept.append(grp)
    if removed:
        settings["hooks"][EVENT] = kept
        if not kept:
            settings["hooks"].pop(EVENT, None)
        bak = _backup(SETTINGS)
        _atomic_write(SETTINGS, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        print("removed %d hook entry/entries (backup: %s)" % (removed, os.path.basename(bak)))
    else:
        print("no hook entry found - nothing to remove")
    if os.path.exists(DST):
        os.remove(DST)
        print("removed %s" % DST)
    print("NOTE: the per-project git repos are left untouched - the history stays.")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    if "--uninstall" in sys.argv:
        sys.exit(uninstall())
    sys.exit(install())
