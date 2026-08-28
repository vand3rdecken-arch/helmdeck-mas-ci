# -*- coding: utf-8 -*-
"""Screenshot + JUDGE the board's Archive scope (CLAUDE.md: UI changes are
judged, not merely confirmed to render).

The bug (owner report 2026-08-27, card 20260827-224828-machine): an ACTIVE
needs_you card showed up under the board's "Archiv" chip, and no lane move
cleared it. Cause: the NextUp strip (and the GxP sign-off bar) read `rows`
directly and rendered regardless of the selected scope, so under "Archiv" the
board showed live cards above the archived lanes.

Drives the REAL board on the Expo web dev server in DEMO mode - the one way to
reach it without a paired daemon - archives a card through the card screen's
own menu, checks what the Archive scope then shows, and brings the card back
out again (the restore path that did not exist before).

Navigation is CLICKS, never page.goto: the demo board is module state, so a
full page load resets it to SEED and the archive under test would vanish.

Start the server first:
    cd surfaces/app && npx expo start --web --port <port> --offline
Then:
    py -3.12 ops/tests/shot_archive_scope.py <port> <outdir>
"""
import sys

from playwright.sync_api import sync_playwright

port = sys.argv[1] if len(sys.argv) > 1 else "3800"
out = sys.argv[2] if len(sys.argv) > 2 else "."
base = "http://localhost:%s" % port

D1 = "Rechnungs-PDF pro Kunde automatisch erzeugen"   # demo.c1.task (lane done)
D4 = "Soll ich die alten Exporte migrieren?"          # demo.c4.task (needs_you)

FAILED = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILED.append(what)


def say(s):
    # this console is cp1252; the app renders icon glyphs and umlauts
    print(str(s).encode("ascii", "replace").decode("ascii"))


def shot(pg, name):
    path = "%s/archive-%s.png" % (out, name)
    pg.screenshot(path=path, full_page=False)
    print("wrote", path)


def open_menu(pg):
    pg.get_by_role("button", name="Kartenmenü").or_(
        pg.get_by_role("button", name="Card menu")).first.click(timeout=20000)
    pg.wait_for_timeout(1500)


def run():
    with sync_playwright() as p:
        b = p.chromium.launch()
        # Pin the locale: the app renders in the BROWSER's language, and an
        # English run would silently "pass" every German text assertion by
        # absence (the trap shot_outbox.py hit).
        ctx = b.new_context(viewport={"width": 420, "height": 900}, locale="de-DE")
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('helmdeck.demo','1');")
        # Metro compiles the whole app on the FIRST request - minutes, not
        # seconds, on a cold dev server.
        pg.goto(base, wait_until="domcontentloaded", timeout=300000)
        pg.wait_for_timeout(18000)
        # The app opens on the Dashboard; the scope chips live on the Board tab.
        pg.get_by_text("Board", exact=True).first.click(timeout=30000)
        pg.wait_for_timeout(4000)

        body = pg.inner_text("body")
        say("---- board, scope=all ----")
        say(body[:900])
        shot(pg, "1-board-all")
        check("Archiv" not in body and "Archive" not in body,
              "no Archive chip before anything is archived")
        # Assert on the CARD TASK, never on the "ALS NÄCHSTES" heading: the
        # Dashboard tab stays mounted behind the Board and has a next-up list
        # of its own (plan items), so the heading is in the DOM either way.
        check(body.count(D4) >= 2,
              "the live needs_you card is on the board twice (NextUp + lane)")

        # --- archive a card through the card screen's own menu -------------
        # d1 is the DONE demo card - archiving a finished card is the normal
        # case, and it leaves the needs_you card live for the real assertion.
        pg.get_by_text(D1, exact=False).first.click(timeout=20000)
        pg.wait_for_timeout(5000)
        open_menu(pg)
        shot(pg, "2-card-menu")
        menu_text = pg.inner_text("body")
        check("Archivieren" in menu_text or "Archive" == menu_text,
              "the card menu offers Archive")
        pg.get_by_text("Archivieren", exact=True).or_(
            pg.get_by_text("Archive", exact=True)).first.click(timeout=20000)
        pg.wait_for_timeout(5000)          # archive + router.back()

        body = pg.inner_text("body")
        say("---- board, scope=all, one card archived ----")
        say(body[:900])
        shot(pg, "3-board-all-with-chip")
        check("Archiv" in body or "Archive" in body, "the Archive chip appeared")
        check(D1 not in body, "the archived card left the default board")
        # The fix must not silence NextUp everywhere - only under Archive.
        check(body.count(D4) >= 2,
              "NextUp still renders under the default scope")

        # --- tap Archiv ----------------------------------------------------
        pg.get_by_role("button").filter(has_text="Archiv").first.click(timeout=20000)
        pg.wait_for_timeout(3500)
        arch = pg.inner_text("body")
        say("---- board, scope=archived ----")
        say(arch[:900])
        shot(pg, "4-board-archived")
        check(D4 not in arch,
              "the active needs_you card is NOWHERE under Archive (THE BUG)")
        check(D1 in arch, "the archived card IS listed under Archive")

        # --- and back out again --------------------------------------------
        pg.get_by_text(D1, exact=False).first.click(timeout=20000)
        pg.wait_for_timeout(5000)
        open_menu(pg)
        shot(pg, "5-card-menu-archived")
        menu_text = pg.inner_text("body")
        check("Aus dem Archiv holen" in menu_text or "Restore from archive" in menu_text,
              "an archived card offers the way BACK")
        pg.get_by_text("Aus dem Archiv holen", exact=True).or_(
            pg.get_by_text("Restore from archive", exact=True)).first.click(timeout=20000)
        pg.wait_for_timeout(3000)
        shot(pg, "6-card-restored")
        restored = pg.inner_text("body")
        check("zurück auf dem Board" in restored or "back on the board" in restored,
              "the restore is confirmed to the owner, on the card")

        pg.go_back()
        pg.wait_for_timeout(5000)
        body = pg.inner_text("body")
        say("---- board after restore, still on the Archive scope ----")
        say(body[:900])
        shot(pg, "7-board-archive-empty")
        # The scope is STILL "archived" and now matches nothing. The bar must
        # not vanish with it, or there is no way back to the board at all.
        check("Archiv" in body, "the Archive chip survives its own last card")
        pg.get_by_role("button").filter(has_text="Alle").first.click(timeout=20000)
        pg.wait_for_timeout(3000)
        body = pg.inner_text("body")
        shot(pg, "8-board-restored")
        check(D1 in body, "the restored card is back on the board")
        b.close()


run()
if FAILED:
    print("\nFAILED (%d): %s" % (len(FAILED), "; ".join(FAILED)))
    sys.exit(1)
print("\nall archive-scope UI checks passed")
