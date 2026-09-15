# -*- coding: utf-8 -*-
"""A/B measurement for copilot_prune (card 'chat-henry-kontext-pruning'):
does the between-turns tool-result pruning make Henry SMARTER, THE SAME, or
DUMBER? Runs the identical scripted conversation twice, live against the
real Claude CLI, as two independent throwaway sessions:

  A (baseline) - never touched.
  B (pruned)   - copilot_prune.prune_session_file() run on ITS OWN file, in
                 place, same session id - EXACTLY the code path
                 copilot.py._do_prune runs in production. This is
                 deliberately NOT a copy/rename fork (an untested shape the
                 real feature never uses) - see spine/ops/probe_henry_prune.py
                 for why the in-place-same-sid shape is the one that's
                 actually verified safe.

Both sessions get the SAME fixed question set at the end: one that can only
be answered from a fact buried in an OLD, big tool_result (a pruning
candidate - deliberately NOT repeated in the assistant's own text reply, so
the fact lives ONLY in the tool channel this feature touches), and a couple
of ordinary current-state questions that have nothing to do with history
(a regression check: pruning must not make Henry dumber on the easy stuff
either).

Prints both sessions' answers side by side plus the ctx floor (last turn's
usage) for each - read it, don't just skim the exit code. This is a real,
now-executed comparison for ONE scripted conversation; it is not the
week-long production A/B the card also asked for (that needs calendar time
against the owner's real board chat, on/off, and is out of scope for a
single sitting - see the card's own report for the honest split of what
this script did prove vs. what still needs the owner's clock).

    py -3.12 ops/tools/prune_ab_bench.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import drivers                      # noqa: E402
from spine.agent.agentcli import CLAUDE               # noqa: E402
from spine.agent.spawnenv import tool_path            # noqa: E402
from spine.agent import claude_sessions               # noqa: E402
from cells.copilot.chat import copilot_prune          # noqa: E402

SECRET = "QX-88214-FENRIS"     # the fact planted ONLY in a tool_result, never repeated in prose
# A blanket "don't show me the output" reads as a prompt-injection/exfiltration
# pattern and haiku refuses it outright (measured while building this bench) -
# naming exactly ONE value not to restate, with a mundane reason, is accepted.
SEED_PROMPT = (
    "Fuehre python -c \"print('%s'); print('x'*3000)\" aus. Bestaetige danach "
    "nur mit dem Wort 'ok' - nenne den ausgegebenen Identifier in deiner "
    "Antwort nicht noch einmal, den kann ich selbst im Tool-Output nachlesen."
    % SECRET
)
FILLER_TURNS = 7    # ages the seed tool_result past copilot_prune.TURN_AGE (6)

QUESTIONS = [
    ("old-fact recall (pruning candidate)",
     "Schau in dieser Session ganz an den Anfang zurueck: welcher Code wurde "
     "dort von dem Python-Befehl ausgegeben? Wenn du es nicht mehr sehen "
     "kannst, sag das ehrlich statt zu raten."),
    ("current, history-independent #1",
     "Was ist 47 plus 55? Antworte nur mit der Zahl."),
    ("current, history-independent #2",
     "Nenne in einem Satz: was macht die Python-Funktion 'sorted()'?"),
]


def _turn(cwd, prompt, sid=None, timeout=120):
    argv = [CLAUDE, "-p", "--output-format", "json",
            "--permission-mode", "bypassPermissions", "--model", "haiku"]
    if sid:
        argv += ["--resume", sid]
    p = subprocess.run(drivers._cmd_line(argv), cwd=cwd, input=prompt,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=tool_path(), timeout=timeout)
    if not (p.stdout or "").strip():
        raise RuntimeError("no output: rc=%s stderr=%s" % (p.returncode, (p.stderr or "")[:300]))
    return json.loads(p.stdout)


def _ctx_of(r):
    u = r.get("usage") or {}
    return (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0))


def _seed_tool_ran(path):
    """Haiku sometimes just answers 'ok' without actually invoking the tool
    (measured while building this bench - model tool-use is not
    deterministic) - verify the seed turn really produced a qualifying
    tool_result before spending 7 filler turns on a session that would
    prove nothing."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            recs = f.read().split("\n")
    except OSError:
        return False
    for ln in recs:
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        c = (d.get("message") or {}).get("content") if d.get("type") == "user" else None
        if not isinstance(c, list):
            continue
        for p in c:
            if (isinstance(p, dict) and p.get("type") == "tool_result"
                    and copilot_prune._tool_result_size(p.get("content")) > copilot_prune.MIN_BYTES):
                return True
    return False


