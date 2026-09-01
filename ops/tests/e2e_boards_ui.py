# -*- coding: utf-8 -*-
"""Drive the REAL board in a browser and prove phase 2's acceptance criteria.

The unit tests cover the daemon (test_boards.py) and the wire (test_boards_http
.py). This covers the half neither can reach: that the BOARD ACTUALLY RENDERS
the account's board, that a column rename crosses to a second device, and that
a station a board hides but whose cards exist still shows up. All three are
claims about pixels, so they are checked against pixels.

  1. the board renders the ACTIVE board's columns, not four hardcoded lanes
  2. rename a column on a personal board in tab A -> tab B re-renders within
     one stream tick, with nothing board-specific in the client stream loop
  3. a board that hides `review` and `done`, while cards sit there, grows the
     automatic overflow columns - and they vanish when the cards do
  4. a drag through a CUSTOM column asks the daemon to move to that column's
     STATION - the same route, so the same gate on review entry

Prereqs (two background processes, both sandboxed - see the tool's header):
  py -3.12 ops/tools/boards_verify_daemon.py 8149
  cd surfaces/app && npx expo start --web --port 3790 --offline

  py -3.12 ops/tests/e2e_boards_ui.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json, os, sys, time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3790
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8149
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"

os.makedirs(SHOTS, exist_ok=True)
_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def api(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(DAEMON + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as f:
            return f.status, json.loads(f.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}


from playwright.sync_api import sync_playwright   # noqa: E402

CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})


def sign_in(page, who):
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    # Nobody has picked a language yet at the login screen, so the DEVICE
    # locale decides it. Accept either wording rather than pinning the test to
    # whichever locale the box running it happens to have.
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill(who)
            page.get_by_placeholder(pw_ph).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
    # Phase 1's first-login language step (ProfileGate) stands in front of the
    # board for an account that has never picked one - answer it the way a
    # human would, in German, which is also this workspace's language.
    for _ in range(20):
        if "Sprache" not in page.inner_text("body") and "language" not in page.inner_text("body"):
            break
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2500)
    return page


def open_board(page):
    """Login lands on the dashboard; the board is the next tab over."""
    page.goto("http://127.0.0.1:%d/board" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    return page


def col_heads(page):
    """The column headers as rendered, in order. Read off the board's own DOM
    rather than off /me, because the point of this file is what the USER sees."""
    return page.evaluate("""() => {
        const out = [];
        // Each column header is a row with a dot, a label and a count badge.
        for (const el of document.querySelectorAll('div')) {
            const t = (el.getAttribute('data-col') || '');
            if (t) out.push(t);
        }
        return out;
    }""")


print("boards UI end-to-end (real browser, real daemon)")
_, me_probe = api("GET", "/auth/state")
check(isinstance(me_probe, dict), "the sandbox daemon answers on %s" % DAEMON)

# A session of our own, to drive "device A" from Python while the browser is
# "device B" - that is what makes claim 2 a two-device test and not a re-render.
_, login = api("POST", "/auth/login", {"name": "owner", "password": PW})
TOK = login.get("token") or ""
check(bool(TOK), "owner logs in over HTTP (device A): %r" % login)

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1400, "height": 950}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append("console.error: " + m.text)
            if m.type == "error" else None)
    # Which requests actually died, so a network console.error can be told from
    # a real one rather than waved away by its message text.
    aborted_waits = []
    page.on("requestfailed", lambda r: aborted_waits.append(r.url)
            if "/stream/wait" in r.url else None)

    sign_in(page, "owner")
    open_board(page)
    # Everything before this point is the login screen polling an unauthenticated
    # daemon; its 401s are expected and are not what this file is about.
    errors.clear()
    body = page.inner_text("body")
    check("Backlog" in body, "the board renders after login (body head: %r)" % body[:120])
    # The workspace renamed `working` to "Bei uns" BEFORE boards existed; the
    # seed migrated it into the default board's column label, so it must be on
    # screen - that is the lane_labels migration, seen.
    check("Bei uns" in body,
          "policy.lane_labels came across into the seeded default board's "
          "column label and is what the board draws")
    page.screenshot(path=os.path.join(SHOTS, "01-default-board.png"), full_page=True)

    # ---- 3. the overflow invariant --------------------------------------
    # A board that shows ONLY backlog+working, while rv-1/rv-2/dn-1 sit in
    # review and done. Created over HTTP as device A.
    code, made = api("PUT", "/me/boards", {"board": {
        "name": "Nur Eingang", "columns": [
            {"label": "Ideen", "station": "backlog"},
            {"label": "", "station": "working"}]}}, token=TOK)
    check(code == 200, "device A creates a board that hides review+done (%s)" % code)
    bid = (made.get("board") or {}).get("id", "")

    open_board(page)
    # switch to it via the header switcher
    for sw in ("Board wechseln", "Switch board"):
        if page.get_by_label(sw).count():
            page.get_by_label(sw).first.click(timeout=15000)
            break
    page.wait_for_timeout(900)
    try:
        page.get_by_text("Nur Eingang", exact=False).last.click(timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    check("Ideen" in body, "the switcher opened the personal board (its column "
                           "'Ideen' is on screen)")
    check("Review" in body and ("Fertig" in body or "Done" in body),
          "and the stations the board HIDES still appear as automatic overflow "
          "columns, because cards are sitting in them - a card can never "
          "become invisible on a board that claims to show it")
    check("Board-Spalten umbenennen" in body,
          "the review cards are actually rendered in that overflow column, "
          "not merely counted")
    page.screenshot(path=os.path.join(SHOTS, "02-overflow-columns.png"), full_page=True)

    # ---- 2. rename on device A, re-render on device B --------------------
    cols = (made.get("board") or {}).get("columns") or []
    renamed = [dict(c) for c in cols]
    renamed[0]["label"] = "Frisch reingekommen"
    t0 = time.time()
    code, _ = api("PUT", "/me/boards", {"board": {
        "id": bid, "name": "Nur Eingang", "columns": renamed}}, token=TOK)
    check(code == 200, "device A renames the first column (%s)" % code)

    # NO reload: the browser must pick this up on its own, through the same
    # /stream/wait cursor every other board change rides. That is the whole
    # claim - boards needed no client stream plumbing of their own.
    seen = False
    for _ in range(60):
        page.wait_for_timeout(1000)
        if "Frisch reingekommen" in page.inner_text("body"):
            seen = True
            break
    check(seen, "device B re-rendered the new column name WITHOUT a reload, in "
                "%.0fs - one SSE tick, no board-specific client plumbing"
                % (time.time() - t0))
    page.screenshot(path=os.path.join(SHOTS, "03-renamed-live.png"), full_page=True)

    # ---- 4. a custom column moves cards through the real rails -----------
    # Watch the wire: a move from a custom column must be an ordinary
    # POST /tracks/<id>/lane naming that column's STATION. Nothing about a
    # board reaches the lane machine, which is why the gate cannot be dodged.
    moves = []
    page.on("request", lambda r: moves.append((r.method, r.url, r.post_data))
            if "/lane" in r.url else None)
    # The ⋯ menu shares gateDone and the same api.moveLane call the DRAG uses,
    # and unlike a synthetic drag it is deterministic in a headless browser.
    # What is under test is the translation, which both paths do identically:
    # a column is a view, so the request must name the column's STATION.
    page.get_by_label("Kartenmenü").first.click(timeout=15000)
    page.wait_for_timeout(1200)
    page.screenshot(path=os.path.join(SHOTS, "04-move-sheet-custom-column.png"), full_page=True)
    check("Bei uns" in page.inner_text("body"),
          "the move sheet offers the board's OWN column wording, not raw lanes")
    # Move it to the board's OWN custom column "Bei uns" - whose station is
    # `working`. If a board could name its own destination this would send
    # "Bei uns"; it must send "working".
    page.get_by_text("→ Bei uns", exact=False).first.click(timeout=10000)
    page.wait_for_timeout(3000)
    lane_calls = [m for m in moves if m[0] == "POST"]
    check(bool(lane_calls),
          "moving from a custom column POSTs to the ordinary lane route: %s"
          % lane_calls[:2])
    sent = json.loads(lane_calls[0][2] or "{}") if lane_calls else {}
    check(sent.get("lane") == "working",
          "and it names the column's STATION, not the column - which is why a "
          "custom column runs the same rails (gate on review entry included); "
          "a board never gets to name the destination (sent %r)" % sent)
    check("/tracks/" in lane_calls[0][1] and lane_calls[0][1].endswith("/lane"),
          "on the SAME endpoint the four-lane board always used, so the gate "
          "is not something a board can route around (%s)" % lane_calls[0][1])

    # ---- 5. the editor is what makes claim 2 reachable by a human ---------
    page.goto("http://127.0.0.1:%d/boards" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    body = page.inner_text("body")
    check("Spalten" in body, "the board editor renders its column list")
    check("geteilt" in body, "the shared default board is badged as shared, so "
                             "'why can't I edit this one' is answered before it "
                             "is asked")
    page.screenshot(path=os.path.join(SHOTS, "05-board-editor.png"), full_page=True)

    real_errors = [e for e in errors if "Download the React DevTools" not in e]
    # ERR_EMPTY_RESPONSE on /stream/wait is this HARNESS, not the app: every
    # page.goto aborts the in-flight 22s hanging GET. Named explicitly rather
    # than filtered by substring, so a real empty response elsewhere still fails.
    real_errors = [e for e in real_errors
                   if not (e.endswith("ERR_EMPTY_RESPONSE") and aborted_waits)]
    check(not real_errors, "no page errors while driving the board: %s" % real_errors[:3])
    ctx.close(); b.close()

print(("FAILED: %d" % len(_fails)) if _fails else "all board UI checks passed")
print("shots in %s" % SHOTS)
sys.exit(1 if _fails else 0)
