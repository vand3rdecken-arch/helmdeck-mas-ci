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

from daemon.spine.actionlog import ActionLog
from daemon.spine import wincap

DEFAULT_PORT = int(os.environ.get("HELMDECK_CHROME_PORT") or "9222")


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
