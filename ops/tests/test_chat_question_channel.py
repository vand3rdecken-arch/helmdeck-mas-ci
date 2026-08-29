# -*- coding: utf-8 -*-
"""Headless test for the question channel on the BOARD CHAT side.

The defect this closes (owner screenshot, 2026-08-29 17:56, phone): the Henry
chat rendered a raw `<helmdeck-ask>` block - tags and JSON - as message text,
with nothing to tap.

Why it reached the phone at all, since board-copilot.md sets ask_protocol:false:
/wear/talk and /glance/talk run WEAR_BRIEF / GLASS_BRIEF through the SAME
copilot.chat on the SAME session, and both of those briefs REQUIRE the block.
One session, one copilot_log, three surfaces. The watch stripped it on read
(routes_wear.wear_chat_get); the phone's /chat/history never did, and
copilot.chat itself only ever stripped the ```actions fence.

What this pins:
 1. The block is parsed at EVENT TIME into prose + a typed question, so the
    chat log stores what the owner reads and what he taps - never the grammar.
 2. copilot._readable cleans entries written before that existed, WITHOUT
    rewriting the append-only log, and a MALFORMED block is hidden rather than
    shown raw (the brief's fallback rule).
 3. copilot.open_question derives Henry's open question from the log - newest,
    unsettled - and never claims a mirrored CARD question, which belongs to
    that card's door.
 4. routes_copilot._answer_text turns a tapped option into the owner's next
    message, and refuses a stale, unknown or empty answer.
 5. copilot.live strips a HALF-TYPED block, so the JSON never streams in
    character by character (card parity: claude_sessions.read_transcript_live).

Self-sandboxing: CHATLOG/SESS and the run dir are redirected into a temp dir -
no daemon state is read or written, no claude process, no network.
Run: py -3.12 ops/tests/test_chat_question_channel.py
"""
import copy, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-chatq-")

from spine.ops import ask
from cells.copilot import copilot, routes_copilot

