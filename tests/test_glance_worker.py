# -*- coding: utf-8 -*-
"""The Glance Worker must proxy FOUR paths to the daemon and nothing else.

Why this test carries real weight: glasses/worker/ is the first thing in this
repo that puts a door to the owner's daemon on the open internet. The daemon
behind it serves cards, settings, chat and driver commands. If the Worker ever
grows a generic pass-through - or if a path pattern turns out to be looser than
it reads - that entire surface is published behind one query-string token.

So this asserts the allowlist by EXECUTING the Worker's own routing function
(not by reading it), including the traversal and prefix-confusion attempts that
a regex written slightly wrong would wave through.

Self-sandboxed: no network, no daemon, no wrangler. If node is unavailable the
JS half is skipped and the source-level invariants still run, so the gate stays
honest on a box without node rather than silently passing on nothing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(ROOT, "glasses", "worker")
SRC = os.path.join(WORKER, "src", "index.js")
# The allowlist lives next door to the handler on purpose - the Workers runtime
# rejects a non-function named export from the ENTRY module, so these constants
# cannot sit in index.js. See glasses/worker/src/routes.js.
ROUTES = os.path.join(WORKER, "src", "routes.js")

fails = []
checks = 0


def check(cond, label):
    global checks
    checks += 1
    if cond:
        print("  ok  " + label)
    else:
        print("  FAIL " + label)
        fails.append(label)


# --------------------------------------------------------------------------
# 1. Source-level invariants - these run everywhere, node or not.
# --------------------------------------------------------------------------
check(os.path.exists(SRC), "worker source exists")
check(os.path.exists(ROUTES), "worker routing module exists")
src = open(SRC, encoding="utf-8").read() if os.path.exists(SRC) else ""

# The entry module must export ONLY the default handler. A named non-function
# export there is not a style question - workerd refuses to start:
# "Incorrect type for map entry 'MAX_BODY'". Found by running it, not reading it.
check(not re.search(r"^export\s+(const|let|var|function)\s", src, re.M),
      "entry module has no named exports (workerd rejects them)")
check("export default" in src, "entry module exports a default handler")

# The upstream fetch must live in exactly one place. More than one is how a
# second, unguarded path to the daemon gets added without anyone noticing.
check(len(re.findall(r"\bawait fetch\(", src)) == 1,
      "exactly ONE upstream fetch() in the worker")

# Credentials must be stripped going up (the daemon also authenticates the
# desktop UI by session cookie).
for h in ("cookie", "authorization"):
    check(('"%s"' % h) in src, "strips %r before proxying upstream" % h)

check('"set-cookie"' in src, "strips set-cookie coming back down")

# DAEMON_URL must fail CLOSED.
check("DAEMON_URL is not configured" in src, "unset DAEMON_URL fails closed")


# --------------------------------------------------------------------------
# 2. Behavioural invariants - execute the real routing function under node.
# --------------------------------------------------------------------------
# (path, method, expected) - expected None means "must NOT proxy".
CASES = [
    # the four legitimate routes
    ("/glance", "GET", "/glance"),
    ("/glance/answer", "POST", "/glance/answer"),
    ("/glance/talk", "POST", "/glance/talk"),
    ("/glance/voice/abc123.mp3", "GET", "/glance/voice/abc123.mp3"),

    # right path, wrong method
    ("/glance", "POST", None),
    ("/glance", "DELETE", None),
    ("/glance/answer", "GET", None),
    ("/glance/talk", "GET", None),
    ("/glance/voice/abc123.mp3", "POST", None),

    # the rest of the daemon must be unreachable
    ("/api/cards", "GET", None),
    ("/settings", "GET", None),
    ("/chat", "POST", None),
    ("/", "GET", None),
    ("/relay/pair", "POST", None),

    # the camera's landing point (added 2026-08-21) - POST only
    ("/glance/photo", "POST", "/glance/photo"),
    ("/glance/photo", "GET", None),
    ("/glance/photoX", "POST", None),
    ("/glance/photo/", "POST", None),

    # prefix confusion
    ("/glanceX", "GET", None),
    ("/glance/", "GET", None),
    ("/glance/answerX", "POST", None),
    ("/glance/voice", "GET", None),

    # traversal, in the raw form (the fetch handler also normalises first)
    ("/glance/../api/cards", "GET", None),
    ("/glance/voice/../../settings.mp3", "GET", None),
    ("//glance", "GET", None),

    # the audio id rule mirrors daemon/voice.py: alnum, <= 32 chars
    ("/glance/voice/.mp3", "GET", None),
    ("/glance/voice/" + "a" * 32 + ".mp3", "GET",
     "/glance/voice/" + "a" * 32 + ".mp3"),
    ("/glance/voice/" + "a" * 33 + ".mp3", "GET", None),
    ("/glance/voice/a-b.mp3", "GET", None),
    ("/glance/voice/a b.mp3", "GET", None),
    ("/glance/voice/sub/dir.mp3", "GET", None),
    ("/glance/voice/abc123.mp3.exe", "GET", None),
]

node = shutil.which("node")
if not node:
    print("  ..  node not found - JS execution skipped "
          "(source invariants above still ran)")
else:
    harness = (
        "const mod = await import(%s);\n"
        "const cases = %s;\n"
        "const out = cases.map(([p, m]) => mod.resolveRoute(p, m) ?? null);\n"
        "console.log(JSON.stringify({\n"
        "  out,\n"
        "  routes: Object.keys(mod.PROXY_ROUTES),\n"
        "  maxBody: mod.MAX_BODY,\n"
        "  photoCap: mod.maxBodyFor('/glance/photo'),\n"
        "  talkCap: mod.maxBodyFor('/glance/talk'),\n"
        "  unknownCap: mod.maxBodyFor('/glance/nope'),\n"
        "  protoCap: mod.maxBodyFor('constructor'),\n"
        "  normalised: new URL('https://x/glance/../api/cards').pathname,\n"
        "}));\n"
    ) % (
        json.dumps("file:///" + ROUTES.replace("\\", "/").lstrip("/")),
        json.dumps([[p, m] for p, m, _ in CASES]),
    )

    tmp = tempfile.mkdtemp(prefix="glance-worker-")
    try:
        hp = os.path.join(tmp, "probe.mjs")
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(harness)
        r = subprocess.run([node, hp], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            check(False, "node probe ran (stderr: %s)"
                  % (r.stderr or "").strip()[-300:])
        else:
            got = json.loads(r.stdout.strip().splitlines()[-1])

            for (path, method, want), actual in zip(CASES, got["out"]):
                label = "%-38s %-6s -> %s" % (
                    path[:38], method, want if want else "NOT proxied")
                check(actual == want, label)

            # The allowlist itself must stay inside /glance.
            check(all(k.startswith("/glance") for k in got["routes"]),
                  "every allowlisted route is under /glance")
            check(len(got["routes"]) == 4,
                  "exactly 4 exact-match routes (+1 regex for audio)")
            check(got["maxBody"] <= 128 * 1024, "default POST body cap is small")

            # THE PER-ROUTE CAP. /glance/photo carries an image, so it needs a
            # wide cap - but raising the GLOBAL one would let a 12 MB body be
            # posted to /glance/talk, straight into an agent prompt. The wide
            # cap must belong to exactly one route.
            check(got["photoCap"] == 12 * 1024 * 1024,
                  "/glance/photo cap is 12 MB (mirrors the daemon's pre-decode cap)")
            check(got["talkCap"] == got["maxBody"],
                  "/glance/talk keeps the SMALL default cap (not widened)")
            check(got["unknownCap"] == got["maxBody"],
                  "an unlisted path falls back to the small default")
            # hasOwnProperty guard: a bare `?? MAX_BODY` on a plain object would
            # let 'constructor' resolve to Object.prototype.constructor - a
            # truthy non-number - and a byteLength comparison against it is
            # always false, i.e. NO cap at all.
            check(got["protoCap"] == got["maxBody"],
                  "'constructor' does not inherit a cap from Object.prototype")

            # This is WHY the raw-traversal cases above are belt-and-braces:
            # the fetch handler matches on a parsed URL, which has already
            # collapsed the dot-segments.
            check(got["normalised"] == "/api/cards",
                  "URL parsing collapses ../ before routing sees it")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print("\n%d checks, %d failed" % (checks, len(fails)))
sys.exit(1 if fails else 0)
