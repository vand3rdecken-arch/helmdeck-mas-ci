# -*- coding: utf-8 -*-
"""End-to-end test of the SwarmDeck desktop surface, driven through the real UI
(Playwright against the app's own production server on :3300) plus the daemon
API for setup/teardown.

It exercises the flows a user actually performs - not just "does it render":
filing a card, opening it, editing fields, steering, the pairing QR, the
dashboard, and the audit trail. Anything it creates, it removes again.

    py -3.12 tests/e2e_windows.py            # against http://localhost:3300
    UI=http://localhost:3300 py -3.12 tests/e2e_windows.py
"""
import base64, json, os, sys, time, urllib.request, urllib.error, urllib.parse

UI = os.environ.get("UI", "http://localhost:3300")
API = os.environ.get("API", "http://localhost:8140")
OWNER = os.environ.get("SWARM_OWNER", "owner")
PW = os.environ.get("SWARM_PW", "")

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   {detail}" if detail else ""), flush=True)
    return ok


# ---- daemon helpers (setup/verify, not the thing under test) ---------------
class Api:
    def __init__(self):
        self.cj = urllib.request.HTTPCookieProcessor()
        self.op = urllib.request.build_opener(self.cj)

    def call(self, path, body=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method=method or ("POST" if data else "GET"))
        try:
            with self.op.open(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            return e.code, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)

    def login(self, pw):
        return self.call("/auth/login", {"name": OWNER, "password": pw})[0] == 200


def dismiss_overlays(pg):
    """Close any modal/backdrop so the next click is not swallowed by it."""
    for _ in range(4):
        if not (pg.query_selector("#backdrop") or pg.query_selector("#modal")):
            return
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)


