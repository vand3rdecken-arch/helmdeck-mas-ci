# -*- coding: utf-8 -*-
"""Screenshot the repo type picker + the pipeline, for the CLAUDE.md UI judgement.

A CAMERA, not a test: it drives the real web build against
ops/docs/shots/repo_pipeline_sandbox.py, so what gets judged is the payload the
daemon really serves for two repos that genuinely differ.

    py -3.12 ops/docs/shots/shoot_repo_pipeline.py --port 3869 --cfg <base64 {baseUrl,token}>

Shots, and why each one exists:
    repo-picker    the onboarding screen as it lands - the ONE question
    repo-docs      the document repo selected: deploy dashed, gate "runs empty"
    repo-code      the code repo: all five stations lit, deploy with a command
    map-general    the loop map with no repo - the general machine, unchanged
    map-docs       the loop map filtered to the document repo
    map-deploy     the deploy station TAPPED: the only switchable one, explained
    *-wide         1280px, re-judged for centering and measure
"""
import argparse
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "harness")

# (name, viewport, path, [testIDs to click])
SHOTS = [
    ("repo-picker",  (430, 932),  "/repo",    []),
    ("repo-docs",    (430, 932),  "/repo",    ["repo-TEXT"]),
    ("repo-code",    (430, 932),  "/repo",    ["repo-CODE"]),
    ("map-general",  (430, 932),  "/loopmap", []),
    ("map-docs",     (430, 932),  "/loopmap", ["maprepo-TEXT"]),
    ("map-deploy",   (430, 932),  "/loopmap", ["maprepo-TEXT", "station-deploy"]),
    ("repo-wide",    (1280, 1000), "/repo",   ["repo-TEXT"]),
    ("map-wide",     (1280, 1000), "/loopmap", ["maprepo-CODE", "station-deploy"]),
]

FIND_SCROLLER = """() => {
  const all = [...document.querySelectorAll('div')].filter(e => {
    const s = getComputedStyle(e);
    return /auto|scroll/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 40;
  });
  return all.length ? all.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] : null;
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="3869")
    ap.add_argument("--cfg", required=True, help="base64 {baseUrl,token}")
    # The repo testIDs are the PROJECT NAMES (the repo folder's basename), not
    # the paths: `[data-testid="C:\Users\..."]` reads \U as a CSS escape, so a
    # path-based selector matched 0 nodes and the first run of this script
    # photographed eight unclicked screens while reporting success.
    ap.add_argument("--code-repo", default="code-repo")
    ap.add_argument("--text-repo", default="text-repo")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright

    base = "http://localhost:%s" % a.port
    errors = []
    # The repo testIDs carry the real path, which is a temp dir that changes
    # every run - so the SHOTS table names them symbolically and they are
    # resolved here rather than hardcoded into a file that would rot.
    subst = {"CODE": a.code_repo, "TEXT": a.text_repo}

    def real(tid):
        for k, v in subst.items():
            if tid.endswith("-" + k):
                return tid[:-len(k)] + v
        return tid

    # DARK ONLY: _layout.tsx mounts <ThemeProvider name="dark"> at both call
    # sites, so a "light" pass would write a byte-identical second file.
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 430, "height": 932},
                             device_scale_factor=2, color_scheme="dark")
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        pg.goto("%s/#cfg=%s" % (base, a.cfg), wait_until="load", timeout=120000)
        pg.wait_for_timeout(9000)

        for name, vp, path, clicks in SHOTS:
            pg.set_viewport_size({"width": vp[0], "height": vp[1]})
            pg.goto("%s%s#cfg=%s" % (base, path, a.cfg), wait_until="load", timeout=120000)
            pg.wait_for_timeout(2500)
            # /loop/map takes ~6s (loop_state.transitions shells out to git) -
            # wait for the spinner to be GONE rather than guessing a duration.
            for _ in range(30):
                if pg.locator('[role="progressbar"], .css-progressbar').count() == 0:
                    break
                pg.wait_for_timeout(1000)
            pg.wait_for_timeout(2000)
            for tid in clicks:
                t = real(tid)
                loc = pg.locator('[data-testid="%s"]' % t)
                try:
                    if loc.count() != 1:
                        raise RuntimeError("matched %d nodes" % loc.count())
                    loc.first.click(timeout=8000)
                    pg.wait_for_timeout(1400)
                except Exception as e:                       # noqa: BLE001
                    errors.append("click(%s/%s): %s" % (name, t, str(e)[:160]))
            p = os.path.join(OUT, "%s.png" % name)
            pg.screenshot(path=p)
            print("wrote", os.path.relpath(p, os.path.dirname(HERE)).replace("\\", "/"))
        ctx.close()
        br.close()

    if errors:
        print("\n--- PAGE ERRORS (%d) ---" % len(errors))
        for e in dict.fromkeys(errors):
            print(" ", e[:300])
    else:
        print("\nno console/page errors")


if __name__ == "__main__":
    main()
