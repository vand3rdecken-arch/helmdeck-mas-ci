# -*- coding: utf-8 -*-
"""A throwaway SANDBOX daemon for the dictation e2e: the real request handler
over a temp data root, never the live db.

Isolation is HELMDECK_DATA_ROOT (daemon/paths.DATA_ROOT - every writable path
derives from it), set BEFORE any spine import, then ASSERTED: db, settings and
users must all live under the sandbox or this refuses to run. (The older
ops/tools/demo_phone_daemon.py patches daemon.paths.DAEMON_ROOT, which the
four-folder restructure made a no-op - it correctly refuses now, and that guard
is why this file exists.)

The ONLY thing shared with the live install is the STT model folder, linked
read-only as a directory junction so the real parakeet loads. It is removed with
os.rmdir (never a recursive delete - that would follow the junction).

  py -3.12 ops/tests/dictation_sandbox_daemon.py <port> <data_root>
"""
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PORT = int(sys.argv[1])
SANDBOX = os.path.abspath(sys.argv[2])
os.makedirs(SANDBOX, exist_ok=True)
os.environ["HELMDECK_DATA_ROOT"] = SANDBOX
sys.path.insert(0, ROOT)

from daemon import paths                                  # noqa: E402
assert paths.DATA_ROOT == SANDBOX, "DATA_ROOT did not follow HELMDECK_DATA_ROOT"

from spine.auth import auth                               # noqa: E402
from spine.storage import db, events                      # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET), ("users", auth.USERS)):
    assert os.path.abspath(path).startswith(SANDBOX), "REFUSING TO RUN: %s points at %s" % (label, path)

# model folder: read-only share of the live one
real = os.path.join(ROOT, "daemon", "content", "models_stt")
link = os.path.join(SANDBOX, "content", "models_stt")
os.makedirs(os.path.dirname(link), exist_ok=True)
if os.path.isdir(real) and not os.path.exists(link):
    subprocess.run(["cmd", "/c", "mklink", "/J", link, real], check=True, capture_output=True)

db.init()
try:
    auth.create_user("owner", "hunter2hunter2", "owner")
except ValueError:                      # a re-run over the same sandbox keeps its owner
    pass

from http.server import ThreadingHTTPServer               # noqa: E402
from spine.http.server import H                           # noqa: E402

# The real handler is silent (log_message is a no-op). A sandbox exists to be
# observed, so it logs one line per request: method, path, status is not
# available here, but WHICH calls arrived is what the device tests need
# (did the phone really send chunks, did it call finish).
def _log(self, *a):
    print("REQ %s %s" % (self.command, self.path.split("?")[0]))
    sys.stdout.flush()
H.log_message = _log
srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d  (owner/hunter2hunter2)" % PORT)
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
finally:
    srv.shutdown()
    if os.path.isdir(link):
        try:
            os.rmdir(link)            # unlink the junction only
        except OSError:
            pass
