# -*- coding: utf-8 -*-
"""CDP co-pilot for the Meta developer account / wearables access setup.

Same harness standard as deploy/asc_guide.py: attaches over CDP to the
persistent HelmDeck Chrome (own debug port, own profile - NOT the owner's
daily browser), so whatever the owner logs into here survives between runs
and he can take over the visible window for anything requiring his identity
(Meta/Facebook login, 2FA, org details, terms acceptance).

  py -3.12 deploy/meta_wearables_guide.py open <url>   # attach + go to <url>
  py -3.12 deploy/meta_wearables_guide.py shot         # screenshot current tab
  py -3.12 deploy/meta_wearables_guide.py where        # url + title + visible headline
  py -3.12 deploy/meta_wearables_guide.py click <sel>  # click a selector
"""
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("HELMDECK_CHROME_PORT") or "9222")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _chrome_exe():
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
    raise RuntimeError("no Chrome/Edge found - set HELMDECK_CHROME")


def _cdp_up(port=PORT):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=1):
            return True
    except Exception:
        return False


def ensure_chrome(port=PORT):
    if _cdp_up(port):
        return False
    profile = os.environ.get("HELMDECK_CHROME_PROFILE") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HelmDeck", "chrome-profile")
    os.makedirs(profile, exist_ok=True)
    subprocess.Popen([
        _chrome_exe(),
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % profile,
        "--no-first-run", "--no-default-browser-check",
    ])
    for _ in range(80):
        if _cdp_up(port):
            return True
        time.sleep(0.25)
    raise RuntimeError("Chrome did not open debug port %d in time" % port)


def _attach():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    br = pw.chromium.connect_over_cdp("http://127.0.0.1:%d" % PORT)
    ctx = br.contexts[0] if br.contexts else br.new_context()
    return pw, br, ctx


def _wearables_page(ctx, make=False):
    """Match by actual HOST, not substring - a work.meta.com sign-in URL can carry
    'developer.meta.com' inside an url-encoded redirect_uri query param, which a naive
    substring check false-positives on. Never touch the owner's own tabs (Gmail etc.)."""
    from urllib.parse import urlparse
    hosts = ("wearables.developer.meta.com", "developers.meta.com", "developer.meta.com")
    for p in ctx.pages:
        try:
            if urlparse(p.url or "").netloc in hosts:
                return p
        except Exception:
            pass
    if not make:
        return ctx.pages[-1] if ctx.pages else ctx.new_page()
    return ctx.new_page()


def _headlines(p):
    js = """() => {
      const t = [];
      for (const sel of ['h1','h2','h3','[role=heading]','.page-title','legend','button','a']) {
        document.querySelectorAll(sel).forEach(e => {
          const s = (e.innerText||'').trim();
          if (s && s.length < 120) t.push(sel + ': ' + s);
        });
      }
      return t.slice(0, 60);
    }"""
    try:
        return p.evaluate(js)
    except Exception as e:
        return ["head_err=%s" % e]


def cmd_open():
    url = sys.argv[2] if len(sys.argv) > 2 else "https://developer.meta.com/wearables"
    started = ensure_chrome()
    pw, br, ctx = _attach()
    p = _wearables_page(ctx, make=True)
    p.goto(url, wait_until="domcontentloaded")
    try:
        p.bring_to_front()
    except Exception:
        pass
    time.sleep(2)
    print("chrome_started=%s" % started)
    print("url=%s" % p.url)
    print("title=%s" % p.title())
    for h in _headlines(p):
        print("elem=%s" % h)
    pw.stop()


def cmd_shot():
    pw, br, ctx = _attach()
    p = _wearables_page(ctx)
    out = os.path.join(ROOT, "shots", "meta_wearables.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    p.screenshot(path=out, full_page=True)
    print("url=%s" % p.url)
    print("shot=%s" % out)
    pw.stop()


def cmd_where():
    pw, br, ctx = _attach()
    p = _wearables_page(ctx)
    print("url=%s" % p.url)
    print("title=%s" % p.title())
    for h in _headlines(p):
        print("elem=%s" % h)
    pw.stop()


def cmd_click():
    sel = sys.argv[2]
    pw, br, ctx = _attach()
    p = _wearables_page(ctx)
    p.click(sel)
    time.sleep(1.5)
    print("clicked=%s" % sel)
    print("url=%s" % p.url)
    pw.stop()


CMDS = {"open": cmd_open, "shot": cmd_shot, "where": cmd_where, "click": cmd_click}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "open"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c]()
