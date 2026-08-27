# -*- coding: utf-8 -*-
"""Screenshot judge for the on-device board-move UX (NOT shipped).
Drives the Expo WEB build at a phone viewport against ops/tools/mock_board.py:
  1. board at rest (lane_labels: Inbox/In Arbeit/Abnahme/Fertig)
  2. long-press-drag card 5 onto the FULL "In Arbeit" band -> refusal toast
  3. drag card 4 onto "Abnahme" -> optimistic move + verdict toast
  4. drag card 5 onto "Fertig" (mock 500s card 5) -> rollback, card snaps back
  5. long-press WITHOUT dragging -> move sheet (WIP-full annotation)
Run: py -3.12 ops/tools/judge_board_move.py [http://localhost:8090]
Shots land in ops/tools/shots/.
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
OUT = os.path.join(os.path.dirname(__file__), "shots")
os.makedirs(OUT, exist_ok=True)
PYTEST_CARD = "Pytest suite for pure-logic"       # card 5: unique, Inbox, mock 500s its lane moves
PURGE_CARD = "Purge .fuse_hidden junk"            # card 4: ALSO in NextUp -> board card is nth(1)
BAND = {"backlog": 140, "working": 340, "review": 540, "done": 720}   # band centers @844px


def shot(page, name):
    page.screenshot(path=os.path.join(OUT, name + ".png"))
    print("shot:", name)


def card_center(page, text, nth=0):
    loc = page.get_by_text(text, exact=False).nth(nth)
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    box = loc.bounding_box()
    assert box and box["y"] < 760, "target hidden/behind tab bar: %s %r" % (text, box)
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def long_press_drag(page, from_xy, to_xy, name_mid=None):
    page.mouse.move(*from_xy)
    page.mouse.down()
    page.wait_for_timeout(450)          # > activateAfterLongPress(260)
    page.mouse.move(from_xy[0] + 6, from_xy[1] + 6, steps=2)   # flip `moved`
    page.mouse.move(to_xy[0], to_xy[1], steps=12)
    page.wait_for_timeout(300)
    if name_mid:
        shot(page, name_mid)
    page.mouse.up()


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("text=In Arbeit", timeout=120000)   # lane_labels applied
    page.wait_for_timeout(1500)
    shot(page, "1_board_rest")

    # 2: WIP-full refusal (wip 2/2 in the mock)
    xy = card_center(page, PYTEST_CARD)
    long_press_drag(page, xy, (200, BAND["working"]), name_mid="2_drag_overlay_wip_full")
    page.wait_for_timeout(700)
    shot(page, "3_wip_refused_toast")
    page.wait_for_timeout(5200)                                # let the toast die

    # 3: allowed move -> optimistic + verdict toast
    xy = card_center(page, PURGE_CARD, nth=1)
    long_press_drag(page, xy, (200, BAND["review"]), name_mid="4a_drag_to_abnahme")
    page.wait_for_timeout(800)
    shot(page, "4b_moved_optimistic_toast")
    page.wait_for_timeout(5200)

    # 4: mock 500s card 5 -> optimistic move must ROLL BACK to Inbox
    xy = card_center(page, PYTEST_CARD)
    long_press_drag(page, xy, (200, BAND["done"]))
    page.wait_for_timeout(1200)
    shot(page, "5_rollback_card_back_in_inbox")

    # 5: long-press without dragging -> move sheet with WIP annotation
    xy = card_center(page, PYTEST_CARD)
    page.mouse.move(*xy)
    page.mouse.down()
    page.wait_for_timeout(500)
    page.mouse.up()
    page.wait_for_timeout(500)
    shot(page, "6_longpress_sheet")

    print("pageerrors:", errors or "none")
    b.close()
print("done ->", OUT)
