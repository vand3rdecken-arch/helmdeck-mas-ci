# -*- coding: utf-8 -*-
"""Henry's verbs as a tool he calls INSIDE a turn (cells/copilot/chat/henry_act.py).

Pins 2026-10-20: the ```actions block ran after the turn, so "file a process,
then attach to its id" could not be done in one turn, and runs without the verb
catalog wrote the store directly. Now:
  1. a batch runs in order and a later verb uses "$1.process" from an earlier one
  2. a reference to a verb that produced no id is SKIPPED, never guessed
  3. role gates are the live turn's, not the caller's (client cannot delete)
  4. no live turn (chat) -> 409; advisory turn -> 403; unknown / dead token -> no entry
  5. the POST route: local only, token header, results as JSON
  6. the shell-echo detector does not flag a henry_act call as an unrun action
  7. every verb _run_action dispatches is in ACTION_KINDS (the five it omitted)

Self-sandboxing: temp db. Run: py -3.12 ops/tests/test_henry_act.py
"""
import ast, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-act-")
from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
events.EV = os.path.join(SANDBOX, "events.jsonl")
db.init(role="tool")
assert db.DBPATH.startswith(SANDBOX)
from cells.engineer.chains import processes
from cells.copilot.chat import henry_act, copilot, copilot_actions

REPO = os.path.join(SANDBOX, "repo")
os.makedirs(REPO)
fails = []