def _build_session(prefix, max_attempts=4):
    """(cwd, session_id) with the seed turn's tool_result CONFIRMED present
    and big enough - retries in a fresh cwd on the flaky "model just said ok"
    case rather than silently building a session that can't test anything."""
    for _attempt in range(max_attempts):
        cwd = tempfile.mkdtemp(prefix=prefix)
        r = _turn(cwd, SEED_PROMPT)
        sid = r.get("session_id")
        path = claude_sessions._find_transcript(sid) if sid else None
        if path and _seed_tool_ran(path):
            for _ in range(FILLER_TURNS):
                r = _turn(cwd, "Sag nur 'ok'.", sid=sid)
                sid = r.get("session_id") or sid
            return cwd, sid
        # a failed attempt still left a REAL ~/.claude/projects/<cwd> record
        # (Claude Code creates it on first spawn, independent of the temp
        # cwd) - deleting only the temp dir would leak it.
        if path:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        shutil.rmtree(cwd, ignore_errors=True)
    raise RuntimeError("the model never actually ran the seed tool call after %d attempts" % max_attempts)


def main():
    proj_a = proj_b = None
    try:
        print("== building session A (baseline) ==")
        cwd_a, sid_a = _build_session("helmdeck-ab-baseline-")
        print("== building session B (to be pruned) ==")
        cwd_b, sid_b = _build_session("helmdeck-ab-pruned-")

        path_b = claude_sessions._find_transcript(sid_b)
        proj_b = os.path.dirname(path_b) if path_b else None
        path_a = claude_sessions._find_transcript(sid_a)
        proj_a = os.path.dirname(path_a) if path_a else None

        res = copilot_prune.prune_session_file(path_b)
        print("prune on session B:", res)
        if not res or not res[0]:
            print("FAIL: nothing pruned in B - seed shape didn't clear the "
                  "TURN_AGE/MIN_BYTES bars, this run proves nothing")
            return 1

        rows = []
        for label, q in QUESTIONS:
            ra = _turn(cwd_a, q, sid=sid_a)
            rb = _turn(cwd_b, q, sid=sid_b)
            rows.append((label, q, ra, rb))

        print("\n== answers ==")
        for label, q, ra, rb in rows:
            print("\n-- %s --\nQ: %s" % (label, q))
            print("A (baseline): %s" % (ra.get("result") or "").strip())
            print("B (pruned)  : %s" % (rb.get("result") or "").strip())

        print("\n== ctx floor (last question's usage) ==")
        print("A (baseline): %d tokens" % _ctx_of(rows[-1][2]))
        print("B (pruned)  : %d tokens" % _ctx_of(rows[-1][3]))

        secret_in_a = SECRET in (rows[0][2].get("result") or "")
        secret_in_b = SECRET in (rows[0][3].get("result") or "")
        print("\n== verdict ==")
        print("  A recalled the pruned-candidate fact:", secret_in_a, "(expected True)")
        print("  B recalled the pruned-candidate fact:", secret_in_b,
              "(expected False - it was pruned; a truthful 'I can't see it "
              "anymore' is the CORRECT behavior here, not a defect)")
        print("  both answered the two current-state questions (spot-check "
              "them above by eye - correctness of free text isn't a bool)")
        return 0
    finally:
        shutil.rmtree(cwd_a, ignore_errors=True)
        shutil.rmtree(cwd_b, ignore_errors=True)
        for d in (proj_a, proj_b):
            if d and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
