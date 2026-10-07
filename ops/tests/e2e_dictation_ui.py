# -*- coding: utf-8 -*-
"""STREAMING DICTATION end to end: the REAL composer in a REAL browser, a
getUserMedia stub playing a rendered German sentence, a sandbox daemon, the real
streaming manager and the real parakeet model. Only the microphone SOURCE is
synthetic; capture, resampling, chunking, the wire and the daemon are real.

What it proves (each one is a way dictation can look fine and be broken):
 1. TAP the mic -> the bar appears, chunks stream to /voice/dictation/chunk
    WHILE the audio plays (not after), insert puts the spoken words in the input
 2. the batch route /voice/transcribe is NOT used (that would be the fallback)
 3. HOLD = push-to-talk: releasing after a hold inserts without touching a button
 4. "insert and send" sends the dictated words through the real send path
    (POST /chat is intercepted - no model turn is paid for)
 5. cancel discards: no text, bar gone
 6. silence says so ("nothing understood") instead of inserting nothing silently
 7. stop -> text latency is measured and printed (the number streaming exists for)

Prereqs: the web bundle exported to %TEMP%/hd-dict-web
   (cd surfaces/app && node node_modules/expo/bin/cli export --platform web --output-dir <dir>)
Run: py -3.12 ops/tests/e2e_dictation_ui.py [web_dir]
Named e2e_* so ops/tools/run_gate.py skips it (needs ports + a browser).
"""
import functools
import http.server
import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WEB_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "hd-dict-web")
SHOTS = os.path.join(HERE, "_shots")
os.makedirs(SHOTS, exist_ok=True)
PW = "hunter2hunter2"
SAY = ("Verschiebe die Karte bitte auf Review und starte danach einen neuen Build für die App.")
KEYS = ("Karte", "Review", "App")
FAILS = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def make_wav(path, pcm16, lead=0.6, tail=1.5):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * lead) + pcm16 + b"\0\0" * int(16000 * tail))


def render_speech():
    sys.path.insert(0, ROOT)
    from ops.tools.dictation_stream_bench import render
    return render(SAY)


# ---- sandbox daemon -------------------------------------------------------
DPORT = free_port()
SANDBOX = tempfile.mkdtemp(prefix="hd-dictation-")
# The sandbox daemon prints one line per request. Into a FILE, never a PIPE: nothing
# here drains a pipe, and a full 64 KB pipe BLOCKS the daemon on its next print -
# every request then hangs ("Direktverbindung antwortet nicht") and the page
# never loads. (Measured 2026-10-07 after ~1,500 chunk requests; it looked like CPU
# contention for two runs.)
DLOG = os.path.join(SANDBOX, "daemon.log")
daemon = subprocess.Popen([sys.executable, os.path.join(HERE, "dictation_sandbox_daemon.py"),
                           str(DPORT), SANDBOX], stdout=open(DLOG, "w", encoding="utf-8"),
                          stderr=subprocess.STDOUT, text=True)
DAEMON = "http://127.0.0.1:%d" % DPORT


def api(method, path, body=None, token=None):
    r = urllib.request.Request(DAEMON + path, method=method,
                               data=json.dumps(body).encode() if body is not None else None)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode() or "{}")


