# -*- coding: utf-8 -*-
"""The relay bridge's pull loop must never block on the public /health probe.

Measured 2026-09-19 12:17 + 12:18 (67 s apart = LOCAL_PROBE_TTL boundaries):
the loop sat 8-12 s inside _resolve_base while phone frames queued in the
relay ("frame waited 12.2s ... before the bridge pulled it") on an idle daemon.
Runs the REAL _resolve_base with the real cache; only _health is replaced by
a slow fake (public leg 3 s, like a tunnel hiccup). Proven to FAIL on the
pre-fix code (second call blocks 3 s). Run: py -3.12 ops/tests/test_bridge_probe_nonblocking.py
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from spine.comms import relay_client as rc

PUBLIC = "https://relay.example.test"
LOCAL = "http://127.0.0.1:%d" % rc.LOCAL_RELAY_PORT
INSTANCE = {"id": "inst-A"}
SLOW = {"s": 0.0}
def fake_health(url, timeout=3):
    if url == LOCAL:
        return {"ok": True, "instance": INSTANCE["id"]}
    time.sleep(SLOW["s"])                     # the public leg over the tunnel
    return {"ok": True, "instance": "inst-A"}
rc._health = fake_health

fails = 0
def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1

t = time.time(); base = rc._resolve_base(PUBLIC)
check(base == LOCAL, "first call proves loopback (%s)" % base)

# verdict now stale + tunnel slow: the loop must get its answer instantly
rc._base_cache["ts"] = 0.0
SLOW["s"] = 3.0
t = time.time(); base = rc._resolve_base(PUBLIC); dt = time.time() - t
check(base == LOCAL, "stale verdict is served as is")
check(dt < 0.5, "and served WITHOUT waiting for the public probe (%.2fs)" % dt)

# the background refresh lands and moves the timestamp
time.sleep(3.5)
check(time.time() - rc._base_cache["ts"] < 2.0, "background probe refreshed the verdict")

# a relay restart (new instance id, public no longer matches) is still noticed
INSTANCE["id"] = "inst-B"; SLOW["s"] = 0.0
rc._base_cache["ts"] = 0.0
rc._resolve_base(PUBLIC); time.sleep(0.5)
check(rc._base_cache["base"] == PUBLIC, "instance change flips the leg back to the public URL (%s)" % rc._base_cache["base"])

print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
