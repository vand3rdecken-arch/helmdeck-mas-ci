# -*- coding: utf-8 -*-
"""Instrumented agent browser: Playwright drives Edge, records video natively, and every
action goes through act() so the timeline and the footage share one clock. Agents use this
instead of a raw browser — that's what makes their browser work auditable."""
import os
from playwright.sync_api import sync_playwright
from actionlog import ActionLog

class AgentBrowser:
    def __init__(self, run_dir, log=None, headless=False):
        self.run_dir = run_dir
        self.log = log or ActionLog(run_dir)
        self._pw = sync_playwright().start()
        # channel=msedge: uses the installed Edge (no chromium download needed on this box)
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
        try:
            self._ctx.close()      # finalizes the .webm
            self._browser.close()
        finally:
            self._pw.stop()
        # normalize playwright's random video name to browser.webm
        for f in os.listdir(self.run_dir):
            if f.endswith(".webm") and f != "browser.webm":
                try:
                    os.replace(os.path.join(self.run_dir, f),
                               os.path.join(self.run_dir, "browser.webm"))
                except OSError:
                    pass
