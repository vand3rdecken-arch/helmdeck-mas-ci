# -*- coding: utf-8 -*-
"""delivered-parked carries two FACT lines for Henry (owner 2026-09-29, root-cause
of card 20260929-125756): 'App-Dateien geaendert: ja/nein, .shots/: N Dateien' and
'WebSearch/WebFetch im Turn: N'. Fails on the old code (detail had neither line).
Also: the driver counts WebSearch/WebFetch tool_use into meta['turn_web'].

Run: py -3.12 ops/tests/test_delivered_evidence.py
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from cells.engineer.cards import turnrunner

fails = []


def check(desc, ok):
    print(("ok   " if ok else "FAIL ") + desc)
    if not ok:
        fails.append(desc)


def git(wt, *a):
    subprocess.run(["git", "-C", wt] + list(a), check=True, capture_output=True)


wt = tempfile.mkdtemp(prefix="hd-evid-")
git(wt, "init", "-q"); git(wt, "symbolic-ref", "HEAD", "refs/heads/main")
git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
t = {"worktree": wt}

out = turnrunner._evidence_lines(t, {"turn_web": 0})
check("clean tree: app nein, 0 shots, 0 web",
      "App-Dateien geaendert: nein, .shots/: 0 Dateien" in out and "WebSearch/WebFetch im Turn: 0" in out)

os.makedirs(os.path.join(wt, "surfaces", "app", "src"))
open(os.path.join(wt, "surfaces", "app", "src", "x.tsx"), "w").write("x")
os.makedirs(os.path.join(wt, ".shots"))
for n in ("a.png", "b.png", "a.txt"):
    open(os.path.join(wt, ".shots", n), "w").write("x")
out = turnrunner._evidence_lines(t, {"turn_web": 3})
check("app file + 2 shots + 3 web calls reported",
      "App-Dateien geaendert: ja, .shots/: 2 Dateien" in out and "WebSearch/WebFetch im Turn: 3" in out)

check("no ref_code reads -> 'keiner'", "Vorbild-Code gelesen: keiner" in out)
open(os.path.join(wt, ".refs.log"), "w").write(chr(10).join(["getpaseo/paseo:docs/x.md"] * 2 + ["foo/bar:a.ts"]))
out = turnrunner._evidence_lines(t, {})
check("ref_code reads listed once each",
      "Vorbild-Code gelesen: foo/bar:a.ts, getpaseo/paseo:docs/x.md" in out)

# the escalation itself carries both lines
from spine.registry import escalations
sent = []
escalations.emit = lambda kind, **k: sent.append((kind, k))
escalations.list_open = lambda: []
escalations.decided_recently = lambda *a, **k: False
turnrunner.is_delivered = lambda t: True
turnrunner._emit_delivered_parked({"id": "c1", "lane": "working", "task": "x", "worktree": wt},
                                  "needs_you", "done", {"turn_web": 1})
d = sent[0][1]["detail"] if sent else ""
check("delivered-parked detail has both fact lines",
      "App-Dateien geaendert" in d and "WebSearch/WebFetch im Turn: 1" in d and "Vorbild-Code gelesen: foo/bar" in d)

sys.exit(1 if fails else 0)
