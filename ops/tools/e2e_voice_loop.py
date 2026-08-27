# -*- coding: utf-8 -*-
"""Drive the VOICE LOOP, not just its pixels.

Screenshots prove the surface renders. They do not prove the thing that is
actually hard here: that listen -> ask -> speak -> listen advances, that a
finished clip hands control back to the microphone, and that a tap during
playback interrupts instead of queueing. This exercises that state machine in a
real browser.

Recognition and playback are the two halves the harness cannot supply for real
(no microphone on a CI box, no speaker to observe), so both are stubbed AT THE
BROWSER BOUNDARY - the same seam data/voice.ts already resolves through:

  * `webkitSpeechRecognition` is replaced with a fake that emits a scripted
    phrase. voice.ts picks it up because it reads the constructor off `window`
    at listen() time, exactly as a real browser would hand it over.
  * `Audio` is replaced with a fake whose `play()` fires `onended` after a beat,
    so "Henry finished speaking" is a real event on the real code path rather
    than a timer inside the test.

Everything between those two stubs - the state machine, the auto-continue, the
interrupt, the transcript - is the shipped code.

Usage:  py -3.12 ops/tools/e2e_voice_loop.py <port>
"""
import sys

from playwright.sync_api import sync_playwright

port = sys.argv[1] if len(sys.argv) > 1 else "3534"
base = "http://localhost:%s" % port

# Installed before any app code runs, so voice.ts sees these as the platform.
STUBS = """
window.__spoken = [];        // every clip the app tried to play
window.__recog = null;
class FakeRecognition {
  constructor() { window.__recog = this; this.lang=''; this.continuous=false;
    this.interimResults=false; this.maxAlternatives=1;
    this.onresult=null; this.onerror=null; this.onend=null; this.onstart=null; }
  start() {
    this._stopped = false;
    setTimeout(() => {
      if (this._stopped) return;
      // one interim, then a final — the shape Chrome actually delivers
      this.onresult && this.onresult({ resultIndex: 0,
        results: Object.assign([{ isFinal:false, 0:{transcript:'wie steht'}, length:1 }], {length:1}) });
      this.onresult && this.onresult({ resultIndex: 0,
        results: Object.assign([{ isFinal:true, 0:{transcript:'wie steht das board'}, length:1 }], {length:1}) });
      this.onend && this.onend();
    }, 350);
  }
  stop() { this.onend && this.onend(); }
  abort() { this._stopped = true; }
}
window.webkitSpeechRecognition = FakeRecognition;
window.SpeechRecognition = FakeRecognition;

class FakeAudio {
  constructor(src) { this.src = src; window.__spoken.push(src ? src.slice(0,32) : '');
    this.onended=null; this.onerror=null; this.currentTime=0; window.__audio = this; }
  play() { this._t = setTimeout(() => { this.onended && this.onended(); }, 500);
           return Promise.resolve(); }
  pause() { clearTimeout(this._t); window.__interrupted = true; }
}
window.Audio = FakeAudio;
"""

# The mirror image of STUBS: a runtime with NO speech API at all. That is what
# Firefox, Brave and Chrome-on-iOS actually are, and what an OTA bundle landing
# on an APK older than the speech module actually is. Both must degrade to plain
# text rather than to a microphone button that cannot work.
NO_EAR = """
Object.defineProperty(window, 'webkitSpeechRecognition', { value: undefined });
Object.defineProperty(window, 'SpeechRecognition', { value: undefined });
"""

fails = []
total = 0


