"""Browser check for the app pages (/readproof/*, /label-doktor/*) against a running `wrangler dev`.

  - every page in EN and DE: full-page screenshot, the other language is really hidden,
    no horizontal scroll, the toggle sits in the nav bar, hd_lang carries across pages
  - consent: with no choice and after Decline NOT ONE request goes to google-analytics.com /
    googletagmanager.com; after Accept the gtag.js request happens; the footer link reopens the banner
  - Google hosts are answered by a stub here, so tests never send hits to the real property
Run: py -3.12 check_app_pages_browser.py [base-url]   Needs playwright. Shots: layout-shots/app-i18n (git-ignored).
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://localhost:8799")
OUT = Path(__file__).parent / "layout-shots" / "app-i18n"
OUT.mkdir(parents=True, exist_ok=True)
PATHS = [f"/{app}/{sub}" for app in ("readproof", "label-doktor")
         for sub in ("", "docs", "support", "privacy", "terms", "compare")] + ["/readproof/security"]
GOOGLE = ("google-analytics.com", "googletagmanager.com", "analytics.google.com")
bad = []


def slug(p):
    return p.strip("/").replace("/", "_") or "root"


def watch(ctx):
    hits = []

    def handle(route):
        hits.append(route.request.url)
        route.fulfill(status=200, content_type="application/javascript", body="")
    for h in GOOGLE:
        ctx.route(f"**://*.{h}/**", handle)
        ctx.route(f"**://{h}/**", handle)
    return hits


with sync_playwright() as pw:
    br = pw.chromium.launch()

    # 1) pages x languages (consent pre-declined so the banner does not cover the shot)
    for lang in ("en", "de"):
        ctx = br.new_context(viewport={"width": 1000, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('hd_lang','{lang}');localStorage.setItem('hd_ga_consent','denied')")
        hits = watch(ctx)
        pg = ctx.new_page()
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        for p in PATHS:
            r = pg.goto(BASE + p)
            if r.status != 200:
                bad.append(f"{p}: HTTP {r.status}")
                continue
            info = pg.evaluate("""() => {
              const vis = (el) => el.getClientRects().length > 0;
              const en = [...document.querySelectorAll('.en')].filter(e=>!e.closest('#cb')), de = [...document.querySelectorAll('.de')].filter(e=>!e.closest('#cb'));
              return {lang: document.documentElement.lang, enVis: en.filter(vis).length, deVis: de.filter(vis).length,
                      nEn: en.length, nDe: de.length, hscroll: document.documentElement.scrollWidth > innerWidth + 1,
                      toggle: (document.querySelector('.bar .lang') || {}).textContent, title: document.title}
            }""")
            exp_hidden = "deVis" if lang == "en" else "enVis"
            exp_shown = "enVis" if lang == "en" else "deVis"
            if info["lang"] != lang: bad.append(f"{p} {lang}: html lang={info['lang']}")
            if info[exp_hidden] != 0: bad.append(f"{p} {lang}: {info[exp_hidden]} blocks of the other language visible")
            if info[exp_shown] != info["nEn" if lang == "en" else "nDe"]: bad.append(f"{p} {lang}: not all blocks visible")
            if info["hscroll"]: bad.append(f"{p} {lang}: horizontal scroll")
            if info["toggle"] != ("DE" if lang == "en" else "EN"): bad.append(f"{p} {lang}: toggle label {info['toggle']}")
            pg.screenshot(path=str(OUT / f"{slug(p)}-{lang}.png"), full_page=True)
        if hits: bad.append(f"{lang}: google request despite decline: {hits[:2]}")
        if errs: bad.append(f"{lang}: console errors: {errs[:3]}")
        ctx.close()

    # 2) hd_lang carries across pages via the toggle
    ctx = br.new_context(viewport={"width": 1000, "height": 700})
    pg = ctx.new_page()
    pg.goto(BASE + "/readproof/")
    pg.click(".bar .lang")
    pg.goto(BASE + "/readproof/privacy")
    if pg.evaluate("document.documentElement.lang") != "de": bad.append("toggle choice did not carry to next page")
    if pg.evaluate("localStorage.getItem('hd_lang')") != "de": bad.append("hd_lang not stored")
    ctx.close()

    # 3) consent: nothing before choice, nothing after Decline, gtag after Accept
    for lang in ("en", "de"):
        ctx = br.new_context(viewport={"width": 1000, "height": 700})
        ctx.add_init_script(f"if(!localStorage.getItem('x_seen')){{localStorage.setItem('hd_lang','{lang}');localStorage.setItem('x_seen','1')}}")
        hits = watch(ctx)
        pg = ctx.new_page()
        pg.goto(BASE + "/readproof/privacy")
        pg.wait_for_timeout(1500)
        if pg.evaluate("document.getElementById('cb').hidden"): bad.append(f"{lang}: banner not shown on first visit")
        if hits: bad.append(f"{lang}: request before consent: {hits}")
        sizes = pg.evaluate("['cy','cn'].map(i=>{const b=document.getElementById(i);const r=b.getBoundingClientRect();const c=getComputedStyle(b);return [Math.round(r.width),Math.round(r.height),c.backgroundColor,c.color,c.borderColor]})")
        if sizes[0] != sizes[1]: bad.append(f"{lang}: Accept/Decline differ: {sizes}")
        pg.screenshot(path=str(OUT / f"banner-{lang}.png"))
        pg.click("#cn")
        pg.wait_for_timeout(800)
        pg.reload(); pg.wait_for_timeout(1000)
        if not pg.evaluate("document.getElementById('cb').hidden"): bad.append(f"{lang}: banner back after Decline")
        if hits: bad.append(f"{lang}: request after Decline: {hits}")
        pg.click("#cs")
        if pg.evaluate("document.getElementById('cb').hidden"): bad.append(f"{lang}: Cookie settings link does not reopen banner")
        pg.click("#cy")
        pg.wait_for_timeout(2000)
        gtag = [h for h in hits if "googletagmanager.com/gtag/js?id=G-8V1ZGSKD54" in h]
        print(f"[{lang}] requests after Accept: {len(hits)} (gtag.js: {len(gtag)})")
        for h in hits[:4]: print("   ", h[:110])
        if not gtag: bad.append(f"{lang}: no gtag.js request after Accept")
        ctx.close()
    br.close()

print("FAIL" if bad else "OK")
for b in bad: print(" -", b)
sys.exit(1 if bad else 0)
