# -*- coding: utf-8 -*-
"""A throwaway daemon for LOOKING AT the Prozesse screen (owner 2026-10-21: "haesslich
und unuebersichtlich - ich sehe nicht, an welchem Schritt ich stehe").

Serves the real request handler (spine.http.server.H) over a SANDBOX store with three
plans in the states the owner actually has: one mid-way with a finished step that
delivered something and the owner's review next, one whose current step waits on a
question to the owner, one that was just filed. Same exclusion rule as
boards_verify_daemon.py: only the handler runs - no serve(), so no orphan reaping, no
worktree sweeping - and the chain's auto-dispatch is cut, so looking at a screenshot
can never start a real agent.

  py -3.12 ops/tools/processes_verify_daemon.py [port]

Prints the #cfg fragment (base url + a sandbox token) for the Expo web build.
"""
import base64, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-procui-")
os.environ["HELMDECK_DATA_ROOT"] = SANDBOX
import daemon.paths
daemon.paths.DAEMON_ROOT = SANDBOX
daemon.paths.DATA_ROOT = SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import db, events            # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET), ("users", auth.USERS)):
    assert path.startswith(SANDBOX), "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8178
PW = "hunter2hunter2"
db.init()
db.workspace_config_replace({"policy": {"lang": "de", "auto_dispatch_modes": []}, "appearance": {"backdrop": "mesh"}})
auth.create_user("owner", PW, "owner")

from cells.engineer.chains import processes     # noqa: E402
processes._auto_dispatch = lambda tid: None     # a screenshot must never start an agent
processes._auto_accept = lambda tid: None

NOW = time.strftime("%Y-%m-%d %H:%M:%S")
REPO = ROOT.replace("\\", "/")
CHAIN = [
    ("Nachfrage, KI-Gefahr und Konkurrenz prüfen", "do"),
    ("Kernfunktion bauen", "do"),
    ("Design nach Atlassian-Standard, Selbstprüfung per Screenshot", "do"),
    ("Dein Review in Chrome", "human"),
    ("Nacharbeit aus deinem Review", "do"),
    ("Vergleich und Preis (mit deinem Ja)", "human"),
    ("Listing, Video, Rechtstexte und helmdeck.de-Seite", "do"),
    ("Vorprüfung vor dem Einreichen", "do"),
]


def card(cid, task, lane, status, reply="", question=None, ended=""):
    t = {"id": cid, "task": task, "lane": lane, "status": status, "priority": "medium",
         "branch": "proc-" + cid, "repo": REPO, "created": NOW, "rank": 0, "driver": "claude",
         "actor": "owner", "client": "", "ai_cost": 0.0, "last_reply": reply,
         "turn_ended": ended or NOW, "run_dir": ""}
    if question:
        t["question"] = question
    db.track_put(t)


def plan(pid, request, client, n_done, cur_state, cards):
    steps = []
    for i, (title, mode) in enumerate(CHAIN):
        cid = cards.get(i)
        st = {"title": title, "desc": "", "mode": mode, "days": 1,
              "status": "accepted" if cid else "proposed", "track": cid, "due": ""}
        steps.append(st)
    ps = processes._load()
    ps.insert(0, {"id": pid, "request": request, "client": client, "due": "", "status": "running",
                  "steps": steps, "cost": 0.0, "created": NOW, "actor": "owner", "repo": REPO})
    processes._save(ps)


# A: three done (one with a delivered note), the owner's Chrome review is next.
cards_a = {}
for i, (title, mode) in enumerate(CHAIN):
    cid = "pa-%d" % (i + 1)
    cards_a[i] = cid
    if i == 0:
        card(cid, title, "done", "accepted", "Nachfrage belegt: 4 Konkurrenz-Apps, keine kann den Baum per Drag-and-Drop umhängen. KI-Gefahr gering.")
    elif i == 1:
        card(cid, title, "done", "accepted", "DELIVERED Baum, Drag-and-Drop und Verlauf laufen auf label-doktor-test (v3.5.0). Tests grün.")
    elif i == 2:
        card(cid, title, "done", "accepted", "Atlassian-Design umgesetzt, Screenshots hell und dunkel geprüft.")
    elif i == 3:
        card(cid, title, "review", "submitted", "Bereit zur Prüfung auf der Testseite. Prüfe: Komponente umbenennen, Verantwortlichen setzen, Verlauf.")
    else:
        card(cid, title, "backlog", "queued")
plan("20261020-223009-516-proc",
     "Subkomponenten (Jira-App jira-subkomponenten): bis zum Marketplace. Stand: Kernfunktion, Baum, DnD fertig; laufend Ausbau Historie und Bearbeiten im Baum.",
     "Project Kaiser", 3, "ready", cards_a)

# B: the first step asks the owner a question.
cards_b = {}
for i, (title, mode) in enumerate(CHAIN):
    cid = "pb-%d" % (i + 1)
    cards_b[i] = cid
    if i == 0:
        card(cid, title, "working", "needs_you", "",
             question={"id": "q-1", "kind": "question", "questions": [{
                 "question": "Soll die Space-Kopie auch Anhänge und Kommentare kopieren?",
                 "header": "Anhänge und Kommentare?", "options": [{"label": "Ja", "description": ""}, {"label": "Nein", "description": ""}]}]},
             ended="2026-10-20 23:10:00")
    else:
        card(cid, title, "backlog", "queued")
plan("20261020-223012-663-proc",
     "Space-Kopie (Confluence-App space-kopie): bis zum Marketplace", "Project Kaiser", 0, "waiting", cards_b)

# C: just filed, nothing built yet.
plan("20261020-223633-436-proc",
     "Ticket-Merge (JSM-App jsm-ticket-merge): bis zum Marketplace. Schritte 1-3 sind schon erledigt und nicht Teil dieser Kette.",
     "Project Kaiser", 0, "proposed", {})

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402

tok = auth.issue_token("owner", "verify")
tok = tok[0] if isinstance(tok, (tuple, list)) else (tok.get("token") if isinstance(tok, dict) else tok)
srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
cfg = base64.b64encode(json.dumps({"baseUrl": "http://127.0.0.1:%d" % PORT, "token": tok}).encode()).decode()
print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d" % PORT)
print("#cfg    : #cfg=%s" % cfg)
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.shutdown()
