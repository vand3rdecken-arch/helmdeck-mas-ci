# -*- coding: utf-8 -*-
"""Instrumented agent browser. THE HelmDeck harness standard is CDP-ATTACH: Playwright
docks onto a real, persistent Chrome (the owner's HelmDeck profile - its extensions and
logins, e.g. Claude for Chrome), so agents drive the actual browser instead of a blank
sandbox. Every action still goes through the audited verbs, and the whole turn is
screen-recorded via wincap (screen.mp4 + the live.jpg glance feed the phone reads) - the
flight-recorder promise, now over the real browser.

Why attach and not launch a fresh context: a fresh Playwright context has none of your
extensions or sessions, so it can't touch Claude-for-Chrome or anything you're logged into.
Attaching to a persistent Chrome (own debug port + own user-data-dir, NOT your daily
browser) keeps that state across runs while staying out of your main profile's way.

  AgentBrowser(run_dir)                     # standard: attach to the HelmDeck Chrome
  AgentBrowser(run_dir, attach=False)       # fallback: fresh sandbox context + webm

Env overrides: HELMDECK_CHROME (exe path), HELMDECK_CHROME_PORT (default 9222),
HELMDECK_CHROME_PROFILE (default %LOCALAPPDATA%/HelmDeck/chrome-profile)."""
import os
import subprocess
import time
import urllib.request

from playwright.sync_api import sync_playwright

from spine.ops.actionlog import ActionLog
from spine.media import wincap

DEFAULT_PORT = int(os.environ.get("HELMDECK_CHROME_PORT") or "9222")

# token-burn-hardening Karte C: the antidote to windows-mcp's Snapshot, which
# returned 600-700 KB of UIA tree PER CALL (the 190M-token Wear-OS turn -
# ops/docs/backlog/token-burn-hardening/README.md). Every browser verb's
# return value is capped here, upstream of the model context, same principle
# as ops/tools/mcp_capper.py's channel-level cap.
MAX_ACTION_CHARS = 5_000
_TRUNC = "\n…[gekürzt — Selektor oder Viewport enger fassen]"

# Fails-fast default for every page action (Playwright's own default is 30s):
# a selector miss should cost seconds, not eat the turn, and a raw Playwright
# TimeoutError's "Call log:" tail is exactly the kind of unbounded text this
# card exists to cap.
DEFAULT_ACTION_TIMEOUT_MS = 8_000


def _cap_text(text, limit=MAX_ACTION_CHARS):
    """Named _cap_text, not _cap: AgentBrowser already owns a `self._cap`
    (the wincap recording handle) - same word, different thing, kept apart
    on sight."""
    text = text or ""
    return text if len(text) <= limit else text[:limit] + _TRUNC


# document.querySelectorAll order == Playwright's own `nth=` chaining engine
# order, so an index this returns is directly usable as `<selector> >> nth=i`
# in click()/type() - no separate ID scheme to keep in sync.
#
# Page.evaluate takes exactly ONE expression - each visibility check is
# nested INSIDE its arrow function (not concatenated before it) so the
# string it receives stays a single, valid function expression.
#
# TWO different checks on purpose: read() must be viewport-scoped (the
# viewport IS the cap - that's what keeps a 2000-paragraph page small
# without truncating mid-thought), but find() locates something to act on
# and Playwright's own click()/fill() already scroll a target into view
# before acting - restricting find() to the current scroll position would
# make an off-screen element permanently unreachable through these five
# verbs (no scroll verb exists). So find() only excludes genuinely NOT
# rendered elements (zero-size, display:none, visibility:hidden), not
# off-screen ones. Registered as debt (browser-find-not-viewport-scoped):
# every non-viewport-scoped output is a shortcut per this card's own rule.
_ON_SCREEN_FN = """
  function _hdOnScreen(el) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    if (r.bottom <= 0 || r.right <= 0) return false;
    if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  }
"""

_RENDERED_FN = """
  function _hdRendered(el) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  }
"""

_READ_JS = """
() => {""" + _ON_SCREEN_FN + """
  const leaf = 'h1,h2,h3,h4,h5,h6,a,button,li,p,span,label,td,th,div';
  const out = [], seen = new Set();
  document.querySelectorAll(leaf).forEach(el => {
    if (!_hdOnScreen(el)) return;
    // skip containers whose own visible child already emits this text
    if (Array.from(el.children).some(c => _hdOnScreen(c) && c.innerText && c.innerText.trim())) return;
    const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
    if (!text || seen.has(text)) return;
    seen.add(text);
    if (el.tagName === 'A' && el.href) out.push(`[${text}](${el.href})`);
    else if (/^H[1-6]$/.test(el.tagName)) out.push('#'.repeat(+el.tagName[1]) + ' ' + text);
    else out.push(text);
  });
  return out.join('\\n');
}
"""

_FIND_JS = """
({selector, limit}) => {""" + _RENDERED_FN + """
  const all = Array.from(document.querySelectorAll(selector));
  const out = [];
  for (let i = 0; i < all.length && out.length < limit; i++) {
    const el = all[i];
    if (!_hdRendered(el)) continue;
    const label = (el.innerText || el.getAttribute('aria-label') ||
                   el.getAttribute('placeholder') || el.value || '')
                  .trim().replace(/\\s+/g, ' ').slice(0, 60);
    out.push({i, tag: el.tagName.toLowerCase(), label});
  }
  return out;
}
"""


