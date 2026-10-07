# -*- coding: utf-8 -*-
"""Streaming dictation - the daemon half of "hold the mic, text appears".

Shape copied from Paseo (packages/server/src/server/dictation/
dictation-stream-manager.ts), cut down to what our transport needs. The phone
sends numbered PCM chunks WHILE the owner talks, each as an ordinary sealed
relay frame; this module reassembles them in order, decodes the growing buffer
in the background so a partial transcript is always at hand, and on `finish`
only the last bit of audio is left to decode - stop-to-text is the tail, not
the whole utterance (the batch route /voice/transcribe uploads and decodes
everything AFTER the owner stopped).

Why numbered chunks and acks, not "just send them in order": a phone frame is
served on a pool thread (relay_client SERVE_WORKERS), so two chunks sent
back to back can reach this module swapped. `seq` is the order; `ack` is the
highest seq received IN ORDER, which is what the client may drop from its
replay buffer. Replay under a NEW id after a dropped connection is the
client's job (src/data/dictation.ts) - a stream here is disposable state that
dies with its idle timeout, never something to resume.

Silence is dropped before the model sees it (peak below SILENCE_PEAK): the
recognizer hallucinates words on room noise, and an unspoken tap must come
back as "" not as a sentence. Every COMMIT_S of audio the buffer is decoded
once and frozen, so re-decoding for partials stays bounded (Paseo: 15 s).

The decoder is one owner (`decoder`), replaceable for tests; the default is
spine.media.stt.transcribe_pcm16 behind stt's single decode door. No db, no
settings: nothing here can touch the live data.
"""
import threading
import time

PCM_FORMAT = "audio/pcm;rate=16000;bits=16"
BYTES_PER_S = 16000 * 2
COMMIT_S = 15                       # hard limit: freeze everything at this much audio
MIN_SEG_S = 3.0                     # a segment is at least this long before a pause may close it
PAUSE_S = 0.4                       # near-silence this long counts as a pause
PARTIAL_EVERY_S = 1.0               # min NEW audio between two partial decodes
SILENCE_PEAK = 300                  # int16 peak below this = nothing was said
IDLE_S = 180                        # a stream untouched this long is dropped
FINISH_WAIT_S = 10.0                # finish waits this long for a missing chunk
MAX_CHUNK_BYTES = 512 * 1024
MAX_STREAM_S = 600                  # ten minutes of dictation is a mistake
MAX_STREAMS_PER_OWNER = 4

_STREAMS = {}                       # (owner, id) -> Stream
_REG = threading.Lock()


class DictationError(Exception):
    """A typed refusal the route maps to a status. `retryable` tells the client
    whether starting over (new id, replay) can succeed."""
    def __init__(self, msg, status=400, retryable=False):
        super().__init__(msg)
        self.status = status
        self.retryable = retryable


def _default_decoder(pcm):
    from spine.media import stt
    return stt.transcribe_pcm16(pcm)


#: pcm bytes -> text. Tests assign a fake; production never touches it.
decoder = _default_decoder


def _default_warm():
    from spine.media import stt
    stt._model()


#: Load the speech model. Called the moment a stream STARTS: the first decode in
#: a fresh daemon spends seconds loading the 0.6B model, and without this that
#: wait lands while the owner is already talking - measured 2026-10-07, stop-to-
#: text was 3 s and no partial showed for the first 5 s of speech. stt._model is
#: idempotent under its own lock, so a second start costs nothing.
warm = _default_warm


def _warm_quietly():
    try:
        warm()
    except Exception:                    # noqa: BLE001 - the real error surfaces at decode/finish
        pass


def _peak(pcm):
    import numpy as np
    if len(pcm) < 2:
        return 0
    x = np.frombuffer(pcm[:len(pcm) - (len(pcm) % 2)], dtype="<i2")
    return int(np.abs(x.astype(np.int32)).max())


def _silent(pcm):
    return _peak(pcm) < SILENCE_PEAK


class Stream:
    def __init__(self, owner, did):
        self.owner = owner
        self.id = did
        self.cond = threading.Condition()
        self.next_seq = 0
        self.pending = {}           # seq -> pcm, waiting for the gap before it
        self.buf = bytearray()      # uncommitted audio, in order
        self.committed = []         # frozen segment texts
        self.partial = ""           # text of buf[:decoded_len]
        self.decoded_len = 0
        self.busy = False           # a decode thread owns the model right now
        self.error = None
        self.total = 0
        self.touched = time.time()

    def text(self):
        return " ".join(t for t in self.committed + [self.partial] if t).strip()


def _sweep(now):
    for k, st in list(_STREAMS.items()):
        if now - st.touched > IDLE_S:
            _STREAMS.pop(k, None)


def start(owner, did, fmt=PCM_FORMAT):
    if not did or not isinstance(did, str) or len(did) > 80:
        raise DictationError("id required")
    if fmt != PCM_FORMAT:
        raise DictationError("unsupported format %r (need %s)" % (fmt, PCM_FORMAT))
    now = time.time()
    with _REG:
        _sweep(now)
        mine = [s for s in _STREAMS.values() if s.owner == owner]
        while len(mine) >= MAX_STREAMS_PER_OWNER:
            oldest = min(mine, key=lambda s: s.touched)
            _STREAMS.pop((oldest.owner, oldest.id), None)
            mine.remove(oldest)
        _STREAMS[(owner, did)] = Stream(owner, did)
    threading.Thread(target=_warm_quietly, daemon=True, name="dictation-warm").start()
    return {"id": did, "ack": -1}