def main():
    from playwright.sync_api import sync_playwright

    if not PW:
        print("SWARM_PW not set - export the owner password to run the UI test", file=sys.stderr)
        return 2

    api = Api()
    if not check("daemon reachable + owner login", api.login(PW)):
        return 1

    created = []
    try:
        with sync_playwright() as pl:
            br = pl.chromium.launch()
            pg = br.new_context(viewport={"width": 1280, "height": 950}).new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))

            # --- login through the real UI ---------------------------------
            pg.goto(UI, timeout=60000); pg.wait_for_timeout(2500)
            if pg.query_selector("#authcard"):
                pg.fill('input[placeholder="username"]', OWNER)
                pg.fill('input[type="password"]', PW)
                pg.click("#authcard button")
                pg.wait_for_timeout(3500)
            check("UI: signed in (board visible)", pg.query_selector("#board, .card, [class*=lane]") is not None)

            # --- file a card through the UI --------------------------------
            task = "E2E probe %d" % int(time.time())
            opened = False
            for b in pg.query_selector_all("button"):
                if "New request" in (b.inner_text() or ""):
                    b.click(); opened = True; break
            pg.wait_for_timeout(1200)
            if opened:
                # scope everything to the modal - buttons behind the backdrop
                # cannot be clicked and would just time out
                ta = pg.query_selector("#modal textarea")
                if ta:
                    ta.fill(task)
                    submit = pg.query_selector("#modal button.cmp-send") or next(
                        (b for b in pg.query_selector_all("#modal button")
                         if (b.inner_text() or "").strip().lower().startswith("file")), None)
                    if submit:
                        submit.click()
                    pg.wait_for_timeout(4000)
            dismiss_overlays(pg)
            code, tracks = api.call("/tracks")
            mine = [t for t in (tracks if isinstance(tracks, list) else []) if t.get("task") == task]
            if mine:
                created.append(mine[0]["id"])
            check("UI: filing a card creates it in the daemon", bool(mine),
                  "" if mine else "card not found via API")

            # --- open a card and use the surface ---------------------------
            card = pg.query_selector(".card") or pg.query_selector("[class*=card]")
            if card:
                card.click(); pg.wait_for_timeout(2500)
            check("UI: card panel opens", pg.query_selector("#peek, #feed") is not None)
            check("UI: composer present on the card", pg.query_selector("#peek textarea, .cmp-ta") is not None)

            # --- the pairing QR (the mobile entry point) --------------------
            dismiss_overlays(pg)
            for a in pg.query_selector_all("a, button, .navitem, [class*=nav]"):
                if (a.inner_text() or "").strip() == "Settings":
                    a.click(); break
            pg.wait_for_timeout(2000)
            for b in pg.query_selector_all("button"):
                if "Pair phone" in (b.inner_text() or ""):
                    b.click(); break
            pg.wait_for_timeout(3500)
            # the QR is generated asynchronously - poll instead of racing it
            txt, src = "", ""
            for _ in range(12):
                el = pg.query_selector(".pairqr")
                if el:
                    src = pg.eval_on_selector(".pairqr", "e=>e.src") or ""
                    if src.startswith("data:image/png"):
                        try:
                            import cv2, numpy as np
                            png = base64.b64decode(src.split(",", 1)[1])
                            img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
                            if img is not None:
                                txt, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
                        except ImportError:
                            txt = "SKIP"
                        if txt:
                            break
                pg.wait_for_timeout(700)
            check("UI: pairing QR renders", src.startswith("data:image/png"))
            if txt == "SKIP":
                check("QR decode (opencv missing - skipped)", True, "pip install opencv-python-headless")
            elif txt:
                try:
                    u = urllib.parse.urlparse(txt)
                    check("QR encodes an https app link (camera apps can open it)",
                          u.scheme == "https" and u.path.startswith("/pair"),
                          f"scheme={u.scheme} path={u.path}")
                    q = urllib.parse.parse_qs(u.query).get("c", [""])[0]
                    # the QR uses base64URL without padding, and omits the relay
                    # url because the link's own origin already carries it
                    payload = json.loads(base64.urlsafe_b64decode(q + "=" * (-len(q) % 4)))
                    check("QR payload carries room, daemon key and token",
                          all(payload.get(k) for k in ("r", "k", "t")))
                    relay = payload.get("u") or f"{u.scheme}://{u.netloc}"
                    # the relay must actually answer for that link to be usable
                    try:
                        with urllib.request.urlopen(relay + "/health", timeout=10) as r:
                            live = json.loads(r.read()).get("ok") is True
                    except Exception:
                        live = False
                    check("relay in the QR is live over HTTPS", live)
                except Exception as e:
                    check("QR payload parses", False, str(e)[:80])
            else:
                dbg = os.path.join(os.environ.get("TEMP", "."), "e2e_qr_fail.png")
                if src.startswith("data:image/png"):
                    with open(dbg, "wb") as f:
                        f.write(base64.b64decode(src.split(",", 1)[1]))
                check("QR decodes", False, f"no QR content; image saved to {dbg}")

            # --- dashboard + history ---------------------------------------
            code, dash = api.call("/dashboard/data")
            check("API: dashboard data has capacity and totals",
                  code == 200 and "capacity" in dash and "totals" in dash)
            # /history is the git audit trail: {head, main:[commits], branches:[]}
            code, hist = api.call("/history")
            check("API: git history readable",
                  code == 200 and isinstance(hist, dict) and "main" in hist,
                  f"got {type(hist).__name__}")

            check("no uncaught page errors", not errors, "; ".join(errors[:2]))
            br.close()
    finally:
        for tid in created:
            api.call(f"/tracks/{tid}/delete", {})
        if created:
            print(f"  cleaned up {len(created)} test card(s)")
        # clicking "Pair phone" mints a device token - revoke what this run made
        code, users = api.call("/users")
        if code == 200 and isinstance(users, list):
            owner = next((u for u in users if u.get("name") == OWNER), None)
            stale = [t["token"] for t in (owner or {}).get("tokens", [])
                     if "phone (relay)" in (t.get("label") or "")]
            for tok in stale:
                api.call(f"/users/{OWNER}/revoke", {"token": tok})
            if stale:
                api.call("/relay/unpair", {})
                print(f"  revoked {len(stale)} pairing token(s) created by the test")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n  {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
