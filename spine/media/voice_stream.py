# -*- coding: utf-8 -*-
"""Speak the answer WHILE it is written, not after it is finished.

THE PROBLEM THIS EXISTS FOR. `voice.render_b64` turns a finished reply into one
mp3, so voice mode stayed SILENT for the whole turn and then talked. A copilot
turn is seconds - copilot.py's own comment calls out a "dead 40s wait" - so the
owner sat in silence for the part that costs the most and got audio only once
there was nothing left to wait for.

WHERE THE IDEA COMES FROM. huggingface/speech-to-speech (Apache-2.0, read
2026-08-21) cascades the same four stages HelmDeck already has, and its whole
latency answer is one move: it never waits for the model. Its
`LLM/language_model.py` tokenises the STREAMING output into sentences and hands
batches on as they complete (`stream_batch_sentences`, default 3). That is what
this module does. What is NOT taken from there: their local models
(Parakeet/Kokoro/Qwen3-TTS - gigabytes of weights to replace an edge-tts that is
free and a platform STT that works) and their WebRTC/Realtime session, which
buys talk-over-the-model barge-in that HFP/A2DP forbids on the glasses anyway.

WHY THE PHONE CAN HAVE THIS AT ALL - the objection that had to be checked, not
assumed. The phone reaches the daemon through an E2EE relay that seals ONE
request/response, so "stream audio to the phone" sounds impossible. It isn't,
because nothing here streams: the daemon renders whole small clips and the
client COLLECTS them, one sealed request at a time, over the `/chat/live` poll
the board chat already runs (`client.ts` chatLive, `chat.tsx`). Same transport,
same auth, no new channel.

OWNERSHIP (the no-monkey-patches law). The chunk list is derived from ONE
source - the prose the pump has actually emitted - and is folded in AT EVENT
TIME by `feed()`, from inside the pump, exactly where `live_partial.txt` is
already written. It is never reconstructed by re-reading artifacts. The client
holds only a READ CURSOR (`after_seq`); it cannot move the daemon's state, so
two consumers, a reload or a lost poll can never desynchronise it.

FAILS SOFT like voice.py, for the same reason: `render_b64` returns None when
edge-tts is unreachable, and a chunk that will not render is simply never
emitted. The answer is on screen either way; speech may not take it away.
"""
import itertools
import queue
import re
import threading

from spine.media import voice

# Chunk size in CHARACTERS, growing. Zero for the first one is not a typo and
# not a placeholder: it means "the moment ONE sentence exists, say it". That
# chunk is the only one whose latency the owner ever feels - every character
# waited for in it is silence he sits through - and the first draft of this
# file got it wrong by accumulating to 40 chars, which quietly glued a short
# opening sentence onto the long one after it and pushed first audio out to
# char 104 of 170. Later chunks get longer on purpose: by then audio is already
# playing, so the only thing size still costs is round trips to Microsoft's
# voice service (voice.py; quota risk in ops/docs/voice-interaction-design.md SS9.5).
BATCH_CHARS = (0, 140, 260)

# Never render a two-word fragment on its own: an abbreviation the splitter
# below misses would otherwise become its own clip, and a 300ms mp3 of "Dr."
# costs a whole round trip to say nothing. This is the floor under every chunk,
# including the first.
MIN_CHARS = 16

# A sentence ends at terminal punctuation followed by whitespace. The trailing
# whitespace is the point: with token deltas, a "." that has nothing after it
# yet may still be mid-token, so the space is what PROVES the sentence closed.
# Same principle as the rest of this repo - derive the boundary from a signal,
# do not guess it from a timer.
_END = re.compile(r'[.!?…]+["\'”’)\]]*(\s+)')

# Abbreviations that would otherwise split mid-sentence. Not exhaustive on
# purpose - a missed one costs an early pause, never a wrong word, and MIN_CHARS
# glues the fragment onto its neighbour anyway.
_ABBR = {"z.b", "d.h", "u.a", "bzw", "ca", "dr", "prof", "nr", "vs", "etc",
         "usw", "ggf", "inkl", "evtl", "e.g", "i.e", "mr", "mrs", "st", "no",
         "vgl", "abb", "bspw"}


def _looks_abbreviated(text, end):
    """True when the '.' at `end` closes a known abbreviation rather than a
    sentence."""
    head = text[:end].rstrip(".")
    word = re.split(r"[\s(]", head)[-1].lower().rstrip(".")
    return word in _ABBR or (len(word) == 1 and word.isalpha())


def cut(text):
    """Split into (complete sentences, unfinished tail).

    Public because it is the one piece here worth testing on its own - the rest
    is threads and I/O.
    """
    out, start = [], 0
    for m in _END.finditer(text):
        if _looks_abbreviated(text, m.start() + 1):
            continue
        s = text[start:m.start(1)].strip()
        if s:
            out.append(s)
        start = m.end()
    return out, text[start:]


