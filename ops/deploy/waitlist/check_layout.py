"""Layout gate for helmdeck.de (the worker in this folder).

Loads the page from a running `wrangler dev` (default http://localhost:8799) at the five
viewports the owner cares about, in EN and DE, and fails (exit 1) when:
  - the hero bottom, the primary download CTA or the store badges leave the viewport
  - the cookie bar covers the CTA / badges
  - the page scrolls horizontally
  - text is clipped: an overflow:hidden/clip box with text whose content is bigger than
    the box, or a text element that pokes out of the viewport
  - a hero screenshot did not load
Screenshots land in ./layout-shots (git-ignored). Run:  py -3.12 check_layout.py [base-url]
Needs: pip install playwright ; playwright install chromium
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://localhost:8799")
OUT = Path(__file__).parent / "layout-shots"
VIEWPORTS = [(1366, 768), (1440, 900), (1742, 980), (1920, 1080), (390, 844)]

JS = """() => {
  const vw = innerWidth, vh = innerHeight, out = [];
  const box = (el) => { const r = el.getBoundingClientRect(); return {l:r.left, t:r.top, r:r.right, b:r.bottom, w:r.width, h:r.height}; };
  const inside = (r) => r.t >= -0.5 && r.l >= -0.5 && r.b <= vh + 0.5 && r.r <= vw + 0.5;
  const hero = document.querySelector('.hero'), dl = document.getElementById('hero-dl');
  const bar = document.getElementById('cookiebar');
  const barBox = bar && !bar.hidden ? box(bar) : null;
  const hit = (a, b) => b && a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t;
  const r = {};
  r.hero = box(hero);
  if (r.hero.b > vh + 0.5) out.push('hero bottom ' + Math.round(r.hero.b) + ' > viewport ' + vh);
  const need = [['download CTA', dl], ...[...document.querySelectorAll('.badge')].map((e, i) => ['badge ' + i, e]),
                ...[...document.querySelectorAll('.hero h1, .hero .sub')].map((e, i) => ['hero text ' + i, e])];
  for (const [name, el] of need) {
    if (!el) { out.push(name + ' missing'); continue; }
    const b = box(el);
    if (b.w < 1 || b.h < 1) { out.push(name + ' has no size'); continue; }
    if (!inside(b)) out.push(name + ' outside viewport: ' + JSON.stringify(b, (k, v) => typeof v === 'number' ? Math.round(v) : v));
    if (hit(b, barBox)) out.push(name + ' covered by the cookie bar');
  }
  for (const img of document.querySelectorAll('.hero-stage img')) {
    const cs = getComputedStyle(img.closest('figure'));
    if (cs.display === 'none') continue;
    if (!img.complete || !img.naturalWidth) out.push('hero image not loaded: ' + img.getAttribute('src'));
    const b = box(img);
    if (b.w < 80) out.push('hero image tiny: ' + img.getAttribute('src') + ' ' + Math.round(b.w) + 'px');
    if (b.t < -0.5 || b.r > vw + 0.5 || b.l < -0.5) out.push('hero image outside viewport: ' + img.getAttribute('src'));
    if (b.b > vh + 0.5 && vw >= 900) out.push('hero image below viewport: ' + img.getAttribute('src'));
  }
  if (document.documentElement.scrollWidth > vw) out.push('horizontal overflow: scrollWidth ' + document.documentElement.scrollWidth + ' > ' + vw);
  // clipped text: overflow hidden/clip boxes holding text that does not fit, and text poking out of the viewport
  const hasText = (el) => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('[hidden]') || el.closest('.hp')) continue;
    const ov = cs.overflowX + cs.overflowY;
    if (/hidden|clip/.test(ov) && el.innerText && el.innerText.trim() &&
        (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1))
      out.push('clipped text in <' + el.tagName.toLowerCase() + ' class="' + el.className + '"> "' + el.innerText.trim().slice(0, 40) + '"');
    if (hasText(el)) {
      const b = box(el);
      if (b.w > 0 && (b.r > vw + 1 || b.l < -1)) out.push('text outside viewport: "' + el.textContent.trim().slice(0, 40) + '"');
      if (el.scrollWidth > el.clientWidth + 1 && cs.display !== 'inline' && /^(H1|H2|H3|P|A|B|SPAN|SMALL|BUTTON)$/.test(el.tagName) && cs.overflow === 'visible' && cs.whiteSpace !== 'nowrap')
        out.push('text overflows its box: <' + el.tagName.toLowerCase() + '> "' + el.textContent.trim().slice(0, 40) + '"');
    }
  }
  return out;
}"""


def main():
    OUT.mkdir(exist_ok=True)
    fails = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for lang in ("en", "de"):
            for (w, h) in VIEWPORTS:
                mobile = w < 500
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mobile else 1,
                                          is_mobile=mobile, has_touch=mobile)
                ctx.add_init_script(f"try{{localStorage.setItem('hd_lang','{lang}')}}catch(e){{}}")
                page = ctx.new_page()
                page.goto(f"{BASE}/?hd_test=1", wait_until="networkidle")
                page.wait_for_timeout(1300)  # entrance animation
                tag = f"{lang} {w}x{h}"
                for issue in page.evaluate(JS):
                    fails.append(f"[{tag}, cookie bar shown] {issue}")
                page.screenshot(path=str(OUT / f"{lang}-{w}x{h}.png"))
                if lang == "en" and w == 1440:
                    page.screenshot(path=str(OUT / f"{lang}-{w}x{h}-full.png"), full_page=True)
                # second pass: bar dismissed, the hero grows into the freed space
                page.click("#cookie-decline")
                page.wait_for_timeout(300)
                for issue in page.evaluate(JS):
                    fails.append(f"[{tag}, cookie bar dismissed] {issue}")
                page.screenshot(path=str(OUT / f"{lang}-{w}x{h}-nobar.png"))
                ctx.close()
        browser.close()
    if fails:
        print("LAYOUT CHECK FAILED:")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print(f"layout check OK: {len(VIEWPORTS)} viewports x EN/DE x 2 cookie states ({BASE}); shots in {OUT}")


if __name__ == "__main__":
    main()
