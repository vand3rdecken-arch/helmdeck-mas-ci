# -*- coding: utf-8 -*-
"""Drive the rebuilt "Team & Geraete" door in a real browser against a real
daemon (owner decree 2026-09-09, 22:15: ONE invitation flow, role chosen AT
invitation time, like Jira).

ops/tests/test_invites.py already proves the OBJECT MODEL over HTTP. This file
proves the model is wired to pixels, which is a different claim and the one the
owner reviews: that the button exists, that the dialog really carries the role
into the daemon's record, that the code the owner reads off the screen is the
code someone can actually sign up with, and that the surfaces this replaced -
the "create a user" form, the global invite-code field, the default-role
picker, the raw token list - are GONE rather than merely unlinked.

What is checked:
  1. the door leads with "Mitglied einladen"; members and open invitations are
     the first two panels
  2. the retired surfaces are absent from the DOM, not just from the eye
  3. the invite dialog offers a real role choice, and creating an invitation
     produces a code the DAEMON stores with that role
  4. the open-invitations list picks it up live, and revoke removes it
  5. a member row folds open into DEVICES (label + last used + revoke), not
     into a list of raw tokens
  6. end to end: the link prefills the code, the invited person signs up, and
     lands with the role the owner picked - never a workspace default
  7. a client role cannot see the door at all (unchanged, re-checked because
     this card moved every panel behind it)
  8. no JS exception, no refused request, and it survives phone width

Prereqs (two background processes, both sandboxed):
  py -3.12 ops/tools/boards_verify_daemon.py 13709
  cd surfaces/app && npx expo start --web --port 3709 --offline

  py -3.12 ops/tests/e2e_team_door.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json, os, re, sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3709
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 13709
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
                  "room": "", "daemonPub": "", "mySec": "", "myPub": "",
                  "deviceId": ""})


def sign_in(page, who, pw=PW):
    """Same flow as e2e_settings_hub.py's - kept in step with it deliberately."""
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill(who)
            page.get_by_placeholder(pw_ph).first.fill(pw)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
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


