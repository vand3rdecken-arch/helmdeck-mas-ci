# -*- coding: utf-8 -*-
"""Records the "15-Sekunden-Demo-Clip" (owner backlog card): a card asks a
question, the phone answers, the card continues - against the REAL app UI
driven by Playwright, over ops/tools/demo_ask_daemon.py's sandbox.

Prereqs (three processes, same recipe as ops/tests/e2e_boards_ui.py, plus one
pip package for the mp4 encode - see the ffmpeg note below):
  py -3.12 -m pip install imageio-ffmpeg
  py -3.12 ops/tools/demo_ask_daemon.py 8199
  cd surfaces/app && npx expo start --web --port <web-port> --offline

  py -3.12 ops/tools/demo_ask_clip_record.py [web-port] [daemon-port]

Writes the finished clip to .loop/artifacts/demo-ask-reply-continue.mp4.
Named demo_* (not e2e_*) on purpose: this produces a marketing artifact, not
a pass/fail check, so ops/tools/run_gate.py has no reason to touch it.
"""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ARTIFACTS = os.path.join(ROOT, ".loop", "artifacts")
os.makedirs(ARTIFACTS, exist_ok=True)

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3956
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8199
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"
VIEWPORT = {"width": 390, "height": 844}          # phone-shaped, the point of the clip

CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

from playwright.sync_api import sync_playwright   # noqa: E402


def sign_in(page):
    """Verbatim recipe from ops/tests/e2e_boards_ui.py::sign_in - proven
    against this same login/ProfileGate flow, reused rather than reinvented."""
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill("owner")
            page.get_by_placeholder(pw_ph).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
    for _ in range(20):
        if "Sprache" not in page.inner_text("body") and "language" not in page.inner_text("body"):
            break
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(1500)


with sync_playwright() as p:
    browser = p.chromium.launch()

    # Pass 1 (not recorded): log in, capture the authenticated storage state.
    warm = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
    wp = warm.new_page()
    sign_in(wp)
    state = warm.storage_state()
    warm.close()

    # Pass 2 (RECORDED): a fresh context that opens straight into /chat
    # already authenticated - the clip should show the feature, not a login
    # form.
    video_dir = tempfile.mkdtemp(prefix="hd-askclip-")
    ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2,
                              storage_state=state,
                              record_video_dir=video_dir,
                              record_video_size=VIEWPORT)
    page = ctx.new_page()
    page.goto("http://127.0.0.1:%d/chat" % WEB, wait_until="domcontentloaded")

    # 1. THE CARD ASKS A QUESTION - wait for the real QuestionPanel to render
    # the mirrored card question (ops/tools/demo_ask_daemon.py seeded it).
    option = page.get_by_role("radio", name="Web-Push")
    option.wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(4000)   # let the question sit on screen, readable

    # 2. THE PHONE REPLIES - tap the option, then confirm.
    option.click()
    page.wait_for_timeout(1200)
    page.get_by_text("Antworten", exact=True).first.click()
    page.wait_for_timeout(500)

    # 3. THE CARD CONTINUES - the sandbox's faked steer() writes the result
    # line after a short "thinking" delay; wait for it to land live (no
    # reload), same long-poll pattern e2e_boards_ui.py proves for the board.
    seen = False
    for _ in range(20):
        page.wait_for_timeout(500)
        if "Web-Push eingerichtet" in page.inner_text("body"):
            seen = True
            break
    if not seen:
        print("WARNING: continuation line never appeared - clip will still "
              "show the ask+reply half only")
    page.wait_for_timeout(5000)   # hold on the finished state

    ctx.close()      # finalizes the .webm
    browser.close()

webm = [f for f in os.listdir(video_dir) if f.endswith(".webm")]
if not webm:
    sys.exit("no video was written to %s" % video_dir)
src = os.path.join(video_dir, webm[0])

# Playwright's own bundled ffmpeg is a minimal libvpx/webm-only build (no
# H.264, no mp4 muxer) - fine for its own trace viewer, useless for an actual
# .mp4 deliverable. imageio-ffmpeg ships a full static build with libx264.
import imageio_ffmpeg                              # noqa: E402
ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

dst = os.path.join(ARTIFACTS, "demo-ask-reply-continue.mp4")
subprocess.run([ffmpeg, "-y", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", dst], check=True,
              capture_output=True)

print("clip    : %s" % dst)
print("size    : %d bytes" % os.path.getsize(dst))
