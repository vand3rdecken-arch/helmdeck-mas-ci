# Analytics smoke: load the web build in demo mode, do tracked actions, and
# PROVE events leave the app by capturing the requests to eu.i.posthog.com.
# (Arrival in the dashboard is verified separately in the PostHog UI.)
import gzip
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3434"
events = []
statuses = []

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()

    def on_request(req):
        if "posthog.com" in req.url and req.method == "POST":
            try:
                raw = req.post_data_buffer or b""
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                batch = json.loads(raw.decode("utf-8")).get("batch", [])
                for e in batch:
                    events.append(e.get("event"))
                print("POSTHOG ->", req.url, [e.get("event") for e in batch])
            except Exception as ex:  # noqa: BLE001
                raw = req.post_data_buffer or b""
                print("POSTHOG ->", req.url, "(unparsed:", ex, "head:", raw[:24], ")")

    def on_response(resp):
        if "posthog.com" in resp.url:
            # the /batch/ 200 is the send-side proof (names are verified in the
            # PostHog Activity UI; the fetch body is a stream Playwright can't read)
            statuses.append((resp.status, "/batch/" in resp.url))
            print("POSTHOG <-", resp.status, resp.url)

    pg.on("request", on_request)
    pg.on("response", on_response)
    pg.goto(BASE, wait_until="networkidle", timeout=120_000)
    pg.evaluate("localStorage.setItem('helmdeck.demo','1')")
    pg.reload(wait_until="networkidle")
    time.sleep(3)

    # board chat -> chat_message (demo seam answers locally, no daemon needed)
    pg.goto(BASE + "/chat", wait_until="networkidle")
    time.sleep(2)
    box = pg.locator("textarea").first
    if box.count():
        box.fill("Analytics smoke ping")
        box.press("Enter")
        time.sleep(2)

    # posthog-react-native flushes on an interval; give it time, then force a
    # final flush by navigating (pagehide) and waiting again.
    time.sleep(12)
    pg.goto(BASE, wait_until="networkidle")
    time.sleep(8)
    pg.screenshot(path="../shots/analytics_smoke_web.png", full_page=False)

    # ---- opt-out phase: with the persisted preference off, NOTHING may send ----
    opted_out_batches = []
    pg2 = b.new_page()
    pg2.on("response", lambda r: opted_out_batches.append(r.url)
           if "/batch/" in r.url else None)
    pg2.goto(BASE, wait_until="networkidle", timeout=120_000)
    pg2.evaluate("localStorage.setItem('helmdeck.analytics','0');"
                 "localStorage.setItem('helmdeck.demo','1')")
    pg2.reload(wait_until="networkidle")
    time.sleep(15)
    b.close()
    if opted_out_batches:
        print("OPT-OUT LEAK:", opted_out_batches)
        sys.exit(1)
    print("opt-out: no batch sent - OK")

print("captured events:", events)
print("response statuses:", statuses)
if not any(s == 200 and is_batch for (s, is_batch) in statuses):
    print("NO accepted /batch/ POST - events not sent")
    sys.exit(1)
print("SMOKE PASS - batch accepted by eu.i.posthog.com")
