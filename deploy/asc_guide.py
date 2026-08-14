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

The read-back verbs are the point: what lands in eas.json is observed, not
retyped. Note `appid` asks the App Store Connect API, NOT the page.

⚠ Do not trust the ASC web UI as the source of truth here. Right after the app
record was created on 2026-08-14 the Apps list still rendered "No Apps" - a
stale SPA view - while `GET /v1/apps` already returned the app and its id. A
DOM-based read would have concluded the creation had failed and sent the card
off to re-create an app that existed. The API is the runtime's own signal; the
rendered page is a cache. `apps`/`appid` therefore go to the API, and the
browser verbs (`open`/`where`/`shot`) exist only to get the HUMAN through
password + 2FA, which the API key cannot do.
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


# (a DOM scraper for the Apps list lived here and was deleted: it read "No Apps"
#  from a stale SPA view minutes after the record existed. _api_apps() replaced it.)


def _api_apps():
    """Authoritative app list, straight from App Store Connect via the .p8. No
    browser, no login - the same key eas-cli uses."""
    import jwt
    env = {}
    envf = os.path.join(ROOT, ".env")
    if os.path.exists(envf):
        for line in open(envf, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    kid = env.get("ASC_KEY_ID") or os.environ.get("ASC_KEY_ID")
    iss = env.get("ASC_ISSUER_ID") or os.environ.get("ASC_ISSUER_ID")
    p8 = env.get("ASC_API_KEY_PATH") or os.environ.get("ASC_API_KEY_PATH")
    if not (kid and iss and p8 and os.path.exists(p8)):
        raise RuntimeError("ASC_* not configured in .env (see DEPLOY.md 2b)")
    now = int(time.time())
    tok = jwt.encode({"iss": iss, "iat": now, "exp": now + 600,
                      "aud": "appstoreconnect-v1"},
                     open(p8).read(), algorithm="ES256",
                     headers={"kid": kid, "typ": "JWT"})
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com/v1/apps?limit=100",
        headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    return [{"id": a["id"],
             "bundle": a["attributes"].get("bundleId"),
             "name": a["attributes"].get("name"),
             "sku": a["attributes"].get("sku")} for a in d.get("data", [])]


def cmd_apps():
    rows = _api_apps()
    print("source=App Store Connect API")
    if not rows:
        print("apps=0  (no app records on this team yet)")
    for r in rows:
        print("app id=%s  bundle=%s  name=%s  sku=%s"
              % (r["id"], r["bundle"], r["name"], r["sku"]))


def cmd_appid():
    """The read-back that makes this worth automating: observe the id, never
    retype it - and observe it from the API, which the stale Apps page proved
    necessary (see the module docstring)."""
    rows = _api_apps()
    hit = [r for r in rows if r["bundle"] == BUNDLE]
    if len(hit) == 1:
        print("ascAppId=%s" % hit[0]["id"])
        print("source=api bundle=%s name=%s" % (hit[0]["bundle"], hit[0]["name"]))
    elif not hit:
        print("ascAppId=  (no app record for %s - create it: My Apps -> +)" % BUNDLE)
    else:
        print("ascAppId=  (ambiguous - %d records claim %s)" % (len(hit), BUNDLE))


CMDS = {"open": cmd_open, "shot": cmd_shot, "where": cmd_where,
        "apps": cmd_apps, "appid": cmd_appid}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "open"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c]()
