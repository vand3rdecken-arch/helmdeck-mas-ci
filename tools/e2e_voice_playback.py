# -*- coding: utf-8 -*-
"""Prove the DAEMON->BROWSER audio contract with a real rendered clip.

The loop test (e2e_voice_loop.py) runs in demo mode, where no daemon exists and
so no speech is ever rendered - it can only prove the silent path. This proves
the other half, and it is the half with the actual risk in it: that the exact
bytes `voice.render_b64()` produces, wrapped in the exact `data:` URI
`data/voice.ts` builds, are playable by a real browser engine.

That contract is easy to get subtly wrong (wrong mime, wrong base64 padding, a
URI the engine silently refuses) and impossible to catch by reading. So this
renders a REAL clip through the real daemon module, hands it to real Chromium
exactly as the app does, and requires that it decode to a plausible duration and
fire `ended` - not merely that `play()` did not throw.

Usage:  py -3.12 tools/e2e_voice_playback.py
"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright                     # noqa: E402

from daemon.spine.media import voice                                # noqa: E402

PHRASE = "Der Deploy ist blockiert. Soll ich anfangen?"

clip = voice.render_b64(PHRASE)
if not clip:
    print("SKIP: edge-tts unavailable (offline?) - nothing to verify")
    sys.exit(0)

raw = base64.b64decode(clip["b64"])
print("rendered %d bytes, mime=%s, id=%s" % (len(raw), clip["mime"], clip["id"]))
if clip["mime"] != "audio/mpeg":
    # iOS's expo-audio matches the prefix `data:audio/` literally; a drift here
    # would fail on device only.
    print("FAIL: mime drifted to %r - the iOS base64 path keys off audio/*" % clip["mime"])
    sys.exit(1)

# built exactly as data/voice.ts speak() builds it
uri = "data:%s;base64,%s" % (clip["mime"], clip["b64"])

PROBE = """
async (uri) => {
  const el = new Audio(uri);
  const out = { ended: false, duration: 0, error: null };
  const done = new Promise((res) => {
    el.onended = () => { out.ended = true; res(); };
    el.onerror = () => { out.error = 'media error'; res(); };
    setTimeout(() => res(), 25000);
  });
  try {
    await el.play();
  } catch (e) {
    out.error = String(e);
    return out;
  }
  await done;
  out.duration = el.duration;
  return out;
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = b.new_page()
    page.goto("about:blank")
    res = page.evaluate(PROBE, uri)
    b.close()

print("browser: %r" % (res,))
if res.get("error"):
    print("FAIL: browser refused the clip: %s" % res["error"])
    sys.exit(1)
if not res.get("ended"):
    print("FAIL: playback never reached 'ended' - a voice loop would hang here")
    sys.exit(1)
dur = res.get("duration") or 0
if not (0.5 < dur < 30):
    print("FAIL: implausible decoded duration %.2fs" % dur)
    sys.exit(1)
print("PLAYBACK OK - decoded %.2fs and fired 'ended'" % dur)