# Redirect the ONLY two files this module reads/writes before anything touches
# them. _log() opens CHATLOG directly, so this is the whole isolation.
copilot.CHATLOG = os.path.join(SANDBOX, "copilot_log.json")
copilot.SESS = os.path.join(SANDBOX, "copilot_sessions.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


BLOCK = ('<helmdeck-ask>\n'
         '{"questions": [{"question": "Womit soll ich weitermachen?",'
         ' "header": "Naechstes", "options": ['
         '{"label": "Deploy", "description": "OTA rausschicken"},'
         ' {"label": "Warten", "description": "erst review"}]}]}\n'
         '</helmdeck-ask>')
REPLY = "Beide Karten sind gruen.\n\n" + BLOCK

USER = {"name": "owner", "role": "owner"}


def _seed(entries):
    """Put a chat log in place, exactly as _append_log would have left it."""
    import json
    with open(copilot.CHATLOG, "w", encoding="utf-8") as f:
        json.dump({"owner": entries}, f)


def _bot(text, question=None, **extra):
    e = {"cls": "bot", "text": text, "ts": "17:56"}
    if question:
        e["question"] = question
    e.update(extra)
    return e


# ---------------------------------------------------------------- 1. parse
def test_parse():
    print("\n[parse] the block becomes prose + typed question")
    q, prose = ask.parse(REPLY)
    check(q is not None, "a question is recovered from Henry's reply")
    check("helmdeck-ask" not in prose.lower(), "the prose carries no sentinel")
    check("{" not in prose, "the prose carries no JSON")
    check(prose.strip() == "Beide Karten sind gruen.", "the prose is what he said")
    check([o["label"] for o in q["questions"][0]["options"]] == ["Deploy", "Warten"],
          "both options survive, in order")
    # A reply that is ONLY a block still has to say something - copilot.chat
    # falls back to summary() rather than logging an empty bubble.
    only_q, only_prose = ask.parse(BLOCK)
    check(not only_prose.strip(), "a block-only reply leaves no prose")
    check(ask.summary(only_q) == "Womit soll ich weitermachen?",
          "summary() is the honest text for a block-only reply")


# ------------------------------------------------------------- 2. _readable
def test_readable():
    print("\n[_readable] legacy entries are cleaned on READ, never rewritten")
    raw = _bot(REPLY)                       # what the log already holds
    stored = copy.deepcopy(raw)
    out = copilot._readable(raw)
    check("helmdeck-ask" not in (out["text"] or "").lower(),
          "the stored block is gone from what the app receives")
    check(out["text"] == "Beide Karten sind gruen.", "the prose is kept intact")
    check(raw == stored, "the log ENTRY itself is untouched (append-only)")

    check(copilot._readable(_bot("nur text"))["text"] == "nur text",
          "an ordinary reply passes through unchanged")
    check(copilot._readable({"cls": "you", "text": REPLY})["text"] == REPLY,
          "only Henry's own entries are cleaned - a `you` entry is the owner's "
          "words verbatim")

    block_only = copilot._readable(_bot(BLOCK))
    check(block_only["text"] == "Womit soll ich weitermachen?",
          "a legacy block-only reply reads back as the question's first line")

    # THE FALLBACK RULE: a block that cannot be parsed is HIDDEN, not shown.
    broken = copilot._readable(_bot('<helmdeck-ask>\n{"questions": [{"quest'))
    check("helmdeck-ask" not in (broken["text"] or "").lower()
          and "{" not in (broken["text"] or ""),
          "a MALFORMED block never reaches the screen as raw text")
    check(not (broken["text"] or "").strip(),
          "and it leaves the entry empty, so the app drops the bubble")

    half = copilot._readable(_bot("Kurz vorweg. <helmdeck-ask>{\"questi"))
    check(half["text"] == "Kurz vorweg.",
          "a truncated block is cut, the prose before it survives")


def test_history_is_clean():
    print("\n[history] /chat/history serves cleaned text")
    _seed([{"cls": "you", "text": "status?", "ts": "17:55"}, _bot(REPLY)])
    msgs = copilot.history("owner")["messages"]
    check(all("helmdeck-ask" not in (m.get("text") or "").lower() for m in msgs),
          "no message the phone receives carries the sentinel")
    check(copilot._log()["owner"][1]["text"] == REPLY,
          "the file on disk still holds the original - the record is not edited")


# --------------------------------------------------------- 3. open_question
def test_open_question():
    print("\n[open_question] derived from the log, newest and unsettled")
    q, _ = ask.parse(REPLY)

    _seed([_bot("Beide Karten sind gruen.", question=q)])
    check((copilot.open_question("owner") or {}).get("id") == q["id"],
          "Henry's question is open while nothing has been said since")

    _seed([_bot("...", question=q), {"cls": "you", "text": "Deploy", "ts": "17:57"}])
    check(copilot.open_question("owner") is None,
          "the owner speaking settles it")

    _seed([_bot("...", question=q), _bot("Schon erledigt.")])
    check(copilot.open_question("owner") is None,
          "Henry speaking again settles it")

    # A mirrored CARD question rides `cls:"card"` and is answered on the card
    # (sessions.answer_question). Claiming it here would answer a worker's
    # question with a Henry turn.
    _seed([{"cls": "card", "text": "Welche Farbe?", "card": "t1",
            "kind": "question", "question": q, "ts": "17:56"}])
    check(copilot.open_question("owner") is None,
          "a mirrored CARD question is NOT Henry's to answer")

    _seed([])
    check(copilot.open_question("owner") is None, "an empty log has no question")


# --------------------------------------------------------- 4. the answer door
def test_answer_text():
    print("\n[_answer_text] a tapped option becomes the owner's next message")
    q, _ = ask.parse(REPLY)
    _seed([_bot("Beide Karten sind gruen.", question=q)])

    text, err, code = routes_copilot._answer_text(USER, q["id"], {"Naechstes": "Deploy"})
    check(not err and text == "Deploy", "the chosen label IS the message")

    text, err, _c = routes_copilot._answer_text(
        USER, q["id"], {"Naechstes": "erst die Tests gruen kriegen"})
    check(not err and text == "erst die Tests gruen kriegen",
          "free text passes through as the owner's own words, unquoted")

    _t, err, code = routes_copilot._answer_text(USER, "q-999", {"Naechstes": "Deploy"})
    check(err and code == 409, "a stale request_id is refused (409), not answered")

    _t, err, code = routes_copilot._answer_text(USER, q["id"], {"Naechstes": ""})
    check(err and code == 400, "an empty answer is refused (400)")

    _t, err, code = routes_copilot._answer_text(USER, q["id"], {"Falsch": "Deploy"})
    check(err and code == 400, "an answer to a question he never asked is refused")

    _seed([_bot("nur text")])
    _t, err, code = routes_copilot._answer_text(USER, q["id"], {"Naechstes": "Deploy"})
    check(err and code == 409, "answering when nothing is open is refused (409)")


def test_answer_wording():
    print("\n[chat_answer_text] reads as a message, not as a card steer")
    picks = [{"question": "Womit weiter?", "header": "Naechstes",
              "labels": ["Deploy"], "custom": []}]
    one = ask.chat_answer_text(picks)
    check(one == "Deploy", "one question -> just the answer")
    check("Rueckfrage" not in one and "Arbeite" not in one,
          "NOT answer_prompt's card-worker wording (that one orders a parked "
          "session to resume; a chat turn has no such state)")

    two = ask.chat_answer_text(picks + [
        {"question": "Wann?", "header": "Zeitpunkt", "labels": ["Heute"], "custom": []}])
    check(two == "Naechstes: Deploy; Zeitpunkt: Heute",
          "two questions -> each answer keeps its header, so neither is ambiguous")

    multi = ask.chat_answer_text([{"question": "?", "header": "H",
                                   "labels": ["A", "B"], "custom": ["C"]}])
    check(multi == "A, B, C", "multiSelect + free text all ride the one message")


# ------------------------------------------------------------------ 5. live
def test_live_stream():
    print("\n[live] a half-typed block never streams in")
    run = os.path.join(SANDBOX, "run")
    os.makedirs(run, exist_ok=True)
    copilot._copilot_run_dir = lambda user: run          # sandboxed, no daemon dir

    def _partial(text):
        with open(os.path.join(run, "live_partial.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        return copilot.live("owner")["text"]

    check(_partial("Beide Karten sind gruen.\n\n<helmdeck-ask>\n{\"questions\": [{")
          == "Beide Karten sind gruen.",
          "the JSON is cut while it is still being typed")
    check(_partial("Beide Karten sind gruen.\n\n<helmdec")
          == "Beide Karten sind gruen.",
          "even a half-typed OPENING tag never flickers on screen")
    check(_partial(REPLY) == "Beide Karten sind gruen.",
          "a completed block is stripped too")
    check(_partial("Alles gruen.") == "Alles gruen.",
          "an ordinary partial is untouched")


test_parse()
test_readable()
test_history_is_clean()
test_open_question()
test_answer_text()
test_answer_wording()
test_live_stream()

print()
if _fails:
    print("FAILED: %d check(s): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("ALL CHAT-QUESTION-CHANNEL CHECKS PASSED")
