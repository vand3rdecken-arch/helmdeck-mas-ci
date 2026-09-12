# -*- coding: utf-8 -*-
"""Drive the REAL glasses webapp at the lens's own 600x600, against a REAL
daemon, and photograph every state of the conversation.

WHY THIS EXISTS RATHER THAN A UNIT TEST. The card this was built for is a UX
card: the complaint was not "the endpoint is wrong", it was "I cannot see that
the glasses are listening, and I never see what I said". Both are claims about
PIXELS. ops/tests/test_glance_conversation.py proves the daemon publishes the
right facts; only this can show they arrive on the display, in the right place,
readable. CLAUDE.md is explicit: screenshot and JUDGE, do not just confirm
rendering.

The daemon is real (sandboxed to a temp dir, ephemeral port, never :8140) and the
webapp is the real three files served over HTTP - not a fixture, not a mock. The
only thing stubbed is copilot.chat, because a live model call would spend plan
quota to produce a sentence this test does not read.

Shots land in ops/docs/shots/glance-conversation/.

Run: py -3.12 ops/tests/e2e_glance_conversation.py
"""
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

SHOTS = os.path.join(ROOT, "ops", "docs", "shots", "glance-conversation")
TOKEN = "e2e-lens-token"

_fails = []


def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def _serve_static(directory):
    """The webapp on its own origin, exactly as the Worker serves it."""
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        def log_message(self, *a):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main():
    os.makedirs(SHOTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="helmdeck-e2e-lens-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from cells.copilot.chat import copilot
    copilot.ROOT = tmp

    db.init(role="tool")
    events.save_settings({"glance_token": TOKEN, "glance_talk": True,
                          "glance_decide": True})

    # THE ONE STUB. A real turn would spend plan quota on a sentence nothing
    # here reads - but everything around it stays real: the route, ask.parse,
    # the turn-state transitions, the transcript write, the lens's stream.
    def _fake_chat(user, msg, **kw):
        copilot._append_log(user, [
            {"cls": "you", "text": msg, "ts": "14:02"},
            {"cls": "bot", "text": "Two cards need you: a red gate and a "
                                   "delivered card waiting to be accepted.",
             "ts": "14:02"},
        ])
        return {"reply": "Two cards need you: a red gate and a delivered card "
                         "waiting to be accepted.",
                "question": {"questions": [{
                    "question": "What first?", "header": "Next",
                    "options": [
                        {"label": "Show the gate", "description": "the red one"},
                        {"label": "Accept delivered", "description": "hand it back"},
                        {"label": "Something else", "description": "ask wider"}]}]},
                "refused": []}
    copilot.chat = _fake_chat
    # edge-tts is optional and usually absent here; the lens must fall back to
    # text without erroring, which is also what this run exercises.
    from spine.media import voice
    voice.render = lambda text, voice_name="": None

    from spine.http import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    api_port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    static, web_port = _serve_static(os.path.join(ROOT, "surfaces", "glasses"))
    api = "http://127.0.0.1:%d" % api_port

    def post_state(state, mic="", text=""):
        body = json.dumps({"token": TOKEN, "state": state, "mic": mic,
                           "text": text}).encode()
        r = urllib.request.Request(api + "/glance/state", data=body,
                                   headers={"Content-Type": "application/json"})
        # The BODY, not just the status: a draft answers with the seq it was
        # published as, and the confirm step is addressed to that seq.
        return json.loads(urllib.request.urlopen(r, timeout=10).read() or b"{}")

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            # THE LENS'S OWN VIEWPORT. Judging this at any other size is how a
            # collision ships: 600x600 is the whole screen, there is no scroll
            # chrome, and the turnbar has to fit under a conversation.
            page = br.new_page(viewport={"width": 600, "height": 600})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append("console.error: " + m.text)
                    if m.type == "error" else None)

            page.goto("http://127.0.0.1:%d/" % web_port)
            # Connect the lens the way the owner does - the Connect screen.
            page.fill("#cfg-base", api)
            page.fill("#cfg-token", TOKEN)
            page.click('[data-action="save-settings"]')
            page.wait_for_timeout(1200)
            ok(not page.is_hidden("#home"), "the lens connects and lands on the board")
            page.screenshot(path=os.path.join(SHOTS, "01-home.png"))

            # ---- STATE 1: LISTENING, reported by the microphone's owner ------
            # This is the whole card. Nothing is tapped on the lens; the phone's
            # service says a mic is open, and the display must react on its own.
            post_state("listening", mic="glasses", text="")
            page.wait_for_timeout(1500)
            here = page.evaluate("document.querySelector('.screen:not(.hidden)').id")
            ok(here == "talk",
               "a mic opening PULLS the lens to the conversation - the owner "
               "never has to navigate to find out he is being heard")
            label = page.text_content("#turn-label")
            ok("Listening" in label, "the indicator says the word, not just a colour (%r)" % label)
            cls = page.get_attribute("#turnbar", "class")
            ok("listening" in cls, "the turnbar carries the listening state (%r)" % cls)
            mic = page.text_content("#turn-mic")
            ok("glasses" in (mic or ""),
               "WHICH mic is named - glasses vs phone is a real difference (8 kHz "
               "HFP vs A2DP), not decoration (%r)" % mic)
            page.screenshot(path=os.path.join(SHOTS, "02-listening.png"))

            # ---- STATE 2: the partial transcript, mid-sentence ---------------
            post_state("listening", mic="glasses", text="what is blocked right now")
            page.wait_for_timeout(1200)
            body = page.text_content("#talk-chat")
            ok("what is blocked right now" in body,
               "THE WORDS ARE ON THE DISPLAY while he is still speaking - the "
               "second half of the complaint this card was filed for")
            ok(page.locator(".msg.pending").count() == 1,
               "and they are marked as not-yet-sent, not mixed into the record")
            page.screenshot(path=os.path.join(SHOTS, "03-partial-transcript.png"))

            # ---- STATE 2b: THE DRAFT, waiting on him -------------------------
            # Owner, 2026-09-04: "wie auf watch erstmal per turn ... user kann
            # bestaetigen oder loeschen und neu sprechen". The recogniser has
            # finished; the words are NOT sent. Everything below is judged at the
            # lens's real 600x600 because that is where the decision is made.
            d = post_state("draft", mic="glasses",
                           text="wie viele karten warten gerade auf mich")
            draft_seq = d.get("seq")
            ok(isinstance(draft_seq, int) and draft_seq > 0,
               "the draft comes back with its own seq (%r)" % (draft_seq,))
            page.wait_for_timeout(1500)
            here = page.evaluate("document.querySelector('.screen:not(.hidden)').id")
            ok(here == "talk",
               "a draft PULLS the lens - words waiting on him must not sit on a "
               "screen he is not looking at")
            label = page.text_content("#turn-label")
            ok("Send this?" in label,
               "the bar asks the QUESTION rather than naming a state (%r)" % label)
            ok("draft" in (page.get_attribute("#turnbar", "class") or ""),
               "the turnbar carries the draft state")
            ok("wie viele karten warten gerade auf mich" in page.text_content("#talk-chat"),
               "HIS OWN WORDS are on the display, verbatim, before anything is sent")
            ok(page.locator(".msg.pending.draft").count() == 1,
               "and they are marked as a DRAFT - visually distinct from a line "
               "already on its way to Henry")

            # Exactly two ways forward, and no leftovers from the last answer.
            opts = page.locator("#talk-options .list-item")
            ok(opts.count() == 2,
               "a draft offers exactly two choices - accept or re-record (%d)" % opts.count())
            otext = page.text_content("#talk-options")
            ok("Send" in otext and "Speak again" in otext,
               "and they say what they do (%r)" % otext[:80])
            ok(page.locator('#talk-options .list-item.primary').count() == 1,
               "the affirmative one is the emphasised one - on an additive "
               "waveguide the dimmer row is the one ambient light eats")
            page.screenshot(path=os.path.join(SHOTS, "03b-draft-confirm.png"))

            # LAYOUT, measured: the buttons he must tap have to be ON the lens.
            dbox = page.evaluate("""() => {
              const rows = [...document.querySelectorAll('#talk-options .list-item')];
              const bar = document.getElementById('turnbar').getBoundingClientRect();
              return {last: rows.length ? rows[rows.length-1].getBoundingClientRect().bottom : 0,
                      first: rows.length ? rows[0].getBoundingClientRect().top : 0,
                      barTop: bar.top};
            }""")
            ok(dbox["last"] <= 600.5,
               "both choices fit inside the 600px lens (last row ends %.0f)" % dbox["last"])
            ok(dbox["first"] >= 0, "the first choice is not clipped off the top")

            # THE HANDOFF. A waiter is parked on /glance/decision exactly as the
            # phone service parks there; the owner taps Send on the LENS; the
            # phone must be woken with his verdict. This is the one link that
            # makes the confirm step more than a picture.
            got = {}

            def _wait_decision():
                try:
                    u = api + "/glance/decision?token=%s&seq=%d" % (TOKEN, draft_seq)
                    got["r"] = json.loads(urllib.request.urlopen(u, timeout=40).read())
                except Exception as e:                       # noqa: BLE001
                    got["r"] = {"error": str(e)}
            th = threading.Thread(target=_wait_decision)
            th.start()
            time.sleep(0.5)
            ok(th.is_alive(), "the phone's wait is HELD open, not answered empty")
            page.click('[data-action="talk-send"]')
            th.join(30)
            ok((got.get("r") or {}).get("decision") == "send",
               "tapping Send on the lens wakes the waiting microphone with "
               "'send' (%r)" % (got.get("r"),))
            ok(not errors, "no page errors during the confirm step: %r" % (errors[:3],))

            # ---- STATE 3: sent, Henry thinking -------------------------------
            # Driven through the REAL /glance/talk, so this is the actual
            # transition the daemon publishes, not a simulated one.
            page.evaluate("""(api) => {
                fetch(api + '/glance/talk', {
                  method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({token: '%s',
                                        message: 'what is blocked right now'})});
            }""" % TOKEN, api)
            page.wait_for_timeout(2000)
            page.screenshot(path=os.path.join(SHOTS, "04-answered.png"))

            chat = page.text_content("#talk-chat")
            ok("what is blocked right now" in chat,
               "his own line survives into the record")
            ok("Two cards need you" in chat, "Henry's answer lands in the same conversation")
            ok(page.locator(".msg.pending").count() == 0,
               "the pending line is CONSUMED, not duplicated, once the transcript carries it")
            ok(page.locator(".msg").count() >= 2, "both sides are on screen at once")
            state = page.text_content("#turn-label")
            ok("Answered" in state, "the turn reports answered (%r)" % state)

            # ---- STATE 4: the options are tappable ---------------------------
            #
            # THE REGRESSION THIS CASE EXISTS FOR. Note how the turn above was
            # driven: a bare fetch, the way GlassVoiceService on the PHONE posts
            # it - NOT through the lens's own talk(). That is the primary path
            # (the owner speaks; he does not tap), and on it the lens never sees
            # the /glance/talk response at all.
            #
            # The first run of this test failed here with 0 options, which was a
            # real hole and not a test artifact: the options were being read out
            # of that response, so every SPOKEN turn would have rendered the
            # conversation and the state and nothing to tap - on the one surface
            # that has no keyboard, and against GLASS_BRIEF's whole reason for
            # demanding options ("ending without that block strands him"). They
            # now ride the turn state, which every surface reads.
            opts = page.locator("#talk-options .list-item")
            ok(opts.count() == 3,
               "options reach the lens on a turn it did NOT start - the spoken "
               "path, which is the primary one (%d)" % opts.count())
            ok("Show the gate" in page.text_content("#talk-options"),
               "and they are the worker's own labels, verbatim")

            # ---- LAYOUT JUDGEMENT, measured rather than eyeballed ------------
            box = page.evaluate("""() => {
              const b = document.getElementById('turnbar').getBoundingClientRect();
              const s = document.getElementById('talk-scroll').getBoundingClientRect();
              return {barTop: b.top, barBottom: b.bottom, barH: b.height,
                      scrollBottom: s.bottom, h: window.innerHeight};
            }""")
            ok(box["barBottom"] <= 600.5,
               "the state indicator is INSIDE the 600px lens (bottom=%.0f)" % box["barBottom"])
            ok(box["scrollBottom"] <= box["barTop"] + 0.5,
               "the conversation does not run under the indicator - no collision "
               "(scroll ends %.0f, bar starts %.0f)" % (box["scrollBottom"], box["barTop"]))
            ok(box["barH"] >= 40, "the indicator is big enough to read at a glance (%.0fpx)" % box["barH"])

            # NO DARK FILL ON THE WAVEGUIDE. Black is transparent on this
            # display, so a status bar drawn as a dark rectangle is an invisible
            # one. The bar must be carried by bright pixels - a hairline and
            # text - not by a fill.
            fill = page.evaluate(
                "getComputedStyle(document.getElementById('turnbar')).backgroundColor")
            ok(fill in ("rgba(0, 0, 0, 0)", "transparent"),
               "the turnbar uses no fill - on an additive display a dark strip "
               "simply does not reach the eye (%r)" % fill)

            # Text contrast: the label must not be the 12px grey this repo's own
            # trap register says vanishes on the waveguide.
            size = page.evaluate(
                "parseFloat(getComputedStyle(document.getElementById('turn-label')).fontSize)")
            ok(size >= 15, "the state label is body-sized, not caption-sized (%.0fpx)" % size)

            # ---- STATE 5: the mic closes -------------------------------------
            post_state("idle")
            page.wait_for_timeout(1200)
            ok("Ready" in page.text_content("#turn-label"),
               "a closed mic CLEARS the indicator - it never keeps claiming to "
               "listen after the owner switched it off")
            ok(page.text_content("#turn-mic") == "",
               "and stops naming a microphone that is no longer open")
            page.screenshot(path=os.path.join(SHOTS, "05-idle.png"))

            # ---- the conversation survives navigation ------------------------
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            page.click('[data-action="talk-start"]')
            page.wait_for_timeout(2000)
            ok("Two cards need you" in page.text_content("#talk-chat"),
               "coming back to the conversation shows the WHOLE exchange - the "
               "lens is no longer a one-reply amnesiac")
            page.screenshot(path=os.path.join(SHOTS, "06-return.png"))

            ok(not errors, "no page errors or console errors: %s" % (errors[:3] or "none"))
            br.close()
    finally:
        httpd.shutdown()
        static.shutdown()

    print()
    print("shots -> %s" % SHOTS)
    if _fails:
        print("%d FAILED" % len(_fails))
        for f in _fails:
            print("  - " + f)
        return 1
    print("ALL LENS CONVERSATION E2E CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
