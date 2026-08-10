# -*- coding: utf-8 -*-
"""The QUESTION CHANNEL - a worker may ask the owner a typed multiple-choice
question instead of writing prose and parking (Paseo adoption, Phase 2.4).

WHY THIS IS NOT AN AskUserQuestion INTERCEPTOR
----------------------------------------------
The adoption plan says "intercept AskUserQuestion in the worker's stream-json".
That premise was tested against the claude CLI we actually ship against
(2.1.207, driven `-p --input-format stream-json` exactly like drivers.py) and it
is FALSE: headless sessions are not offered AskUserQuestion at all - the model
reports the tool does not exist - and the CLI never sends a
`control_request/can_use_tool` to the stdin client (an SDK `initialize`
handshake does not unlock it either). So a stream interceptor would be
unreachable code. Paseo can do it only because it drives the Agent SDK with a
`canUseTool` callback, which a raw stream-json driver does not have.

What the worker ACTUALLY does when it needs a decision is write the question as
prose and end the turn - which is precisely the "parks / waiting to be done"
trap. So we fix it where the behaviour really is: we TEACH the worker a
machine-readable ask protocol (`BRIEF` below is appended to its system prompt)
and parse that back out of its reply.

THE PROTOCOL
------------
The worker ends its turn with one block:

    <helmdeck-ask>
    {"questions": [{"question": "Which colour?", "header": "Colour",
                    "options": [{"label": "Red", "description": "warm"},
                                {"label": "Blue", "description": "cool"}]}]}
    </helmdeck-ask>

The owner picks in the app; `answer_prompt()` turns the pick into the next
steer, so the SAME session continues via `--resume` with the decision in hand.
No turn is lost and the card never parks on an unanswerable prose question.

Everything here is defensive: the payload is model-generated, so every field is
bounded and validated, and a malformed block is simply ignored (the reply then
renders as ordinary prose - the old behaviour, never a crash).
"""
import json, re, time

# tool|plan|question|mode - the typed card state (Paseo's permission kinds).
# `question` is what the worker asks for itself; the others exist so the same
# channel can carry a plan approval or a mode escalation without a second
# mechanism.
KINDS = ("tool", "plan", "question", "mode")
DEFAULT_KIND = "question"

MAX_QUESTIONS = 4          # matches the AskUserQuestion contract
MAX_OPTIONS = 6
MAX_Q_LEN = 400
MAX_HEADER_LEN = 24
MAX_LABEL_LEN = 80
MAX_DESC_LEN = 300
MAX_BLOCK = 8000           # refuse to parse an absurd block

_BLOCK = re.compile(r"<helmdeck-ask>\s*(.*?)\s*</helmdeck-ask>", re.S | re.I)

# Taught to every card worker via --append-system-prompt (drivers.py). Kept
# short on purpose: it competes for attention with the rest of the brief.
BRIEF = (
    "ASKING THE OWNER - HARD RULE. Your turn may end with a question for the "
    "owner ONLY if the very LAST thing in your reply is a <helmdeck-ask> block. "
    "HelmDeck is asynchronous: the owner sees a CARD, not a terminal. A "
    "question written only as prose gives him nothing to tap, so the card parks "
    "unanswered and the work stalls. Ending a turn on a prose question is a "
    "DEFECT, not a hand-off.\n"
    "Write your reasoning and your recommendation as normal prose FIRST, then "
    "close the turn with exactly this block and nothing after it:\n"
    "<helmdeck-ask>\n"
    '{\"questions\": [{\"question\": \"<the full question>\", '
    '\"header\": \"<max 24 chars>\", \"options\": ['
    '{\"label\": \"<short choice>\", \"description\": \"<what it means>\"}, '
    '{\"label\": \"<short choice>\", \"description\": \"<what it means>\"}]}]}\n'
    "</helmdeck-ask>\n"
    "2-6 options per question, at most 4 questions, valid JSON. Make your "
    "recommended course one of the options. The owner taps a real button and "
    "his choice arrives as your next message, so you continue exactly where you "
    "stopped. Only ask when you are truly blocked on a DECISION only he can "
    "make - anything you can find out yourself, find out yourself."
)


