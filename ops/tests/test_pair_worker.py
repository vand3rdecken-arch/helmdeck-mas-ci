# -*- coding: utf-8 -*-
"""The Pair Worker must proxy ONE path and nothing else.

Mirrors test_glance_worker.py's own discipline exactly (same reasoning: this
is the second thing in this repo that puts a door to the owner's daemon on
the open internet) - execute the Worker's own routing function under plain
node rather than read the source, including the traversal and
prefix-confusion attempts a slightly-wrong regex would wave through.

Self-sandboxed: no network, no daemon, no wrangler. If node is unavailable
the JS half is skipped and the source-level invariants still run.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKER = os.path.join(ROOT, "surfaces", "relay", "pair_worker")
SRC = os.path.join(WORKER, "src", "index.js")
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
# 1. Source-level invariants - run everywhere, node or not.
# --------------------------------------------------------------------------
check(os.path.exists(SRC), "worker source exists")
check(os.path.exists(ROUTES), "worker routing module exists")
src = open(SRC, encoding="utf-8").read() if os.path.exists(SRC) else ""

check(not re.search(r"^export\s+(const|let|var|function)\s", src, re.M),
      "entry module has no named exports (workerd rejects them)")
check("export default" in src, "entry module exports a default handler")

check(len(re.findall(r"\bawait fetch\(", src)) == 1,
      "exactly ONE upstream fetch() in the worker")

for h in ("cookie", "authorization"):
    check(('"%s"' % h) in src, "strips %r before proxying upstream" % h)
check('"set-cookie"' in src, "strips set-cookie coming back down")
check("DAEMON_URL is not configured" in src, "unset DAEMON_URL fails closed")

# No ASSETS fallback here (unlike the glance worker) - this worker has no
# webapp to serve, so an unmatched path must 404, never fall through.
check("env.ASSETS" not in src, "no static-asset fallback - unmatched paths just 404")

# --------------------------------------------------------------------------
# 2. Behavioural invariants - execute the real routing function under node.
# --------------------------------------------------------------------------
CASES = [
    # the one legitimate route. NOT tested with a "?code=..." suffix here -
    # resolveRoute() is only ever called with a bare PATHNAME in production
    # (index.js's fetch handler strips the query via `new URL(...).pathname`
    # before calling it, same convention test_glance_worker.py's own CASES
    # follow) - see the separate query-string normalisation check below for
    # that half of the contract instead of feeding resolveRoute an input
    # shape it never actually receives.
    ("/relay/pair/claim", "GET", "/relay/pair/claim"),

    # right path, wrong method
    ("/relay/pair/claim", "POST", None),
    ("/relay/pair/claim", "DELETE", None),

    # the rest of the daemon must be unreachable - including the SIBLING
    # pairing route (/relay/pair/code is session-authenticated; this worker
    # strips Authorization, so it must never even attempt to proxy it)
    ("/relay/pair", "POST", None),
    ("/relay/pair/code", "POST", None),
    ("/relay/unpair", "POST", None),
    ("/glance", "GET", None),
    ("/api/cards", "GET", None),
    ("/settings", "GET", None),
    ("/chat", "POST", None),
    ("/", "GET", None),
    ("/auth/login", "POST", None),

    # prefix confusion
    ("/relay/pair/claimX", "GET", None),
    ("/relay/pair/claim/", "GET", None),
    ("/relay/pair/", "GET", None),
    ("/relay/pairXclaim", "GET", None),

    # traversal, in the raw form (the fetch handler also normalises first)
    ("/relay/pair/../pair/code", "POST", None),
    ("//relay/pair/claim", "GET", None),
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
        "  normalised: new URL('https://x/relay/pair/../pair/code').pathname,\n"
        "  queryStripped: new URL('https://x/relay/pair/claim?code=F5ZEK6').pathname,\n"
        "}));\n"
    ) % (
        json.dumps("file:///" + ROUTES.replace("\\", "/").lstrip("/")),
        json.dumps([[p, m] for p, m, _ in CASES]),
    )

    tmp = tempfile.mkdtemp(prefix="pair-worker-")
    try:
        hp = os.path.join(tmp, "probe.mjs")
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(harness)
        r = subprocess.run([node, hp], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, "probe script ran (%s)" % (r.stderr[:200] if r.returncode else "ok"))
        if r.returncode == 0:
            data = json.loads(r.stdout)
            check(data["routes"] == ["/relay/pair/claim"],
                  "PROXY_ROUTES is exactly {'/relay/pair/claim'} - %r" % data["routes"])
            check(data["maxBody"] == 0, "MAX_BODY is 0 (GET only, no body)")
            # WHATWG URL parsing collapses ../ before the fetch handler ever
            # sees the path - the raw-string traversal cases above test the
            # routing function directly; this confirms the platform-level
            # normalisation the real Worker also gets for free.
            check(data["normalised"] == "/relay/pair/code",
                  "WHATWG URL parsing normalises ../ - %r" % data["normalised"])
            check(data["queryStripped"] == "/relay/pair/claim",
                  "URL.pathname strips ?code=... before resolveRoute ever sees it - %r"
                  % data["queryStripped"])
            for (p, m, expected), got in zip(CASES, data["out"]):
                check(got == expected,
                      "%s %s -> %r (want %r)" % (m, p, got, expected))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("test_pair_worker: FAILED (%d/%d)" % (len(fails), checks))
    sys.exit(1)
print("test_pair_worker: PASS (%d checks)" % checks)