try:
    for _ in range(80):
        try:
            api("GET", "/auth/state"); break
        except Exception:
            time.sleep(0.5)
    else:
        print(open(DLOG, encoding="utf-8").read()[-1500:] if daemon.poll() is not None else "daemon did not come up")
        sys.exit(2)
    TOKEN = api("POST", "/auth/login", {"name": "owner", "password": PW}).get("token", "")
    check(bool(TOKEN), "sandbox daemon is up and the owner logs in")

    # ---- web server -------------------------------------------------------
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def translate_path(self, path):
            p = super().translate_path(path.split("?")[0])
            if os.path.isfile(p) or os.path.isdir(p):
                return p
            if os.path.isfile(p + ".html"):
                return p + ".html"
            return os.path.join(WEB_DIR, "index.html")

    WPORT = free_port()
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", WPORT), functools.partial(Q, directory=WEB_DIR))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    WEB = "http://127.0.0.1:%d" % WPORT

    speech = render_speech()
    loud = os.path.join(tempfile.gettempdir(), "hd_dict_say.wav")
    quiet = os.path.join(tempfile.gettempdir(), "hd_dict_quiet.wav")
    make_wav(loud, speech, lead=0.3, tail=0.5)
    make_wav(quiet, b"\0\0" * 16000 * 3, lead=0, tail=0)
    secs = len(speech) / 32000.0
    print("spoken test sentence: %.1f s" % secs)

    CFG = json.dumps({"baseUrl": DAEMON, "token": TOKEN, "relayUrl": "", "room": "",
                      "daemonPub": "", "mySec": "", "myPub": ""})

    from playwright.sync_api import sync_playwright

    def session(p, wav):
        # The microphone is a getUserMedia STUB that plays the rendered sentence
        # from t=0 on every call (Chromium's fake device loops its file from
        # browser start, so each recording would begin at a random point of the
        # sentence). Everything downstream - the app's ScriptProcessor, the
        # resampling to 16 kHz, chunking, the wire, the daemon - is the real code.
        import base64
        wav_b64 = base64.b64encode(open(wav, "rb").read()).decode()
        stub = """(() => {
          const b64 = '%s';
          navigator.mediaDevices.getUserMedia = async () => {
            const ctx = new AudioContext();
            await ctx.resume();
            const u8 = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
            const buf = await ctx.decodeAudioData(u8.buffer.slice(0));
            const src = ctx.createBufferSource(); src.buffer = buf;
            const dst = ctx.createMediaStreamDestination();
            src.connect(dst); src.start();
            return dst.stream;
          };
        })();""" % wav_b64
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 430, "height": 900}, device_scale_factor=2,
                            permissions=["microphone"])
        ctx.set_default_timeout(60000)
        ctx.set_default_navigation_timeout(120000)
        page = ctx.new_page()
        page.add_init_script(stub)
        sent_audio = {}        # stream id -> {seq: pcm bytes}, exactly what the wire carried
        calls = {"audio": sent_audio, "chunk": [], "transcribe": 0, "chat": [], "start": 0, "finish": 0, "cancel": 0}
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def on_req(r):
            u = r.url
            if "/voice/dictation/chunk" in u:
                calls["chunk"].append(time.time())
                try:
                    import base64 as _b
                    j = json.loads(r.post_data or "{}")
                    sent_audio.setdefault(j["id"], {})[j["seq"]] = _b.b64decode(j["audio"])
                except Exception:
                    pass
            elif "/voice/dictation/start" in u:
                calls["start"] += 1
            elif "/voice/dictation/finish" in u:
                calls["finish"] += 1
            elif "/voice/dictation/cancel" in u:
                calls["cancel"] += 1
            elif "/voice/transcribe" in u:
                calls["transcribe"] += 1
        page.on("request", on_req)

        def on_resp(r):                      # how long the daemon's real cleanup call took
            if "/voice/dictation/clean" in r.url and r.request.method == "POST" and calls.get("real_clean"):
                try:
                    calls["clean_ms"] = r.json().get("ms")
                except Exception:
                    pass
        page.on("response", on_resp)

        def fake_chat(route):
            try:
                calls["chat"].append(json.loads(route.request.post_data or "{}"))
            except Exception:
                calls["chat"].append({})
            route.fulfill(status=200, content_type="application/json", body="{}")
        page.route("**/chat", lambda route: fake_chat(route) if route.request.method == "POST" else route.continue_())

        # Every dictation fires a cleanup call at the daemon, and a REAL one is a
        # 4-10 s model process that costs real quota. Only the dedicated cleanup
        # phase gets the real model (calls["real_clean"]); every other dictation
        # answers "unchanged" at once, so the other scenarios stay fast and free.
        calls["real_clean"] = False

        def fake_clean(route):
            if calls["real_clean"]:
                route.continue_()
                return
            try:
                body = json.loads(route.request.post_data or "{}")
            except Exception:
                body = {}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"text": body.get("text", ""), "changed": False, "skipped": "test", "ms": 0}))
        page.route("**/voice/dictation/clean", fake_clean)

        page.goto(WEB + "/", wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CFG)
        page.goto(WEB + "/chat", wait_until="domcontentloaded")
        # a brand-new sandbox user is asked the language once, before anything else
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=6000)
            page.wait_for_timeout(2000)
            page.goto(WEB + "/chat", wait_until="domcontentloaded")
        except Exception:
            pass
        page.wait_for_selector('[data-testid="composer-dictate"]', timeout=120000)
        page.wait_for_timeout(1500)
        return b, page, calls, errors

    def tap(page, sel, ms=90):
        """A human tap: press, ~90 ms, release. Playwright's click() presses and
        releases in the SAME tick, which skips Pressable's press-in - not a
        gesture any finger produces."""
        b = page.locator(sel).bounding_box()
        page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        page.mouse.down(); page.wait_for_timeout(ms); page.mouse.up()

    def word_dist(a, b):
        """Word-level edit distance, punctuation ignored. The model itself is
        not deterministic across slightly different audio - it sometimes drops a
        soft phrase ("einen neuen") or mishears "Build" in a one-piece decode too -
        so batch is NOT ground truth. Both texts are therefore scored against the
        sentence that was actually spoken."""
        import re as _re
        x, y = _re.findall(r"\w+", a.lower()), _re.findall(r"\w+", b.lower())
        d = list(range(len(y) + 1))
        for i in range(1, len(x) + 1):
            prev, d[0] = d[0], i
            for j in range(1, len(y) + 1):
                cur = d[j]
                d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (x[i - 1] != y[j - 1]))
                prev = cur
        return d[len(y)]

    def batch_of(calls, which=-1):
        """Decode, in one piece, the audio the LAST stream really carried. This is
        the property streaming must keep: same audio in -> same words out."""
        sys.path.insert(0, ROOT)
        os.environ["HELMDECK_DATA_ROOT"] = SANDBOX
        from spine.media import stt
        sid = list(calls["audio"])[which]
        parts = calls["audio"][sid]
        return stt.transcribe_pcm16(b"".join(parts[k] for k in sorted(parts)))

    def field(page):
        return page.locator("textarea").first

    def read(page):
        return field(page).input_value()

    def clear(page):
        f = field(page); f.click(); f.fill("")

    with sync_playwright() as p:
        # ===== 1+2+7: tap, talk, insert ====================================
        print("\n[tap -> talk -> insert]")
        b, page, calls, errors = session(p, loud)
        calls["real_clean"] = True          # this ONE dictation gets the real cleanup model
        tap(page, '[data-testid="composer-dictate"]')
        page.wait_for_selector('[data-testid="dictation-bar"]', timeout=15000)
        check(True, "tapping the mic opens the dictation bar")
        t_start = time.time()
        page.wait_for_timeout(2600)                          # mid-sentence: judge the meter + partial
        page.screenshot(path=os.path.join(SHOTS, "dictation-recording-mid.png"))
        page.wait_for_timeout(int((secs + 1.2) * 1000) - 2600)
        n_live = len(calls["chunk"])
        check(n_live >= int(secs) - 1, "chunks were sent WHILE talking (%d chunks in %.1f s)" % (n_live, secs + 0.9))
        sub = page.inner_text('[data-testid="dictation-sub"]')
        print("   partial shown while talking: %r" % sub)
        page.screenshot(path=os.path.join(SHOTS, "dictation-recording.png"))
        t0 = time.time()
        page.click('[data-testid="dictation-insert"]')
        page.wait_for_function("document.querySelector('textarea') && document.querySelector('textarea').value.length > 5",
                               timeout=30000)
        lat = (time.time() - t0) * 1000
        txt = read(page)
        print("   text: %r   stop->text %.0f ms" % (txt, lat))
        check(all(k.lower() in txt.lower() for k in KEYS), "the spoken words are in the input: %r" % txt)
        b1 = batch_of(calls)
        check(word_dist(txt, SAY) <= word_dist(b1, SAY) + 1, "streaming text is no worse than a one-piece decode of the SAME audio, both against the real sentence (stream %d word errors, batch %d: %r | %r)" % (word_dist(txt, SAY), word_dist(b1, SAY), txt, b1))
        check(calls["transcribe"] == 0, "the BATCH route was not used (streaming path)")
        check(calls["finish"] == 1 and calls["start"] == 1, "one stream: start=%d finish=%d" % (calls["start"], calls["finish"]))
        check(page.locator('[data-testid="dictation-bar"]').count() == 0, "the bar is gone after insert")

        # ===== cleanup phase: raw text first, cleaned version swaps in later ==========
        print("\n[cleanup after insert]")
        # the raw transcript is what was read the moment it was inserted (`txt`):
        # by now the daemon may already have swapped the cleaned version in (the
        # checks above - a one-piece decode of the same audio - take seconds too)
        raw_in = txt
        t_clean = time.time()
        shown_working = False
        for _ in range(120):                                  # up to ~60 s: a cold CLI spawn is 5-11 s
            if page.locator('[data-testid="dictation-cleaning"]').count():
                shown_working = True
            if page.locator('[data-testid="dictation-cleaned"]').count() or (
                    shown_working and not page.locator('[data-testid="dictation-cleaning"]').count()):
                break
            page.wait_for_timeout(500)
        after = read(page)
        swapped = page.locator('[data-testid="dictation-cleaned"]').count() == 1
        print("   raw    : %r\n   after  : %r   (%.1f s, swapped=%s)" % (raw_in, after, time.time() - t_clean, swapped))
        check(shown_working or swapped, "the 'tidying up' state showed while the daemon worked")
        check(len(after) > 10, "the field still holds the dictation after the cleanup phase")
        if swapped:
            # A small model is NOT exact on an ambiguous misheard word ("Bird" has come
            # back as "Branch" - a plausible sentence, and wrong). What must hold is
            # that it changed the word, kept the rest, and that undo (checked below)
            # gives the raw text back exactly.
            check(after != raw_in and len(after.split()) == len(raw_in.split()),
                  "the misheard word was replaced and the rest kept: %r" % after)
            print("   the daemon's cleanup call took %s ms" % calls.get("clean_ms"))
            check(calls.get("clean_ms") is not None and calls["clean_ms"] < 4000,
                  "the cleanup was fast: %s ms (a cold one-shot took 4,000-11,000 ms)" % calls.get("clean_ms"))
            page.screenshot(path=os.path.join(SHOTS, "dictation-cleaned.png"))
            page.click('[data-testid="dictation-undo"]')
            page.wait_for_timeout(400)
            check(read(page) == raw_in, "undo restores the raw transcript exactly: %r" % read(page))
            check(page.locator('[data-testid="dictation-cleaned"]').count() == 0, "the 'tidied up' strip is gone after undo")
        else:
            print("   (daemon returned the text unchanged - nothing to swap, which is also valid)")
        calls["real_clean"] = False         # every later dictation: instant "unchanged", no model load
        page.screenshot(path=os.path.join(SHOTS, "dictation-inserted.png"))
        check(not errors, "no JS exceptions: %s" % errors[:2])

        # ===== 3: hold = push to talk ======================================
        print("\n[hold = push-to-talk]")
        clear(page)
        box = page.locator('[data-testid="composer-dictate"]').bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.wait_for_selector('[data-testid="dictation-bar"]', timeout=15000)
        page.wait_for_timeout(int((secs + 1.2) * 1000))
        t0 = time.time()
        page.mouse.up()
        page.wait_for_function("document.querySelector('textarea') && document.querySelector('textarea').value.length > 5",
                               timeout=30000)
        lat2 = (time.time() - t0) * 1000
        txt = read(page)
        print("   text: %r   release->text %.0f ms (warm model)" % (txt, lat2))
        check(all(k.lower() in txt.lower() for k in KEYS), "release after a hold inserts the words: %r" % txt)
        b2 = batch_of(calls)
        check(word_dist(txt, SAY) <= word_dist(b2, SAY) + 1, "hold run: streaming text is no worse than a one-piece decode of the SAME audio, both against the real sentence (stream %d word errors, batch %d: %r | %r)" % (word_dist(txt, SAY), word_dist(b2, SAY), txt, b2))
        check(lat2 < 3000, "warm stop->text under 3 s (%.0f ms; browser + daemon share this CPU)" % lat2)
        print("   first (cold) %.0f ms  vs warm %.0f ms" % (lat, lat2))

        # a SHORT tap must not end the recording it just began
        clear(page)
        tap(page, '[data-testid="composer-dictate"]')
        page.wait_for_timeout(1500)
        check(page.locator('[data-testid="dictation-bar"]').count() == 1, "a short tap keeps recording (tap-to-lock)")
        page.wait_for_timeout(2500)
        tap(page, '[data-testid="composer-dictate"]')          # the mic is also the stop button
        page.wait_for_function("document.querySelector('textarea') && document.querySelector('textarea').value.length > 3",
                               timeout=30000)
        check(page.locator('[data-testid="dictation-bar"]').count() == 0 and len(read(page)) > 3,
              "tapping the mic again ends the recording and inserts what was said: %r" % read(page))
        clear(page)

        # ===== 5: cancel ===================================================
        print("\n[cancel]")
        tap(page, '[data-testid="composer-dictate"]')
        page.wait_for_selector('[data-testid="dictation-bar"]', timeout=15000)
        page.wait_for_timeout(1500)
        page.click('[data-testid="dictation-cancel"]')
        page.wait_for_timeout(800)
        check(page.locator('[data-testid="dictation-bar"]').count() == 0, "cancel closes the bar")
        check(read(page) == "", "cancel inserts nothing")
        check(calls["cancel"] >= 1, "cancel told the daemon (%d)" % calls["cancel"])

        # ===== 4: insert and send ==========================================
        print("\n[insert and send]")
        tap(page, '[data-testid="composer-dictate"]')
        page.wait_for_selector('[data-testid="dictation-bar"]', timeout=15000)
        page.wait_for_timeout(int((secs + 1.2) * 1000))
        page.click('[data-testid="dictation-send"]')
        for _ in range(60):
            if calls["chat"]:
                break
            page.wait_for_timeout(500)
        if not calls["chat"]:      # diagnose instead of guessing: what is the page showing?
            print("   DIAG no POST /chat after 30 s: bar=%d sub=%r textarea=%d cleaning=%d cleaned=%d note=%d errors=%s" % (
                page.locator('[data-testid="dictation-bar"]').count(),
                (page.inner_text('[data-testid="dictation-sub"]') if page.locator('[data-testid="dictation-sub"]').count() else None),
                page.locator("textarea").count(), page.locator('[data-testid="dictation-cleaning"]').count(),
                page.locator('[data-testid="dictation-cleaned"]').count(), page.locator('[data-testid="dictation-note"]').count(),
                errors[:2]))
            page.screenshot(path=os.path.join(SHOTS, "dictation-send-diag.png"))
        sent = (calls["chat"][0].get("text") if calls["chat"] else "") or ""
        check(all(k.lower() in sent.lower() for k in KEYS), "the arrow sent the dictated words via POST /chat: %r" % sent)
        check(read(page) == "", "the input is cleared after the send")
        b.close()

        # ===== 6: silence ==================================================
        print("\n[silence]")
        b, page, calls, errors = session(p, quiet)
        tap(page, '[data-testid="composer-dictate"]')
        page.wait_for_selector('[data-testid="dictation-bar"]', timeout=15000)
        page.wait_for_timeout(2200)
        page.click('[data-testid="dictation-insert"]')
        try:
            page.wait_for_selector('[data-testid="dictation-note"]', timeout=30000)
        except Exception:
            print("   DIAG silence: bar=%d sub=%r textarea=%d value=%r errors=%s" % (
                page.locator('[data-testid="dictation-bar"]').count(),
                (page.inner_text('[data-testid="dictation-sub"]') if page.locator('[data-testid="dictation-sub"]').count() else None),
                page.locator("textarea").count(),
                (read(page) if page.locator("textarea").count() else None), errors[:2]))
            page.screenshot(path=os.path.join(SHOTS, "dictation-silence-diag.png"))
            raise
        note = page.inner_text('[data-testid="dictation-note"]')
        check(True, "silence is reported instead of inserting nothing silently: %r" % note)
        check(read(page) == "", "silence inserts no text (no hallucinated words)")
        b.close()

        # ===== 8: a device WITHOUT our mic (iOS, an old APK, a locked-down browser) =====
        # There the OS keyboard's own dictation key is the voice input, so the
        # composer must simply be a normal one: no dead mic button, no empty
        # gap, typing and sending unchanged.
        print("\n[no streaming mic available]")
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 430, "height": 900}, device_scale_factor=2)
        ctx.set_default_timeout(60000)
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'mediaDevices', {value: undefined, configurable: true});")
        sent_plain = []
        page.route("**/chat", lambda r: (sent_plain.append(json.loads(r.request.post_data or "{}")),
                                         r.fulfill(status=200, content_type="application/json", body="{}"))
                   if r.request.method == "POST" else r.continue_())
        page.goto(WEB + "/", wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CFG)
        page.goto(WEB + "/chat", wait_until="domcontentloaded")
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=6000)
            page.wait_for_timeout(2000)
            page.goto(WEB + "/chat", wait_until="domcontentloaded")
        except Exception:
            pass
        page.wait_for_selector("textarea", timeout=120000)
        page.wait_for_timeout(1500)
        check(page.locator('[data-testid="composer-dictate"]').count() == 0,
              "no mic API -> no dictation button (nothing that refuses)")
        page.locator("textarea").first.fill("hallo henry")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(SHOTS, "dictation-unavailable.png"))
        page.click('[data-testid="composer-send"]')
        for _ in range(20):
            if sent_plain:
                break
            page.wait_for_timeout(300)
        check(bool(sent_plain) and sent_plain[0].get("text") == "hallo henry",
              "typing and sending work exactly as before: %r" % (sent_plain[:1],))
        b.close()

finally:
    daemon.terminate()

print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
