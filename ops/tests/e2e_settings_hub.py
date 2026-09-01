# -*- coding: utf-8 -*-
"""Drive the REAL settings hub in a browser (accounts-boards-prd phase 4).

Two halves prove this card, and they prove different things:

  - surfaces/app/src/data/__settings_hub_selftest__.ts proves the PLACEMENT
    RULE, deterministically and with no daemon: given a knob the client has
    never seen, does placeRows put it in the door it names, in the tier it
    names, with the badge its scope names.
  - THIS file proves the rule is actually WIRED to pixels: that the hub really
    renders from the schema, that a DUMMY knob injected daemon-side appears in
    the right door with the right badge against an unmodified client bundle,
    and that the doors a non-owner may not have are not merely 403 but absent.

What is checked:
  1. the door list shows all seven doors for the owner, in schema order
  2. door 1 "Mein Profil" renders the ACCOUNT's schema rows (from /me) with a
     "Konto" badge, and the device rows with a "Gerät" badge
  3. THE ACCEPTANCE: a dummy knob tagged door=connections scope=device appears
     in door 5 with badge "Gerät" - no client code knows it exists
  4. door 6 "System" renders the dissolved business panel as schema rows
  5. /automation and /modules still resolve, and land in their hub doors
  6. a `client` role sees ONLY door 1 + Boards - the rest are invisible, not 403
  7. no console error or page error on any door

Prereqs (two background processes, both sandboxed - see the tool's header):
  HELMDECK_DUMMY_KNOB=1 py -3.12 ops/tools/boards_verify_daemon.py 8610
  cd surfaces/app && npx expo start --web --port 3610 --offline

  py -3.12 ops/tests/e2e_settings_hub.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json, os, sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3610
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8610
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
    """Same flow as e2e_boards_ui.py's - kept in step with it deliberately."""
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill(who)
            page.get_by_placeholder(pw_ph).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
    # Phase 1's first-login language step stands in front of everything for an
    # account that has never picked one.
    for _ in range(20):
        body = page.inner_text("body")
        if "Sprache" not in body and "language" not in body:
            break
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2500)
    return page


