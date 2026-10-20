"""The app sends ONLY sealed frames to the daemon's advertised LAN address.

Debt [android-cleartext-sealed-lan] (2026-10-20): Android's base config now
permits cleartext so the phone can reach the daemon's direct door on any
RFC1918 address. The guard that keeps that safe is in the app, not the OS:
the advertised address (data/direct.ts DirectPath) may only ever receive the
relay's own NaCl-sealed frame at /relay/direct. This pins it in the source:

  - directPath.usable() - the one place the advertised address leaves the
    state machine - is called exactly once, and its value goes to sendDirect;
  - sendDirect fetches exactly `${base}/relay/direct` and its body is
    {pub, cipher: seal(...)} - never a plain inner request, never a token;
  - no other fetch in surfaces/app/src builds a URL from directPath.

Run: py -3.12 ops/tests/test_app_lan_sealed_only.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "surfaces", "app", "src")
client = open(os.path.join(SRC, "data", "client.ts"), encoding="utf-8").read()

fails = 0


def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    fails += 0 if c else 1


uses = re.findall(r"directPath\.usable\(\)", client)
check(len(uses) == 1, "directPath.usable() is read in exactly one place (%d)" % len(uses))
m = re.search(r"const (\w+) = directPath\.usable\(\);", client)
var = m.group(1) if m else None
check(var is not None, "its value is bound to one name (%s)" % var)
if var:
    flows = re.findall(r"\b%s\b" % var, client)
    via_send = re.findall(r"sendDirect\(%s," % var, client)
    check(len(via_send) == 1 and len(flows) <= 4,
          "that address is only handed to sendDirect (%d uses, %d sendDirect)" % (len(flows), len(via_send)))

body = client[client.index("async function sendDirect"):client.index("const frameFor")]
fetches = re.findall(r"fetch\(([^,]+),", body)
check(fetches == ["`${base}/relay/direct`"], "sendDirect fetches exactly ${base}/relay/direct (%s)" % fetches)
check("cipher: seal(inner" in body and "pub: myPub" in body, "and sends only {pub, cipher: seal(inner, ...)}")
check("authHeaders" not in body and "Authorization" not in body, "no auth header travels outside the box")

others = []
for dp, dn, fn in os.walk(SRC):
    dn[:] = [d for d in dn if d != "node_modules" and not d.startswith(".")]
    for f in fn:
        if not f.endswith((".ts", ".tsx")) or "selftest" in f:
            continue
        p = os.path.join(dp, f)
        txt = open(p, encoding="utf-8").read()
        if p.endswith(os.path.join("data", "client.ts")):
            continue
        if re.search(r"directPath\.(url|usable)", txt):
            others.append(os.path.relpath(p, ROOT))
check(not others, "no other file reads the advertised address (%s)" % others)

print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
