# -*- coding: utf-8 -*-
"""The LIVE state of a spoken turn on the glasses - the one fact the lens cannot
derive for itself.

WHY THIS EXISTS. The glasses voice loop is real and shipped, and it runs
completely PAST the lens: the phone's GlassVoiceService opens the glasses mic
over Bluetooth HFP, hands the recognised words to `POST /glance/talk`, plays the
returned clip and re-listens. The webapp on the lens is not in that path at any
point. So the owner, wearing the display, could not see that anything was
listening (the only status surface is the service's Android foreground
notification - which is on the phone in his pocket; surfaces/app/src/app/chat.tsx
says it outright: the glasses button is "an AFFORDANCE, not a status") and never
saw the words that were about to be sent in his name.

This module is the missing half. It does NOT add a second conversation channel -
the conversation is still exactly one `copilot.chat` session reached through
`/glance/talk`, the same one the phone and the watch read. It publishes the
STATE of that conversation so the lens can show it.

THE LAW THIS FILE IS WRITTEN AGAINST (CLAUDE.md, "NO MONKEY PATCHES"):
load-bearing state is DERIVED and VERIFIED from the runtime's own signals,
folded in at EVENT TIME, mutated at exactly ONE owner. So:

  - `_set` below is the only writer, and it is the only thing that bumps the
    cursor. Nothing reconstructs this by re-scanning the chat log.
  - every transition is named by the party that OBSERVED it, and no transition
    is ever invented because it "must have happened next":

    | state      | who observes it                              | ends when            |
    |------------|----------------------------------------------|----------------------|
    | `listening`| the mic owner (GlassVoiceService), reported  | superseded by `heard`|
    |            | from RecognitionListener's own callbacks     |                      |
    | `heard`    | the daemon, when /glance/talk ARRIVES        | immediately thinking |
    | `thinking` | the daemon, before copilot.chat              | superseded by answer |
    | `answered` | the daemon, when copilot.chat returns        | TERMINAL             |

    `answered` is deliberately terminal and deliberately not called "speaking".
    Whether the clip actually reached the owner's ear is something only the
    device knows, and this process never learns it - so it says the thing it
    genuinely observed (Henry answered) instead of a claim about a speaker it
    cannot hear. A conversation that continues simply overwrites it with the
    next `listening`.

  - `listening` is the ONE state that depends on the native reporter. If that
    half is not deployed, this module never emits it and the lens never shows
    it. That is the honest failure mode: the transcript, the thinking state and
    the answer still work, and nothing on the lens ever claims a mic is open
    when none is.

IN MEMORY ONLY, on purpose. This is liveness, not history - the history is the
Henry transcript, which is already durable and already shared. A turn state that
survived a daemon restart would be a stale "listening" from before the process
died, which is precisely the phantom this design exists to avoid.
"""
import threading
import time

# The transcript cap for the lens. GLASS_Q_LEN's neighbour in spirit (see
# glances.py): the lens is 600x600 and shows one thing at a time, and this line
# has to share the screen with the conversation above it. Long enough for a
# spoken sentence, short enough that it cannot push the state indicator off.
TEXT_MAX = 240

# What the mic field may say. A closed vocabulary rather than free text: this
# value arrives from a client authenticated by the SHARED glance token, and it
# is rendered on the lens - so it can only ever select among words we wrote.
# "glasses" and "phone" mirror GlassVoiceService's own two actions
# (ACTION_LISTEN / ACTION_LISTEN_PHONE_MIC), which is a real distinction the
# owner should see: only the glasses mic collapses his audio to 8 kHz HFP.
MICS = ("glasses", "phone")

_lock = threading.Lock()
_turn = {"state": "idle", "text": "", "mic": "", "question": None,
         "seq": 0, "ts": 0}