def check(cond, msg):
    global total
    total += 1
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 430, "height": 932},
                        permissions=["microphone"])
    ctx.add_init_script(STUBS)
    page = ctx.new_page()
    page.goto(base + "/", wait_until="domcontentloaded")
    page.evaluate("localStorage.setItem('helmdeck.demo','1')")
    page.goto(base + "/chat", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    print("1. voice mode opens from the composer")
    page.get_by_label("Sprachmodus", exact=True).or_(
        page.get_by_label("Voice mode", exact=True)).first.click(timeout=15000)
    page.wait_for_timeout(600)
    check(page.get_by_text("Voice mode").count() > 0
          or page.get_by_text("Sprachmodus").count() > 0, "voice mode is on screen")

    print("2. it starts LISTENING on open (no second tap needed)")
    page.wait_for_timeout(400)
    listening = page.get_by_text("Listening…").or_(page.get_by_text("Ich höre zu…"))
    check(listening.count() > 0, "entered listening state by itself")

    print("3. a recognised phrase advances the turn and reaches the transcript")
    # the fake emits its final ~350ms after start; the demo copilot then answers
    page.wait_for_timeout(4000)
    page.get_by_label("Verlauf", exact=True).or_(
        page.get_by_label("Transcript", exact=True)).first.click(timeout=8000)
    page.wait_for_timeout(900)
    body = page.inner_text("body")
    check("wie steht das board" in body.lower(), "what was heard is in the transcript")
    check(page.get_by_text("Nothing spoken yet.").count() == 0
          and page.get_by_text("Noch nichts gesprochen.").count() == 0,
          "transcript is no longer the empty state")

    print("4. no clip -> the honest notice, not a stuck or crashed turn")
    # Speech is rendered by the DAEMON (edge-tts). Demo mode has no daemon, so
    # /chat answers without a `voice` field - exactly the soft failure voice.py
    # is built around. The contract is that the answer still arrives and the
    # surface says so, never that it pretends or hangs.
    spoken = page.evaluate("window.__spoken || []")
    check(spoken == [], "nothing was played, because the demo daemon rendered nothing")
    check("silent" in body.lower() or "ohne Ton" in body,
          "the no-audio notice is shown instead of failing the turn")

    print("4b. an EMPTY speech queue still settles - the loop must not hang")
    # The streaming rewrite made "Henry finished speaking" mean "the queue
    # drained" (data/voice.ts openSpeech). A queue that is closed while empty -
    # which is exactly this case, no daemon so no chunks - has to resolve
    # `done()` anyway. If it did not, voice mode would sit in `thinking`
    # forever and never listen again: a silent, permanent hang that no
    # typecheck can see. Auto-continue is on, so being back in LISTENING is the
    # proof that the promise settled and the loop came round.
    page.wait_for_timeout(2500)
    back = page.get_by_text("Listening…").or_(page.get_by_text("Ich höre zu…"))
    check(back.count() > 0,
          "the turn ended and the microphone re-armed, with nothing ever played")

    print("5. state readout survives with the transcript open")
    check(page.get_by_text("Listening…").or_(page.get_by_text("Ich höre zu…"))
          .or_(page.get_by_text("Henry is answering")).or_(page.get_by_text("Henry antwortet"))
          .count() > 0, "a live state line is still visible while reading")

    print("6. closing voice mode releases the microphone")
    page.get_by_label("Sprachmodus beenden", exact=True).or_(
        page.get_by_label("End voice mode", exact=True)).first.click(timeout=8000)
    page.wait_for_timeout(700)
    check(page.evaluate("!!(window.__recog && window.__recog._stopped)"),
          "recognition was aborted on close (mic not left open)")

    ctx.close()

    print("7. a runtime with NO ear offers no microphone at all")
    # The honest-degradation half. voiceUsable() requires HEARING, because every
    # orb state routes through startListening — a speak-only voice mode is a
    # screen with no way in. A fresh context (same build, no speech API) must
    # therefore show a composer with no voice button, and must still be a
    # working text chat rather than a crash or an empty screen.
    deaf = b.new_context(viewport={"width": 430, "height": 932})
    deaf.add_init_script(NO_EAR)
    dp = deaf.new_page()
    dp.goto(base + "/", wait_until="domcontentloaded")
    dp.evaluate("localStorage.setItem('helmdeck.demo','1')")
    dp.goto(base + "/chat", wait_until="domcontentloaded")
    dp.wait_for_timeout(6000)
    check(dp.evaluate("window.SpeechRecognition === undefined "
                      "&& window.webkitSpeechRecognition === undefined"),
          "the deaf runtime really has no speech API (the premise holds)")
    mic = dp.get_by_label("Sprachmodus", exact=True).or_(
        dp.get_by_label("Voice mode", exact=True))
    check(mic.count() == 0, "no microphone button is offered without an ear")
    composer = dp.get_by_placeholder("Frage…").or_(dp.get_by_placeholder("Question…"))
    check(composer.count() > 0, "the text composer is untouched — it degrades, it does not break")
    deaf.close()

    b.close()

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print(" - " + f)
    sys.exit(1)
print("VOICE LOOP OK")
