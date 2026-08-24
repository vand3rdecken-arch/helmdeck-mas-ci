# -*- coding: utf-8 -*-
"""Spawn environment - the EXTERNAL env an agent shell inherits, extracted
from drivers.py. _card_env is the per-card overlay (dev port / worktree),
_env layers the driver's settings.json env + Bash/MCP tool timeouts over a
sanitized copy of the daemon os.environ (control/TLS keys AND parent-Claude-
session keys stripped). Pure (os + dicts); drivers.py re-imports
_card_env/_env. Not monkeypatched.
"""
import os


# RUNTIME_CONTROL_ENV_KEYS split: internal env = the daemon's own, external
# env = sanitized for every spawned process). TLS material paths and the
# daemon's claude-binary override are supervision config, not build env; and
# BASH_ENV could rewrite the env behind our back in every shell the agent runs
# (Paseo strips it in createStringCommandShellEnv for the same reason).
_CONTROL_ENV_KEYS = ("HELMDECK_TLS_CERT", "HELMDECK_TLS_KEY", "HELMDECK_TLS_PORT",
                     "HELMDECK_CLAUDE", "BASH_ENV")

# PARENT-SESSION LEAKAGE: when the daemon itself runs inside a Claude Code
# session (a machine/direct card driving the live tree with a Claude Code
# window as its host, or plain dev-from-inside-Claude), these vars are already
# in the daemon's own os.environ and would otherwise pass straight through to
# every spawned card - which the child CLI reads as "I am already nested
# inside another session" and refuses to start. probe_harness_settings.py hit
# this and hand-strips CLAUDE*/CLAUDECODE for its own subprocess (see its
# _probe docstring, "THE ENV IS SCRUBBED OF CLAUDE*") - that was a probe-only
# workaround; production spawns had no such guard. Same lesson Paseo names
# explicitly (PARENT_SESSION_ENV_VARS, provider-launch-config.ts): scrub it
# once, here, for every driver, not per-caller.
_PARENT_SESSION_ENV_KEYS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                           "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_SESSION_ID",
                           "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_AGENT_SDK_VERSION")


def _card_env(t):
    """Per-card overlay for the agent env (Paseo resolveWorktreeRuntimeEnv):
    where the card lives and its reserved dev port, so build/test scripts can
    bind HELMDECK_DEV_PORT instead of fighting siblings over the project's
    default port. Deliberately NOT exposed: the source checkout path (Paseo's
    PASEO_SOURCE_CHECKOUT_PATH) - that is where the secrets live that the
    worktree was isolated away from."""
    if not t:
        return {}
    out = {}
    if t.get("dev_port"):
        out["HELMDECK_DEV_PORT"] = str(t["dev_port"])
    if t.get("worktree"):
        out["HELMDECK_WORKTREE"] = str(t["worktree"])
    if t.get("branch") and not t.get("machine"):
        out["HELMDECK_BRANCH"] = str(t["branch"])
    return out


def _env(cfg, card=None):
    """The environment the agent's shell inherits (the EXTERNAL env model -
    the daemon's own os.environ stays the internal one).

    A card runs in an isolated worktree, which keeps cards from trampling each
    other - but isolation alone does not give the agent a BUILD environment. The
    daemon is usually started from a bare shell (or by the desktop app), so
    JAVA_HOME / ANDROID_HOME / SDK paths are simply absent and any gradle,
    xcode or dotnet build fails before it starts. Declare them once per driver
    in settings.json:

        "drivers": {"claude": {"type": "claude", "env": {
            "JAVA_HOME": "C:/Program Files/Android/Android Studio/jbr",
            "ANDROID_HOME": "C:/Users/you/AppData/Local/Android/Sdk"}}}

    Values are layered over the daemon's own environment, and PATH entries can
    be prepended with the "PATH+" key so the toolchain wins without discarding
    the inherited PATH.
    """
    env = dict(os.environ)
    for k in _CONTROL_ENV_KEYS:
        env.pop(k, None)
    for k in _PARENT_SESSION_ENV_KEYS:
        env.pop(k, None)
    # Bash tool timeouts (Paseo-parity: bound the TOOL, not the turn). Without
    # these a single runaway command - a stuck `adb`, an endless poll - hung the
    # whole turn until the 30-min turn kill or a human hit Stop. Paseo relies on
    # the agent CLI's own per-tool timeout instead: a command that exceeds its
    # bound is killed at the TOOL layer and returns an error to the agent, which
    # then adapts (shorter polls) - no manual Stop needed. A silence/inactivity
    # watchdog would be wrong here: a legitimate long command (waiting on a
    # download) also emits no output while it runs, so you cannot tell hung from
    # busy by silence - only a tool bound distinguishes them. setdefault so the
    # daemon's own env and a driver's `env` in settings.json still win.
    env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "120000")   # 2 min default / command
    env.setdefault("BASH_MAX_TIMEOUT_MS", "300000")       # 5 min ceiling the agent can't exceed
    # MCP server STARTUP grace. A stdio server launched via `uvx <pkg>` cold-
    # starts by resolving+downloading the package the first time, which blows
    # past the CLI's short default and the server lands `failed` on a card's
    # first desktop turn (measured: windows-mcp needed the longer window to move
    # off `pending`). setdefault so the daemon's own env / a driver's env wins.
    env.setdefault("MCP_TIMEOUT", "60000")                # 60s for a cold MCP server to connect
    # Per-CALL MCP tool bound (same "bound the TOOL, not the turn" rule as the
    # Bash timeouts above). A synchronous windows-mcp call that never returns - a
    # foreground `wrangler dev` launched through PowerShell, a wedged WMI query -
    # otherwise hung the whole turn until the 900s silence watchdog, and for a
    # DESKTOP card that whole time it holds the single _desktop_lock and starves
    # every other desktop card (measured: a wedged COWORK turn bounced a machine
    # card). Bounding each call kills the wedge at the TOOL layer, hands the agent
    # an error to adapt to, and lets the turn end - releasing the lock in minutes,
    # not the full silence window. setdefault so the daemon/driver env still wins.
    env.setdefault("MCP_TOOL_TIMEOUT", "300000")          # 5 min ceiling per MCP tool call
    if card:
        env.update(card)                                  # per-card overlay (_card_env)
    extra = cfg.get("env") or {}
    prepend = extra.get("PATH+")
    for k, v in extra.items():
        if k != "PATH+":
            env[k] = str(v)
    if prepend:
        env["PATH"] = str(prepend) + os.pathsep + env.get("PATH", "")
    return env
