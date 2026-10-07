# -*- coding: utf-8 -*-
"""Headless test for STREAMING DICTATION (spine/media/dictation_stream.py).

What this pins - each one a way a streamed dictation silently loses words:
 1. chunks that reach the daemon SWAPPED (the relay serves frames on a pool
    thread) are reassembled in seq order; ack = highest seq received IN ORDER
 2. a re-sent chunk is a no-op (replay after a dropped connection must not
    double the audio)
 3. REPLAY under a NEW id after the old stream is gone reproduces the text
    (the client keeps every chunk until `final`; the daemon keeps nothing)
 4. finish() with the partial already covering the whole buffer decodes
    NOTHING more - stop-to-text is the tail, which is the point of streaming
 5. finish() decodes only the tail the last partial did not cover
 6. silence never reaches the model: a quiet buffer comes back as "" and the
    decoder is not called (the recognizer hallucinates on room noise)
 7. a gap that never fills fails finish() with a retryable 409, not a
    half-sentence returned as if it were the whole
 8. an unknown id is a retryable 404 (client replays under a fresh id)
 9. a stream that crosses COMMIT_S freezes its buffer and keeps the text, and
    the decoder's input stays bounded
10. cancel drops the stream; idle streams are swept
11. bad input: wrong format, oversized chunk, negative seq

The decoder is replaced by a fake that records what it was handed and echoes
the byte length, so ordering is observable. No db, no model, no network.
Run: py -3.12 ops/tests/test_dictation_stream.py
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import numpy as np                                        # noqa: E402

from spine.media import dictation_stream as ds            # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def tone(seconds, level=8000):
    """`seconds` of loud PCM16: a constant, so equal-length chunks differ only
    by a marker sample at the front (lets the fake decoder see ORDER)."""
    n = int(16000 * seconds)
    return np.full(n, level, dtype="<i2").tobytes()


def marked(mark, seconds=0.5):
    b = bytearray(tone(seconds))
    b[0:2] = np.int16(mark).tobytes()
    return bytes(b)


CALLS = []


def fake_decoder(pcm):
    CALLS.append(len(pcm))
    x = np.frombuffer(pcm, dtype="<i2")
    # the marker of every 0.5 s chunk, in the order they sit in the buffer
    marks = [int(x[i]) for i in range(0, len(x), 8000)]
    return " ".join("m%d" % m for m in marks)


WARMS = []
CLEAN_WARMS = []
ds.decoder = fake_decoder
ds.warm = lambda: WARMS.append(1)
ds.cleanup_warm = lambda: CLEAN_WARMS.append(1)      # never spawn a real model process from a test
ds.PARTIAL_EVERY_S = 0.0           # decode on every chunk so partials are testable


def wait_idle(did, owner="o"):
    st = ds._STREAMS[(owner, did)]
    with st.cond:
        while st.busy:
            st.cond.wait(0.05)


def fresh(did, owner="o"):
    CALLS.clear()
    ds.start(owner, did)


# 0: starting a stream warms the model (and a failing warm-up never breaks start)
WARMS.clear()
ds.start("o", "w1")
time.sleep(0.2)
check("start loads the speech model in the background", WARMS == [1], WARMS)
check("start also boots the cleanup model process (so the swap is fast)", CLEAN_WARMS == [1], CLEAN_WARMS)
ds.warm = lambda: (_ for _ in ()).throw(RuntimeError("model missing"))
try:
    ds.start("o", "w2")
    time.sleep(0.2)
    check("a failing warm-up does not fail start", True)
except Exception as e:                              # noqa: BLE001
    check("a failing warm-up does not fail start", False, e)
ds.warm = lambda: WARMS.append(1)
ds.cancel("o", "w1"); ds.cancel("o", "w2")

# 1 + 2: swapped delivery, duplicate
fresh("a")
r2 = ds.chunk("o", "a", 2, marked(2))
check("gap: ack stays -1 while seq 0,1 are missing", r2["ack"] == -1, r2)
ds.chunk("o", "a", 1, marked(1))
r0 = ds.chunk("o", "a", 0, marked(0))
check("gap filled: ack jumps to 2", r0["ack"] == 2, r0)
ds.chunk("o", "a", 1, marked(1))                   # re-sent
st = ds._STREAMS[("o", "a")]
check("duplicate chunk did not double the audio", len(st.buf) == 3 * 16000, len(st.buf))
wait_idle("a")
out = ds.finish("o", "a", 2)
check("finish returns the audio IN SEQ ORDER", out["text"] == "m0 m1 m2", out)
check("finish removed the stream", ("o", "a") not in ds._STREAMS)

# 3: replay under a new id reproduces it
chunks = [marked(i) for i in range(4)]
fresh("old")
ds.chunk("o", "old", 0, chunks[0])
ds.chunk("o", "old", 1, chunks[1])
ds.cancel("o", "old")                              # the connection died, stream gone
try:
    ds.chunk("o", "old", 2, chunks[2])
    check("chunk to a dead stream is refused", False)
except ds.DictationError as e:
    check("chunk to a dead stream is a retryable 404", e.status == 404 and e.retryable)
fresh("new")
for i, c in enumerate(chunks):                     # REPLAY everything
    ds.chunk("o", "new", i, c)
out = ds.finish("o", "new", 3)
check("replay under a new id gives the full text", out["text"] == "m0 m1 m2 m3", out)

# 4: partial covers the whole buffer -> finish decodes nothing more
fresh("cov")
for i in range(3):
    ds.chunk("o", "cov", i, marked(i))
    wait_idle("cov")
before = len(CALLS)
out = ds.finish("o", "cov", 2)
check("covered tail: finish ran NO extra decode", len(CALLS) == before, (before, len(CALLS)))
check("covered tail: text is the last partial", out["text"] == "m0 m1 m2", out)

# 5: tail not covered -> exactly one extra decode of the whole buffer
ds.PARTIAL_EVERY_S = 99.0                          # no partials at all
fresh("tail")
for i in range(3):
    ds.chunk("o", "tail", i, marked(i))
out = ds.finish("o", "tail", 2)
check("uncovered tail: exactly one decode", len(CALLS) == 1, CALLS)
check("uncovered tail: full text", out["text"] == "m0 m1 m2", out)
ds.PARTIAL_EVERY_S = 0.0

# 6: silence never reaches the model
fresh("quiet")
ds.chunk("o", "quiet", 0, tone(1.0, level=20))
wait_idle("quiet")
out = ds.finish("o", "quiet", 0)
check("silence returns an empty text", out["text"] == "", out)
check("silence never called the decoder", CALLS == [], CALLS)

# 7: a gap that never fills
ds.FINISH_WAIT_S = 0.4
fresh("hole")
ds.chunk("o", "hole", 0, marked(0))
ds.chunk("o", "hole", 2, marked(2))
t = time.time()
try:
    ds.finish("o", "hole", 2)
    check("missing chunk fails finish", False)
except ds.DictationError as e:
    check("missing chunk -> retryable 409", e.status == 409 and e.retryable, (e.status, str(e)))
check("finish waited for the straggler, not forever", 0.3 <= time.time() - t < 3, time.time() - t)
ds.FINISH_WAIT_S = 10.0

# 8: unknown id
try:
    ds.finish("o", "ghost", 0)
    check("unknown id refused", False)
except ds.DictationError as e:
    check("unknown id -> retryable 404", e.status == 404 and e.retryable)

# 9: commit freezes the buffer; decoder input stays bounded
ds.COMMIT_S = 2
fresh("long")
for i in range(12):                                # 6 s of audio in 0.5 s chunks
    ds.chunk("o", "long", i, marked(i))
    wait_idle("long")
out = ds.finish("o", "long", 11)
check("long dictation keeps every word across commits",
      out["text"] == " ".join("m%d" % i for i in range(12)), out)
check("decoder input never exceeded the commit window",
      max(CALLS) <= (ds.COMMIT_S + 0.5) * 32000, max(CALLS))
ds.COMMIT_S = 15

# 9b: a long stretch closes at a PAUSE, not at a clock tick
ds.COMMIT_S = 15


def phrase(seconds):
    return tone(seconds)


def gap(seconds):
    return np.zeros(int(16000 * seconds), dtype="<i2").tobytes()


fresh("pause")
audio = phrase(3.5) + gap(0.6) + phrase(3.0)       # speech, pause, speech
step = 8000 * 2
sent = 0
for i in range(0, len(audio), step):
    ds.chunk("o", "pause", sent, audio[i:i + step])
    sent += 1
    wait_idle("pause")
stp = ds._STREAMS[("o", "pause")]
check("a pause closed a segment before the stream ended", len(stp.committed) == 1, stp.committed)
# bytes frozen = everything sent minus what is still uncommitted
frozen = len(audio) - len(stp.buf)
check("the cut sits INSIDE the pause (3.5 s .. 4.1 s)",
      3.5 * 32000 <= frozen <= 4.1 * 32000, (frozen, frozen / 32000.0))
check("only the audio after the pause is left uncommitted",
      0 < len(stp.buf) < len(audio) - 3 * 32000, len(stp.buf))
out = ds.finish("o", "pause", sent - 1)
check("text keeps both halves", out["text"].count("m") > 0 and out["text"] != "", out)

# no pause and short: nothing is cut early
fresh("nopause")
for i in range(5):
    ds.chunk("o", "nopause", i, marked(i))
    wait_idle("nopause")
check("continuous speech under COMMIT_S is not cut", len(ds._STREAMS[("o", "nopause")].committed) == 0)
ds.finish("o", "nopause", 4)

# 10: cancel + sweep
fresh("c")
ds.cancel("o", "c")
check("cancel drops the stream", ("o", "c") not in ds._STREAMS)
fresh("idle")
ds._STREAMS[("o", "idle")].touched -= ds.IDLE_S + 1
ds.start("o", "other")
check("idle stream is swept on the next start", ("o", "idle") not in ds._STREAMS)

# owners are isolated
fresh("mine", owner="alice")
try:
    ds.chunk("bob", "mine", 0, marked(0))
    check("another user cannot feed my stream", False)
except ds.DictationError as e:
    check("another user cannot feed my stream", e.status == 404)

# 11: bad input
for label, fn in (
        ("wrong format", lambda: ds.start("o", "x", "audio/wav")),
        ("oversized chunk", lambda: ds.chunk("o", "mine2", 0, b"\0" * (ds.MAX_CHUNK_BYTES + 2))),
        ("negative seq", lambda: ds.chunk("o", "mine2", -1, b"\0\0"))):
    ds.start("o", "mine2")
    try:
        fn()
        check(label + " refused", False)
    except ds.DictationError as e:
        check(label + " refused", e.status == 400 and not e.retryable)

# per-owner cap evicts the oldest instead of growing
for i in range(ds.MAX_STREAMS_PER_OWNER + 2):
    ds.start("cap", "s%d" % i)
    time.sleep(0.002)
mine = [k for k in ds._STREAMS if k[0] == "cap"]
check("owner stream cap holds", len(mine) == ds.MAX_STREAMS_PER_OWNER, len(mine))

# concurrent swapped delivery from threads (the real relay shape)
fresh("race")
ths = [threading.Thread(target=ds.chunk, args=("o", "race", i, marked(i))) for i in reversed(range(8))]
for th in ths:
    th.start()
for th in ths:
    th.join()
out = ds.finish("o", "race", 7)
check("8 chunks from 8 threads reassemble in order",
      out["text"] == " ".join("m%d" % i for i in range(8)), out)

print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
