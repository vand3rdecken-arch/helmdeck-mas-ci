# -*- coding: utf-8 -*-
"""Instrumented agent browser. THE HelmDeck harness standard is CDP-ATTACH: the agent
opens its OWN tab in a real, persistent Chrome (the owner's HelmDeck profile - its extensions and
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
import sys
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


def _spawn_orphan(argv):
    """Start `argv` OUTSIDE the caller's process tree (measured 2026-09-15:
    the persistent HelmDeck Chrome was a child of whichever hands/card
    process first called ensure_chrome - via this MCP server - and died with
    it: taskkill /T at that run's end took Chrome down, every other run
    attached to it lost its CDP socket ("no close frame received or sent"),
    and the next start showed "Chrome didn't shut down correctly"). A short-
    lived launcher spawns Chrome and exits at once, so Chrome's parent is
    gone before anyone can walk the tree - proctable._descendants and
    taskkill /T both follow live parent links only."""
    if os.name != "nt":
        subprocess.Popen(argv, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    detached = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    launcher = [sys.executable, "-c",
                "import subprocess,sys; subprocess.Popen(sys.argv[1:], creationflags=%d, close_fds=True)" % detached]
    subprocess.run(launcher + list(argv), timeout=30, check=True,
                   creationflags=detached | 0x08000000,          # + CREATE_NO_WINDOW
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    _spawn_orphan([
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


# Resolves a Playwright-style selector (CSS, `text=...`, optional `>> nth=i`)
# to one element, scrolls it into view, returns its viewport centre. nth
# indexes the RAW querySelectorAll list - the same order _FIND_JS reports.
_LOCATE_JS = """
(sel) => {
  let nth = null;
  const m = sel.match(/^([\\s\\S]*?)\\s*>>\\s*nth=(-?\\d+)\\s*$/);
  if (m) { sel = m[1]; nth = +m[2]; }
  let els;
  if (sel.startsWith('text=')) {
    let t = sel.slice(5).trim(), exact = false;
    if (/^".*"$/.test(t)) { t = t.slice(1, -1); exact = true; }
    const norm = s => (s || '').trim().replace(/\\s+/g, ' ');
    const hit = e => exact ? norm(e.innerText) === t : norm(e.innerText).toLowerCase().includes(t.toLowerCase());
    els = Array.from(document.querySelectorAll('body *')).filter(e => hit(e) && !Array.from(e.children).some(hit));
  } else {
    els = Array.from(document.querySelectorAll(sel));
  }
  const el = nth === null ? els[0] : els[nth < 0 ? els.length + nth : nth];
  if (!el) return null;
  el.scrollIntoView({block: 'center', inline: 'center'});
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  if (r.width <= 0 || r.height <= 0 || cs.visibility === 'hidden' || cs.display === 'none') return null;
  return {x: r.left + r.width / 2, y: r.top + r.height / 2};
}
"""

# FORM VERBS (2026-09-17, measured in ops/docs/marketing/jev-bench bench4): the
# five verbs had NO way to set a native <select> (a Gewerbeanmeldung run was
# blocked on it twice) and filled a form field by field - find, click, type,
# read, one model turn each - so the same Lever form took ~370 s here against
# 58-106 s for a browser agent with a select and a batch-fill verb. form()
# lists every control ONCE, bounded; set_field() sets one and reports what the
# DOM holds afterwards, so success is read back, never assumed.
#
# form() stamps each control with data-hd-f="<i>": a plain CSS locator that
# survives sibling re-ordering (unlike `>> nth=i`) and is accepted by every
# other verb. A re-render drops the stamps - call form() again after one.
_FORM_JS = """
({maxOptions}) => {""" + _RENDERED_FN + """
  const norm = s => (s || '').trim().replace(/\\s+/g, ' ');
  const skip = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'file']);
  const out = [];
  let i = 0;
  document.querySelectorAll('input,select,textarea').forEach(el => {
    const type = (el.getAttribute('type') || el.type || '').toLowerCase();
    if (skip.has(type) || !_hdRendered(el)) return;
    el.setAttribute('data-hd-f', String(i));
    const tag = el.tagName.toLowerCase();
    const kind = tag === 'select' ? 'select' : tag === 'textarea' ? 'textarea' : (type || 'text');
    const label = norm((el.labels && el.labels[0] && el.labels[0].innerText) ||
                       (el.closest('label') || {}).innerText || el.getAttribute('aria-label') ||
                       el.getAttribute('placeholder') || el.name || el.id).slice(0, 70);
    const f = {i, kind, label, group: el.name || '', required: !!el.required, disabled: !!el.disabled};
    if (kind === 'select') {
      const opts = Array.from(el.options).map(o => norm(o.text)).filter(Boolean);
      f.value = norm((el.selectedOptions[0] || {}).text);
      f.options = opts.slice(0, maxOptions).map(o => o.slice(0, 60));
      f.more = Math.max(0, opts.length - maxOptions);
    } else if (kind === 'checkbox' || kind === 'radio') {
      f.checked = el.checked;
    } else {
      f.value = kind === 'password' ? (el.value ? '(set)' : '') : String(el.value || '').slice(0, 80);
    }
    out.push(f);
    i++;
  });
  return out;
}
"""

# Sets a <select> / checkbox / radio in the page and reports what the DOM holds
# AFTERWARDS. Text-like fields answer {kind:'text'}: the caller types those
# through the trusted input path (fill), which framework-bound inputs need.
# A <select> is set through the prototype's own value setter and announced
# with input+change, which is what React/Angular-bound selects listen for.
_SET_JS = """
({sel, value}) => {
  let nth = null;
  const m = sel.match(/^([\\s\\S]*?)\\s*>>\\s*nth=(-?\\d+)\\s*$/);
  if (m) { sel = m[1]; nth = +m[2]; }
  const els = Array.from(document.querySelectorAll(sel));
  const el = nth === null ? els[0] : els[nth < 0 ? els.length + nth : nth];
  if (!el) return {ok: false, error: 'no element for ' + sel};
  const norm = s => String(s == null ? '' : s).trim().replace(/\\s+/g, ' ').toLowerCase();
  const fire = () => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); };
  const tag = el.tagName.toLowerCase(), type = (el.type || '').toLowerCase();
  if (tag === 'select') {
    const opts = Array.from(el.options), want = norm(value);
    let hit = opts.find(o => norm(o.text) === want) || opts.find(o => norm(o.value) === want);
    if (!hit && want) {
      const near = opts.filter(o => norm(o.text).startsWith(want) || norm(o.text).includes(want));
      if (near.length === 1) hit = near[0];
    }
    if (!hit) return {ok: false, kind: 'select', error: 'no option matches ' + JSON.stringify(value),
                      options: opts.map(o => o.text.trim()).filter(Boolean).slice(0, 25)};
    el.scrollIntoView({block: 'center'});
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(el, hit.value);
    fire();
    return {ok: true, kind: 'select', now: ((el.selectedOptions[0] || {}).text || '').trim()};
  }
  if (type === 'checkbox' || type === 'radio') {
    const on = !/^(false|0|no|nein|off|)$/.test(norm(value));
    if (el.checked !== on) { el.scrollIntoView({block: 'center'}); el.click(); }
    return {ok: el.checked === on, kind: type, now: String(el.checked)};
  }
  return {kind: 'text'};
}
"""

_VALUE_JS = """
(sel) => {
  let nth = null;
  const m = sel.match(/^([\\s\\S]*?)\\s*>>\\s*nth=(-?\\d+)\\s*$/);
  if (m) { sel = m[1]; nth = +m[2]; }
  const els = Array.from(document.querySelectorAll(sel));
  const el = nth === null ? els[0] : els[nth < 0 ? els.length + nth : nth];
  return el ? String(el.value == null ? '' : el.value) : null;
}
"""

FORM_MAX_OPTIONS = 12

_KEYS = {"Enter": (13, "\r"), "Tab": (9, ""), "Escape": (27, ""), "Backspace": (8, ""),
         "Delete": (46, ""), "ArrowUp": (38, ""), "ArrowDown": (40, ""),
         "ArrowLeft": (37, ""), "ArrowRight": (39, "")}


class _Keyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        code, text = _KEYS.get(key, (ord(key.upper()[0]) if len(key) == 1 else 0, key if len(key) == 1 else ""))
        base = {"key": key, "windowsVirtualKeyCode": code}
        self._page._call("Input.dispatchKeyEvent", dict(base, type="keyDown", text=text) if text
                         else dict(base, type="rawKeyDown"))
        self._page._call("Input.dispatchKeyEvent", dict(base, type="keyUp"))


class CdpTab:
    """ONE tab of the shared HelmDeck Chrome, driven over that tab's OWN CDP
    WebSocket. Not Playwright's connect_over_cdp: that auto-attaches every
    tab in the browser and awaits all of them (playwright 1.61 coreBundle
    CRBrowser.connect -> _waitForAllPagesToBeInitialized, no opt-out), so a
    single hung tab of ANY card blocked every card's attach for 180s
    (2026-09-14). Here no foreign tab is ever contacted - create, drive and
    close touch only our own target - and every call is bounded."""

    def __init__(self, port, timeout_ms=DEFAULT_ACTION_TIMEOUT_MS):
        from websockets.sync.client import connect
        self._port = port
        self._timeout = timeout_ms / 1000.0
        self._id = 0
        self._events = []
        info = self._http("/json/new?about:blank", "PUT")
        self.target_id = info["id"]
        try:
            self._ws = connect(info["webSocketDebuggerUrl"], open_timeout=5, max_size=None)
            self._call("Page.enable")
        except BaseException:
            self._http("/json/close/%s" % self.target_id)
            raise
        self.keyboard = _Keyboard(self)

    def _http(self, path, method="GET"):
        import json
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self._port, path), method=method)
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8", "replace")
        return json.loads(body) if body.startswith("{") else body

    def _call(self, method, params=None, timeout=None):
        import json
        timeout = self._timeout if timeout is None else timeout
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            try:
                if left <= 0:
                    raise TimeoutError
                msg = json.loads(self._ws.recv(timeout=left))
            except TimeoutError:
                raise TimeoutError("browser tab %s did not answer %s within %.0fs - the tab is hung "
                                   "(only this card's own tab; other tabs are never touched)"
                                   % (self.target_id[:8], method, timeout)) from None
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"].get("message")))
                return msg.get("result") or {}
            if "method" in msg:
                self._events.append(msg["method"])

    def set_default_timeout(self, ms):
        self._timeout = ms / 1000.0

    def evaluate(self, js, arg=None):
        import json
        expr = "(%s)(%s)" % (js, json.dumps(arg)) if arg is not None or js.strip().startswith(("(", "function")) else js
        deadline = time.time() + self._timeout
        while True:
            try:
                res = self._call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                      "awaitPromise": True},
                                 timeout=max(0.1, deadline - time.time()))
                break
            except RuntimeError as e:
                # a click that navigated destroys the context mid-call; retry on the new document
                if time.time() >= deadline or "context" not in str(e).lower():
                    raise
                time.sleep(0.1)
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            raise RuntimeError("page script error: %s" % ((d.get("exception") or {}).get("description") or d.get("text")))
        return (res.get("result") or {}).get("value")

    @property
    def url(self):
        return self.evaluate("location.href")

    def title(self):
        return self.evaluate("document.title")

    def goto(self, url, wait_until="domcontentloaded"):
        self._events.clear()
        res = self._call("Page.navigate", {"url": url})
        if res.get("errorText"):
            raise RuntimeError("navigation to %s failed: %s" % (url, res["errorText"]))
        if not res.get("loaderId"):
            return                     # same-document (fragment) navigation
        deadline = time.time() + self._timeout
        while "Page.domContentEventFired" not in self._events:
            if time.time() >= deadline:
                raise TimeoutError("browser tab %s: %s did not reach DOMContentLoaded within %.0fs"
                                   % (self.target_id[:8], url, self._timeout))
            try:
                self._call("Runtime.evaluate", {"expression": "1"}, timeout=max(0.1, deadline - time.time()))
            except RuntimeError:
                time.sleep(0.1)

    def _locate(self, selector):
        deadline = time.time() + self._timeout
        while True:
            pt = self.evaluate(_LOCATE_JS, selector)
            if pt:
                return pt
            if time.time() >= deadline:
                raise TimeoutError("no visible element for selector %r within %.0fs" % (selector, self._timeout))
            time.sleep(0.2)

    def click(self, selector):
        pt = self._locate(selector)
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self._call("Input.dispatchMouseEvent", {"type": kind, "x": pt["x"], "y": pt["y"],
                                                    "button": "left", "clickCount": 1})

    def fill(self, selector, text):
        self.click(selector)
        self.evaluate("() => { const e = document.activeElement; if (e && e.select) e.select(); "
                      "else document.execCommand('selectAll'); }")
        if text:
            self._call("Input.insertText", {"text": text})
        else:
            self.evaluate("() => document.execCommand('delete')")

    def close(self):
        try:
            self._ws.close()
        finally:
            self._http("/json/close/%s" % self.target_id)


class AgentBrowser:
    def __init__(self, run_dir, log=None, headless=False, attach=True, port=DEFAULT_PORT):
        self.run_dir = run_dir
        self.log = log or ActionLog(run_dir)
        self.attached = attach
        self._cap = None
        self._pw = None
        try:
            if attach:
                # STANDARD: our own tab in the real, persistent HelmDeck Chrome.
                ensure_chrome(port)
                self.page = CdpTab(port)          # our own tab; leave the owner's tabs alone
                # the real browser is visible, so the SCREEN recording is the evidence
                self._cap = wincap.start(run_dir)
                self.log.log("note", "attached to HelmDeck Chrome (CDP :%d)" % port)
            else:
                self._pw = sync_playwright().start()
                # FALLBACK: a blank sandbox context with Playwright's native webm.
                self._browser = self._pw.chromium.launch(channel="msedge", headless=headless)
                self._ctx = self._browser.new_context(
                    record_video_dir=run_dir, record_video_size={"width": 1280, "height": 720},
                    viewport={"width": 1280, "height": 720})
                self.page = self._ctx.new_page()
            # fails-fast (see DEFAULT_ACTION_TIMEOUT_MS): a selector miss should
            # cost seconds, not Playwright's 30s default eating the turn.
            self.page.set_default_timeout(DEFAULT_ACTION_TIMEOUT_MS)
        except BaseException:
            # A half-finished start must not leak: our own tab stays open in
            # the shared Chrome otherwise, and a leaked sync-Playwright driver
            # on browser_mcp.py's ONE owner thread poisons every later
            # AgentBrowser() there with "Sync API inside the asyncio loop".
            try:
                if self._pw is not None:
                    self._pw.stop()
                elif isinstance(getattr(self, "page", None), CdpTab):
                    self.page.close()
            except Exception:
                pass
            raise

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

    def form(self):
        """Every rendered form control on the page, ONE call, capped: index,
        kind, label, what it holds now, a <select>'s options (first
        FORM_MAX_OPTIONS, '+N more' beyond) and its locator
        `[data-hd-f="i"]`, which every other verb accepts. The bounded
        alternative to find()+read() per field."""
        items = self.page.evaluate(_FORM_JS, {"maxOptions": FORM_MAX_OPTIONS})
        lines = []
        # A checkbox/radio GROUP is one line, not one per box: Lever's 33
        # language boxes alone ate 2300 of the 5000 chars and pushed the three
        # dropdowns behind them past the cap (measured 2026-09-17 - the agent
        # then hunted them with find/read, 41 turns instead of ~8).
        groups = {}
        for f in items:
            if f["kind"] in ("checkbox", "radio") and f.get("group"):
                groups.setdefault((f["kind"], f["group"]), []).append(f)
        done = set()
        for f in items:
            key = (f["kind"], f.get("group"))
            if key in groups and len(groups[key]) > 2:
                if key in done:
                    continue
                done.add(key)
                g = groups[key]
                on = [x["label"] for x in g if x.get("checked")]
                lines.append('%s group %r (%d, checked: %s) - locator [data-hd-f="<n>"]: %s' % (
                    f["kind"], f["group"][:40], len(g), on or "none",
                    " | ".join("%d=%s" % (x["i"], x["label"][:32]) for x in g)))
                continue
            if f["kind"] == "select":
                more = " +%d more" % f["more"] if f.get("more") else ""
                now = "now=%r options=%s%s" % (f.get("value", ""), f.get("options", []), more)
            elif f["kind"] in ("checkbox", "radio"):
                now = "checked=%s" % f.get("checked")
            else:
                now = "now=%r" % f.get("value", "")
            flags = "".join(" " + k for k in ("required", "disabled") if f.get(k))
            lines.append('[data-hd-f="%d"] %s %r %s%s' % (f["i"], f["kind"], f["label"], now, flags))
        raw = "\n".join(lines) if lines else "(no form fields on this page)"
        out = _cap_text(raw)
        self.log.log("form", "%d field(s)%s" % (len(items), " (capped)" if len(raw) > len(out) else ""))
        return out

    def set_field(self, selector, value, secret=False):
        """Set ONE control of any kind and return what the DOM holds
        afterwards: a <select> by option text (exact, else value, else a
        unique partial match), a checkbox/radio by true/false, anything else
        typed through the trusted input path. A miss on a <select> answers
        with the options actually offered."""
        shown = "•" * len(str(value)) if secret else value
        self.log.log("set", "%s ← %s" % (selector, shown), selector=selector)
        r = self.page.evaluate(_SET_JS, {"sel": selector, "value": value}) or {}
        if r.get("kind") == "text":
            self.page.fill(selector, str(value))
            now = self.page.evaluate(_VALUE_JS, selector)
            ok = now is not None and "".join(now.split()) == "".join(str(value).split())
            return {"ok": ok, "kind": "text", "now": "(set)" if secret else now}
        return r

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
            if self._pw is not None:
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
