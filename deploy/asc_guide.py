# -*- coding: utf-8 -*-
"""CDP co-pilot for the ONE App Store Connect step an agent structurally cannot do.

`eas submit` needs the app record to exist on App Store Connect. That step
(`ensureAscAppAsync`) ignores the ASC API key and always demands an interactive
Apple ID + 2FA login - see DEPLOY.md 2b. So the owner does the human half
(password, 2FA code) in a real browser, and this script does everything around
it: opens the right page, reports what is on screen, and afterwards READS THE
ASC APP ID BACK OUT so nobody has to transcribe a 10-digit number by hand.

It attaches over CDP to the persistent HelmDeck Chrome (own debug port, own
profile - NOT the daily browser), the same harness standard as
daemon/browsercap.py, so the Apple session survives between runs.

  py -3.12 deploy/asc_guide.py open     # launch/attach + go to App Store Connect
  py -3.12 deploy/asc_guide.py shot     # screenshot current tab -> shots/asc.png
  py -3.12 deploy/asc_guide.py where    # url + title + visible headline
  py -3.12 deploy/asc_guide.py apps     # list the apps ASC shows, with their IDs
  py -3.12 deploy/asc_guide.py appid    # print the numeric ascAppId for app.helmdeck

The read-back verbs are the point: `appid` derives the ID from the live DOM/URL
of the owner's authenticated session, so what lands in eas.json is observed, not
retyped.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("HELMDECK_CHROME_PORT") or "9222")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = "app.helmdeck"
ASC = "https://appstoreconnect.apple.com/apps"


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
    """Reuse the HelmDeck Chrome if it is already listening, else start it. Visible
    window, dedicated profile, so the owner's Apple session persists across runs."""
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


def _asc_page(ctx, make=False):
    """Prefer a tab already on App Store Connect - that is the one the owner just
    logged into. Never hijack an unrelated tab."""
    for p in ctx.pages:
        try:
            if "appstoreconnect.apple.com" in (p.url or ""):
                return p
        except Exception:
            pass
    if not make:
        return ctx.pages[-1] if ctx.pages else ctx.new_page()
    return ctx.new_page()


def cmd_open():
    started = ensure_chrome()
    pw, br, ctx = _attach()
    p = _asc_page(ctx, make=True)
    if "appstoreconnect.apple.com" not in (p.url or ""):
        p.goto(ASC, wait_until="domcontentloaded")
    try:
        p.bring_to_front()
    except Exception:
        pass
    time.sleep(2)
    print("chrome_started=%s" % started)
    print("url=%s" % p.url)
    print("title=%s" % p.title())
    pw.stop()


def cmd_shot():
    pw, br, ctx = _attach()
    p = _asc_page(ctx)
    out = os.path.join(ROOT, "shots", "asc.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    p.screenshot(path=out, full_page=False)
    print("url=%s" % p.url)
    print("shot=%s" % out)
    pw.stop()


def cmd_where():
    pw, br, ctx = _attach()
    p = _asc_page(ctx)
    print("url=%s" % p.url)
    print("title=%s" % p.title())
    # the visible headline tells login vs. app-list vs. form apart without a screenshot
    js = """() => {
      const t = [];
      for (const sel of ['h1','h2','[role=heading]','.page-title','legend']) {
        document.querySelectorAll(sel).forEach(e => {
          const s = (e.innerText||'').trim();
          if (s && s.length < 120) t.push(s);
        });
      }
      return t.slice(0, 12);
    }"""
    try:
        for h in p.evaluate(js):
            print("head=%s" % h)
    except Exception as e:
        print("head_err=%s" % e)
    pw.stop()


def _harvest(p):
    """Every /app/<id> link ASC renders, with its row text. ASC is a heavy SPA, so
    read the DOM rather than guessing a REST endpoint."""
    js = """() => {
      const out = [];
      document.querySelectorAll('a[href*="/app/"]').forEach(a => {
        const m = (a.getAttribute('href')||'').match(/\\/app\\/(\\d{6,})/);
        if (!m) return;
        const row = a.closest('tr,li,div') || a;
        out.push({id: m[1], text: ((row.innerText||a.innerText||'').trim()).slice(0,200)});
      });
      return out;
    }"""
    try:
        rows = p.evaluate(js)
    except Exception:
        rows = []
    seen, uniq = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        uniq.append(r)
    return uniq


def cmd_apps():
    pw, br, ctx = _attach()
    p = _asc_page(ctx)
    print("url=%s" % p.url)
    rows = _harvest(p)
    if not rows:
        print("apps=0  (not on the app list, or not logged in - run `where`/`shot`)")
    for r in rows:
        print("app id=%s  %s" % (r["id"], r["text"].replace("\n", " | ")))
    pw.stop()


def cmd_appid():
    """The read-back that makes this worth automating: observe the ID, never retype it."""
    pw, br, ctx = _attach()
    p = _asc_page(ctx)
    # 1) already inside the app? the URL carries the id
    import re
    m = re.search(r"/app/(\d{6,})", p.url or "")
    if m:
        print("ascAppId=%s" % m.group(1))
        print("source=url")
        pw.stop()
        return
    # 2) otherwise pick the row that names our app / bundle
    rows = _harvest(p)
    hit = [r for r in rows if BUNDLE in r["text"] or "HelmDeck" in r["text"]]
    if len(hit) == 1:
        print("ascAppId=%s" % hit[0]["id"])
        print("source=list-row")
    elif not rows:
        print("ascAppId=  (nothing found - are you on appstoreconnect.apple.com/apps and logged in?)")
    else:
        print("ascAppId=  (ambiguous - matched %d rows)" % len(hit))
        for r in rows:
            print("  candidate id=%s  %s" % (r["id"], r["text"].replace("\n", " | ")[:120]))
    pw.stop()


CMDS = {"open": cmd_open, "shot": cmd_shot, "where": cmd_where,
        "apps": cmd_apps, "appid": cmd_appid}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "open"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c]()
