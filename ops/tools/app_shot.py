# -*- coding: utf-8 -*-
"""ONE call to see an app route in a phone viewport - the "verified in the phone
viewport" step a card worker could not do in one call (analysis 20260929-132737:
recipe only in private memory, no node_modules in a worktree, only
feature-specific shot scripts).

    py -3.12 ops/tools/app_shot.py <route> [--offline]     e.g. /board, /card/d1

What it does, end to end: junctions the main repo's surfaces/app/node_modules
into this worktree (removed again with rmdir - NEVER rm -r, that would delete the
main repo's modules through the link), starts `expo start --web --offline`
detached on $HELMDECK_DEV_PORT, opens the route with Playwright at 430x932 with a
touch/mobile context, logged in via DEMO mode (the one way in without a paired
daemon), writes <worktree>/.shots/<route>.png plus <route>.txt (visible text),
stops the server, drops the junction and prints ONE line:
    route=/card/d1 text=1.2k chars shot=.shots/card-d1.png
--offline: after the first load the network is cut and the page gets a moment to
react - shows the offline state, not the initial load.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "surfaces" / "app"
SHOTS = ROOT / ".shots"


def _main_repo():
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    return (ROOT / out).resolve().parent


def _free_port():
    p = os.environ.get("HELMDECK_DEV_PORT")
    if p:
        return int(p)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _up(port):
    try:                                        # listening is enough; "/" may 500 while bundling
        socket.create_connection(("127.0.0.1", port), timeout=3).close()
        return True
    except OSError:
        return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: app_shot.py <route> [--offline]")
    route = args[0] if args[0].startswith("/") else "/" + args[0]
    offline = "--offline" in sys.argv
    SHOTS.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", route).strip("-") or "root"
    port = _free_port()

    link = APP / "node_modules"
    made_link = False
    if not link.exists():
        target = _main_repo() / "surfaces" / "app" / "node_modules"
        if not target.is_dir():
            sys.exit("no node_modules in the main repo at %s - run npm install there" % target)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
        made_link = True

    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        sys.exit("npx not on PATH (headless PATH has no node - prefix it)")
    log = open(SHOTS / "server.log", "w")
    srv = subprocess.Popen([npx, "expo", "start", "--web", "--offline", "--port", str(port)],
                           cwd=APP, stdout=log, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL,
                           env={**os.environ, "CI": "1", "BROWSER": "none"})
    try:
        deadline = time.time() + 240
        while not _up(port):
            if srv.poll() is not None or time.time() > deadline:
                sys.exit("expo did not come up - see .shots/server.log")
            time.sleep(2)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": 430, "height": 932}, device_scale_factor=2,
                                is_mobile=True, has_touch=True)
            ctx.add_init_script("localStorage.setItem('helmdeck.demo','1');")
            pg = ctx.new_page()
            pg.goto("http://localhost:%d%s" % (port, route), wait_until="domcontentloaded",
                    timeout=400000)
            pg.wait_for_timeout(8000)              # first bundle + demo data settle
            if offline:
                ctx.set_offline(True)
                pg.wait_for_timeout(4000)
            shot = SHOTS / (slug + ".png")
            pg.screenshot(path=str(shot))
            text = pg.inner_text("body")
            (SHOTS / (slug + ".txt")).write_text(text, encoding="utf-8")
            b.close()
        n = len(text)
        print("route=%s text=%s chars shot=%s%s" % (
            route, ("%.1fk" % (n / 1000.0)) if n >= 1000 else n,
            shot.relative_to(ROOT).as_posix(), " offline=yes" if offline else ""))
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(srv.pid)], capture_output=True)
        log.close()
        if made_link:
            os.rmdir(link)                         # rmdir only: drops the link, not the target


if __name__ == "__main__":
    main()
