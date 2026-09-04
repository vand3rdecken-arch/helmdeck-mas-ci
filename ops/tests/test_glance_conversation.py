# -*- coding: utf-8 -*-
"""The lens's conversation surface: GET /glance/chat, POST /glance/state, and the
turn state that drives the listening indicator (spine/ops/glassturn.py).

WHAT THIS IS PROTECTING. The glasses voice loop already went to Henry, but it ran
past the lens: nothing on the display said a microphone was open (the only status
surface was the phone's foreground notification) and the recognised words were
never shown before being sent in the owner's name. The fix publishes the state of
the ONE conversation and lets the lens read it. The properties below are the ones
that make that safe and honest rather than merely working.

THE SECURITY PROPERTY WORTH READING FIRST: /glance/state authenticates with the
SHARED glance token, so it accepts exactly two words - "listening" and "idle",
the only two things the microphone's owner actually observes. A token that could
assert "answered" could paint a reply state the owner never got, which is the
very class of lie this whole surface exists to remove.

Self-sandboxing, same discipline as ops/tests/test_server_routes.py: db, auth,
events and copilot are ALL redirected to a temp dir BEFORE anything touches disk,
and the server binds 127.0.0.1:0 in a thread (never :8140, never serve()).

Run: py -3.12 ops/tests/test_glance_conversation.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []


def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-glance-conv-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    events.EV = os.path.join(tmp, "events.jsonl")
    # copilot derives its own paths from __file__ - the transcript this surface
    # READS lives there, so an unsandboxed run would serve the owner's real
    # Henry conversation into a test.
    from cells.copilot.chat import copilot
    copilot.ROOT = tmp
    copilot.SESS = os.path.join(tmp, "copilot_sessions.json")
    copilot.CHATLOG = os.path.join(tmp, "copilot_log.json")

    db.init(role="tool")
    auth.create_user("glance-owner", "s4ndb0x-pw", "owner")
    sid = auth.login("glance-owner", "s4ndb0x-pw")

    from spine.ops import glassturn
    from spine.http import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def req(method, path, body=None, cookie=None, expect=None, timeout=10):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = "sd_session=%s" % cookie
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        try:
            parsed = json.loads(data) if data else None
        except ValueError:
            parsed = None
        if expect is not None:
            ok(r.status == expect, "%s %s -> %d (want %d)" % (method, path, r.status, expect))
        return r.status, parsed

    try:
        # -- OFF BY DEFAULT ---------------------------------------------------
        # Same rule the rest of the /glance family follows: no glance_token
        # configured means the surface does not exist, not that it is open.
        req("GET", "/glance/chat", expect=403)
        req("POST", "/glance/state", {"state": "listening"}, expect=403)

        req("POST", "/settings", {"glance_token": "tok-conv-1"}, cookie=sid, expect=200)
        req("GET", "/glance/chat?token=wrong", expect=403)

        # -- THE READ ---------------------------------------------------------
        # First call carries no cursors, so it must answer IMMEDIATELY - that is
        # what makes the lens's first paint fast and what lets a reconnect
        # resynchronise without a special case.
        t0 = time.time()
        status, body = req("GET", "/glance/chat?token=tok-conv-1", expect=200)
        ok(time.time() - t0 < 5,
           "/glance/chat with no cursors answers at once (does not block)")
        ok(isinstance(body, dict) and "c" in body and "g" in body,
           "/glance/chat returns both cursors")
        ok(isinstance(body.get("turn"), dict) and body["turn"].get("state") == "idle",
           "a fresh daemon reports an idle turn, never a phantom 'listening'")
        ok(body.get("messages") == [],
           "an empty transcript is an empty list, not a placeholder line")

        # -- THE STATE REPORT NEEDS ITS OWN CONSENT ---------------------------
        # glance_talk gates the conversation; a listening indicator for a
        # conversation that cannot happen is noise. Note this is a FEATURE-FLAG
        # refusal with the correct token, not a token error - the two must stay
        # distinguishable or a misconfigured lens is undebuggable.
        status, body = req("POST", "/glance/state",
                           {"token": "tok-conv-1", "state": "listening"}, expect=403)
        ok(isinstance(body, dict) and "glance_talk" in (body.get("error") or ""),
           "/glance/state with a valid token but glance_talk off: names the switch")

        req("POST", "/settings", {"glance_talk": True}, cookie=sid, expect=200)

        # -- THE CLOSED VOCABULARY (the security property) --------------------
        for forbidden in ("answered", "thinking", "heard", "failed"):
            status, body = req("POST", "/glance/state",
                               {"token": "tok-conv-1", "state": forbidden}, expect=400)
            ok(isinstance(body, dict) and "listening" in (body.get("error") or ""),
               "a shared-token client may NOT assert %r - and the error names "
               "what is allowed" % forbidden)
        req("POST", "/glance/state",
            {"token": "tok-conv-1", "state": "'; DROP TABLE"}, expect=400)

        # -- LISTENING, END TO END --------------------------------------------
        before = db.current_glass_version()
        req("POST", "/glance/state",
            {"token": "tok-conv-1", "state": "listening", "mic": "glasses",
             "text": "how is the board"}, expect=200)
        snap = glassturn.snapshot()
        ok(snap["state"] == "listening", "a reported open mic becomes state=listening")
        ok(snap["mic"] == "glasses", "the mic the client named survives to the lens")
        ok(snap["text"] == "how is the board",
           "the partial transcript rides along - 'listening' with nothing under "
           "it is a spinner, not feedback")
        ok(db.current_glass_version() > before,
           "the glasses cursor moved, so a waiting lens is woken by the report "
           "itself rather than by a timer")

        # An unknown mic must not reach the display verbatim: the vocabulary is
        # closed on purpose (glassturn.MICS), because this value is rendered.
        req("POST", "/glance/state",
            {"token": "tok-conv-1", "state": "listening", "mic": "<script>"}, expect=200)
        ok(glassturn.snapshot()["mic"] == "",
           "an unrecognised mic name is dropped, never rendered")

        # -- THE TRIGGER LIVES ON THE GLASSES ---------------------------------
        # Owner, 2026-09-04: "warum ist der Knopf am Handy. Das geht nicht. Das
        # muss in Brille aktiviert werden." The lens cannot capture audio (the
        # webview denies all capture, measured on-device), so the phone stays the
        # Bluetooth radio - but it must stop being the BUTTON.
        status, body = req("GET", "/glance/wake?token=tok-conv-1", expect=200)
        ok(body.get("adopted") is True and isinstance(body.get("wake"), int),
           "a fresh mic owner ADOPTS the counter without consuming a wake meant "
           "for the instance before it (%r)" % (body,))
        cur = body["wake"]

        status, body = req("POST", "/glance/listen",
                           {"token": "tok-conv-1", "mic": "glasses"}, expect=200)
        ok(body.get("wake") == cur + 1,
           "tapping Speak on the LENS raises the wake counter (%r)" % (body,))

        # The parked phone is released by that tap - the whole point.
        status, body = req("GET", "/glance/wake?token=tok-conv-1&since=%d" % cur,
                           expect=200, timeout=40)
        ok(body.get("wake") == cur + 1 and body.get("mic") == "glasses",
           "the parked microphone is released by a tap on the glasses (%r)" % (body,))

        # A wake raised while the phone was mid-reconnect must not be lost: a
        # dropped wake reads to the owner as a dead button on his face.
        req("POST", "/glance/listen", {"token": "tok-conv-1", "mic": "glasses"}, expect=200)
        t0 = time.time()
        status, body = req("GET", "/glance/wake?token=tok-conv-1&since=%d" % (cur + 1),
                           expect=200, timeout=40)
        ok(time.time() - t0 < 3,
           "a wake raised before the phone re-armed is served IMMEDIATELY, not "
           "slept through (%.1fs)" % (time.time() - t0))

        # /glance/listen carries no text - it cannot inject anything.
        req("POST", "/glance/listen", {"token": "nope"}, expect=403)
        req("GET", "/glance/wake?token=nope&since=0", expect=403)

        # -- THE CONFIRM STEP -------------------------------------------------
        # Owner, 2026-09-04: "wie auf watch erstmal per turn ... user kann
        # bestaetigen oder loeschen und neu sprechen". The property that matters
        # is not that confirming works - it is that NOTHING is sent without a
        # confirmation, including when the owner never answers at all.
        status, body = req("POST", "/glance/state",
                           {"token": "tok-conv-1", "state": "draft",
                            "text": "  wie viele karten warten  ", "mic": "glasses"},
                           expect=200)
        draft_seq = body["seq"]
        snap = glassturn.snapshot()
        ok(snap["state"] == "draft" and snap["text"] == "wie viele karten warten",
           "a draft publishes the recognised words WITHOUT sending them")
        ok(draft_seq == snap["seq"],
           "the draft's own seq comes back, so the waiter can address THIS draft")

        # A draft with no words is a bug in the caller, not an empty screen.
        req("POST", "/glance/state",
            {"token": "tok-conv-1", "state": "draft", "text": "   "}, expect=400)

        # THE STALE-TAP CASE, and the reason the seq exists: a verdict meant for
        # an older draft must never release a newer one.
        status, body = req("POST", "/glance/decide",
                           {"token": "tok-conv-1", "decision": "send",
                            "seq": draft_seq + 99}, expect=409)
        ok("draft" in (body.get("error") or ""),
           "a verdict addressed to the wrong draft is refused, not silently applied")

        # Free text cannot ride in on this route - it selects among our words.
        req("POST", "/glance/decide",
            {"token": "tok-conv-1", "decision": "send now please", "seq": draft_seq},
            expect=400)

        # The long-poll BLOCKS while the owner reads, then returns his verdict.
        got = {}

        def _wait():
            got["r"] = req("GET", "/glance/decision?token=tok-conv-1&seq=%d" % draft_seq,
                           expect=200, timeout=40)
        th = threading.Thread(target=_wait)
        th.start()
        time.sleep(0.4)
        ok(th.is_alive(), "/glance/decision holds the request open instead of polling")
        req("POST", "/glance/decide",
            {"token": "tok-conv-1", "decision": "send", "seq": draft_seq}, expect=200)
        th.join(20)
        ok(got.get("r") and got["r"][1].get("decision") == "send",
           "the waiting microphone is woken with the owner's verdict")

        # FAILS CLOSED. The one property worth the whole design: when the owner
        # never answers, the words are DROPPED. A timeout that defaulted to
        # "send" would speak an unconfirmed sentence in his name - exactly what
        # the confirm step exists to prevent.
        seq_t = glassturn.draft("etwas das er nie bestaetigt hat")
        ok(glassturn.await_decision(seq_t, timeout=0.5) == "",
           "an undecided draft times out to NOTHING - never to 'send'")

        # A turn moving on under the waiter is an answer, not a hang.
        seq_s = glassturn.draft("wird gleich ueberholt")
        sup = {}
        th2 = threading.Thread(
            target=lambda: sup.setdefault("v", glassturn.await_decision(seq_s, timeout=20)))
        th2.start()
        time.sleep(0.3)
        glassturn.idle()          # the owner hit STOP on the phone
        th2.join(20)
        ok(sup.get("v") == "superseded",
           "a superseded draft wakes its waiter instead of stranding a thread")

        # /glance/decision is behind the same two gates as the rest of the surface.
        req("GET", "/glance/decision?token=nope&seq=1", expect=403)
        req("GET", "/glance/decision?token=tok-conv-1", expect=400)

        # -- THE HANGING READ -------------------------------------------------
        # Up-to-date cursors must BLOCK (that is what makes this a stream and not
        # a poll), and a stale one must return at once.
        status, body = req("GET", "/glance/chat?token=tok-conv-1", expect=200)
        c_now, g_now = body["c"], body["g"]
        t0 = time.time()
        status, body = req("GET", "/glance/chat?token=tok-conv-1&c=%d&g=%d" % (c_now, g_now),
                           expect=200, timeout=40)
        waited = time.time() - t0
        ok(waited > 5,
           "a caught-up client BLOCKS rather than spinning (waited %.1fs) - the "
           "'never ship a fast poll' rule holds by construction" % waited)

        t0 = time.time()
        req("GET", "/glance/chat?token=tok-conv-1&c=0&g=0", expect=200)
        ok(time.time() - t0 < 5, "a stale cursor is answered immediately")

        # A malformed cursor resynchronises instead of erroring - a lens stuck
        # retrying a 400 would be worse than one that simply catches up.
        t0 = time.time()
        req("GET", "/glance/chat?token=tok-conv-1&c=abc&g=", expect=200)
        ok(time.time() - t0 < 5, "a malformed cursor means 'I have nothing', not an error")

        # -- THE TRANSITIONS THE DAEMON OWNS ----------------------------------
        # These are the ones no client may assert, driven directly - they are
        # what /glance/talk calls at event time.
        glassturn.heard("  what is blocked  ")
        ok(glassturn.snapshot()["text"] == "what is blocked",
           "heard() trims - the lens shows the message, not the whitespace")
        glassturn.thinking()
        ok(glassturn.snapshot()["state"] == "thinking", "thinking() is observable")
        glassturn.answered()
        s = glassturn.snapshot()
        ok(s["state"] == "answered",
           "answered() is TERMINAL and is not called 'speaking' - whether the "
           "clip reached an ear is something this process never learns")
        ok(s["age"] is not None, "the snapshot carries an age, so a stale state is visible as stale")

        glassturn.listening(mic="phone", text="x" * 5000)
        ok(len(glassturn.snapshot()["text"]) <= glassturn.TEXT_MAX,
           "a runaway transcript is capped before it reaches a 600x600 lens")

        seq_a = glassturn.snapshot()["seq"]
        glassturn.idle()
        ok(glassturn.snapshot()["seq"] > seq_a,
           "every transition moves seq, so a client can tell a new turn from a re-render")

        # -- THE TRANSCRIPT IS THE SHARED ONE ---------------------------------
        # Written through copilot's own logger, then read back through the lens
        # route: this is the property that stops the glasses from keeping a
        # private conversation that can drift from the phone's and the watch's.
        copilot._append_log("owner", [
            {"cls": "you", "text": "what is blocked", "ts": "10:00"},
            {"cls": "bot", "text": "**Two** cards.\n```actions\nnoise\n```",
             "ts": "10:00"},
            {"cls": "tool", "text": "internal chrome nobody should read", "ts": "10:00"},
        ])
        status, body = req("GET", "/glance/chat?token=tok-conv-1&c=0&g=0", expect=200)
        msgs = body.get("messages") or []
        ok(len(msgs) == 2, "the lens reads the shared Henry transcript (chrome filtered)")
        ok(msgs[0]["mine"] is True and msgs[1]["mine"] is False,
           "who spoke survives the trip")
        ok("**" not in msgs[1]["text"],
           "markdown is stripped - a lens has no renderer, and literal '**' on "
           "the waveguide is the exact defect the watch already hit")
        ok("noise" not in msgs[1]["text"],
           "fenced machine syntax never reaches the display")
        ok(all("internal chrome" not in m["text"] for m in msgs),
           "an unknown transcript class is dropped, not shown as if Henry said it")

        # A non-dict entry in the log must cost one LINE, not the whole
        # transcript - the exact failure the watch route was hardened against.
        copilot._append_log("owner", ["a stray string", {"cls": "you", "text": "still here"}])
        status, body = req("GET", "/glance/chat?token=tok-conv-1&c=0&g=0", expect=200)
        ok(any(m["text"] == "still here" for m in (body.get("messages") or [])),
           "a malformed log entry does not take the transcript down with it")

    finally:
        httpd.shutdown()

    print()
    if _fails:
        print("%d FAILED" % len(_fails))
        for f in _fails:
            print("  - " + f)
        return 1
    print("ALL GLANCE CONVERSATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
