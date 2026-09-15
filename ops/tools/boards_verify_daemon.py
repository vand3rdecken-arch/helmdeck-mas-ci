# -*- coding: utf-8 -*-
"""A throwaway daemon for LOOKING AT the boards UI (accounts-boards-prd phase 2).

Serves the real request handler (spine.http.server.H) over a SANDBOX store, so
the app under test talks to the actual routes - but nothing else the daemon's
serve() does runs. That exclusion is the point: serve() reaps orphan agent
process trees and sweeps worktrees, which on a developer box would reach into
OTHER cards' live work. A screenshot is not worth that.

  py -3.12 ops/tools/boards_verify_daemon.py [port]

Prints the login and the #cfg fragment to point the Expo web build at it.
Ctrl-C to stop; the sandbox is a temp dir and is not cleaned up on purpose, so
a failed run can still be inspected.
"""
import base64, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-boardsui-")
import daemon.paths
daemon.paths.DAEMON_ROOT = SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import boards, db, events    # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET),
                    ("users", auth.USERS)):
    assert path.startswith(SANDBOX), \
        "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8149
PW = "hunter2hunter2"

db.init()
# "Bei uns" is the default because the boards tests assert on it (a rename that
# survived the seed). HELMDECK_LANE_LABELS lets a verification run reproduce the
# OWNER's actual labels instead - the pipeline row is drawn FROM these, so
# judging it against invented names would judge the wrong picture. Sandbox only;
# the real settings.json is never read or written here (see the assert above).
LANE_LABELS = {"working": "Bei uns"}
if os.environ.get("HELMDECK_LANE_LABELS"):
    LANE_LABELS = json.loads(os.environ["HELMDECK_LANE_LABELS"])
# db store, not settings.json (config-consolidation phase 2).
db.workspace_config_replace({"policy": {"lang": "de", "lane_labels": LANE_LABELS},
                             "appearance": {"backdrop": "mesh"}})

auth.create_user("owner", PW, "owner")
auth.create_user("ada", PW, "client")
boards.ensure_default()

# ONE KNOWN REPO, so the sandbox can answer a per-PROJECT question at all
# (harness-config-ui phase 3). The cards below already carry repo=ROOT, but a
# card's repo string is not a project RECORD - the repo chips and the project
# layer of the config chain both read the registry, and without an entry there
# the harness screen can only ever show the workspace answer. sight_repo is the
# one door in and is idempotent, so seeding it here produces exactly the state
# a real first card against this repo would.
from spine.ops import projects                  # noqa: E402
projects.sight_repo(ROOT, actor="owner", name="HelmDeck")

# Cards in every lane, so the overflow invariant has something to be about.
NOW = "2026-09-01 12:00:00"
CARDS = [
    ("bk-1", "Login-Flow entwerfen", "backlog", "queued", "high"),
    ("bk-2", "Onboarding-Text kürzen", "backlog", "queued", "low"),
    ("wk-1", "Relay-Reconnect härten", "working", "running", "urgent"),
    ("wk-2", "Push-Token erneuern", "working", "needs_you", "medium"),
    ("rv-1", "Board-Spalten umbenennen", "review", "submitted", "high"),
    ("rv-2", "Audit-Zeile für Boards", "review", "submitted", "medium"),
    ("dn-1", "Profil je Konto speichern", "done", "accepted", "medium"),
]
for i, (tid, task, lane, status, prio) in enumerate(CARDS):
    db.track_put({"id": tid, "task": task, "lane": lane, "status": status,
                  "priority": prio, "branch": "feat/" + tid, "repo": ROOT,
                  "created": NOW, "rank": i, "driver": "claude",
                  "actor": "owner", "client": "", "ai_cost": 0.0})

