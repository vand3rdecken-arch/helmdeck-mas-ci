# -*- coding: utf-8 -*-
"""Judge the board chat's SCROLL-TO-NEWEST contract on the phone surface.

Owner report 2026-08-31: the "↓ Neueste" pill is visible above the composer but
a tap does nothing. This drives the real UI (Expo web dev server + demo board)
and answers the two questions a screenshot cannot:

  A) who actually RECEIVES a tap at the pill's centre (document.elementFromPoint)
  B) does the scroller move when the pill is clicked, and does it move on its
     own when a new message arrives

Run:  py -3.12 ops/tests/e2e_chat_scroll.py [port]     (default 3987)
      cd surfaces/app && npx expo start --web --port 3987 --offline
"""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "3987"
BASE = "http://localhost:%s" % PORT

# The scroll container is the one overflowing element that holds the transcript;
# RNW renders ScrollView as a div with its own overflow, so find it by geometry
# rather than by a class name that changes with every bundle.
FIND_SCROLLER = """
() => {
  const all = [...document.querySelectorAll('div')];
  const c = all.filter(d => d.scrollHeight > d.clientHeight + 20
                            && ['auto','scroll'].includes(getComputedStyle(d).overflowY));
  if (!c.length) return null;
  c.sort((a, b) => (b.clientHeight * b.clientWidth) - (a.clientHeight * a.clientWidth));
  c[0].setAttribute('data-e2e-scroller', '1');
  return { scrollTop: c[0].scrollTop, scrollHeight: c[0].scrollHeight, clientHeight: c[0].clientHeight };
}
"""
READ_SCROLLER = """
() => { const d = document.querySelector('[data-e2e-scroller]');
        return d ? { scrollTop: Math.round(d.scrollTop), scrollHeight: d.scrollHeight,
                     clientHeight: d.clientHeight } : null; }
"""
SET_SCROLLTOP = "(y) => { document.querySelector('[data-e2e-scroller]').scrollTop = y; }"

# The composer has no onSubmitEditing (multiline TextInput), so Enter inserts a
# newline - the send arrow is the only door. It is the last sibling of the
# textarea in the input row; located structurally so no icon font is involved.
SEND_BOX = """
() => {
  const ta = [...document.querySelectorAll('textarea')].pop();
  if (!ta) return null;
  const row = ta.parentElement;                 // the input row: [textarea, send]
  const btn = row.lastElementChild;
  if (btn === ta) return null;
  const r = btn.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
"""

# WHO GETS THE TAP. The pill can be perfectly visible and still be dead if a
# later sibling covers it: hit-testing follows tree order, not paint order.
HIT_AT_PILL = """
(sel) => {
  // The pill carries accessibilityLabel -> aria-label. Fallback: the SMALLEST
  // absolutely-positioned element whose text ends in the label (an ancestor
  // matches the text too, and measuring the ancestor would silently "pass").
  let pill = document.querySelector('[aria-label="Neueste"], [aria-label="Latest"]');
  if (!pill) {
    const cands = [...document.querySelectorAll('div,span')]
      .filter(e => /(Neueste|Latest)$/.test((e.textContent || '').trim())
                   && getComputedStyle(e).position === 'absolute');
    cands.sort((a, b) => {
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (ra.width * ra.height) - (rb.width * rb.height);
    });
    pill = cands[0];
  }
  if (!pill) return { pill: false };
  const r = pill.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const top = document.elementFromPoint(x, y);
  return {
    pill: true, x, y, rect: { top: r.top, left: r.left, w: r.width, h: r.height },
    // is the topmost element at the pill's own centre the pill (or inside it)?
    hitIsPill: !!(top && (pill.contains(top) || top.contains(pill))),
    hitTag: top ? top.tagName : null,
    hitText: top ? (top.textContent || '').slice(0, 60) : null,
  };
}
"""


def send(pg, text: str) -> None:
    box = pg.locator("textarea").last
    box.click()
    box.fill(text)
    pg.wait_for_timeout(150)
    b = pg.evaluate(SEND_BOX)
    pg.mouse.click(b["x"], b["y"])


