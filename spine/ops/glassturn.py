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
    | `listening`| the mic owner (GlassVoiceService), reported  | superseded by `draft`|
    |            | from RecognitionListener's own callbacks     |                      |
    | `draft`    | the mic owner, when the recogniser produced  | the owner accepts or |
    |            | WORDS - parked for the owner to accept       | rejects, or it times |
    |            | (`decide`), never auto-sent                   | out and is DROPPED   |
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

# How long ONE /glance/decision request is held open.
#
# ⚠ THIS IS AN EDGE CONSTRAINT, NOT A UX ONE, and getting it from the wrong
# place is how this route would have failed in production only. The lens and the
# phone reach the daemon through the Cloudflare Worker, and Cloudflare gives up
# on an origin response at ~100s with a 524 - so a hold sized to human patience
# (the owner reading a sentence and deciding, easily a minute or two) would be
# killed by the edge and look exactly like "the buttons do nothing". The
# neighbouring hanging GET, /glance/chat, is ~20s and is PROVEN through the
# deployed Worker, so this sits beside it rather than inventing a new number.
#
# Human patience is therefore the CLIENT's budget, not the server's: the mic
# owner re-arms this wait until DECIDE_TOTAL_S is spent (GlassVoiceService.
# awaitDecision), which is the same shape app.js's chatLoop already uses.
DECIDE_WAIT_S = 25

# The total the mic owner will keep re-arming for before it gives up, goes idle
# and DROPS the words. Never sends: an unconfirmed sentence spoken in the
# owner's name is the exact thing the confirm step exists to prevent, so the
# timeout has to fail closed. Advisory here (the client owns the loop); stated
# here so both halves read the same number from one place.
DECIDE_TOTAL_S = 150

# The closed vocabulary of what the owner may decide about a draft. Same reason
# MICS is closed: this arrives from a client holding the shared glance token and
# it steers whether words are sent in the owner's name.
DECISIONS = ("send", "redo", "cancel")

_lock = threading.Lock()
# One Condition over the SAME lock as the turn itself, so a decision and the
# state it is about can never be observed half-applied by the waiting service.
_decided = threading.Condition(_lock)
_turn = {"state": "idle", "text": "", "mic": "", "question": None,
         "seq": 0, "ts": 0}
# The pending verdict on ONE draft, addressed by that draft's seq. Addressed
# rather than boolean because the alternative is a stale tap: the owner rejects
# draft N, speaks again, and the verdict meant for N is consumed by draft N+1 -
# sending a sentence he had just discarded. `seq` is what makes that impossible.
_decision = {"seq": 0, "value": ""}


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
    with _decided:
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
        # Wake anyone waiting on a draft verdict. A transition AWAY from their
        # draft is itself an answer ("superseded"), so the waiter must not sleep
        # through it - that is how a service ends up holding a thread for two
        # minutes over a turn that is already gone.
        _decided.notify_all()
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


def draft(text, mic=""):
    """Words RECOGNISED but not yet sent - the confirm step (owner, 2026-09-04:
    "wie auf watch erstmal per turn ... user kann bestaetigen oder loeschen und
    neu sprechen").

    WHY THIS STATE EXISTS AT ALL, and why the watch does not need it. On Wear the
    confirm step is the SYSTEM's: HenryScreen launches ACTION_RECOGNIZE_SPEECH
    and the platform dictation UI shows the transcript and takes the accept
    before ever returning it to us (surfaces/app/plugins/wear/HenryScreen.kt:288-302).
    The glasses have no such activity - the lens is a webview served by the
    Worker and the recogniser runs headless in a phone service - so the same
    interaction has to be built out of the pieces we own. This state is that
    build: the mic owner parks its words here instead of posting them to
    /glance/talk, and the lens renders them with an accept and a reject.

    Returns the seq it just published, because the service must address its wait
    to THIS draft and no other - see `_decision`.

    Deliberately NOT terminal and deliberately not `heard`: `heard` means the
    words are already on their way to Henry and is observed by the daemon at
    /glance/talk. A draft is the owner's sentence sitting in front of him,
    still his to throw away. Conflating them would put the confirm step after
    the point of no return."""
    _set("draft", text=text, mic=mic)
    with _decided:
        # Arm a fresh slot for exactly this draft. Clearing is the point: a
        # verdict left over from the previous draft must never satisfy this one.
        _decision["seq"] = 0
        _decision["value"] = ""
        return _turn["seq"]


def decide(value, seq=0):
    """The owner accepted or rejected the draft on the lens.

    Refuses anything but a live draft, and refuses a verdict addressed to a seq
    that is no longer the one on screen: both are the stale-tap case, and both
    are answered False so the caller can say so rather than silently doing
    nothing. Returns True when the verdict was recorded and a waiter (if any)
    was woken."""
    if value not in DECISIONS:
        return False
    with _decided:
        if _turn["state"] != "draft":
            return False
        if seq and seq != _turn["seq"]:
            return False
        _decision["seq"] = _turn["seq"]
        _decision["value"] = value
        _decided.notify_all()
        return True


def await_decision(seq, timeout=None):
    """Block until the owner rules on draft `seq`. Called by the mic owner.

    A LONG-POLL rather than a poll loop, for the same reason /glance/chat is one:
    the waiting party is a foreground service on a phone, and waking it every
    second to be told "not yet" spends battery to learn nothing. The daemon
    already owns the event that ends this wait, so it holds the request until it
    happens.

    Three distinct outcomes, and they are distinct because the service does
    genuinely different things with them:
      - one of DECISIONS - the owner ruled
      - "superseded"     - the turn moved on under us (a new draft, an
                           ACTION_STOP idle, anything). NOT an error and NOT a
                           send: someone else already owns what happens next.
      - ""               - nothing was decided in time. The service goes idle
                           and the words are DROPPED, never sent on a timeout.
    """
    deadline = time.time() + (DECIDE_WAIT_S if timeout is None else timeout)
    with _decided:
        while True:
            if _decision["seq"] == seq and _decision["value"]:
                return _decision["value"]
            # The draft we were asked about is no longer the live turn.
            if _turn["state"] != "draft" or _turn["seq"] != seq:
                return "superseded"
            left = deadline - time.time()
            if left <= 0:
                return ""
            _decided.wait(min(left, 5.0))


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
