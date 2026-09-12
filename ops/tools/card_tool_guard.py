# -*- coding: utf-8 -*-
"""PreToolUse hook for a card worker (wired via cells/engineer/harness/settings/card.json).

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

CLIENT-SCOPE BUILD/TEST ALLOWLIST (2026-08-25, owner request: a client card
must still be able to WORK, not just be fenced in). Measured first, not
assumed: acceptEdits already auto-approves ordinary in-worktree shell (ls,
mkdir, git, etc. - no allow-list entry needed) but the CLI treats toolchain
launchers like npm as needing explicit approval regardless of the actual
subcommand, which headless mode can never give. card.json's static
`permissions.allow` is one global list with no notion of scope; rather than
grow that file with client-specific nuance, this hook grants a CURATED,
narrow set of build/test invocations via permissionDecision:"allow" (proven
in the same probe session to genuinely pre-approve a command the base CLI
would otherwise block) - but ONLY under HELMDECK_TOOL_SCOPE=client, and
ONLY after the same path-escape scan every Bash command already goes
through. A DENY-first check for package-mutating/publishing verbs
(install, publish, add a dependency, ...) wins even if a command's prefix
would otherwise match the allowlist - "run the tests" and "add a new
dependency from the network" are different risk classes and must not share
one gate.

Matched on ARGV, not the raw string (_client_allow_argv_hit): the first cut
of this allowlist matched a raw string prefix, so "npm run test; rm -rf /"
matched "npm run test" and _grant()'d the whole line - found by adversarial
testing the same day, before landing, and fixed before this file was ever
committed. See _grant()'s own comment for the invariant that closes the
class of bug, not just this one instance.

FAIL-CLOSED ON OUR OWN BUGS: a PreToolUse hook that crashes does NOT block the
tool call (measured in the same probe session - a Python SyntaxError in a
test hook let the call through, permission_denials stayed empty). So every
branch below is wrapped; an unexpected exception denies rather than allows -
the one place in this file where "safe default" and "permissive default" are
opposites, and permissive is not safe.
"""
import json
import os
import re
import shlex
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


def _grant(reason):
    # INVARIANT (learned the hard way, 2026-08-25): a pre-approve must be at
    # LEAST as strict as whatever check it skips past. _bash_escape_paths'
    # own docstring below says it relies on the base CLI's static analysis
    # to already catch `;`/`&`/`$(...)` shell-chaining - but _grant() runs
    # BEFORE that analysis gets a turn (that IS the point: pre-approving
    # something the CLI would otherwise hold). So every _grant() call site
    # must independently re-verify that same property itself. The first
    # version of the client-scope allowlist didn't: it matched a RAW STRING
    # prefix, so "npm run test; rm -rf /" matched "npm run test" and got
    # the whole line - chained rm included - waved through. Fixed same day
    # by _client_allow_argv_hit (argv-tokenized + metachar refusal), pinned
    # in ops/tests/test_card_tool_guard.py. Any NEW _grant() call site must
    # clear this bar too, not just "looks like a safe prefix".
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


_PATH_KEYS = ("file_path", "path", "notebook_path")

# ---------------------------------------------------------------------------
# HARD INVARIANTS FOR EVERY SCOPE (owner decree 2026-09-12: "mehr Rechte geben
# und dann ueber Hook einschraenken"). Henry's broker and the machine/direct
# cards run --permission-mode bypassPermissions; the Bash allow-list is gone
# as a boundary, so the things the laws protect are enforced HERE, as code
# that needs no judgement (HARNESS dual architecture: judgement -> Henry,
# invariants -> code, never judgement in hooks). Deterministic, word/regex
# based, fail-closed like everything else in this file. NOT a shell parser
# (debt live-guard-text-scan): it catches the honest mistake and the obvious
# command, not an adversary - the OS sandbox is the only thing that would.
#
# A deny here comes back to the model WITH its reason (permissionDecisionReason),
# which is the other half of the decree: a headless permission deny is silent
# and Henry used to invent a cause for it ("Sandbox-Policy", 3 times).
_SECRET_MARKERS = ("daemon/settings.json", "daemon/users.json", "helmdeck.db",
                   "daemon/certs", ".keystore", ".pem", "copilot_log.json")
