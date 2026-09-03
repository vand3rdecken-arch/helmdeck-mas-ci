# -*- coding: utf-8 -*-
"""The board chat's warm process must SWITCH model, not respawn.

Why this test exists: the persistent chat process was keyed by (model,
permission mode) and any change killed it. The composer defaults to "auto"
(card_composer.tsx), so turnopts.pick_model re-picks the tier from every
message's TEXT - "danke" -> haiku, a plain question -> sonnet, "debug das" ->
opus - which meant an ordinary typed conversation threw the warm process away
turn after turn and paid node boot + a full --resume prefill each time. The
process was warm in name only.

Run: py -3.12 ops/tests/test_copilot_warm_switch.py   (from the repo root)
Uses ops/tests/fake_claude.py as the CLI stand-in - it answers set_model /
set_permission_mode control_requests exactly like the real binary, so nothing
here needs a live daemon, a session or the network.
"""
import os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cells.copilot.chat import copilot                                  # noqa: E402

FAKE = os.path.join(ROOT, "ops", "tests", "fake_claude.py")
USER = "warm-switch-test"
fails = []


def check(name, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + name + (("  " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def spawn(script_args):
    return subprocess.Popen([sys.executable] + script_args, cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)


def main():
    mode = copilot.henry_pmode()

    # -- 1. a model change reuses the LIVE process via the control plane ------
    p = spawn([FAKE])
    copilot._persist[USER] = {"p": p, "key": ("claude-sonnet-5", mode)}
    t0 = time.time()
    got, fresh = copilot._persist_get(USER, "claude-opus-5", None, "brief")
    dt = time.time() - t0
    check("model change reuses the same process", got is p)
    check("reuse is not reported as a fresh spawn", fresh is False)
    check("key advanced to the new model",
          copilot._persist[USER]["key"] == ("claude-opus-5", mode),
          "key=%r" % (copilot._persist[USER]["key"],))
    check("switch is fast (no respawn, no resume prefill)", dt < 3.0, "took %.2fs" % dt)
    check("process still alive after the switch", p.poll() is None)

    # the switched process must still ANSWER a turn - a control op that wedged
    # the pipe would be worse than the respawn it replaced.
    p.stdin.write('{"type":"user","message":{"role":"user","content":"hallo"}}\n')
    p.stdin.flush()
    saw = ""
    for _ in range(12):
        line = p.stdout.readline()
        if '"type": "result"' in line or '"type":"result"' in line:
            saw = line
            break
    check("warm process still answers a turn after the switch", "echo:hallo" in saw)
    copilot._persist_drop(USER)

    # -- 2. an unchanged key must not touch the control plane at all ---------
    p2 = spawn([FAKE])
    copilot._persist[USER] = {"p": p2, "key": ("claude-sonnet-5", mode)}
    got2, fresh2 = copilot._persist_get(USER, "claude-sonnet-5", None, "brief")
    check("identical key reuses without a switch", got2 is p2 and fresh2 is False)
    copilot._persist_drop(USER)

    # -- 3. a process that never answers must NOT be adopted -----------------
    # (no monkey patches: the key advances on the runtime's confirmation only)
    deaf = spawn(["-c", "import sys\nfor _ in sys.stdin: pass\n"])
    ent = {"p": deaf, "key": ("claude-sonnet-5", mode)}
    t0 = time.time()
    ok = copilot._persist_switch(ent, ("claude-opus-5", mode))
    dt = time.time() - t0
    check("unconfirmed switch is refused", ok is False)
    check("refused switch leaves the key untouched",
          ent["key"] == ("claude-sonnet-5", mode), "key=%r" % (ent["key"],))
    check("refusal is bounded by the 3s control timeout", dt < 6.0, "took %.2fs" % dt)
    try:
        deaf.kill()
    except Exception:
        pass

    # -- 4. a DEAD process is never handed back ------------------------------
    p3 = spawn([FAKE])
    p3.kill(); p3.wait(timeout=5)
    copilot._persist[USER] = {"p": p3, "key": ("claude-sonnet-5", mode)}
    ent_before = copilot._persist.get(USER)
    switched = copilot._persist_switch(ent_before, ("claude-opus-5", mode))
    check("dead process cannot be switched", switched is False)
    copilot._persist_drop(USER)

    # -- 5. prewarm leaves a LIVE process alone -------------------------------
    # (it must not switch a warm process to its own guess just to have the next
    # real turn switch it back)
    p4 = spawn([FAKE])
    copilot._persist[USER] = {"p": p4, "key": ("claude-sonnet-5", mode)}
    copilot._prewarm_at.pop(USER, None)
    copilot.prewarm(USER, spoken=True)          # would guess haiku
    time.sleep(1.5)                             # it is fire-and-forget
    check("prewarm does not disturb a live process",
          copilot._persist.get(USER) is not None
          and copilot._persist[USER]["p"] is p4
          and copilot._persist[USER]["key"] == ("claude-sonnet-5", mode),
          "key=%r" % ((copilot._persist.get(USER) or {}).get("key"),))
    # ...and it throttles itself against the /chat/history fallback poll
    before = copilot._prewarm_at.get(USER)
    copilot.prewarm(USER, spoken=True)
    check("prewarm is throttled inside the cooldown",
          copilot._prewarm_at.get(USER) == before)
    copilot._persist_drop(USER)
    copilot._prewarm_at.pop(USER, None)

    # -- 6. the live feed says WHICH surface the running turn belongs to ------
    # (card_transcript renders Henry's stream only when it matches - otherwise a
    # board-chat answer would appear inside a card's timeline)
    check("live() reports no card when nothing runs",
          copilot.live(USER).get("card") is None)
    copilot._running[USER] = object()
    copilot._running_card[USER] = "20260902-105701"
    try:
        got_card = copilot.live(USER)
        check("live() reports the running turn's card",
              got_card.get("card") == "20260902-105701" and got_card.get("running") is True)
    finally:
        copilot._running.pop(USER, None)
        copilot._running_card.pop(USER, None)
    check("card clears with the turn", copilot.live(USER).get("card") is None)

    print("")
    if fails:
        print("FAIL (%d): %s" % (len(fails), ", ".join(fails)))
        return 1
    print("PASS - warm chat process switches model instead of respawning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