# HARNESS-INJECTED PROMPTS
# ------------------------
# Some turns are started by the harness itself, not by the owner: the repair
# turn below, and the auto-continue after a background task finishes. Claude
# Code records them as role=user (that is the only way to feed a message in), so
# without a marker the card feed shows them as messages the OWNER typed - the
# owner reading "STOP - do not continue the work" in his own voice. Claude
# Code's own injected envelopes (task notifications, slash commands) are
# re-attributed for exactly this reason; ours must be too.
#
# The tag is the first line, so claude_sessions can re-attribute the message to
# a short neutral system note (and the worker sees an honest "this is the
# harness talking" header).
HARNESS_PREFIX = "[[helmdeck:"


def harness_msg(tag, text):
    """Wrap a prompt the HARNESS is sending on its own initiative."""
    return "%s%s]]\n%s" % (HARNESS_PREFIX, tag, text)


def harness_tag(text):
    """The tag of a harness-injected message, or None for a human's message."""
    if not isinstance(text, str):
        return None
    lead = text.lstrip()
    if not lead.startswith(HARNESS_PREFIX):
        return None
    end = lead.find("]]")
    return lead[len(HARNESS_PREFIX):end] if end != -1 else None


# The REPAIR turn. System-prompt compliance alone is unreliable - a worker that
# needs a decision reliably writes prose and stops (measured). So when a turn
# parks on what looks like an open question, the harness asks ONCE, as the
# immediate instruction, for the same question in protocol form. Deliberately
# narrow: restate, decide nothing, do no work.
REPAIR = harness_msg(
    "ask-repair",
    "STOP - do not continue the work and do not change any files.\n"
    "Your last turn ended with an open question for the owner, but not in the "
    "form he can answer. HelmDeck can only render real buttons from a "
    "<helmdeck-ask> block.\n"
    "Reply with NOTHING except that block, restating the SAME open question and "
    "the concrete choices you already described:\n"
    "<helmdeck-ask>\n"
    '{\"questions\": [{\"question\": \"<the full question>\", '
    '\"header\": \"<max 24 chars>\", \"options\": ['
    '{\"label\": \"<short choice>\", \"description\": \"<what it means>\"}, '
    '{\"label\": \"<short choice>\", \"description\": \"<what it means>\"}]}]}\n'
    "</helmdeck-ask>\n"
    "2-6 options, valid JSON, no prose before or after. If your last turn had "
    "no open question after all, reply with exactly: NOQUESTION"
)

NO_QUESTION = "NOQUESTION"

# Cheap gate for "this parked reply is really an open question". A MISS costs
# nothing (the card behaves exactly as it did before this feature); a false
# positive costs one short repair turn that the worker answers with NOQUESTION.
# So this is deliberately biased towards asking.
_ASK_HINT = re.compile(
    r"\b(?:entscheid\w*|blocker|rueckfrage|rückfrage|sag mir|antworte mit|"
    r"welche[srn]?\b|wie soll|soll ich|brauche deine|deine entscheidung|"
    r"which (?:one|option|of)|should i|shall i|let me know|your call|"
    r"waiting on you|need(?:s)? (?:your|a) decision)\b", re.I)

# The worker is told to end finished work exactly this way (drivers._CARD_BRIEF),
# so a delivered turn is recognisable without a model call.
_DONE_HINT = re.compile(r"\bDELIVERED\b|Ready for Review", re.I)


