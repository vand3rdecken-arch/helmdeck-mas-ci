# -*- coding: utf-8 -*-
"""MCP stdio server exposing the bounded browser verbs - navigate/read/find/
click/type, plus the FORM verbs form/fill/select (2026-09-17: a native
<select> was unreachable and a form cost one model turn per field) - backed by spine/media/browsercap.py's AgentBrowser (CDP-attach
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
import threading
import queue

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("helmdeck-browser")

# THE THREAD RULE (root cause of "Playwright Sync API inside the asyncio
# loop", measured on the first real card turn after registration): FastMCP
# calls a sync tool function ON its asyncio loop thread, and Playwright's sync
# API refuses any thread that has a running loop - it is greenlet-based and
# thread-affine, every call must come from the thread that started it. So the
# browser cannot live on the server's thread at all. It lives on exactly ONE
# owner thread of its own, created lazily, and every verb is a job marshalled
# onto that thread and awaited. Not a workaround: this is the documented way
# to host the sync API inside an async program, and it matches the repo's
# one-owner rule for mutable state. AgentBrowser stays sync on purpose - its
# other consumers (card recorders, ops runs) are sync, and a second async
# copy of browsercap would be the real monkey patch.
_jobs = queue.Queue()
_owner = None
_owner_lock = threading.Lock()
_browser = None            # only ever touched from the owner thread


def _owner_loop():
    while True:
        fn, done = _jobs.get()
        if fn is None:
            done.put((True, None))
            return
        try:
            done.put((True, fn()))
        except BaseException as e:      # a verb must never kill the owner
            done.put((False, e))


def _on_owner(fn):
    """Run fn on the browser owner thread and return its result (re-raises
    its exception here, on the caller's thread)."""
    global _owner
    with _owner_lock:
        if _owner is None or not _owner.is_alive():
            _owner = threading.Thread(target=_owner_loop, name="helmdeck-browser-owner", daemon=True)
            _owner.start()
    done = queue.Queue(maxsize=1)
    _jobs.put((fn, done))
    ok, val = done.get()
    if ok:
        return val
    raise val


def _get_browser():
    """Lazily open the shared AgentBrowser on first verb call - not at process
    start, so `tools/list` still answers even before Chrome is reachable.
    Owner-thread only (called from inside a job).
    HELMDECK_BROWSER_ATTACH=0 selects browsercap's sandbox fallback context
    (no CDP attach to the owner's Chrome) - what the e2e test uses."""
    global _browser
    if _browser is None:
        from spine.media.browsercap import AgentBrowser
        from spine.ops.runs import new_run
        _rid, run_dir = new_run("agent", "browser-verbs MCP session")
        attach = os.environ.get("HELMDECK_BROWSER_ATTACH", "1") != "0"
        _browser = AgentBrowser(run_dir, attach=attach)
    return _browser


def _shaped(fn):
    """Run a verb against the shared browser and turn any exception into a
    short, capped string instead of letting a raw Playwright TimeoutError's
    verbose 'Call log:' tail (or any other unbounded traceback text) reach the
    model - the same failure mode this whole module exists to prevent, just
    from the error path instead of the result path."""
    from spine.media.browsercap import _cap_text
    try:
        return _on_owner(fn)
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


def _set_line(b, selector, value):
    r = b.set_field(selector, value)
    if r.get("ok"):
        return "ok: %s = %r" % (selector, r.get("now"))
    extra = " - offered: %s" % r["options"] if r.get("options") else ""
    return "FAILED: %s -> %s (holds %r)%s" % (selector, r.get("error") or "value did not stick", r.get("now"), extra)


@mcp.tool()
def form() -> str:
    """ALL form fields of the current page in ONE call (whole page, not just
    the viewport): kind, label, current value, a dropdown's options, and a
    locator `[data-hd-f="i"]` for each. START HERE on any form - then set
    everything with ONE fill() call, and call form() again to verify. After
    a page change or re-render the locators are stale: call form() again."""
    return _shaped(lambda: _get_browser().form())


@mcp.tool()
def fill(fields: dict[str, str]) -> str:
    """Set MANY fields in one call: {locator: value, ...} with the locators
    from form(). Text is typed, a dropdown is chosen by its option TEXT, a
    checkbox/radio takes "true"/"false". One result line per field with the
    value the page holds AFTERWARDS - a dropdown that has no such option
    answers with the options it does offer. Never submits anything."""
    def do():
        from spine.media.browsercap import _cap_text
        b = _get_browser()
        return _cap_text("\n".join(_set_line(b, sel, val) for sel, val in fields.items()))
    return _shaped(do)


@mcp.tool()
def select(selector: str, option: str) -> str:
    """Choose `option` (its visible TEXT) in the <select> dropdown matching
    `selector`. For several fields at once use fill()."""
    return _shaped(lambda: _set_line(_get_browser(), selector, option))


@mcp.tool()
def close() -> str:
    """Close this card's own browser tab. Call it when you are DONE with the
    browser and nothing on that page still has to stay open (the owner is not
    about to look at it or finish a login there). Leave it open while a later
    step still needs the page. Logins survive either way (they live in the
    Chrome profile, not the tab), and the next verb opens a fresh tab. Other
    cards' tabs are never touched. The tab is also closed automatically when
    the session ends."""
    def shut():
        global _browser
        if _browser is None:
            return "ok: no tab open"
        b, _browser = _browser, None
        b.close()
        return "ok: tab closed"
    return _shaped(shut)


def _close():
    """Close the browser ON ITS OWNER THREAD, then retire the thread."""
    global _browser
    def shut():
        global _browser
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
    if _owner is not None and _owner.is_alive():
        try:
            _on_owner(shut)
            done = queue.Queue(maxsize=1)
            _jobs.put((None, done))
            done.get(timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        _close()
