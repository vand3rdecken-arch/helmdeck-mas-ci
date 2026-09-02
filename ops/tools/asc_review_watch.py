# -*- coding: utf-8 -*-
"""Watch Apple's Beta App Review for the iOS build and TELL the owner when it
resolves. Owner decision 2026-09-02: "Review beobachten, dann fragen" - so this
OBSERVES and NOTIFIES, it never publishes.

It deliberately cannot go live on its own: it only ever issues GETs against ASC
(via ops/deploy/asc_external_beta.py's client, the repo's single ASC client) and
has no code path that calls submit or enable-link. Turning the public TestFlight
link on stays a separate, explicit, owner-triggered command.

    py -3.12 ops/tools/asc_review_watch.py --status      # print state, never push
    py -3.12 ops/tools/asc_review_watch.py               # check + notify on change
    py -3.12 ops/tools/asc_review_watch.py --install     # schtasks entry, every 30 min
    py -3.12 ops/tools/asc_review_watch.py --uninstall   # remove it again

Two traps this handles rather than trips over:

* QUIET HOURS. push_fcm() holds a non-urgent push at night and returns False.
  Marking "notified" on a False would eat the one message this whole watcher
  exists to deliver, so the notified-marker is written ONLY on a True and an
  undelivered event is retried on the next run - it lands in the morning.
* REJECTED is also "review durch". A watcher that only knows APPROVED would sit
  silent for days on a rejected build, which is the failure it was meant to
  prevent, so every terminal state notifies.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "deploy"))

from daemon.paths import DAEMON_ROOT  # noqa: E402

STATE = os.path.join(DAEMON_ROOT, "asc_review_watch.json")
LOG = os.path.join(DAEMON_ROOT, "asc_review_watch.log")
TASK_NAME = "HelmDeck ASC Beta Review Watch"

# Terminal states worth waking the owner for. WAITING_FOR_REVIEW / IN_REVIEW are
# the "still queued" states and stay silent on purpose - the point is one message
# when something actually changed, not a heartbeat.
TERMINAL = {"APPROVED", "REJECTED", "INVALID"}


def _log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE)


def observe():
    """Current ASC facts, read-only. Returns (event, detail-dict)."""
    from asc_external_beta import _get, _external_group, APP_ID

    g = _external_group()
    ga = (g or {}).get("attributes") or {}
    link = ga.get("publicLink")
    link_on = bool(ga.get("publicLinkEnabled"))

    d = _get("/v1/builds?filter[app]=%s&sort=-uploadedDate&limit=1" % APP_ID)
    builds = d.get("data", [])
    if not builds:
        return "NO_BUILD", {"link": link, "link_on": link_on, "build": None}
    b = builds[0]
    ver = (b["attributes"] or {}).get("version")
    sub = _get("/v1/builds/%s/betaAppReviewSubmission" % b["id"]).get("data")
    review = sub["attributes"].get("betaReviewState") if sub else "NOT SUBMITTED"

    detail = {"link": link, "link_on": link_on, "build": ver, "review": review}
    # The link going live is the end of the watch, whoever flipped it.
    if link_on and link:
        return "LINK_LIVE", detail
    if review in TERMINAL:
        return review, detail
    return "WAITING", detail


def message(event, d):
    ver = d.get("build")
    if event == "APPROVED":
        return ("TestFlight-Review durch",
                "Build %s ist von Apple freigegeben. Der oeffentliche Link ist "
                "noch AUS - sag Bescheid, ob ich ihn live schalten soll." % ver)
    if event == "REJECTED":
        return ("TestFlight-Review abgelehnt",
                "Apple hat Build %s in der Beta App Review abgelehnt. Die "
                "Begruendung steht in App Store Connect." % ver)
    if event == "INVALID":
        return ("TestFlight-Build ungueltig",
                "Build %s wurde von Apple als invalid markiert." % ver)
    if event == "LINK_LIVE":
        return ("TestFlight-Link ist live",
                "Der oeffentliche Beitrittslink ist aktiv: %s" % d.get("link"))
    return None


def check(argv):
    st = _state()
    if st.get("done"):
        _log("watch already complete - no-op (remove with --uninstall)")
        return 0
    try:
        event, detail = observe()
    except Exception as e:                                    # noqa: BLE001
        # A transient ASC/network failure must not look like "nothing happened".
        _log("ASC query FAILED: %r" % (e,))
        return 1

    _log("event=%s build=%s review=%s link_on=%s"
         % (event, detail.get("build"), detail.get("review"), detail.get("link_on")))

    if event == "WAITING" or event == "NO_BUILD":
        st["last_seen"] = detail
        _save(st)
        return 0

    key = "%s:%s" % (event, detail.get("build"))
    if st.get("notified_for") == key:
        return 0

    msg = message(event, detail)
    if not msg:
        return 0
    title, body = msg
    from spine.comms import notify
    if not notify.fcm_ready():
        _log("NOT notified - no paired device / no service account; will retry")
        st["last_seen"] = detail
        _save(st)
        return 1
    ok = notify.push_fcm(title, body, kind="asc_review")
    if ok:
        # Only NOW is it safe to remember: a quiet-hours hold returns False and
        # must be retried, not recorded as delivered.
        st["notified_for"] = key
        st["notified_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if event == "LINK_LIVE":
            st["done"] = True
        _log("notified: %s" % title)
    else:
        _log("push not delivered (quiet hours or transport) - retrying next run")
    st["last_seen"] = detail
    _save(st)
    return 0 if ok else 1


def cmd_status(argv):
    event, detail = observe()
    print("event  : %s" % event)
    print("build  : %s" % detail.get("build"))
    print("review : %s" % detail.get("review"))
    print("link   : enabled=%s url=%s" % (detail.get("link_on"), detail.get("link")))
    st = _state()
    print("watcher: notified_for=%s done=%s"
          % (st.get("notified_for"), bool(st.get("done"))))
    return 0


def _task_action():
    # pyw.exe is the WINDOWLESS launcher - py.exe would flash a console on the
    # owner's desktop every 30 minutes, which is its own small defect.
    pyw = os.path.join(os.environ.get("WINDIR", r"C:\WINDOWS"), "pyw.exe")
    script = os.path.abspath(__file__)
    return '"%s" -3.12 "%s"' % (pyw, script)


def cmd_install(argv):
    every = "30"
    if "--every" in argv:
        every = argv[argv.index("--every") + 1]
    # No /RU or /RP: the task runs as the logged-on owner, so nothing has to
    # store or handle a password.
    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", _task_action(),
           "/SC", "MINUTE", "/MO", every, "/F"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout or "")
    sys.stderr.write(r.stderr or "")
    if r.returncode == 0:
        print("installed %r every %s min -> %s" % (TASK_NAME, every, _task_action()))
    return r.returncode


def cmd_uninstall(argv):
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout or "")
    sys.stderr.write(r.stderr or "")
    return r.returncode


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--status" in a:
        sys.exit(cmd_status(a))
    if "--install" in a:
        sys.exit(cmd_install(a))
    if "--uninstall" in a:
        sys.exit(cmd_uninstall(a))
    sys.exit(check(a))