def check(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fails.append(m)


# the log rows go to the owner's chat file - keep them out of the live one
copilot._append_log = lambda user, entries: None

SKEY = "owner"
tok = henry_act.new_token()
henry_act.register(tok, "owner", SKEY, "chat", os.getpid())      # a pid that is alive: this test
entry = henry_act.resolve(tok)
check(entry and entry["account"] == "owner", "a registered token for a live pid resolves")
check(henry_act.resolve("nope") is None, "an unknown token does not")
dead = henry_act.new_token()
henry_act.register(dead, "owner", SKEY, "chat", 2 ** 22 - 4)       # no such process
check(henry_act.resolve(dead) is None, "a token whose process is gone does not")

st, doc = henry_act.run(entry, [{"type": "new_process", "request": "x"}])
check(st == 409, "chat surface without a running turn -> 409")

henry_act.set_turn(SKEY, "owner", True)
st, doc = henry_act.run(entry, [
    {"type": "new_process", "request": "Kette A", "repo": REPO,
     "steps": [{"title": "Schritt 1", "mode": "do"}, {"title": "Schritt 2", "mode": "do"}]},
    {"type": "add_step", "process": "$1.process", "title": "Nachtrag", "mode": "human"},
    {"type": "process_status", "process": "$1.process"},
])
check(st == 200 and len(doc["results"]) == 3, "a batch of three runs in one call")
pid = doc["results"][0]["ids"].get("process")
check(bool(pid) and processes.get(pid) is not None, "new_process reports the id it made (recorded, not parsed)")
check(len(processes.get(pid)["steps"]) == 3, "a later verb used $1.process: the step landed in THAT process")

st, doc = henry_act.run(entry, [
    {"type": "steer", "card": "gibts-nicht-xyz", "text": "hi"},
    {"type": "add_step", "process": "$1.process", "title": "nie"}])
check(doc["results"][1]["result"].startswith("skipped") and len(processes.get(pid)["steps"]) == 3,
      "a $ref to a verb with no id is skipped, never guessed")

st, doc = henry_act.run(entry, [{"type": "delete_process", "process": pid}])
check(processes.get(pid) is None, "owner turn: delete_process runs")
check("BY HENRY" in doc["results"][0]["result"], "... and says whose hand it was")

p2 = processes.create("Kette B", actor="owner")
henry_act.set_turn(SKEY, "client", True)
st, doc = henry_act.run(entry, [{"type": "delete_process", "process": p2["id"]}])
check(processes.get(p2["id"]) is not None, "a client-role turn cannot delete (the TURN's role gates, not the caller)")

henry_act.set_turn(SKEY, "owner", False)
st, doc = henry_act.run(entry, [{"type": "new_process", "request": "y"}])
check(st == 403, "an advisory turn (allow_actions false) is refused")

henry_act.set_turn(SKEY, "owner", True)
st, doc = henry_act.run(entry, [{"type": "file_card", "task": "x"}] * (henry_act.MAX_BATCH + 1))
check(st == 400, "more than MAX_BATCH verbs per call is refused")
henry_act.set_turn(SKEY, "owner", True)
for _ in range(henry_act.MAX_CALLS_PER_TURN):
    henry_act.run(entry, [{"type": "process_status"}])
st, doc = henry_act.run(entry, [{"type": "process_status"}])
check(st == 429, "a loop is bounded per turn")
henry_act.clear_turn(SKEY)
st, _ = henry_act.run(entry, [{"type": "process_status"}])
check(st == 409, "clear_turn closes the door between turns")

# 5. the route
sent = []


class H:
    client_address = ("127.0.0.1", 5)
    headers = {"X-Henry-Act-Token": tok}

    def _send(self, code, body):
        sent.append((code, json.loads(body)))


henry_act.set_turn(SKEY, "owner", True)
h = H(); henry_act.act_post(h, {"type": "process_status"})
check(sent[-1][0] == 200 and "results" in sent[-1][1], "POST /henry/act with the token -> results JSON")
h = H(); h.client_address = ("10.0.0.7", 5); henry_act.act_post(h, {"type": "process_status"})
check(sent[-1][0] == 403, "not from this machine -> 403")
h = H(); h.headers = {}; henry_act.act_post(h, {"type": "process_status"})
check(sent[-1][0] == 401, "no token -> 401")

# 6. the echo detector
steps = [{"tool": "Bash", "detail": {"command": "py -3.12 ../ops/tools/henry_act.py '{\"type\":\"new_process\"}'"}}]
check(copilot._actions_in_shell(steps) == [], "a henry_act call is not flagged as an action typed into a shell")
steps = [{"tool": "Bash", "detail": {"command": "echo '{\"type\":\"new_process\"}'"}}]
check(copilot._actions_in_shell(steps) == ["new_process"], "an echoed verb still is")

# 7. ACTION_KINDS covers every verb _run_action dispatches
src = open(copilot_actions.__file__, encoding="utf-8").read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_action")
handled = set()
for node in ast.walk(fn):
    if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "kind":
        for c in node.comparators:
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                handled.add(c.value)
            elif isinstance(c, (ast.Tuple, ast.List, ast.Set)):
                handled |= {e.value for e in c.elts if isinstance(e, ast.Constant)}
missing = sorted(handled - set(copilot_actions.ACTION_KINDS))
check(not missing, "ACTION_KINDS covers every verb _run_action handles (missing: %s)" % missing)

# 8. the briefs teach it (and only where it is allowed)
from spine.registry import harness
check("henry_act.py" in harness.brief("board-copilot"), "Henry's brief teaches the in-turn tool")
check("BOARD CHANGES" in harness.brief("hands") and "never by" in harness.brief("hands"),
      "the hands brief says: board changes only through the verb tool, never the store")
check("BOARD CHANGES" not in harness.brief("delegate"), "a research agent's brief does not offer it")
check(os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "henry_act.py")),
      "the CLI the briefs name exists")

# 9. the broker's hands round is told the same (it has Bash and no catalog)
from cells.copilot.broker import henry_broker as hb
_t = hb._HANDS_TAIL % "Plan"
check("henry_act.py" in _t and "nie den Speicher" in _t and os.path.isfile(hb._ACT_TOOLS + "/henry_act.py"),
      "the broker hands round names the verb tool (a real path) and forbids writing the store")

print("PASS test_henry_act" if not fails else "FAIL (%d)" % len(fails))
sys.exit(1 if fails else 0)