# process killers + anything that says "the daemon tree": taskkill /IM
# pythonw.exe, /T (tree), /F on a python image, Stop-Process -Name python...
_KILL_RE = re.compile(r"\b(taskkill|tskill|stop-process|pkill|killall|kill)(\.exe)?\b", re.I)
_DAEMON_RE = re.compile(r"python|daemon\.swarm|8140|/im\b|/t\b|-name\b|-processname\b|-force\b", re.I)
_FORCE_PUSH_RE = re.compile(
    r"\bgit\b[^;&|]*\bpush\b[^;&|]*(\s--force(-with-lease)?\b|\s-f\b|\s\+[\w./-]+)", re.I)
# history-destroying verbs, denied on the LIVE tree only (a worktree card may
# reset its own branch; the owner's checkout is not the card's to rewrite)
_LIVE_GIT_RE = re.compile(
    r"\bgit\b[^;&|]*\b(reset\s+--hard|clean\s+-[a-z]*[fdx]|worktree\s+(remove|prune)|branch\s+-D)\b", re.I)
_SCHTASKS_RE = re.compile(r"\bschtasks(\.exe)?\b", re.I)
# the ONE scheduled task an agent may touch, and only to run/create/query it
# (ops/tools/restart_helmdeck.ps1 - the restart route that survives the
# daemon's own taskkill /T). Double slashes are how Git Bash spells /Run.
_SCHTASKS_OK = re.compile(r"/+(run|create|query)\b[^;&|]*/+tn\s+\"?helmdeckrestart", re.I)
_MEMORY_DIR = ".claude/projects"
_WRITEY_RE = re.compile(r"(\b(rm|del|erase|remove-item|ri|mv|move|move-item|set-content|out-file|add-content|cp|copy|copy-item|tee)\b|>)", re.I)


def _norm(s):
    return (s or "").replace("\\", "/").lower()


def _secret_in(s):
    n = _norm(s)
    for m in _SECRET_MARKERS:
        if m in n:
            return m
    # `.env` as a FILE, not the word "environment"
    if re.search(r"(^|[/\s\"'])\.env(\.[a-z0-9]+)?([\s\"']|$)", n):
        return ".env"
    return ""


def _live_rule_hit(tool, ti, worktree):
    """The reason to deny, or "" - pure function over the hook payload."""
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        hit = _secret_in(cmd)
        if hit:
            return "touches a HelmDeck secret (%s) - never readable/writable by an agent" % hit
        if _KILL_RE.search(cmd) and _DAEMON_RE.search(cmd):
            return ("kills processes by image/tree - the daemon (and this very session) "
                    "live in that tree; the restart route is: schtasks //Run //TN HelmDeckRestart")
        if _FORCE_PUSH_RE.search(cmd):
            return "force-push rewrites shared history - not available to an agent"
        if not worktree and _LIVE_GIT_RE.search(cmd):
            return "history-destroying git verb on the owner's live checkout (reset --hard / clean / worktree remove / branch -D)"
        if _SCHTASKS_RE.search(cmd) and not _SCHTASKS_OK.search(cmd):
            return "schtasks: only /Run, /Create or /Query on the HelmDeckRestart task is allowed"
        if _MEMORY_DIR in _norm(cmd) and _WRITEY_RE.search(cmd):
            return "writes into the shared memory directory (~/.claude/projects) - read-only for agents"
        return ""
    if tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        for k in _PATH_KEYS:
            p = ti.get(k) or ""
            if not p:
                continue
            hit = _secret_in(p)
            if hit:
                return "%s targets a HelmDeck secret (%s)" % (tool, hit)
            if tool != "Read":
                n = _norm(p)
                if "/.git/" in n or n.endswith("/.git"):
                    return "%s targets .git internals" % tool
                if _MEMORY_DIR in n:
                    return "%s targets the shared memory directory - read-only for agents" % tool
    return ""

