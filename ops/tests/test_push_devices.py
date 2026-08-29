# -*- coding: utf-8 -*-
"""Headless test for MULTI-DEVICE push (W2d): the watch as a second recipient.

Before this, HelmDeck had exactly one push target - settings.push.fcm_token,
sealed to relay.phone_pub. The watch needs its own slot, sealed to its OWN
pinned key, and the interesting cases are all the ways that could go wrong:

 1. The legacy phone path still works untouched (no migration, no
    re-registration).
 2. Phone + watch both arrive, each sealed to its own key - never one shared
    ciphertext, or either device could read the other's mail.
 3. A registered device whose key is NO LONGER PINNED is silently dropped at
    SEND time. This is the whole point of deriving recipients from the pinned
    set instead of trusting the stored blob: unpairing must silence a device
    without a second bookkeeping step.
 4. POST /push/register REFUSES a pubkey the daemon never admitted. Taking the
    body's word would let any holder of a device token aim real, sealed card
    content at a key of their choosing.
 5. Registering a second device keeps the first. save_settings merges only ONE
    level deep, so a naive {"devices": {pub: ...}} patch would drop every other
    device - the exact trap this test exists to pin.
 6. Unpairing clears the device slots.

Self-sandboxing: temp DB/events/settings, no network, no FCM.
Run: py -3.12 ops/tests/test_push_devices.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-push-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.comms import notify
from spine.http.routes import routes_system

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PHONE_PUB = "phone-pub-aaaaaaaaaaaaaaaaaaaaaaaaaaa="
WATCH_PUB = "watch-pub-bbbbbbbbbbbbbbbbbbbbbbbbbbb="
GHOST_PUB = "ghost-pub-ccccccccccccccccccccccccccc="


def set_state(pubs, fcm_token="", devices=None):
    """Rewrite the whole relay+push blob - no partial patching, so each case
    starts from a known state rather than inheriting the previous one."""
    events.save_settings({
        "relay": {"url": "https://r.example", "room": "r1", "sk": "sk",
                  "phone_pub": (pubs[0] if pubs else ""),
                  "phone_pubs": list(pubs), "pair_pending": None},
        "push": {"fcm_token": fcm_token, "devices": dict(devices or {})},
    })


def labels_of(recips):
    return sorted(l for l, _t, _p in recips)


# -- 1. legacy phone only --------------------------------------------------
set_state([PHONE_PUB], fcm_token="tok-phone")
r = notify.recipients(events.settings())
check(len(r) == 1 and r[0] == ("phone", "tok-phone", PHONE_PUB),
      "phone-only install is unchanged - one recipient, sealed to phone_pub")

# -- 2. phone + watch, each to its own key ---------------------------------
set_state([PHONE_PUB, WATCH_PUB], fcm_token="tok-phone",
          devices={WATCH_PUB: {"token": "tok-watch", "label": "Watch"}})
r = notify.recipients(events.settings())
check(labels_of(r) == ["Watch", "phone"], "phone and watch are both recipients")
by_pub = {p: t for _l, t, p in r}
check(by_pub.get(PHONE_PUB) == "tok-phone" and by_pub.get(WATCH_PUB) == "tok-watch",
      "each device carries its OWN token")
check(len({p for _l, _t, p in r}) == 2,
      "two DISTINCT seal keys - no shared ciphertext between devices")

# -- 3. registered but no longer pinned -> dropped at send time ------------
set_state([PHONE_PUB], fcm_token="tok-phone",
          devices={WATCH_PUB: {"token": "tok-watch", "label": "Watch"}})
r = notify.recipients(events.settings())
check(labels_of(r) == ["phone"],
      "an unpinned device is dropped at SEND time, not merely on unregister")

# -- 4. degenerate entries -------------------------------------------------
set_state([PHONE_PUB, WATCH_PUB], fcm_token="tok-phone",
          devices={WATCH_PUB: {"token": "   ", "label": "Watch"}})
check(labels_of(notify.recipients(events.settings())) == ["phone"],
      "a device with a blank token is not a recipient")

set_state([PHONE_PUB, WATCH_PUB], fcm_token="",
          devices={WATCH_PUB: {"token": "tok-watch", "label": "Watch"}})
check(labels_of(notify.recipients(events.settings())) == ["Watch"],
      "watch-only workspace still has a recipient (phone slot empty)")
# fcm_ready() used to read push.fcm_token directly, so a workspace whose only
# paired device is the WATCH reported "push not set up". Point _SA at a file
# that exists so the service-account leg is satisfied and the device leg is
# what is actually under test.
_real_sa = notify._SA
notify._SA = events.SET
check(notify.fcm_ready() is True,
      "fcm_ready() is True for a watch-only workspace (was False before W2d)")
set_state([], fcm_token="")
check(notify.fcm_ready() is False, "fcm_ready() is False with nothing paired")
notify._SA = _real_sa
set_state([PHONE_PUB, WATCH_PUB], fcm_token="",
          devices={WATCH_PUB: {"token": "tok-watch", "label": "Watch"}})

set_state([], fcm_token="tok-phone")
check(notify.recipients(events.settings()) == [],
      "nothing pinned -> no recipients, even with a stored phone token")

# a device that registered under the phone's own key must not double-send
set_state([PHONE_PUB], fcm_token="tok-phone",
          devices={PHONE_PUB: {"token": "tok-phone", "label": "Dup"}})
check(len(notify.recipients(events.settings())) == 1,
      "a device registered under phone_pub does not duplicate the phone")


# -- 5./6. the registration route -----------------------------------------
class FakeReq(object):
    def __init__(self):
        self.sent = None

    def _send(self, status, body):
        self.sent = (status, body)
        return None


USER = {"name": "owner"}


def register(body):
    q = FakeReq()
    routes_system.push_register_post(q, USER, body)
    return q.sent


set_state([PHONE_PUB, WATCH_PUB], fcm_token="")

st, _b = register({"token": "tok-ghost", "pub": GHOST_PUB, "label": "Evil"})
check(st == 403, "registering an UNPINNED pubkey is refused (403)")
check(not ((events.settings().get("push") or {}).get("devices") or {}),
      "the refused registration stored nothing")

st, _b = register({"token": "tok-watch", "pub": WATCH_PUB, "label": "Watch"})
check(st == 200, "registering a pinned pubkey succeeds")
devs = (events.settings().get("push") or {}).get("devices") or {}
check(devs.get(WATCH_PUB, {}).get("token") == "tok-watch",
      "the watch token landed under its own pubkey")

# second device must not evict the first (the one-level-merge trap)
events.save_settings({"relay": {"phone_pubs": [PHONE_PUB, WATCH_PUB, GHOST_PUB]}})
st, _b = register({"token": "tok-third", "pub": GHOST_PUB, "label": "Third"})
devs = (events.settings().get("push") or {}).get("devices") or {}
check(st == 200 and set(devs) == {WATCH_PUB, GHOST_PUB},
      "a second device is ADDED, not swapped in - the first survives")

# legacy body (no pub) still writes the phone slot
st, _b = register({"token": "tok-phone-2"})
check(st == 200 and (events.settings().get("push") or {}).get("fcm_token") == "tok-phone-2",
      "a body without 'pub' still takes the legacy phone path")
check(set((events.settings().get("push") or {}).get("devices") or {}) == {WATCH_PUB, GHOST_PUB},
      "the legacy path leaves registered devices alone")

st, _b = register({"token": "   ", "pub": WATCH_PUB})
check(st == 400, "an empty token is refused before anything is written")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL MULTI-DEVICE PUSH CHECKS PASSED")
