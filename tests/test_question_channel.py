# -*- coding: utf-8 -*-
"""Headless test for the QUESTION CHANNEL (Paseo adoption, Phase 2.4).

The trap being closed: HelmDeck runs claude headless, where AskUserQuestion is
not offered at all (verified against CLI 2.1.207 - the model reports the tool
does not exist and no can_use_tool control_request is ever sent). A worker that
needs a decision therefore writes PROSE and ends its turn, and the card parks
with nothing the owner can answer.

What this pins:
 1. ask.parse recovers a typed question from the <helmdeck-ask> block, and the
    block never leaks into the prose the owner reads.
 2. Malformed / degenerate blocks are ignored rather than crashing or rendering
    a dead panel (fewer than 2 options is not a choice).
 3. validate_answers accepts either an offered label OR the owner's own free
    text (the Paseo 'Other' escape hatch, a0853d4/4730f9e) - free text is no
    injection risk, the authenticated owner can /steer any text anyway - while
    still rejecting an EMPTY answer and capping the free text's length.
 4. _settle_reply stores the question, clears a stale one, and spends a repair
    turn exactly when a parked reply looks like a prose question - with the
    repair's spend BILLED (measured-economics law).
 5. answer_question rejects a stale/answered question and otherwise continues
    the SAME session with the decision (a steer), so no turn is lost.

Self-sandboxing: temp sqlite DB + temp events.jsonl/settings.json, and the
driver is faked - no claude process, no network, no board state.
Run: py -3.12 tests/test_question_channel.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-q-")

import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

import ask, claude_sessions, sessions
from actionlog import ActionLog

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


BLOCK = ('<helmdeck-ask>\n'
         '{"questions": [{"question": "Welche Farbe?", "header": "Farbe",'
         ' "options": [{"label": "Rot", "description": "warm"},'
         ' {"label": "Blau", "description": "kuehl"}]}]}\n'
         '</helmdeck-ask>')


def _track(tid, **extra):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "status": "needs_you", "lane": "working", "task": "t",
         "branch": tid, "run_dir": run_dir, "worktree": "", "turns": 1,
         "session_id": "sess-" + tid, "ai_cost": 0.0, "tokens_in": 0,
         "tokens_out": 0, "models": [], "updated": "2026-08-07 00:00:00"}
    t.update(extra)
    db.track_put(t)
    return t


def test_parse():
    print("ask.parse:")
    q, cleaned = ask.parse("Kurz die Abwaegung.\n\n" + BLOCK)
    check(q is not None, "block parsed into a question")
    check(cleaned == "Kurz die Abwaegung.", "prose kept, block stripped (got %r)" % cleaned)
    check(q["kind"] == "question", "default kind is 'question'")
    opts = q["questions"][0]["options"]
    check([o["label"] for o in opts] == ["Rot", "Blau"], "options in order with labels")
    check(q["questions"][0]["header"] == "Farbe", "header carried")

    # a question with one option is not a choice - must not render a dead panel
    one = '<helmdeck-ask>{"questions":[{"question":"X?","options":[{"label":"A"}]}]}</helmdeck-ask>'
    q1, c1 = ask.parse(one)
    check(q1 is None, "single-option question rejected")
    check("<helmdeck-ask" not in c1, "rejected block still stripped from the prose")

    bad = "Text\n<helmdeck-ask>{not json at all}</helmdeck-ask>"
    q2, c2 = ask.parse(bad)
    check(q2 is None and c2 == "Text", "malformed JSON ignored, prose preserved")

    check(ask.parse("no block here") == (None, "no block here"), "plain reply untouched")

    # duplicate labels would render two identical buttons
    dup = ('<helmdeck-ask>{"questions":[{"question":"X?","options":['
           '{"label":"A"},{"label":"A"},{"label":"B"}]}]}</helmdeck-ask>')
    qd, _ = ask.parse(dup)
    check(qd and [o["label"] for o in qd["questions"][0]["options"]] == ["A", "B"],
          "duplicate option labels collapsed")


def test_stream_strip():
    print("ask.strip_stream (live feed):")
    check(ask.strip_stream("Prosa\n<helmdeck-ask>\n{\"quest") == "Prosa",
          "unterminated block hidden while streaming")
    check(ask.strip_stream("Prosa <helmdec") == "Prosa",
          "half-typed opening tag hidden")
    check(ask.strip_stream("Prosa ohne Block") == "Prosa ohne Block",
          "ordinary streaming text untouched")


def test_validate():
    print("ask.validate_answers:")
    q, _ = ask.parse(BLOCK)
    picks, err = ask.validate_answers(q, {"Farbe": "Rot"})
    check(not err and picks[0]["labels"] == ["Rot"], "valid pick accepted")
    check("Rot" in ask.answer_prompt(picks), "answer prompt carries the choice")

    # Free text is now ACCEPTED as the owner's own answer (the 'Other' hatch):
    # it lands in `custom`, not `labels`, and answer_prompt quotes it so the
    # worker can tell a typed answer from a preset pick.
    p2, e2 = ask.validate_answers(q, {"Farbe": "irgendwas eigenes"})
    check(not e2 and p2[0]["custom"] == ["irgendwas eigenes"] and not p2[0]["labels"],
          "free text accepted as the owner's own answer")
    check('"irgendwas eigenes"' in ask.answer_prompt(p2), "free text quoted in the answer prompt")
    # An EMPTY / whitespace answer is still rejected - nothing to answer with.
    _p, e2b = ask.validate_answers(q, {"Farbe": "   "})
    check(e2b and _p is None, "empty answer rejected")
    # Free text is length-capped (a model/client can't shove an unbounded blob).
    p2c, _ = ask.validate_answers(q, {"Farbe": "x" * (ask.MAX_FREE_LEN + 5000)})
    check(p2c and len(p2c[0]["custom"][0]) == ask.MAX_FREE_LEN, "free text length-capped")
    # a real multi-paragraph answer (well under the cap) must NOT be truncated -
    # the whole point of raising MAX_FREE_LEN past a steer-sized paste.
    long_answer = ("Absatz eins. " * 400).strip()   # ~5200 chars, still < MAX_FREE_LEN
    p2d, e2d = ask.validate_answers(q, {"Farbe": long_answer})
    check(not e2d and p2d[0]["custom"] == [long_answer],
          "a long pasted answer is kept whole, not truncated mid-sentence")
    _p, e3 = ask.validate_answers(q, {})
    check(e3 and _p is None, "missing answer rejected")
    _p, e4 = ask.validate_answers(q, {"Farbe": ["Rot", "Blau"]})
    check(_p and _p[0]["labels"] == ["Rot"], "single-select keeps one label")


def test_heuristic():
    print("ask.looks_like_question (when to spend a repair turn):")
    check(ask.looks_like_question("Soll ich A oder B nehmen?"), "prose question detected")
    check(not ask.looks_like_question(
        "DELIVERED: fertig.\nReady for Review - move the card to Review; accepting it deploys."),
        "a DELIVERED turn never triggers a repair turn")
    check(not ask.looks_like_question("Fertig. Datei liegt in src/."),
          "plain completion does not trigger a repair turn")


def test_settle_and_repair():
    print("_settle_reply:")
    t = _track("t-q")
    log = ActionLog(t["run_dir"])

    reason = sessions._settle_reply(t, "Abwaegung.\n\n" + BLOCK, log)
    check(reason == "question", "reply with a block reports the 'question' reason")
    check(t["question"]["questions"][0]["header"] == "Farbe", "question stored on the card")
    check("<helmdeck-ask" not in t["last_reply"], "raw protocol never lands in last_reply")

    # a later turn that does NOT ask must clear the stale panel
    reason = sessions._settle_reply(t, "Fertig, alles gebaut. DELIVERED", log)
    check(reason == "needs_you" and "question" not in t,
          "a non-asking turn clears the stale question")

    print("_settle_reply repair path:")
    calls = []
    orig_turn = sessions._turn

    def fake_turn(track, prompt, model=None, perm=None):
        calls.append(prompt)
        return "sess", BLOCK, {"usage": {"input_tokens": 10, "output_tokens": 5},
                               "cost_usd": 0.25, "models": ["m"]}

    sessions._turn = fake_turn
    try:
        t2 = _track("t-repair")
        reason = sessions._settle_reply(t2, "Soll ich A oder B nehmen?", log)
        check(len(calls) == 1 and ask.REPAIR in calls[0], "one repair turn spent")
        check(reason == "question", "prose question repaired into a typed question")
        check(t2["question"]["questions"][0]["header"] == "Farbe", "repaired question stored")
        # billing goes through sessions._mutate to the STORE (the one write
        # path, P3.4) - the caller's local dict is deliberately left stale.
        t2s = db.track_get("t-repair")
        check(t2s["ai_cost"] > 0 and t2s["tokens_out"] == 5,
              "repair turn is BILLED (measured economics) - cost %r" % t2s["ai_cost"])

        # a worker that declines must not leave a phantom question
        calls.clear()
        sessions._turn = lambda track, prompt, model=None, perm=None: (
            "sess", ask.NO_QUESTION, {"usage": {}, "cost_usd": 0, "models": []})
        t3 = _track("t-noq")
        reason = sessions._settle_reply(t3, "Soll ich A oder B nehmen?", log)
        check(reason == "needs_you" and "question" not in t3,
              "NOQUESTION leaves the card as an ordinary needs_you")

        # a DELIVERED turn must not spend a repair turn at all
        calls.clear()
        sessions._turn = fake_turn
        t4 = _track("t-done")
        sessions._settle_reply(t4, "DELIVERED - fertig. Ready for Review", log)
        check(not calls, "no repair turn spent on delivered work")

        # kill-switch
        calls.clear()
        events.save_settings({"policy": {"ask_repair": False}})
        t5 = _track("t-off")
        sessions._settle_reply(t5, "Soll ich A oder B nehmen?", log)
        check(not calls, "policy.ask_repair=false disables the repair turn")
        events.save_settings({"policy": {"ask_repair": True}})
    finally:
        sessions._turn = orig_turn


def test_answer():
    print("answer_question:")
    t = _track("t-ans")
    log = ActionLog(t["run_dir"])
    sessions._settle_reply(t, BLOCK, log)
    sessions._save_track(t)
    qid = t["question"]["id"]

    steers = []
    orig = sessions.steer
    sessions.steer = lambda tid, text, **kw: steers.append((tid, text, kw)) or {"id": tid}
    try:
        sessions.answer_question("t-ans", {"Farbe": "Blau"}, request_id=qid)
        check(len(steers) == 1, "answering continues the session with a steer")
        check("Blau" in steers[0][1], "the steer carries the chosen option")
        check(steers[0][2].get("source") == "answer", "steer tagged as an answer")

        # stale panel (already answered / worker asked again)
        stale = False
        try:
            sessions.answer_question("t-ans", {"Farbe": "Blau"}, request_id="q-stale")
        except RuntimeError:
            stale = True
        check(stale, "a stale request_id is rejected")

        # no pending question at all
        t2 = _track("t-none")
        none = False
        try:
            sessions.answer_question("t-none", {"Farbe": "Blau"})
        except RuntimeError:
            none = True
        check(none, "answering a card with no question is rejected")
    finally:
        sessions.steer = orig


def test_harness_turns_are_not_the_owner():
    """A turn the HARNESS starts must never read as the owner's own message.

    The repair prompt and the auto-continue are fed in as role=user (the only
    way to send a message), so without re-attribution the owner reads
    "STOP - do not continue the work" in his own voice - the same defect Claude
    Code's task-notification envelopes already had."""
    print("harness-injected turns:")
    import json as _json, tempfile as _tmp
    check(ask.harness_tag(ask.REPAIR) == "ask-repair", "the repair prompt is tagged")
    check(ask.harness_tag(sessions._continue_prompt()) == "background-done",
          "the auto-continue prompt is tagged")
    check(ask.harness_tag("Bau das bitte fertig") is None,
          "a human's message carries no tag")
    check(ask.harness_tag(None) is None, "non-string input is handled")

    proj = os.path.join(_tmp.mkdtemp(), "proj")
    os.makedirs(proj)
    old = claude_sessions.PROJECTS
    claude_sessions.PROJECTS = os.path.dirname(proj)
    try:
        recs = [{"type": "user", "message": {"role": "user", "content": "Bau die Maske"}},
                {"type": "user", "message": {"role": "user", "content": ask.REPAIR}},
                {"type": "user", "message": {"role": "user",
                                             "content": sessions._continue_prompt()}}]
        with open(os.path.join(proj, "h1.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(_json.dumps(r) for r in recs))
        steps = claude_sessions.read_transcript("h1")
        kinds = [(s.get("kind"), s.get("role")) for s in steps]
        check(kinds[0] == ("text", "user"), "the owner's own message stays his")
        check(all(k == "system" for k, _r in kinds[1:]),
              "both harness turns render as system notes (got %r)" % kinds[1:])
        check(all("STOP" not in (s.get("text") or "") for s in steps),
              "the raw harness instruction never reaches the feed")
    finally:
        claude_sessions.PROJECTS = old


def test_delivered_predicate():
    """The wiring that keeps the rest of the harness honest.

    Every automation that reads status == needs_you as "the worker is done"
    must go through sessions.is_delivered, or it will auto-accept a card that is
    still ASKING (merging an unfinished branch and discarding the question) or
    announce a background wait as delivered work."""
    print("is_delivered / waits_for_owner:")
    plain = {"status": "needs_you"}
    asking = {"status": "needs_you", "question": {"id": "q-1", "questions": []}}
    bg = {"status": "needs_you", "waiting_on": "background",
          "background": {"n": 1}}

    check(sessions.is_delivered(plain), "a plain parked card IS delivered work")
    check(not sessions.is_delivered(asking),
          "a card with a pending question is NOT delivered (never auto-accept it)")
    check(not sessions.is_delivered(bg),
          "a card waiting on a background task is NOT delivered")
    check(not sessions.is_delivered({"status": "running"}), "a running card is not delivered")
    check(not sessions.is_delivered({"status": "bounced"}), "a bounced card is not delivered")
    check(not sessions.is_delivered(None), "None is handled")

    check(sessions.waits_for_owner(plain), "a parked card wants the owner")
    check(sessions.waits_for_owner(asking), "an asking card wants the owner")
    check(sessions.waits_for_owner({"status": "bounced"}), "a bounced card wants the owner")
    check(not sessions.waits_for_owner(bg),
          "a background wait is NOT the owner's move")


test_parse()
test_harness_turns_are_not_the_owner()
test_delivered_predicate()
test_stream_strip()
test_validate()
test_heuristic()
test_settle_and_repair()
test_answer()

print()
if _fails:
    print("FAILED: %d check(s): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("ALL QUESTION-CHANNEL CHECKS PASSED")
