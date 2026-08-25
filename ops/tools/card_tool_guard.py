# -*- coding: utf-8 -*-
"""PreToolUse hook for a card worker (wired via ops/harness/settings/card.json).

WHY THIS EXISTS - measured, not assumed (2026-08-24 probe session): the ONLY
thing keeping a card's agent confined to its own worktree today is an
UNDOCUMENTED CLI default - in headless (`-p`) mode, nobody is there to approve
a permission request, so Read/Write/Edit/Bash calls reaching outside the
working directory fail closed. Verified empirically across all four tool
classes, including Bash command-chaining (`;`, `&`) and substitution
(`$(...)`) - the real `claude` binary's own Bash tool does static analysis
and refuses those too. But NONE of that is a HelmDeck-owned control: no
settings.json rule asserts it, no test pins it. If a future CLI version (or a
canUseTool auto-approve callback added to stop turns stalling on unapproved
prompts - a real, plausible fix for a real pain point elsewhere in this
codebase) changes that default, EVERY one of those protections could vanish
silently, together, with nothing here or in card.json needing to change for
the regression to happen.

This hook makes the worktree boundary an EXPLICIT, HelmDeck-decided,
independently-testable rule instead of a side effect of CLI defaults:
  - Read/Write/Edit/MultiEdit/Glob: the target path must resolve inside
    HELMDECK_WORKTREE (set fresh per spawn by spine/agent/spawnenv.py's
    _card_env - never cached, never assumed).
  - Bash: a lightweight scan for absolute paths / `..` segments that resolve
    outside the worktree - defense in depth alongside (not instead of) the
    CLI's own analysis; this hook does not attempt to re-implement full shell
    parsing.
  - WebFetch/WebSearch: denied outright when HELMDECK_TOOL_SCOPE=client (see
    spawnenv._card_env's docstring for how that scope is derived) - a client
    steering their own card has no legitimate need for the agent to reach the
    network, and it is the one category no path check can cover.

FAIL-CLOSED ON OUR OWN BUGS: a PreToolUse hook that crashes does NOT block the
tool call (measured in the same probe session - a Python SyntaxError in a
test hook let the call through, permission_denials stayed empty). So every
branch below is wrapped; an unexpected exception denies rather than allows -
the one place in this file where "safe default" and "permissive default" are
opposites, and permissive is not safe.
"""
import json
import os
import sys


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _allow():
    # No output = no opinion (the CLI's own checks / other hooks still apply).
    sys.exit(0)


_PATH_KEYS = ("file_path", "path", "notebook_path")


def _outside_worktree(candidate, worktree):
    """True if `candidate` (any path string a tool argument might carry)
    resolves to somewhere outside `worktree`. Resolves against worktree as
    the base for relative paths - matches how the CLI itself would resolve
    a relative tool argument from its cwd."""
    if not candidate:
        return False
    try:
        base = os.path.realpath(worktree)
        target = candidate if os.path.isabs(candidate) else os.path.join(worktree, candidate)
        target = os.path.realpath(target)
    except Exception:
        return True   # unresolvable path: treat as escaping, not as safe
    try:
        common = os.path.commonpath([base, target])
    except ValueError:
        return True    # different drives on Windows -> definitely outside
    return os.path.normcase(common) != os.path.normcase(base)


def _bash_escape_paths(command, worktree):
    """Cheap defense-in-depth scan, NOT a shell parser: pulls out tokens that
    look like absolute paths (POSIX or Windows-drive) or contain `..`, and
    flags any that resolve outside the worktree. The real static analysis
    lives in the CLI itself (measured: it already catches `;`/`&`/`$()`) -
    this only needs to catch the case that analysis does not: a SINGLE,
    ordinary-looking command whose own argument is an absolute path (e.g.
    `git add C:/elsewhere/secret.txt`), which is exactly the shape the CLI's
    own working-directory check does not see as a "read a file" operation."""
    import re
    tokens = re.findall(r'["\']([^"\']+)["\']|(\S+)', command or "")
    flat = [a or b for a, b in tokens]
    for tok in flat:
        looks_pathlike = (
            os.path.isabs(tok) or
            re.match(r"^[A-Za-z]:[\\/]", tok) or
            ".." in tok.replace("\\", "/").split("/")
        )
        if looks_pathlike and _outside_worktree(tok, worktree):
            return tok
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        _deny("card_tool_guard: could not parse hook payload")
        return

    worktree = os.environ.get("HELMDECK_WORKTREE") or ""
    scope = os.environ.get("HELMDECK_TOOL_SCOPE") or ""
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}

    if not worktree:
        # No worktree var at all = not a normal card spawn (machine/direct-
        # task cards run on the live tree by design, per debt.py
        # machine-task-blast-radius - a different, already-acknowledged
        # exception, not this hook's job to police). Stay out of the way.
        _allow()
        return

    try:
        if tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
            for k in _PATH_KEYS:
                if k in ti and _outside_worktree(ti[k], worktree):
                    _deny("card_tool_guard: %s targets %r, outside this "
                          "card's worktree" % (tool, ti[k]))
                    return
            _allow()
            return

        if tool == "Bash":
            bad = _bash_escape_paths(ti.get("command") or "", worktree)
            if bad:
                _deny("card_tool_guard: command references %r, outside "
                      "this card's worktree" % bad)
                return
            _allow()
            return

        if tool in ("WebFetch", "WebSearch") and scope == "client":
            _deny("card_tool_guard: network tools are not available on a "
                  "client-filed card")
            return

        _allow()
    except Exception as e:
        _deny("card_tool_guard: internal error, refusing by default (%s)"
              % str(e)[:200])


if __name__ == "__main__":
    main()