def team_door(page):
    page.goto("http://127.0.0.1:%d/settings?door=team" % WEB,
              wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    return page.inner_text("body")


def counts():
    """What the DAEMON thinks the two headline numbers are. The panel is
    checked for AGREEMENT with these rather than against hardcoded fixtures:
    the sandbox daemon outlives a single run of this file, so "(0) invitations"
    is only true the first time - and a test that only passes on a pristine
    store is a test nobody re-runs."""
    _, users = api("GET", "/users", token=TOK)
    _, invs = api("GET", "/invites", token=TOK)
    return len(users), len([i for i in invs if i["state"] == "open"])


print("Team & Geraete door end-to-end (real browser, real daemon)")
_, probe = api("GET", "/auth/state")
check(isinstance(probe, dict), "the sandbox daemon answers on %s" % DAEMON)
_, login = api("POST", "/auth/login", {"name": "owner", "password": PW})
TOK = login.get("token") or ""
check(bool(TOK), "owner logs in over HTTP: %r" % login)

crashes = []
refused = []

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1400, "height": 950}, device_scale_factor=2)
    ctx.set_default_navigation_timeout(240000)
    ctx.set_default_timeout(60000)
    page = ctx.new_page()
    page.on("pageerror", lambda e: crashes.append(str(e)))
    page.on("response", lambda r: refused.append("%d %s" % (r.status, r.url))
            if r.status >= 400 else None)

    sign_in(page, "owner")
    crashes.clear(); refused.clear()      # the auth handshake 401s by design

    # -- 1. the door leads with the invitation ------------------------------
    # SectionLabel upper-cases its text (ui/kit.tsx) and Chrome's innerText
    # reflects text-transform, so headings arrive shouting. Compared against an
    # upper-cased body rather than against the dict spelling - the same trap
    # e2e_settings_hub.py documents for "DUMMY-SEKTION".
    body = team_door(page)
    up = body.upper()
    n_users, n_open = counts()
    check("Mitglied einladen" in body, "the door shows the 'Mitglied einladen' button")
    check("MITGLIEDER (%d)" % n_users in up,
          "the members panel count agrees with /users (%d)" % n_users)
    check("OFFENE EINLADUNGEN (%d)" % n_open in up,
          "the invitations count agrees with /invites (%d open)" % n_open)
    check(up.index("MITGLIEDER (") < up.index("TELEFON KOPPELN"),
          "members come BEFORE the pairing panels - the door's job is people now")
    page.screenshot(path=os.path.join(SHOTS, "team-01-door.png"), full_page=True)

    # -- 2. the retired surfaces are gone -----------------------------------
    for dead, why in (
        ("Neuen User anlegen", "the owner typed a stranger's password into it"),
        ("Invite-Code (leer", "one global, never-expiring, reusable code"),
        ("Default-Rolle", "a workspace-wide role every signup inherited"),
    ):
        check(dead not in body, "GONE: %r (%s)" % (dead, why))
    check("SELBSTREGISTRIERUNG" in up,
          "...and the one knob that survives it is still here, as a switch")

    # -- 3. the dialog carries the ROLE into the daemon's record ------------
    def newest_open():
        _, rows = api("GET", "/invites", token=TOK)
        return next((r for r in rows if r["state"] == "open"), None)

    page.get_by_text("Mitglied einladen").first.click()
    page.wait_for_timeout(1500)
    # The dialog's own strings, matched exactly - no ancestor-depth guessing,
    # which is the brittle half of scoping a modal. "Arbeitet am ganzen Board
    # mit." exists nowhere else in the app.
    dlg_seen = page.inner_text("body")
    check("Arbeitet am ganzen Board mit." in dlg_seen,
          "each role is explained in a sentence - 'operator' means nothing on its own")
    check("Nur eigene Karten anlegen und kommentieren." in dlg_seen,
          "the dialog offers both invitable roles, each with its own sentence")
    check("Alles, inklusive Einstellungen und Mitglieder." not in dlg_seen,
          "owner is NOT offered as an invitable role")
    page.screenshot(path=os.path.join(SHOTS, "team-02-dialog.png"))

    # Click the role by its SENTENCE, not by the word "Operator": that word is
    # also a role chip in the invitations list behind the modal, and the first
    # match on the page is that one - which Playwright then cannot click,
    # because the modal overlay is (correctly) in front of it.
    page.get_by_text("Arbeitet am ganzen Board mit.", exact=True).first.click()
    page.get_by_text("30 Tage", exact=True).first.click()
    page.get_by_text("Einladung erstellen", exact=True).first.click()
    page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(SHOTS, "team-03-code.png"))

    match = newest_open()
    shown = (match or {}).get("code", "")
    check(match is not None, "the daemon now holds an open invitation")
    check(match and match["role"] == "operator",
          "...with role=operator - the role travelled from the dialog into the object")
    # The direction that matters: the code the DAEMON stored is the one on the
    # owner's screen. A dialog showing anything else would invite nobody.
    check(bool(shown) and page.get_by_text(shown, exact=True).count() > 0,
          "the dialog shows exactly that code (%r)" % shown)

    # -- 4. the list picks it up live, and revoke works ---------------------
    page.get_by_text("Schließen", exact=True).first.click()
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    check("OFFENE EINLADUNGEN (%d)" % counts()[1] in body.upper(),
          "the open-invitations list refreshed without a reload")
    check(body.count(shown) >= 1, "the code is listed, selectable and copyable")
    page.screenshot(path=os.path.join(SHOTS, "team-04-listed.png"), full_page=True)

    # A second invitation, revoked through the UI, to prove the kill switch.
    # Revoked BY ITS OWN ROW, not by "the last widerrufen link": list_all() is
    # newest-first, so positional targeting would have killed the invitation
    # step 6 then tries to redeem.
    page.get_by_text("Mitglied einladen").first.click()
    page.wait_for_timeout(1200)
    page.get_by_text("Einladung erstellen", exact=True).first.click()
    page.wait_for_timeout(2000)
    doomed = (newest_open() or {}).get("code", "")
    page.get_by_text("Schließen", exact=True).first.click()
    page.wait_for_timeout(2000)
    two = counts()[1]
    check("OFFENE EINLADUNGEN (%d)" % two in page.inner_text("body").upper(),
          "a second invitation joins the list (%d open)" % two)
    check(doomed and doomed != shown, "the second invitation has its own code")
    row = page.get_by_text(doomed, exact=True).locator("xpath=ancestor::div[2]")
    page.once("dialog", lambda d: d.accept())
    row.get_by_text("widerrufen", exact=True).first.click()
    page.wait_for_timeout(2500)
    after_body = page.inner_text("body")
    check("OFFENE EINLADUNGEN (%d)" % (two - 1) in after_body.upper(),
          "revoking one through the UI removes it from the list")
    check(doomed not in after_body and shown in after_body,
          "...the RIGHT one - the other invitation is untouched")

    # -- 5. a member folds open into DEVICES --------------------------------
    # "(du)" appears only on the signed-in owner's row in the members panel -
    # clicking "owner" would have hit the sidebar account footer instead.
    page.get_by_text("(%s)" % "du", exact=True).first.click()
    page.wait_for_timeout(1200)
    body = page.inner_text("body")
    check("zuletzt" in body or "noch nie benutzt" in body,
          "an expanded member shows its devices with a last-used line")
    check("+ Gerät/Skript" in body,
          "...and the way to mint a token for a script is still there, in its place")
    page.screenshot(path=os.path.join(SHOTS, "team-05-devices.png"), full_page=True)

    # -- 6. end to end: the invited person actually gets in -----------------
    ctx2 = b.new_context(viewport={"width": 1400, "height": 950}, device_scale_factor=2)
    ctx2.set_default_navigation_timeout(240000)
    p2 = ctx2.new_page()
    p2.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    p2.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    p2.goto("http://127.0.0.1:%d/?invite=%s" % (WEB, shown), wait_until="domcontentloaded")
    p2.wait_for_timeout(6000)
    check(p2.locator("input[value='%s']" % shown).count() > 0,
          "the invitation link prefills the code and opens the sign-up tab")
    p2.screenshot(path=os.path.join(SHOTS, "team-06-invited.png"))

    # The invited person's browser has NO session yet, so useT cannot resolve a
    # workspace language and falls back to the DEVICE locale (login_screen.tsx
    # documents this) - on a CI-ish box that is English. Both spellings, same
    # reasoning as sign_in() above.
    # Named off the code, so a re-run against a daemon that already served this
    # file does not collide with the account the LAST run created (create_user
    # refuses a duplicate name, which would look like an invitation failure).
    who = "mara" + shown[:4].lower()
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Konto anlegen"),
                                ("Username", "Password", "Create account")):
        if p2.get_by_placeholder(user_ph).count():
            p2.get_by_placeholder(user_ph).first.fill(who)
            p2.get_by_placeholder(pw_ph, exact=False).first.fill(PW)
            p2.get_by_text(cta, exact=True).last.click()
            break
    p2.wait_for_timeout(8000)
    p2.screenshot(path=os.path.join(SHOTS, "team-07-joined.png"))

    _, users = api("GET", "/users", token=TOK)
    joined = next((u for u in users if u["name"] == who), None)
    check(joined is not None, "the invited person now has an account (%s)" % who)
    check(joined and joined["role"] == "operator",
          "...with the role chosen AT INVITATION TIME, not a workspace default")

    _, after = api("GET", "/invites", token=TOK)
    spent = next((i for i in after if i["code"] == shown), None)
    check(spent and spent["state"] == "used" and spent["used_by"] == who,
          "the invitation is spent and records who used it")

    body = team_door(page).upper()
    n_users2, n_open2 = counts()
    check("MITGLIEDER (%d)" % n_users2 in body and n_users2 == n_users + 1,
          "the owner's panel gained exactly one member (%d)" % n_users2)
    check("OFFENE EINLADUNGEN (%d)" % n_open2 in body and shown not in body,
          "...and the redeemed invitation left the actionable list")
    page.screenshot(path=os.path.join(SHOTS, "team-08-after-join.png"), full_page=True)

    check(not crashes, "no JS exception on the door: %s" % (crashes[:3] or "none"))
    check(not refused, "no refused request on the door: %s" % (refused[:4] or "none"))

    # -- 7. a client still cannot see the door ------------------------------
    page.evaluate("() => { localStorage.clear(); }")
    sign_in(page, "ada")
    page.goto("http://127.0.0.1:%d/settings" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    check("Team & Geräte" not in page.inner_text("body"),
          "a client does not see the door at all - invisible, not a 403")

    # -- 8. phone width, because the owner reviews UI hard ------------------
    phone = ctx.new_page()
    phone.set_viewport_size({"width": 390, "height": 844})
    phone.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    phone.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    sign_in(phone, "owner")
    phone.goto("http://127.0.0.1:%d/settings?door=team" % WEB, wait_until="domcontentloaded")
    phone.wait_for_timeout(4000)
    phone.screenshot(path=os.path.join(SHOTS, "team-09-phone.png"), full_page=True)
    phone.get_by_text("Mitglied einladen").first.click()
    phone.wait_for_timeout(1500)
    phone.screenshot(path=os.path.join(SHOTS, "team-10-phone-dialog.png"))

    b.close()

print("\nshots in %s" % SHOTS)
print(("FAILED: %d" % len(_fails)) if _fails else "all Team-door UI checks passed")
sys.exit(1 if _fails else 0)