def door(page, which):
    page.goto("http://127.0.0.1:%d/settings?door=%s" % (WEB, which),
              wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    return page.inner_text("body")


print("settings hub end-to-end (real browser, real daemon)")
_, probe = api("GET", "/auth/state")
check(isinstance(probe, dict), "the sandbox daemon answers on %s" % DAEMON)

# The dummy knob must actually be on the wire, or claim 3 proves nothing about
# the client. Checked over HTTP first so a failure here is unambiguous.
_, login = api("POST", "/auth/login", {"name": "owner", "password": PW})
TOK = login.get("token") or ""
check(bool(TOK), "owner logs in over HTTP: %r" % login)
_, auto = api("GET", "/automation", token=TOK)
wire = {e["path"]: e for e in (auto.get("config_schema") or [])}
check("dummy.knob" in wire,
      "the daemon serves the dummy knob on /automation (set HELMDECK_DUMMY_KNOB=1)")
if "dummy.knob" in wire:
    check(wire["dummy.knob"]["door"] == "connections"
          and wire["dummy.knob"]["scope"] == "device",
          "the dummy is tagged door=connections scope=device")
_, me = api("GET", "/me", token=TOK)
prof_schema = {e["path"] for e in (me.get("config_schema") or [])}
check(prof_schema == {"lang", "appearance.backdrop"},
      "/me serves the account's own schema rows: %s" % sorted(prof_schema))

# Two DIFFERENT signals, kept apart because they mean different things.
#
#   crashes  - a JS exception. Always a bug, never expected.
#   refused  - an HTTP >=400 the app actually asked for, recorded WITH ITS URL.
#              Bare console text ("Failed to load resource: 403") names no
#              endpoint and so cannot be acted on; the URL is the whole point.
#
# Deliberately NOT counted: the aborted long-poll. Every navigation cancels an
# in-flight /stream/wait, which surfaces as net::ERR_EMPTY_RESPONSE - that is
# the stream working, and e2e_boards_ui.py hit and documented the same thing.
crashes = []
refused = []


def watch(pg):
    pg.on("pageerror", lambda e: crashes.append(str(e)))
    pg.on("response", lambda r: refused.append("%d %s" % (r.status, r.url))
          if r.status >= 400 else None)
    return pg


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1400, "height": 950}, device_scale_factor=2)
    page = ctx.new_page()
    # The Expo dev server BUNDLES ON DEMAND, and a cold `--clear` start spends
    # minutes on the first request. Playwright's 30s default turns that into a
    # navigation timeout that reads like an app failure - so the budget is set
    # to what a cold bundle actually costs, once, here.
    ctx.set_default_navigation_timeout(240000)
    ctx.set_default_timeout(60000)
    watch(page)

    sign_in(page, "owner")
    # Everything before this point is the auth handshake: the app boots with no
    # token, fires /me, and gets a 401 by design - that IS the login gate
    # working, and counting it would make the check unfalsifiable noise. From
    # here on the session is real, so any error belongs to the hub.
    crashes.clear(); refused.clear()

    # -- 1. the door list ----------------------------------------------------
    page.goto("http://127.0.0.1:%d/settings" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    body = page.inner_text("body")
    for label in ("Mein Profil", "Boards", "Agenten & Autonomie", "Zellen",
                  "Verbindungen", "Team & Geräte", "System"):
        check(label in body, "door list shows %r" % label)
    check(body.index("Boards") < body.index("Agenten & Autonomie"),
          "the Boards door sits between Mein Profil and Agenten (PRD section 5)")
    page.screenshot(path=os.path.join(SHOTS, "hub-01-doors.png"), full_page=True)

    # -- 2. door 1: account rows + device rows, each badged ------------------
    body = door(page, "general")
    check("Sprache" in body, "door 1 renders the account's language row (from /me's schema)")
    check("Konto" in body, "the account rows wear the 'Konto' badge")
    check("Gerät" in body, "the device-local rows wear the 'Gerät' badge")
    check("Workspace" in body, "the owner also sees the workspace-default panel, badged")
    page.screenshot(path=os.path.join(SHOTS, "hub-02-profile.png"), full_page=True)

    # -- 3. THE ACCEPTANCE: the dummy knob, in door 5, with its badge --------
    body = door(page, "connections")
    # SectionLabel upper-cases its text (ui/kit.tsx), and Chrome's innerText
    # reflects text-transform - so the heading arrives as "DUMMY-SEKTION".
    check("DUMMY-SEKTION" in body.upper(),
          "the dummy knob's SECTION renders in door 5 - heading straight off the "
          "knob's groupKey, with no client-side group->label table")
    check("Dummy-Knopf" in body, "the dummy knob's label renders")
    check("Erfunden fuer den Abnahmetest." in body, "its descKey renders as the row hint")
    check("Gerät" in body, "the dummy row wears the badge its SCOPE names")
    page.screenshot(path=os.path.join(SHOTS, "hub-03-dummy-knob.png"), full_page=True)

    # ...and nowhere else. A knob that also leaks into another door would be an
    # edit offered in a place that does not own it.
    for other in ("general", "boards", "automation", "cells", "team", "system"):
        check("Dummy-Knopf" not in door(page, other),
              "the dummy does NOT leak into door %r" % other)

    # -- 4. door 6: the dissolved business panel, as schema rows -------------
    body = door(page, "system")
    # The German labels the dict actually ships for these three knobs.
    for label in ("Standard-Repo", "WIP-Limit", "Wert/Karte"):
        check(label in body, "door 6 renders %r as a schema row" % label)
    check("Erweitert" in body, "the advanced tier is folded, not dropped")
    page.screenshot(path=os.path.join(SHOTS, "hub-06-system.png"), full_page=True)

    # -- 5. the other doors render at all, and the redirects still resolve ---
    for d in ("boards", "automation", "cells", "team"):
        body = door(page, d)
        check(len(body) > 200, "door %r renders content" % d)
        page.screenshot(path=os.path.join(SHOTS, "hub-door-%s.png" % d), full_page=True)

    for path, expect in (("/automation", "door=automation"), ("/modules", "door=cells")):
        page.goto("http://127.0.0.1:%d%s" % (WEB, path), wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        check(expect in page.url,
              "%s still resolves and redirects into the hub (url=%s)" % (path, page.url))

    check(not crashes, "OWNER: no JS exception on any door: %s" % (crashes[:3] or "none"))
    check(not refused, "OWNER: no refused request on any door: %s" % (refused[:4] or "none"))

    # -- 6. a client role: door 1 + Boards, the rest ABSENT ------------------
    page.evaluate("() => { localStorage.clear(); }")
    sign_in(page, "ada")
    crashes.clear(); refused.clear()   # the second handshake, same reasoning
    page.goto("http://127.0.0.1:%d/settings" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    body = page.inner_text("body")
    check("Mein Profil" in body, "a client sees door 1")
    check("Boards" in body, "a client sees the Boards door")
    for label in ("Agenten & Autonomie", "Team & Geräte"):
        check(label not in body,
              "a client does NOT see %r - invisible, not a 403 (the plan's "
              "'Rest unsichtbar statt 403')" % label)
    body = door(page, "general")
    check("Sprache" in body,
          "and door 1 still WORKS for them - the account rows ride on /me, "
          "which a client may read, not on the owner-only /automation")
    page.screenshot(path=os.path.join(SHOTS, "hub-07-client.png"), full_page=True)

    # -- 7. phone width, because the owner reviews UI hard ------------------
    phone = ctx.new_page()
    phone.set_viewport_size({"width": 390, "height": 844})
    phone.goto("http://127.0.0.1:%d/settings" % WEB, wait_until="domcontentloaded")
    phone.wait_for_timeout(3500)
    phone.screenshot(path=os.path.join(SHOTS, "hub-08-phone-doors.png"), full_page=True)
    phone.goto("http://127.0.0.1:%d/settings?door=general" % WEB, wait_until="domcontentloaded")
    phone.wait_for_timeout(3000)
    phone.screenshot(path=os.path.join(SHOTS, "hub-09-phone-profile.png"), full_page=True)

    b.close()

# A CLIENT must produce no NEW refusal on the doors that are theirs: this is
# the role the hub newly lets in, and every owner-only query the screen fires
# is gated on the live capability rather than attempted and refused.
#
# GET /cells is the one exception, and it is NOT the hub's: (tabs)/_layout.tsx
# queries it on every screen for every role, to hide the tabs of disabled
# cells, and routes_policy.py refuses a client. React-query keys both callers
# on ["cells"], so the hub adds no request of its own - opening the hub as a
# client is exactly as noisy as opening the dashboard as one. Named here rather
# than filtered silently, because the day it stops being the only one, this
# check must say so.
PREEXISTING = ("/cells",)
new_refusals = [r for r in refused if not any(r.endswith(p) for p in PREEXISTING)]
check(not crashes, "CLIENT: no JS exception: %s" % (crashes[:3] or "none"))
check(not new_refusals,
      "CLIENT: nothing refused on the doors that are theirs, beyond the "
      "pre-existing app-wide /cells fetch: %s" % (new_refusals[:4] or "none"))
if refused and not new_refusals:
    print("  note   the only refusals were the known app-wide ones: %s"
          % sorted(set(refused)))
print("\nshots in %s" % SHOTS)
print(("FAILED: %d" % len(_fails)) if _fails else "all settings-hub UI checks passed")
sys.exit(1 if _fails else 0)
