# -*- coding: utf-8 -*-
"""Adversarial tests for the deterministic pairing lifecycle
(daemon/relay_client.py: _admit / pairing_payload / unpair) and the relay's
idle-room GC. SELF-SANDBOXING: events.SET/EV are redirected into a temp dir
before anything runs - the real settings.json is never read or written.

Run: py -3.12 ops/tests/test_pairing_lifecycle.py
"""
import os, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spine.storage import events  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="helmdeck-pairtest-")
events.SET = os.path.join(_TMP, "settings.json")
events.EV = os.path.join(_TMP, "events.jsonl")

from spine.comms import relay_client as rc  # noqa: E402  (after the sandbox redirect)

FAILS = []


def check(name, cond, note=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" - " + note) if note else ""))
    if not cond:
        FAILS.append(name)


def reset(relay_patch=None):
    if os.path.exists(events.SET):
        os.remove(events.SET)
    if relay_patch:
        events.save_settings({"relay": relay_patch})


# 1. Unknown device, no code ever issued -> refused, with an actionable reason.
reset()
ok, reason = rc._admit("PUB-A")
check("unknown-device-no-window refused", not ok and "not paired" in reason, reason)

# 2. Issue a code -> exactly ONE new device gets in; the window is consumed.
reset()
pay = rc.pairing_payload()
check("payload has room+key+ttl", bool(pay["room"]) and bool(pay["daemon_pub"])
      and pay["expires_in"] == rc.PAIR_TTL)
ok, _ = rc._admit("PUB-A")
check("first device inside window admitted", ok)
ok, reason = rc._admit("PUB-B")
check("second device after consumption refused", not ok and "not paired" in reason, reason)
ok, _ = rc._admit("PUB-A")
check("pinned device stays admitted (persists)", ok)

# 3. Re-issuing a code must NOT drop the pinned device (old bug: issuance
#    cleared the pin and whichever device spoke first re-pinned).
rc.pairing_payload()
ok, _ = rc._admit("PUB-A")
check("pinned device survives new code issuance", ok)
ok, _ = rc._admit("PUB-B")
check("new code admits a second device", ok)
_, _, _, pubs = rc._cfg()
check("both devices pinned, order stable", pubs == ["PUB-A", "PUB-B"], str(pubs))

# 4. Expired window -> refused with 'expired', and the stale window is cleared.
reset({"sk": "x", "room": "r", "pair_pending": {"expires": time.time() - 1}})
ok, reason = rc._admit("PUB-C")
check("expired window refused", not ok and "expired" in reason, reason)
check("stale window cleared", not (events.settings()["relay"].get("pair_pending")))

# 5. Garbage pair_pending must not crash admission.
reset({"sk": "x", "room": "r", "pair_pending": {"expires": "garbage"}})
ok, reason = rc._admit("PUB-C")
check("garbage window refused, no crash", not ok, reason)

# 6. Legacy install (only phone_pub set) keeps working and migrates to the list.
#    (sk left empty: pairing_payload generates a real keypair on demand.)
reset({"room": "r", "phone_pub": "LEGACY"})
ok, _ = rc._admit("LEGACY")
check("legacy phone_pub still admitted", ok)
rc.pairing_payload()
rc._admit("PUB-NEW")
rel = events.settings()["relay"]
check("legacy stays push target ([0] mirrored)",
      rel["phone_pubs"][0] == "LEGACY" and rel["phone_pub"] == "LEGACY", str(rel["phone_pubs"]))

# 7. No cap on total paired devices: each one still needs its OWN fresh
#    owner-issued single-use code (the real boundary, checked in steps 1-5),
#    so admitting many in a row is safe and none are refused for "over limit".
reset()
N = 12   # comfortably past the old MAX_DEVICES=8 to prove the cap is gone
for i in range(N):
    rc.pairing_payload()
    ok, reason = rc._admit("PUB-%d" % i)
    check("device %d admitted (no cap)" % i, ok, reason)
pubs = events.settings()["relay"]["phone_pubs"]
check("all %d devices pinned" % N, len(pubs) == N, str(len(pubs)))

# 8. Concurrency: the same new device racing itself pins exactly once.
reset()
rc.pairing_payload()
results = []
threads = [threading.Thread(target=lambda: results.append(rc._admit("PUB-RACE")))
           for _ in range(6)]
[th.start() for th in threads]
[th.join() for th in threads]
admitted = [r for r in results if r[0]]
pubs = events.settings()["relay"]["phone_pubs"]
check("racing same pub: >=1 admitted, pinned once",
      len(admitted) >= 1 and pubs.count("PUB-RACE") == 1,
      "admitted=%d pins=%s" % (len(admitted), pubs))

# 9. Unpair = kill-switch: pins gone, room+sk ROTATED (old codes dead), push
#    token dropped, and no window left open.
reset()
rc.pairing_payload()
rc._admit("PUB-A")
events.save_settings({"push": {"fcm_token": "FCM"}})
before = events.settings()["relay"]
rc.unpair()
after = events.settings()["relay"]
check("unpair clears pins", after["phone_pubs"] == [] and after["phone_pub"] == "")
check("unpair rotates room", after["room"] != before["room"])
check("unpair rotates keypair", after["sk"] != before["sk"])
check("unpair closes window", not after.get("pair_pending"))
check("unpair drops push token", events.settings()["push"]["fcm_token"] == "")
ok, reason = rc._admit("PUB-A")
check("old device refused after unpair", not ok, reason)

# 10. Relay idle-room GC: hour-dead rooms are swept on growth, active/queued
#     rooms survive.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "surfaces", "relay"))
import relay  # noqa: E402

relay._rooms.clear()
dead = relay._room("dead");   dead["last_pull"] = time.time() - relay.ROOM_IDLE_GC - 5
qd = relay._room("queued");   qd["last_pull"] = time.time() - relay.ROOM_IDLE_GC - 5
qd["q"].append({"id": "f"})
live = relay._room("live");   live["last_pull"] = time.time()
relay._room("fresh")
check("idle room GC'd", "dead" not in relay._rooms)
check("room with queued frame survives GC", "queued" in relay._rooms)
check("recently pulled room survives GC", "live" in relay._rooms)

print()
if FAILS:
    print("FAILED: %d case(s): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("ALL PASS (%s)" % _TMP)
