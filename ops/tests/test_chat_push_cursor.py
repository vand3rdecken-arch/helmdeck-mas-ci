"""A Henry chat push carries the chat cursor (2026-10-20).

Diag 2026-10-20: every Henry reply loaded the history twice - once on the
socket event, again 1-3 s later on the FCM push ("delta +0"). The push now
seals the chat cursor the reply moved to; the app skips the second load when
its stream already delivered exactly that cursor (data/stream.ts
pushStillNews). Drives the real notify.chat_reply with push_fcm captured.

Run: py -3.12 ops/tests/test_chat_push_cursor.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import db  # noqa: E402
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-pushc-"), "helmdeck.db")
db.init()
from spine.comms import notify  # noqa: E402

sent = []
notify.push_fcm = lambda *a, **k: sent.append(k) or True
db.bump_chat(); db.bump_chat()
notify.chat_reply("Erledigt: die Karte ist durch und gemerged.")
ok = len(sent) == 1 and (sent[0].get("extra") or {}).get("c") == db.current_chat_version()
print(("ok   " if ok else "FAIL ") + "the chat push seals the current chat cursor (%s)" % sent)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
