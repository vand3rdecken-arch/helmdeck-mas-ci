"""An unchanged settings write must not move the board version (2026-10-19).
The phone re-registered its FCM token every ~2 s; each save_settings bumped
the version, the socket pushed it, the phone refetched everything."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import db
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-idem-"), "helmdeck.db")
db.init()
from spine.storage import events
fails = 0
def check(c, m):
    global fails; print(("ok   " if c else "FAIL ") + m); fails += 0 if c else 1
events.save_settings({"push": {"fcm_token": "tok-1"}}, actor="t")
v = db.current_version()
events.save_settings({"push": {"fcm_token": "tok-1"}}, actor="t")
check(db.current_version() == v, "same token again: version unchanged (%d -> %d)" % (v, db.current_version()))
events.save_settings({"push": {"fcm_token": "tok-2"}}, actor="t")
check(db.current_version() > v, "a new token moves it")
print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