def main() -> int:
    fails = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 700})
        pg = ctx.new_page()
        pg.set_default_timeout(180000)
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.evaluate("localStorage.setItem('helmdeck.demo','1')")
        pg.goto(BASE + "/chat", wait_until="networkidle")
        pg.wait_for_timeout(3000)

        # Grow the transcript until it actually overflows - a chat that fits on
        # screen can never show the pill, so testing it there proves nothing.
        for i in range(8):
            info = pg.evaluate(FIND_SCROLLER)
            if info and info["scrollHeight"] > info["clientHeight"] + 120:
                break
            send(pg, "Testnachricht %d zum Auffuellen des Verlaufs" % (i + 1))
            pg.wait_for_timeout(1400)
        info = pg.evaluate(FIND_SCROLLER)
        print("scroller:", info)
        if not info:
            print("FAIL: no scroll container found")
            return 1

        # --- B1: does a NEW message auto-scroll to the bottom? ---------------
        pg.evaluate(SET_SCROLLTOP, 10**7)
        pg.wait_for_timeout(400)
        before = pg.evaluate(READ_SCROLLER)
        send(pg, "Loest das Auto-Scrollen aus")
        pg.wait_for_timeout(2500)
        after = pg.evaluate(READ_SCROLLER)
        gap = after["scrollHeight"] - after["scrollTop"] - after["clientHeight"]
        print("auto-scroll: grew %d -> %d, gap-to-bottom=%d"
              % (before["scrollHeight"], after["scrollHeight"], gap))
        if after["scrollHeight"] <= before["scrollHeight"]:
            fails.append("transcript did not grow - send path broken, test inconclusive")
        elif gap > 40:
            fails.append("AUTO-SCROLL: new message did not pin to bottom (gap=%d)" % gap)

        # --- A + B2: the explicit pill --------------------------------------
        pg.evaluate(SET_SCROLLTOP, 0)
        pg.wait_for_timeout(600)
        hit = pg.evaluate(HIT_AT_PILL)
        print("pill hit-test:", hit)
        pg.screenshot(path="shot_chat_scroll_pill.png")
        if not hit.get("pill"):
            fails.append("PILL: not rendered after scrolling up")
        else:
            if not hit["hitIsPill"]:
                fails.append("PILL: tap at its own centre lands on <%s> %r - the pill is "
                             "COVERED and can never fire" % (hit["hitTag"], hit["hitText"]))
            top_before = pg.evaluate(READ_SCROLLER)["scrollTop"]
            pg.mouse.click(hit["x"], hit["y"])
            pg.wait_for_timeout(1500)
            st = pg.evaluate(READ_SCROLLER)
            gap = st["scrollHeight"] - st["scrollTop"] - st["clientHeight"]
            print("pill click: scrollTop %d -> %d, gap-to-bottom=%d"
                  % (top_before, st["scrollTop"], gap))
            if gap > 40:
                fails.append("PILL: click did not reach the newest message (gap=%d)" % gap)

        # --- the CARD chat, same component, own layout ----------------------
        # It was the surface that already worked; it now shares ChatScroll with
        # the board chat, so it is the regression half of this check.
        pg.goto(BASE + "/card/d3?tab=chat", wait_until="networkidle")
        pg.wait_for_timeout(2500)
        info = pg.evaluate(FIND_SCROLLER)
        print("card scroller:", info)
        if not info or info["scrollHeight"] <= info["clientHeight"] + 20:
            fails.append("CARD: transcript does not overflow - check inconclusive")
        else:
            pg.evaluate(SET_SCROLLTOP, 0)
            pg.wait_for_timeout(600)
            hit = pg.evaluate(HIT_AT_PILL)
            print("card pill hit-test:", hit)
            pg.screenshot(path="shot_chat_scroll_card.png")
            if not hit.get("pill"):
                fails.append("CARD PILL: not rendered after scrolling up")
            elif not hit["hitIsPill"]:
                fails.append("CARD PILL: covered by <%s> %r" % (hit["hitTag"], hit["hitText"]))
            else:
                pg.mouse.click(hit["x"], hit["y"])
                pg.wait_for_timeout(1500)
                st = pg.evaluate(READ_SCROLLER)
                gap = st["scrollHeight"] - st["scrollTop"] - st["clientHeight"]
                print("card pill click: gap-to-bottom=%d" % gap)
                if gap > 40:
                    fails.append("CARD PILL: click did not reach the newest step (gap=%d)" % gap)

        ctx.close(); b.close()

    print()
    for f in fails:
        print("FAIL:", f)
    print("RESULT:", "FAIL (%d)" % len(fails) if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