def _get(owner, did):
    with _REG:
        st = _STREAMS.get((owner, did))
    if st is None:
        # retryable: the client replays its buffered audio under a fresh id
        raise DictationError("dictation stream not started", 404, retryable=True)
    st.touched = time.time()
    return st


def _find_cut(pcm):
    """Byte offset to freeze the buffer at: the middle of the LAST pause
    (>= PAUSE_S of near-silence) that leaves at least MIN_SEG_S of speech
    before it, or None. Cutting at a pause instead of at a clock tick is what
    keeps a word from being split across two decodes - measured 2026-10-07,
    a hard cut at 15 s turned "schiebt ihn bitte" into "schiebt er ein Karte."."""
    import numpy as np
    win = 320                                        # 20 ms
    x = np.abs(np.frombuffer(pcm[:len(pcm) - (len(pcm) % 2)], dtype="<i2").astype(np.int32))
    n = len(x) // win
    if n == 0:
        return None
    peaks = x[:n * win].reshape(n, win).max(axis=1)
    quiet = peaks < max(SILENCE_PEAK, int(0.06 * peaks.max()))
    need = int(PAUSE_S / 0.02)
    first_ok = int(MIN_SEG_S / 0.02)
    best = None
    i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= need and i >= first_ok:
                best = (i + j) // 2                  # the middle of the pause
            i = j
        else:
            i += 1
    return None if best is None else best * win * 2


def _decode_job(st):
    """One background decode. Single-flight per stream (`busy`; the caller set
    it under the lock). Past MIN_SEG_S it freezes the audio up to the last pause
    (or, at COMMIT_S with no pause at all, everything); otherwise it refreshes
    the partial over the whole uncommitted buffer."""
    with st.cond:
        snap = bytes(st.buf)
    n = len(snap)
    cut = None
    if n >= MIN_SEG_S * BYTES_PER_S:
        cut = _find_cut(snap)
    if cut is None and n >= COMMIT_S * BYTES_PER_S:
        cut = n
    piece = snap[:cut] if cut else snap
    try:
        text = "" if _silent(piece) else decoder(piece)
        err = None
    except Exception as e:                       # noqa: BLE001 - surfaced at finish
        text, err = "", e
    with st.cond:
        if err is not None:
            st.error = str(err)[:200]
        elif cut:
            if text:
                st.committed.append(text)
            del st.buf[:cut]                     # audio that arrived meanwhile stays
            st.decoded_len = 0
            st.partial = ""
        else:
            st.partial = text
            st.decoded_len = n
        st.busy = False
        st.cond.notify_all()


def _maybe_decode(st):
    """Caller holds st.cond. Start a partial/commit decode when enough NEW audio
    arrived and the model is not already ours."""
    if st.busy or st.error:
        return
    new = len(st.buf) - st.decoded_len
    if new >= PARTIAL_EVERY_S * BYTES_PER_S or len(st.buf) >= COMMIT_S * BYTES_PER_S:
        st.busy = True
        threading.Thread(target=_decode_job, args=(st,), daemon=True,
                         name="dictation-decode").start()


def chunk(owner, did, seq, pcm):
    st = _get(owner, did)
    if not isinstance(seq, int) or seq < 0:
        raise DictationError("seq must be a non-negative int")
    if len(pcm) > MAX_CHUNK_BYTES:
        raise DictationError("chunk too large")
    with st.cond:
        if st.total + len(pcm) > MAX_STREAM_S * BYTES_PER_S:
            raise DictationError("dictation too long")
        if seq >= st.next_seq and seq not in st.pending:     # a re-sent chunk is a no-op
            st.pending[seq] = pcm
            st.total += len(pcm)
            while st.next_seq in st.pending:
                st.buf += st.pending.pop(st.next_seq)
                st.next_seq += 1
            _maybe_decode(st)
        return {"ack": st.next_seq - 1, "partial": st.text()}


def finish(owner, did, final_seq):
    """Everything up to `final_seq` was sent. Wait for stragglers, decode only
    what no partial covered yet, return the whole text."""
    st = _get(owner, did)
    deadline = time.time() + FINISH_WAIT_S
    with st.cond:
        while st.next_seq - 1 < final_seq:
            left = deadline - time.time()
            if left <= 0:
                raise DictationError("chunks missing after seq %d" % (st.next_seq - 1),
                                     409, retryable=True)
            st.cond.wait(min(left, 0.25))
        while st.busy:
            st.cond.wait(0.1)
        if st.error:
            raise DictationError(st.error, 500, retryable=True)
        snap = bytes(st.buf)
        covered = st.decoded_len == len(snap)
        st.busy = True                       # nothing else decodes while we finish
        partial = st.partial
    try:
        if covered or not snap:
            tail = partial if snap else ""
        else:
            tail = "" if _silent(snap) else decoder(snap)
    except Exception as e:                   # noqa: BLE001
        with st.cond:
            st.busy = False
        raise DictationError(str(e)[:200], 500, retryable=True)
    with st.cond:
        st.busy = False
        text = " ".join(t for t in st.committed + [tail] if t).strip()
    with _REG:
        _STREAMS.pop((owner, did), None)
    return {"text": text}


def cancel(owner, did):
    with _REG:
        _STREAMS.pop((owner, did), None)
    return {"ok": True}