def _set(state, text=None, mic=None, question=None):
    """The ONE writer. Everything else in this module funnels through here so no
    path can move the state and forget to publish it - the bug that would look
    like "the lens froze on 'listening' even though Henry already answered".

    `seq` increments on every transition, so a client can tell a genuinely new
    turn from a re-render of the one it already has without comparing prose.

    The cursor bump is LAST and is best-effort, the same contract
    copilot._append_log uses: the state is already visible to any reader that
    asks, and a notify failure must never turn an observed transition into a
    dropped one. A waiting lens re-arms on its own timeout regardless.
    """
    with _lock:
        _turn["state"] = state
        if text is not None:
            _turn["text"] = (text or "").strip()[:TEXT_MAX]
        if mic is not None:
            _turn["mic"] = mic if mic in MICS else ""
        # ALWAYS assigned, never conditionally: the options belong to the answer
        # that produced them, so every other transition must clear them. Leaving
        # the previous turn's options tappable while a new one is being spoken is
        # how the owner answers a question that is no longer on the table.
        _turn["question"] = question
        _turn["seq"] += 1
        _turn["ts"] = int(time.time())
    try:
        from spine.storage import db
        db.bump_glass()
    except Exception as _be:                                    # noqa: BLE001
        print("glassturn: cursor bump failed -", str(_be)[:200])


def listening(mic="", text=""):
    """The mic is OPEN. Reported by the only party that can know it - the
    process holding the microphone - never guessed here.

    `text` carries the recogniser's partial result when there is one, so the
    lens shows the words forming while they are still being spoken. A partial is
    the whole point of this state: "listening" with nothing under it is a
    spinner, "listening" with the half-sentence he is saying is feedback.
    """
    _set("listening", text=text, mic=mic)


def idle(mic=""):
    """The mic owner stopped listening without producing words - the owner
    switched the loop off, or the recogniser closed on silence.

    Reported, not inferred. Without it a lens would sit on "listening" after the
    glasses button was toggled off on the phone, which is the same lie in the
    other direction: a mic indicator that stays lit with no mic open."""
    _set("idle", text="", mic=mic)


def heard(text):
    """Final words, in hand, about to become a message to Henry.

    Observed by the daemon at the moment `/glance/talk` arrives - no native
    support needed - which is why the transcript reaches the lens even on a
    build that never reports `listening`."""
    _set("heard", text=text)


def thinking():
    """The turn is with Henry. Set immediately after `heard`, from the same
    request, so the lens shows the owner's own line and the wait under it
    without a second round trip."""
    _set("thinking")


def answered(question=None):
    """copilot.chat returned. TERMINAL - see the module docstring for why this
    is not called "speaking".

    `question` is the tappable half of the reply, and carrying it HERE rather
    than only in the /glance/talk response is what makes the primary path work
    at all. On a spoken turn the POST is made by GlassVoiceService on the PHONE,
    so the lens never sees that response - it would show the conversation and
    the state but none of the options, on every voice turn. And GLASS_BRIEF
    requires Henry to end every reply with options precisely so the owner is
    never stranded on a keyboard-less surface.

    So the options travel with the turn state, which every surface reads,
    instead of with the reply, which only the caller reads. One source, and it
    does not care who did the talking.
    """
    _set("answered", question=question)


def failed():
    """The turn did not produce an answer (the model call raised).

    A distinct state rather than a silent drop back to idle: a lens left on
    "thinking" after a 502 is the silent wait the on-device UX laws forbid
    outright, and one that jumps to "idle" tells the owner his sentence was
    never heard - which is worse, because it was."""
    _set("failed")


def snapshot():
    """What is true right now, as plain data.

    Returns a COPY: the caller serialises it into a response while another
    thread may be mid-turn, and handing out the live dict would let a reply
    describe two different moments in its own fields.

    `age` is served rather than left to the client to compute, because the lens
    and the daemon do not share a clock - the webapp runs on the glasses, whose
    time comes from wherever the headset last synced it. `ts` rides along for
    the record; `age` is the number anything should actually reason about."""
    with _lock:
        t = dict(_turn)
    t["age"] = max(0, int(time.time()) - t["ts"]) if t["ts"] else None
    return t