def looks_like_question(text):
    """True when a turn that just parked appears to be waiting on a DECISION,
    and is therefore worth one repair turn to convert into real buttons.

    Only the tail is inspected: a reply that merely discusses questions earlier
    on ("the open questions were X, I resolved them") is not an ask - what
    matters is how the turn ENDS, because that is what the owner is left with."""
    if not isinstance(text, str) or not text.strip():
        return False
    if _DONE_HINT.search(text):
        return False               # finished work, not a question
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    tail = " ".join(lines[-4:])
    return "?" in tail or bool(_ASK_HINT.search(tail))


def _clip(v, n):
    return str(v).strip()[:n]


def _options(raw):
    """Normalize an options list. Accepts plain strings or {label,description}.
    Returns [] when nothing usable is left, which invalidates the question."""
    out = []
    for o in (raw or [])[:MAX_OPTIONS]:
        if isinstance(o, str):
            label, desc = _clip(o, MAX_LABEL_LEN), ""
        elif isinstance(o, dict):
            label = _clip(o.get("label") or o.get("value") or "", MAX_LABEL_LEN)
            desc = _clip(o.get("description") or o.get("desc") or "", MAX_DESC_LEN)
        else:
            continue
        if not label:
            continue
        if any(x["label"] == label for x in out):   # a duplicate button is a bug, not a choice
            continue
        out.append({"label": label, "description": desc})
    return out


def _question(raw, idx):
    if not isinstance(raw, dict):
        return None
    text = _clip(raw.get("question") or raw.get("text") or "", MAX_Q_LEN)
    if not text:
        return None
    opts = _options(raw.get("options"))
    if len(opts) < 2:
        # A "choice" with fewer than two options is not a choice - reject it so
        # the worker's prose still reaches the owner instead of a dead panel.
        return None
    header = _clip(raw.get("header") or "", MAX_HEADER_LEN) or _clip(text, MAX_HEADER_LEN)
    return {"question": text, "header": header, "options": opts,
            "multiSelect": bool(raw.get("multiSelect")), "idx": idx}


def parse(text):
    """(question, cleaned_text). `question` is the typed card state or None;
    `cleaned_text` is the reply with the machine block removed, so the feed
    shows the worker's prose and never raw JSON."""
    if not isinstance(text, str) or "<helmdeck-ask" not in text.lower():
        return None, text
    m = _BLOCK.search(text)
    if not m:
        return None, text
    body = m.group(1).strip()
    cleaned = strip(text)
    if len(body) > MAX_BLOCK:
        return None, cleaned
    # tolerate a fenced block inside the sentinel (```json ... ```)
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", body).strip()
    try:
        d = json.loads(body)
    except ValueError:
        return None, cleaned
    if isinstance(d, list):
        d = {"questions": d}
    if not isinstance(d, dict):
        return None, cleaned
    raw_qs = d.get("questions")
    if raw_qs is None and (d.get("question") or d.get("text")):
        raw_qs = [d]                       # single-question shorthand
    if not isinstance(raw_qs, list):
        return None, cleaned
    qs = []
    for i, rq in enumerate(raw_qs[:MAX_QUESTIONS]):
        q = _question(rq, len(qs))
        if q:
            qs.append(q)
    if not qs:
        return None, cleaned
    kind = str(d.get("kind") or DEFAULT_KIND)
    if kind not in KINDS:
        kind = DEFAULT_KIND
    return {"id": "q-%d" % int(time.time() * 1000), "kind": kind, "questions": qs,
            "asked": time.strftime("%Y-%m-%d %H:%M:%S"), "ta": time.time()}, cleaned


def strip(text):
    """Remove the machine block from a reply (feed/transcript rendering)."""
    if not isinstance(text, str) or "<helmdeck-ask" not in text.lower():
        return text
    return _BLOCK.sub("", text).strip()


_OPEN_TAG = "<helmdeck-ask>"


