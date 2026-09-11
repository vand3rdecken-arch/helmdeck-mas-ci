# -*- coding: utf-8 -*-
"""MCP stdio server exposing FIVE bounded browser verbs - navigate/read/find/
click/type - backed by spine/media/browsercap.py's AgentBrowser (CDP-attach
to the persistent, logged-in HelmDeck Chrome).

WHY (ops/docs/backlog/token-burn-hardening/README.md, Karte C): the 190M-
token Wear-OS turn burned its budget on windows-mcp `Snapshot` calls, each
returning 600-700 KB of UIA tree for a page a card only needed to READ or
CLICK something on. Output-shaping IS the deliverable here - every verb's
result is capped at browsercap.MAX_ACTION_CHARS (5000) chars, upstream of the
model context, same principle as ops/tools/mcp_capper.py's channel-level cap
(that proxy wraps an EXISTING server's output after the fact; this module
generates the output small in the first place, so there is nothing to cap
downstream of it).

One shared AgentBrowser (one Chrome tab, one screen recording, one audited
action timeline) backs the whole process lifetime - lazily opened on first
verb call, closed on stdin EOF (the CLI closes stdin when the card's turn
ends, same shutdown signal mcp_capper.py's child-process relay relies on).

SELF-REGISTERING, no per-machine setup: spine/agent/agentcli.py
._builtin_mcp_servers() derives this server's definition at spawn time
(sys.executable + this file's repo-relative path), so a fresh install needs
no `claude mcp add` step and no ~/.claude.json edit. The "claude-desktop"
driver's default allowed_tools (spine/storage/events.py DEFAULTS) already
grants "mcp__helmdeck-browser__*". An owner MAY still add a `helmdeck-browser`
entry to ~/.claude.json by hand (e.g. to point at a different interpreter) -
_user_mcp_servers() merges it over the builtin definition, user config wins."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("helmdeck-browser")

_browser = None


def _get_browser():
    """Lazily open the shared AgentBrowser on first verb call - not at process
    start, so `tools/list` still answers even before Chrome is reachable."""
    global _browser
    if _browser is None:
        from spine.media.browsercap import AgentBrowser
        from spine.ops.runs import new_run
        _rid, run_dir = new_run("agent", "browser-verbs MCP session")
        _browser = AgentBrowser(run_dir)
    return _browser


def _shaped(fn):
    """Run a verb against the shared browser and turn any exception into a
    short, capped string instead of letting a raw Playwright TimeoutError's
    verbose 'Call log:' tail (or any other unbounded traceback text) reach the
    model - the same failure mode this whole module exists to prevent, just
    from the error path instead of the result path."""
    from spine.media.browsercap import _cap_text
    try:
        return fn()
    except Exception as e:
        return _cap_text("error: %s" % e)


@mcp.tool()
def navigate(url: str) -> str:
    """Load `url` in the shared HelmDeck browser tab. Returns a short status
    line (title, url) - NEVER the page content; call read() for that."""
    def go():
        b = _get_browser()
        b.goto(url)
        return "ok: %r (%s)" % (b.page.title(), b.page.url)
    return _shaped(go)


@mcp.tool()
def read() -> str:
    """Markdown-ish text of what is CURRENTLY VISIBLE in the browser
    viewport, hard-capped at 5000 chars. Off-screen content is never
    included - use find() to locate something further down (it searches the
    whole page, not just the viewport) and click() it; click()/type()
    auto-scroll their target into view, so read() again afterwards shows the
    viewport around it. This is the bounded replacement for a full
    accessibility-tree snapshot."""
    return _shaped(lambda: _get_browser().read())


@mcp.tool()
def find(selector: str) -> str:
    """Up to 20 rendered matches for a CSS selector (e.g. 'button', 'a',
    'input[type=text]') ANYWHERE on the page, not just the viewport - each
    with its tag, a short label, and a ready-to-use locator
    ('<selector> >> nth=i') that click()/type() accept directly."""
    return _shaped(lambda: _get_browser().find(selector))


@mcp.tool()
def click(selector: str) -> str:
    """Click the element matching `selector` (a CSS selector, or a locator
    string returned by find()). Fails fast (~8s) on a miss instead of
    hanging the turn."""
    def do():
        b = _get_browser()
        b.click(selector)
        return "ok: clicked %r -> now %r (%s)" % (selector, b.page.title(), b.page.url)
    return _shaped(do)


@mcp.tool()
def type(selector: str, text: str) -> str:
    """Fill `text` into the input/textarea matching `selector` (a CSS
    selector, or a locator string returned by find()). Fails fast (~8s) on a
    miss instead of hanging the turn."""
    def do():
        _get_browser().type(selector, text)
        return "ok: typed into %r" % selector
    return _shaped(do)


def _close():
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        _close()