# Turn identity, monotonically increasing for the daemon's lifetime. Every clip
# carries its stream's turn number, so a client can tell "chunk 1 of the answer
# I am waiting for" from "chunk 1 of an answer I already interrupted". A bare
# seq cannot: it restarts at 1 every turn, and the huggingface/speech-to-speech
# lesson (ops/docs/voice-interaction-design.md SS8d) - like the Realtime APIs' -
# is that audio must be addressed as (turn, seq), never seq alone.
_TURN = itertools.count(1)


class _Stream(object):
    """One turn's worth of spoken chunks."""

    def __init__(self, turn):
        self.turn = turn
        self.clips = []                 # [{turn, seq, text, id, mime, b64}]
        self.seq = 0
        self.cursor = 0                 # chars of prose already turned into chunks
        self.buf = []                   # complete sentences not yet long enough
        self.q = queue.Queue()
        self.alive = True
        self.inflight = 0               # chunks queued or rendering
        self.lock = threading.Lock()
        # ONE worker, so clips can only be appended in the order they were cut.
        # Rendering them concurrently would be faster and would also let chunk 3
        # arrive before chunk 2 - and speech that arrives out of order is worse
        # than speech that arrives late.
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def _run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            seq, text = item
            clip = None
            try:
                clip = voice.render_b64(text)
            except Exception:
                clip = None                     # fails soft - see the header
            with self.lock:
                if self.alive and clip:
                    c = dict(clip)
                    c["turn"] = self.turn
                    c["seq"] = seq
                    c["text"] = text
                    self.clips.append(c)
                self.inflight -= 1

    def _emit(self, text):
        with self.lock:
            self.seq += 1
            self.inflight += 1
            seq = self.seq
        self.q.put((seq, text))

    def feed(self, prose, final=False):
        """Fold in the prose emitted SO FAR. Cheap and idempotent: only the part
        past the cursor is ever looked at."""
        # A FLOOR, not a second action parser. The pump already hands over
        # `_strip_actions_live(...)`, so a fence should never arrive - but the
        # cost of being wrong here is the owner listening to a JSON array read
        # aloud, and "nothing inside a code fence is speakable" is this module's
        # own concern, true whatever the fence happens to contain.
        fence = prose.find("```")
        if fence != -1:
            prose = prose[:fence].rstrip()
            final = True            # nothing past the fence will ever be prose
        fresh = prose[self.cursor:]
        if not fresh and not final:
            return
        done, tail = cut(fresh)
        self.buf.extend(done)
        self.cursor += len(fresh) - len(tail)
        if final and tail.strip():
            # The last sentence of a reply often has no trailing whitespace, so
            # `cut` cannot see it close. The turn ending is that proof instead.
            self.buf.append(tail.strip())
            self.cursor += len(tail)
        while self.buf:
            want = max(BATCH_CHARS[min(self.seq, len(BATCH_CHARS) - 1)], MIN_CHARS)
            joined = " ".join(self.buf)
            if len(joined) >= want or (final and len(joined) >= MIN_CHARS):
                self._emit(joined[:voice.MAX_TEXT])
                self.buf = []
            elif final:
                self.buf = []               # too short to be worth a round trip
            else:
                break

    def close(self):
        self.q.put(None)

    def kill(self):
        with self.lock:
            self.alive = False
            self.clips = []
        self.q.put(None)


_STREAMS = {}
_LOCK = threading.RLock()


def begin(user):
    """Start a fresh turn. Any previous stream is dropped - a new question makes
    the old answer's remaining audio wrong, not merely stale."""
    with _LOCK:
        old = _STREAMS.pop(user, None)
        if old:
            old.kill()
        _STREAMS[user] = _Stream(next(_TURN))


def feed(user, prose):
    s = _STREAMS.get(user)
    if s:
        try:
            s.feed(prose)
        except Exception:
            pass                    # a bad split must never kill the pump


def finish(user, prose):
    s = _STREAMS.get(user)
    if s:
        try:
            s.feed(prose, final=True)
        except Exception:
            pass
        s.close()


def drop(user):
    """Stop was pressed, or the turn died. Queued audio is discarded rather than
    played over whatever comes next."""
    with _LOCK:
        s = _STREAMS.pop(user, None)
    if s:
        s.kill()


def take(user, after_seq, turn=None):
    """Clips with seq > after_seq, plus whether more may still arrive.

    `pending` is what lets the client know the difference between "the turn is
    over and that was all" and "the turn is over but chunk 4 is still
    rendering" - without it the last sentence would be cut off whenever the
    render lagged the model, which is exactly when it matters.

    `turn` is the turn the client's cursor BELONGS to. A cursor is only ever
    meaningful against the stream that produced it: after a steer, the client
    may still hold last turn's high seq while this stream's clips start at 1
    again, and honouring that stale cursor would silently swallow the whole
    new answer. A caller that names a different (or no longer current) turn
    gets everything. `None` = an old client that cannot say - keep the exact
    pre-turn-id semantics it was built against.
    """
    s = _STREAMS.get(user)
    if not s:
        return [], False
    if turn is not None and turn != s.turn:
        after_seq = 0
    with s.lock:
        out = [c for c in s.clips if c["seq"] > after_seq]
        pending = s.inflight > 0
    return out, pending