def _chrome_exe():
    """Locate a Chrome/Edge binary: env override, then the usual install paths, then Edge."""
    cand = [os.environ.get("HELMDECK_CHROME")]
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    cand += [
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pfx86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for c in cand:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("no Chrome/Edge found - set HELMDECK_CHROME to the browser exe")


def _cdp_up(port):
    """True if a browser is already answering CDP on this port (so we reuse it)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=1):
            return True
    except Exception:
        return False


def ensure_chrome(port=DEFAULT_PORT, profile=None, exe=None):
    """Start the persistent HelmDeck Chrome with a debug port + its own profile, or reuse
    the one already listening. Returns when CDP is reachable. Leaves the process running so
    subsequent runs (and the owner's one-time extension/login setup) persist."""
    if _cdp_up(port):
        return
    exe = exe or _chrome_exe()
    profile = profile or os.environ.get("HELMDECK_CHROME_PROFILE") or \
        os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HelmDeck", "chrome-profile")
    os.makedirs(profile, exist_ok=True)
    # visible window (screen-recorded), dedicated profile, no first-run nags. NOT headless
    # and NOT your daily user-data-dir.
    subprocess.Popen([
        exe,
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % profile,
        "--no-first-run", "--no-default-browser-check",
        "--restore-last-session",
    ])
    for _ in range(60):          # up to ~15s for the port to come up
        if _cdp_up(port):
            return
        time.sleep(0.25)
    raise RuntimeError("Chrome did not open its debug port %d in time" % port)


class AgentBrowser:
    def __init__(self, run_dir, log=None, headless=False, attach=True, port=DEFAULT_PORT):
        self.run_dir = run_dir
        self.log = log or ActionLog(run_dir)
        self.attached = attach
        self._cap = None
        self._pw = sync_playwright().start()
        if attach:
            # STANDARD: dock onto the real, persistent HelmDeck Chrome.
            ensure_chrome(port)
            self._browser = self._pw.chromium.connect_over_cdp("http://127.0.0.1:%d" % port)
            ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
            self._ctx = ctx
            self.page = ctx.new_page()        # our own tab; leave the owner's tabs alone
            # the real browser is visible, so the SCREEN recording is the evidence
            self._cap = wincap.start(run_dir)
            self.log.log("note", "attached to HelmDeck Chrome (CDP :%d)" % port)
        else:
            # FALLBACK: a blank sandbox context with Playwright's native webm.
            self._browser = self._pw.chromium.launch(channel="msedge", headless=headless)
            self._ctx = self._browser.new_context(
                record_video_dir=run_dir, record_video_size={"width": 1280, "height": 720},
                viewport={"width": 1280, "height": 720})
            self.page = self._ctx.new_page()
        # fails-fast (see DEFAULT_ACTION_TIMEOUT_MS): a selector miss should
        # cost seconds, not Playwright's 30s default eating the turn.
        self.page.set_default_timeout(DEFAULT_ACTION_TIMEOUT_MS)

    # -- the audited verbs ------------------------------------------------
    def goto(self, url):
        self.log.log("navigate", url)
        self.page.goto(url, wait_until="domcontentloaded")

    def click(self, selector, label=None):
        self.log.log("click", label or selector, selector=selector)
        self.page.click(selector)

    def type(self, selector, text, label=None, secret=False):
        shown = "•" * len(text) if secret else text
        self.log.log("type", "%s ← %s" % (label or selector, shown), selector=selector)
        self.page.fill(selector, text)

    def read(self):
        """Markdown-ish text of what is CURRENTLY VISIBLE in the viewport, hard-
        capped at MAX_ACTION_CHARS - the bounded alternative to windows-mcp's
        whole-tree Snapshot (token-burn-hardening Karte C). Off-screen content
        is never included - find() and click()/type() are NOT viewport-limited
        (Playwright scrolls a target into view before acting), so locate
        something further down with find() first; read() then shows the
        viewport around wherever the page ends up."""
        raw = self.page.evaluate(_READ_JS)
        out = _cap_text(raw)
        self.log.log("read", "%d chars%s" % (len(out), " (capped)" if len(raw) > len(out) else ""))
        return out

    def find(self, selector, limit=20):
        """Up to `limit` rendered (non-zero-size, not display:none/hidden)
        matches for `selector` ANYWHERE on the page - not viewport-limited,
        because click()/type() already scroll their target into view and
        these five verbs have no separate scroll primitive (debt: browser-
        find-not-viewport-scoped). Each match carries a ready-to-use locator
        (`<selector> >> nth=i`, the same order Playwright's own `nth=`
        chaining engine uses) that click()/type() can take directly."""
        items = self.page.evaluate(_FIND_JS, {"selector": selector, "limit": limit})
        lines = ["%d: <%s> %r -> %s >> nth=%d" % (it["i"], it["tag"], it["label"], selector, it["i"])
                 for it in items]
        out = _cap_text("\n".join(lines) if lines else "(no visible matches)")
        self.log.log("find", "%r -> %d match(es)" % (selector, len(items)), selector=selector)
        return out

    def press(self, key):
        self.log.log("key", key)
        self.page.keyboard.press(key)

    def note(self, text):
        self.log.log("note", text)

    def flag(self, text):
        """Marks a step for the reviewer's attention (renders highlighted)."""
        self.log.log("flag", text)

    def close(self):
        if self._cap is not None:
            try:
                wincap.stop(self._cap)      # finalize screen.mp4
            except Exception:
                pass
        try:
            if self.attached:
                # our tab only; NEVER close the owner's persistent browser
                try:
                    self.page.close()
                except Exception:
                    pass
            else:
                self._ctx.close()           # finalizes the .webm
                self._browser.close()
        finally:
            self._pw.stop()
        if not self.attached:
            # normalize playwright's random video name to browser.webm
            for f in os.listdir(self.run_dir):
                if f.endswith(".webm") and f != "browser.webm":
                    try:
                        os.replace(os.path.join(self.run_dir, f),
                                   os.path.join(self.run_dir, "browser.webm"))
                    except OSError:
                        pass
