# -*- coding: utf-8 -*-
"""Agent-CLI / argv / MCP-config plumbing — extracted from drivers.py (the 1.5k
line spawn module) as a clean, self-contained module seam. These are the helpers
that resolve the real `claude` executable behind an npm .cmd shim, decide the
quote-safe spawn form, and bridge a driver's MCP tool grants to their server
definitions in ~/.claude.json. None are monkeypatched by the test suite, and
their only external dependency is drivers.CLAUDE (referenced lazily to avoid a
circular import). drivers.py re-imports these names, so build_argv/_spawn and
copilot.argv_form_safe callers are unchanged.
"""
import json
import os
import re as _re
import shutil
import subprocess


def _real_claude_exe(cmd_path):
    """The actual executable behind an npm `claude.cmd` shim, or None.

    THE SILENT CONTEXT KILLER (found 2026-08-10, 'warum immer Kontext
    verloren'): running claude.cmd via `cmd /s /c "<list2cmdline(argv)>"` is
    NOT quote-safe. Our --append-system-prompt brief contains JSON double
    quotes (the <helmdeck-ask> protocol); list2cmdline escapes them as \\" but
    cmd.exe does not understand backslash escaping, and the .cmd shim re-parses
    %* a second time. The argument boundaries shift and the TRAILING args are
    swallowed - `--resume <sid>` is last, so every respawn silently started a
    FRESH session instead of resuming (reproduced deterministically: the same
    argv resumes fine as an argv list against the real exe, and loses the
    session as a cmd-string through the shim; the BatBadBut class - .cmd
    targets are not safely quotable, CVE-2024-24576).

    So: never exec the shim. Resolve what it points at (npm layout:
    <dir>\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe, or
    cli.js + node.exe for older installs) and spawn THAT as a plain argv list,
    which CreateProcess + CommandLineToArgvW quote correctly."""
    d = os.path.dirname(os.path.abspath(cmd_path))
    exe = os.path.join(d, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
    if os.path.isfile(exe):
        return [exe]
    js = os.path.join(d, "node_modules", "@anthropic-ai", "claude-code", "cli.js")
    node = os.path.join(d, "node.exe")
    if os.path.isfile(js) and os.path.isfile(node):
        return [node, js]
    return None


def _cmd_line(argv):
    """Spawn form for the agent CLI. On Windows a .cmd shim cannot be spawned
    directly by CreateProcess, and routing it through `cmd /s /c` mangles
    quoted arguments (see _real_claude_exe - it silently ate `--resume`).
    Prefer resolving the shim to its real executable and returning a PLAIN
    ARGV LIST; the cmd.exe string form survives only as the last-resort
    fallback for a shim we cannot see through - with the known quote hazard."""
    if os.name != "nt":
        return argv
    head = str(argv[0]).lower()
    if head.endswith((".cmd", ".bat")):
        real = _real_claude_exe(argv[0])
        if real:
            return real + list(argv[1:])
        return 'cmd /s /c "%s"' % subprocess.list2cmdline(argv)
    return list(argv)


def argv_form_safe(exe=None):
    """True when a spawn will pass arguments as a REAL argv list, so an argument
    may safely contain quotes, newlines and JSON.

    The fallback branch of _cmd_line builds a `cmd /s /c "<string>"` command line,
    and that form is not quote-safe (the BatBadBut class - see _real_claude_exe;
    it is what silently ate `--resume`). Anything long and quote-heavy must ASK
    before it rides on an argv: copilot.py uses this to decide whether its 10 KB
    system prompt can go in --append-system-prompt (real role separation) or has
    to stay in the stdin prompt (the old way, safe everywhere)."""
    if exe is None:
        from daemon.spine import drivers  # lazy: drivers.CLAUDE is the single source, no import cycle
        exe = drivers.CLAUDE
    if os.name != "nt":
        return True
    if not str(exe).lower().endswith((".cmd", ".bat")):
        return True
    return _real_claude_exe(exe) is not None


def _opts_sig(cfg, t):
    """The launch options that, if changed, require a fresh query (Paseo's
    queryRestartNeeded). A steer with a different model/mode/tool-grant can't be
    fed to a process already launched with the old ones."""
    return (cfg.get("perm", t.get("perm", "acceptEdits")),
            cfg.get("model") or t.get("model") or "",
            tuple(cfg.get("allowed_tools") or []))


def _user_mcp_servers():
    """The user-scope MCP servers from ~/.claude.json - the SAME file
    `claude mcp add -s user` writes, and the single source of truth for a
    globally-configured server like windows-mcp. Returns {} on any error so a
    spawn is never broken by a missing or malformed config (test_never_breaks
    _a_spawn is a law here)."""
    try:
        path = os.path.join(os.path.expanduser("~"), ".claude.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("mcpServers") or {}
    except Exception:
        return {}


def _resolve_cmd(cmd):
    """Absolute path for a bare MCP-server command (e.g. `uvx`), robust to the
    daemon NOT inheriting the user's Python/uv Scripts dir on PATH - a tray or
    service launch usually doesn't, and that is exactly what turns an injected
    server from `pending` (connecting) into `failed` (measured: bare `uvx`
    failed, the absolute path connected). Tries PATH first, then the standard
    user-local install locations uv/uvx/pipx use. Returns None if nothing
    matches - the caller keeps the bare command and warns LOUDLY, so a miss is
    diagnosable instead of a silent failure to connect."""
    hit = shutil.which(cmd)
    if hit:
        return hit
    import glob
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, ".local", "bin"),
            os.path.join(home, ".cargo", "bin")]
    dirs += glob.glob(os.path.join(home, "AppData", "Local", "Programs",
                                   "Python", "Python*", "Scripts"))
    dirs += glob.glob(os.path.join(home, "AppData", "Roaming", "Python",
                                   "Python*", "Scripts"))
    existing = [d for d in dirs if os.path.isdir(d)]
    return shutil.which(cmd, path=os.pathsep.join(existing)) if existing else None