# A PM PLAN (opt-in via HELMDECK_SEED_PLAN=1). Without one, StatusPanel
# ("dash.status.title") returns null - `goal = data?.plan?.goal; if (!goal)
# return null` - so the Übersicht tab renders an empty canvas below its
# header. Real production state, seeded through the same doors production
# writes through (pm.set_goal, db.pm_plan_put) rather than invented shape;
# live_plan() recomputes triage/budget/eta from live economics on every read,
# so only the LLM-authored content (milestones/critical_path/risks) needs
# seeding here.
if os.environ.get("HELMDECK_SEED_PLAN") == "1":
    from cells.copilot.planning import pm

    # live_plan() (cells/copilot/planning/pm_triangle.py) recomputes the
    # Budget corner from spine.ops.usage.snapshot() on EVERY read, which
    # reads the REAL local Claude Code OAuth token and calls the REAL
    # Anthropic usage endpoint - the owner's actual live subscription
    # pacing, unsandboxed (measured 2026-09-15: it leaked "25% genutzt,
    # projiziert 106%" - the real account's own numbers - straight into a
    # screenshot meant for the public App Store listing). Stubbed here, in
    # this throwaway sandbox process only, to a calm fixed reading - the
    # same reasoning as the assert at the top of this file that refuses to
    # touch the real db/settings/users paths.
    from spine.ops import usage as _usage

    def _fake_snapshot(force=False):
        return {"status": "ok", "plan": "Max",
                "windows": [
                    {"id": "five_hour", "label": "5-Stunden", "usedPct": 8,
                     "remainingPct": 92, "resetsAt": "2026-09-15T22:00:00Z", "tone": "ok"},
                    {"id": "weekly", "label": "Woche", "usedPct": 14,
                     "remainingPct": 86, "resetsAt": "2026-09-20T22:00:00Z", "tone": "ok",
                     "pacing": {"projected_pct": 22, "exhaust_before_reset": False, "flag": False}},
                ],
                "fetchedAt": NOW}
    _usage.snapshot = _fake_snapshot

    pm.set_goal("App-Store-Launch (iOS + macOS) abschließen")
    db.pm_plan_put(time.strftime("%Y%m%d"), {
        "goal": "App-Store-Launch (iOS + macOS) abschließen",
        "generated_at": NOW,
        "summary": "TestFlight läuft, Mac-CI ist grün - Rest ist Owner-Handarbeit.",
        "done_pct": 72,
        "milestones": [
            {"name": "iOS-Signing + TestFlight", "status": "done", "est_turns": 6},
            {"name": "macOS-CI (Mac + MAS)", "status": "done", "est_turns": 5},
            {"name": "Store-Screenshots (iPhone + macOS)", "status": "doing", "est_turns": 3},
            {"name": "App Store Review einreichen", "status": "todo", "est_turns": 2,
             "blocked_by": "Export-Compliance-Antwort"},
        ],
        "critical_path": [
            {"step": "Export-Compliance-Frage beantworten", "who": "du",
             "why": "blockiert die Einreichung"},
            {"step": ".pkg zu App Store Connect hochladen", "who": "du"},
            {"step": "Review einreichen", "who": "agent", "card": "rv-1"},
        ],
        "risks": ["Review-Wartezeit unbekannt (erster Store-Release)."],
        "open_questions": ["Export-Compliance: enthält die App nicht-exempte Verschlüsselung?"],
    })

# THE DUMMY KNOB (accounts-boards-prd phase 4, opt-in via HELMDECK_DUMMY_KNOB=1).
#
# The card's acceptance is "a dummy knob with a scope tag appears in the correct
# door with the correct badge with NO client code change". The placement RULE is
# proved without a browser by surfaces/app/src/data/__settings_hub_selftest__.ts;
# this is the other half - that a knob the client bundle has never heard of
# really does draw itself, in the real app, against the real routes.
#
# Wrapping the schema function HERE, in a throwaway verification daemon, is
# deliberate: the dummy must not exist in shipped code, and "no client change"
# is only an honest claim if the knob enters through the same door a real new
# knob would - one entry in the daemon's table. The wrapper APPENDS; it never
# edits what apimeta emits, so everything else on the screen stays real.
if os.environ.get("HELMDECK_DUMMY_KNOB") == "1":
    from spine.http import apimeta                  # noqa: E402
    _real_schema = apimeta._config_schema

    def _with_dummy(s):
        rows = list(_real_schema(s))
        rows.append({
            "group": "dummySection", "groupKey": "Dummy-Sektion",
            "path": "dummy.knob", "control": "text",
            "labelKey": "Dummy-Knopf", "descKey": "Erfunden fuer den Abnahmetest.",
            "value": (s.get("dummy") or {}).get("knob") or "",
            # A door that has NO schema rows of its own, and a scope the daemon
            # never otherwise emits - so nothing about this can be satisfied by
            # a special case somebody wrote for the real knobs.
            "door": "connections", "level": "basic", "scope": "device",
        })
        return rows

    apimeta._config_schema = _with_dummy
    # routes_settings.py imported the symbol BY VALUE at import time, so the
    # module that actually serves /automation has to be rebound too - patching
    # apimeta alone would leave the live route on the original function and the
    # test would silently prove nothing.
    from spine.http.routes import routes_settings   # noqa: E402
    routes_settings._config_schema = _with_dummy
    print("dummy   : dummy.knob -> door=connections scope=device")

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = base64.b64encode(
    json.dumps({"baseUrl": "http://127.0.0.1:%d" % PORT}).encode()).decode()
print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d  (owner/%s, ada/%s)" % (PORT, PW, PW))
print("#cfg    : #cfg=%s" % cfg)
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.shutdown()
