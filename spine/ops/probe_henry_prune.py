# -*- coding: utf-8 -*-
"""Does `claude -p --resume` survive copilot_prune's in-place rewrite of its
OWN session .jsonl? Companion to probe_henry_guard.py, same rule: read the
CLI's own records, not the model's prose.

Card 'chat-henry-kontext-pruning' (2026-09-15) was explicit: prove this on a
THROWAWAY session before the real Henry board session is ever touched. No
pre-existing 'probe' entry was found in copilot_stats or anywhere else in
this repo (checked before writing this script) - rather than assume one,
this mints its OWN disposable session in a fresh temp cwd, so nothing about
the owner's real board chat is ever at risk.

Sequence: one turn whose tool call produces a >MIN_BYTES result, seven filler
turns to age it past TURN_AGE, prune_session_file() on the resulting .jsonl,
then one more --resume turn. The verdict checks the CLI's own evidence: did
the file actually shrink, is there a backup, did the resumed turn come back
clean (no is_error, no dangling tool_use_id complaint), did it continue the
SAME session rather than being forced to start fresh.

    py -3.12 spine/ops/probe_henry_prune.py
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


def main():
    cwd = tempfile.mkdtemp(prefix="helmdeck-prune-probe-")
    proj_dir = None
    try:
        print("probe cwd:", cwd)
        r1 = _turn(cwd, "Fuehre GENAU dies aus und zeig die volle Ausgabe, sonst nichts: "
                        "python -c \"print('x'*3000)\"")
        sid = r1.get("session_id")
        if not sid:
            print("FAIL: first turn returned no session_id")
            return 1
        print("turn 1 session:", sid, "is_error:", r1.get("is_error"))
        for _ in range(7):
            r = _turn(cwd, "Antworte nur mit 'ok'.", sid=sid)
            sid = r.get("session_id") or sid
        path = claude_sessions._find_transcript(sid)
        if not path:
            print("FAIL: could not find transcript for", sid)
            return 1
        proj_dir = os.path.dirname(path)
        size_before = os.path.getsize(path)
        res = copilot_prune.prune_session_file(path)
        size_after = os.path.getsize(path)
        print("prune result:", res, "| size before/after:", size_before, size_after)
        if not res or not res[0]:
            print("FAIL: nothing was pruned - the probe transcript was not "
                  "shaped as expected (check MIN_BYTES/TURN_AGE against it)")
            return 1
        backup = path + ".pre-prune"
        r_final = _turn(cwd, "Was hast du in der allerersten Nachricht dieser "
                             "Session ausgefuehrt? Antworte in einem Satz.", sid=sid)
        print("resume-after-prune result:", json.dumps(r_final, ensure_ascii=False)[:600])
        ok_resumed = bool((r_final.get("result") or "").strip()) and not r_final.get("is_error")
        verdict = {
            "prune actually shrank the file": size_after < size_before,
            "backup file written": os.path.exists(backup),
            "resume after prune produced a clean answer (no is_error)": ok_resumed,
            "resume continued the SAME session (no forced-fresh)": r_final.get("session_id") == sid,
        }
        print("\n== verdict ==")
        for k, v in verdict.items():
            print(("  ok   " if v else "  FAIL ") + k)
        return 0 if all(verdict.values()) else 1
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
        if proj_dir and os.path.isdir(proj_dir):
            shutil.rmtree(proj_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