def _mcp_config_arg(cfg):
    """`--mcp-config` for the MCP servers a driver's tool grants actually need.

    THE BUG THIS CLOSES: an `allowed_tools` pattern `mcp__<server>__*` only
    PRE-AUTHORIZES a server's tools - it does not REGISTER the server. Cards
    spawn with `--setting-sources project` (harness.cli_args), which drops the
    USER settings layer where a globally-configured server like windows-mcp
    lives. So the grant named a server the process never loaded, and the tools
    simply did not exist - measured, not reasoned: with only `--setting-sources
    project` the CLI's system/init lists no windows-mcp at all, and a card's
    ToolSearch finds nothing however many times it looks. `--allowedTools
    mcp__windows-mcp__*` was authorising a ghost.

    THE FIX: bridge the grant to its definition from the ONE source of truth -
    the user's own ~/.claude.json mcpServers - and hand it to the spawn via
    `--mcp-config`, which is ADDITIVE and independent of --setting-sources (so
    the personal rtk-hook/model/skill layer stays dropped; only the named
    server comes back). Proven at the real CLI 2.1.207: with this flag the
    server appears in system/init; without it, it is absent. No second copy of
    the config to drift.

    A bare server command (`uvx`) is resolved to an absolute path via the
    daemon's own PATH, because the daemon is often launched from the tray or a
    bare shell and the spawned CLI cannot be assumed to find it otherwise -
    verbatim if PATH can't resolve it (never invent a path). A server the grant
    NAMES but the user config does not DEFINE is reported, never dropped in
    silence (HARNESS.md's measured trap: the CLI ignores a bad config quietly)."""
    try:
        wanted = set()
        for pat in cfg.get("allowed_tools") or []:
            m = _re.match(r"^mcp__(.+?)__", pat)
            if m:
                wanted.add(m.group(1))
        if not wanted:
            return []
        avail = _user_mcp_servers()
        picked = {}
        for n in wanted:
            if n not in avail:
                continue
            d = dict(avail[n])
            cmd = d.get("command")
            if cmd and os.path.basename(cmd) == cmd:      # bare name, no dir
                resolved = _resolve_cmd(cmd)
                if resolved:
                    d["command"] = resolved
                else:
                    print("DRIVERS: MCP server '%s' command %r is not on the "
                          "daemon PATH nor the usual user-local bins - it will "
                          "likely fail to start; add its dir to the daemon PATH "
                          "or the driver's env in settings.json." % (n, cmd))
            picked[n] = d
        missing = wanted - set(picked)
        if missing:
            print("DRIVERS: driver grants MCP server(s) not defined in "
                  "~/.claude.json mcpServers - UNAVAILABLE to the card: %s"
                  % ", ".join(sorted(missing)))
        if not picked:
            return []
        return ["--mcp-config", json.dumps({"mcpServers": picked})]
    except Exception as e:
        print("DRIVERS: _mcp_config_arg skipped (%s)" % e)
        return []