def strip_stream(text):
    """Streaming variant of strip(), for the live partial feed.

    While the worker is still typing the block, its CLOSING tag has not arrived
    yet, so strip() (which needs a complete block) would let the raw JSON appear
    in the card feed character by character. Cut from the opening tag onward,
    and also drop a half-typed opening tag so the owner never sees `<helmdec`
    flicker at the end of the reply."""
    if not isinstance(text, str) or not text:
        return text
    text = strip(text)
    low = text.lower()
    i = low.find(_OPEN_TAG)
    if i != -1:
        return text[:i].rstrip()
    j = text.rfind("<")
    if j != -1 and _OPEN_TAG.startswith(low[j:]):
        return text[:j].rstrip()
    return text


def summary(question):
    """One short line for the actionlog, the board and a push body."""
    qs = (question or {}).get("questions") or []
    if not qs:
        return ""
    head = qs[0]["question"]
    return head + (" (+%d)" % (len(qs) - 1) if len(qs) > 1 else "")


MAX_FREE_LEN = 2000        # the owner's own words - matches a steer's freedom


def validate_answers(question, answers):
    """(picks, error). `answers` maps question header -> chosen answer(s); a list
    is accepted for multiSelect.

    An answer is EITHER one of the labels the worker offered OR the owner's own
    free text (the Paseo 'Other' escape hatch). Free text used to be rejected
    here 'so the client cannot inject arbitrary text into the worker's next
    prompt' - but that guard was moot: the owner is the authenticated principal
    and can already inject any text he likes through /steer. Blocking it here
    only cost him the ability to answer with anything the worker failed to
    foresee, which is exactly what he asked to have back. Free text is length-
    capped and tagged as HIS words in answer_prompt so the worker can tell a
    typed answer from a preset pick."""
    if not isinstance(answers, dict):
        return None, "answers must be an object"
    qs = (question or {}).get("questions") or []
    picks = []
    for q in qs:
        got = answers.get(q["header"])
        if got is None:
            got = answers.get(q["question"])
        if got is None:
            return None, "missing answer for '%s'" % q["header"]
        chosen = got if isinstance(got, list) else [got]
        valid = {o["label"] for o in q["options"]}
        labels, custom = [], []
        for c in chosen:
            s = str(c).strip()
            if not s:
                continue
            if s in valid:
                if s not in labels:
                    labels.append(s)
            elif s not in custom:
                custom.append(s[:MAX_FREE_LEN])
        if not labels and not custom:
            return None, "no answer given for '%s'" % q["header"]
        if not q.get("multiSelect"):
            # single-select: exactly one answer. A preset pick wins if both
            # somehow arrive, otherwise the one typed answer stands.
            if labels:
                labels, custom = labels[:1], []
            else:
                custom = custom[:1]
        picks.append({"question": q["question"], "header": q["header"],
                      "labels": labels, "custom": custom})
    if not picks:
        return None, "nothing to answer"
    return picks, ""


def _pick_parts(p):
    """Rendered answer fragments for a pick: preset labels verbatim, free text
    quoted so the worker sees it is the owner's own phrasing, not an option."""
    return list(p.get("labels", [])) + ['"%s"' % c for c in p.get("custom", [])]


def answer_prompt(picks):
    """The next steer text. Phrased as the owner's decision plus an explicit
    'carry on' so the worker RESUMES the work it stopped for instead of
    treating the answer as a fresh, contextless instruction."""
    lines = ["[Antwort auf deine Rueckfrage]"]
    for p in picks:
        lines.append("%s -> %s" % (p["question"], ", ".join(_pick_parts(p))))
    lines.append("")
    lines.append("Arbeite mit dieser Entscheidung genau dort weiter, wo du "
                 "aufgehoert hast. Frag nicht erneut nach dem, was hier "
                 "beantwortet ist.")
    return "\n".join(lines)


def answer_note(picks):
    """The audit line recorded in the card's flight recorder."""
    return "FRAGE beantwortet: " + "; ".join(
        "%s -> %s" % (p["header"], ", ".join(_pick_parts(p))) for p in picks)