# Package-mutating/publishing verbs - network egress and arbitrary
# postinstall-script execution, the two things a client card must not get
# just because its stated task happens to touch a package.json. Checked as
# whole words so "install" doesn't also kill "npm run reinstall-fixtures"
# (a project script name), and matched BEFORE the allowlist so it wins on
# any overlap.
_DENY_VERBS = (
    "install", "uninstall", "add", "remove", "publish", "unpublish",
    "link", "unlink", "update", "upgrade", "dedupe", "audit", "ci",
    "config", "login", "logout", "token", "owner", "deprecate", "star",
    "pip3",  # bare pip/pip3 invocation without an allowlisted subcommand
)

# Curated, narrow build/test invocations - matched as an ARGV PREFIX (not a
# raw string prefix; see _client_allow_argv_hit). ("npm","run") alone means
# "npm run <any script name>" - the script itself still runs inside the
# worktree under the card's own permissions, same trust boundary the old
# string-prefix form already accepted; this only changes HOW the prefix is
# matched, not what scope it grants.
_CLIENT_ALLOW_ARGV = (
    ("npm", "run"),
    ("npm", "test"),
    ("npx", "tsc", "--noEmit"),
    ("npx", "jest"),
    ("npx", "eslint"),
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("py", "-3.12", "-m", "pytest"),
    ("py", "-3.12", "ops/tools/run_gate.py"),
    ("python", "ops/tools/run_gate.py"),
)

# Shell control operators that would let a second, unreviewed command ride
# in after an otherwise-legitimate prefix. Checked on the RAW string BEFORE
# any tokenizing - shlex.split() is a plain word-splitter, not a POSIX/cmd
# shell, so it does not treat `;`/`&`/`|` as separators; it would just hand
# back "test;" or "rm" as ordinary-looking tokens, silently defeating an
# argv-prefix match if this check were skipped. Measured 2026-08-25: before
# this existed, "npm run test; rm -rf /" matched the "npm run test" STRING
# prefix and _grant()'d the whole line, chained rm included.
_SHELL_METACHARS = (";", "&", "|", "`", "$(", "\n", "\r", ">", "<")


def _client_allow_argv_hit(command):
    """True if `command` is EXACTLY one curated invocation - its argv starts
    with one of _CLIENT_ALLOW_ARGV's tuples - and carries no shell control
    operator that could chain a second command after it. Any ambiguity
    (a metacharacter present, or shlex failing to parse the string at all -
    unbalanced quotes) refuses the fast-grant; that is NOT a new denial, it
    is simply "no opinion", falling through to the same _allow() this
    command would have reached before this allowlist ever existed."""
    if any(ch in (command or "") for ch in _SHELL_METACHARS):
        return False
    try:
        argv = shlex.split(command or "", posix=(os.name != "nt"))
    except ValueError:
        return False
    if not argv:
        return False
    for prefix in _CLIENT_ALLOW_ARGV:
        if len(argv) < len(prefix) or tuple(argv[:len(prefix)]) != prefix:
            continue
        if prefix == ("npm", "run") and len(argv) < 3:
            continue   # "npm run" alone names no script - nothing to grant
        return True
    return False


def _bash_word_hit(command, words):
    import re
    toks = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", (command or "").lower()))
    return next((w for w in words if w in toks), None)


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

    # Hard invariants first, in EVERY scope (worktree card, live-tree direct/
    # machine card, Henry's broker with no worktree at all).
    try:
        why = _live_rule_hit(tool, ti, worktree)
    except Exception as e:                                     # noqa: BLE001
        _deny("card_tool_guard: internal error in the invariant check, refusing (%s)" % str(e)[:120])
        return
    if why:
        _deny("card_tool_guard: " + why)
        return

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
            command = ti.get("command") or ""
            bad = _bash_escape_paths(command, worktree)
            if bad:
                _deny("card_tool_guard: command references %r, outside "
                      "this card's worktree" % bad)
                return
            if scope == "client":
                hit = _bash_word_hit(command, _DENY_VERBS)
                if hit:
                    _deny("card_tool_guard: '%s' is a package-mutating/"
                          "publishing command, not available on a "
                          "client-filed card" % hit)
                    return
                if _client_allow_argv_hit(command):
                    _grant("card_tool_guard: curated build/test command "
                           "for a client-filed card")
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
