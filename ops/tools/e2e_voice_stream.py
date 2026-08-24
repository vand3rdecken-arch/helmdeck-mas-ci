# -*- coding: utf-8 -*-
"""Drive the STREAMING-SPEECH cut, batch and flush - the half a browser cannot see.

`e2e_voice_loop.py` proves the client's state machine and `e2e_voice_playback.py`
proves one clip decodes. Neither can prove the thing this feature actually is:
that a reply arriving one TOKEN at a time is turned into whole spoken sentences,
in order, with nothing dropped and nothing spoken twice.

So this feeds `voice_stream` the way the copilot pump does - character by
character, always passing the FULL prose so far, exactly as `_strip_actions_live`
hands it over - and checks what comes out. Rendering is stubbed at the ONE seam
where the network would be (`voice.render_b64`), because what is under test is
segmentation and sequencing, not Microsoft's voice service; the real render is
already covered by e2e_voice_playback.py.

Usage:  py -3.12 ops/tools/e2e_voice_stream.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spine.media import voice, voice_stream                  # noqa: E402

fails = []
total = 0


def check(cond, msg):
    global total
    total += 1
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


# The one seam where the network would be. Returns a marker instead of audio so
# a dropped or reordered chunk is visible as text.
def _fake_render(text, voice_name=None):
    return {"id": "fake%d" % len(text), "mime": "audio/mpeg", "b64": "AAAA"}


voice.render_b64 = _fake_render

REPLY = (
    "Der Deploy ist blockiert. Zwei Karten warten seit gestern auf dich, "
    "und eine davon haengt an einem Gate. Soll ich die erste jetzt starten? "
    "Danach raeume ich den Rest auf."
)
# What the model actually emits at the end - prose, then the machine block the
# owner must never hear. The pump strips it before feeding, so it must never
# reach a clip either.
TAIL_ACTIONS = "\n```actions\n[{\"type\":\"move\"}]\n```"


def drain(user, timeout=10.0):
    """Wait until nothing is left rendering, then take everything."""
    dead = time.time() + timeout
    while time.time() < dead:
        clips, pending = voice_stream.take(user, 0)
        if not pending:
            return clips
        time.sleep(0.05)
    return voice_stream.take(user, 0)[0]


print("1. a reply arriving one character at a time becomes whole sentences")
U = "e2e"
voice_stream.begin(U)
first_seen_at = None
for i in range(1, len(REPLY) + 1):
    voice_stream.feed(U, REPLY[:i])
    if first_seen_at is None and voice_stream.take(U, 0)[1]:
        first_seen_at = i
voice_stream.finish(U, REPLY)
clips = drain(U)

check(len(clips) >= 2, "the reply was split into several chunks (got %d)" % len(clips))
check([c["seq"] for c in clips] == sorted(c["seq"] for c in clips),
      "chunks are in order - one render worker, so seq cannot overtake itself")
check(len({c["seq"] for c in clips}) == len(clips), "no chunk was emitted twice")

spoken = " ".join(c["text"] for c in clips)
lost = [w for w in REPLY.replace("?", "").replace(".", "").replace(",", "").split()
        if w not in spoken]
check(not lost, "every word of the reply was spoken (missing: %r)" % (lost[:5],))

print("2. the FIRST chunk is short - that latency is the whole point")
check(first_seen_at is not None and first_seen_at < len(REPLY) // 2,
      "rendering started before half the reply existed (at char %s of %d)"
      % (first_seen_at, len(REPLY)))
check(len(clips[0]["text"]) < len(REPLY) / 2,
      "first chunk is a fraction of the reply (%d of %d chars)"
      % (len(clips[0]["text"]), len(REPLY)))
check(len(clips[-1]["text"]) >= len(clips[0]["text"]),
      "later chunks are not smaller - fewer round trips once audio is already playing")

print("3. the last sentence survives (it has no trailing space to end it)")
check(clips[-1]["text"].rstrip().endswith("auf."),
      "final sentence was flushed by the turn ending, not dropped: %r"
      % clips[-1]["text"][-30:])

print("4. the machine ```actions block is never spoken")
voice_stream.begin(U)
voice_stream.feed(U, REPLY)
# the pump feeds _strip_actions_live(...), so the block never arrives - assert
# the contract holds even if a caller forgets and hands over the raw reply
voice_stream.finish(U, REPLY + TAIL_ACTIONS)
raw = " ".join(c["text"] for c in drain(U))
check("```" not in raw and "\"type\"" not in raw,
      "no fence or JSON reached a clip")

print("5. a cursor only ever returns what the client has not seen")
voice_stream.begin(U)
voice_stream.feed(U, REPLY)
voice_stream.finish(U, REPLY)
all_clips = drain(U)
seen = all_clips[0]["seq"]
rest, _ = voice_stream.take(U, seen)
check(len(rest) == len(all_clips) - 1 and all(c["seq"] > seen for c in rest),
      "take(after=%d) skipped exactly what was already played" % seen)
check(voice_stream.take(U, all_clips[-1]["seq"])[0] == [],
      "a fully caught-up client gets nothing back")

print("6. Stop drops queued audio instead of talking over the next question")
voice_stream.begin(U)
voice_stream.feed(U, REPLY)
voice_stream.drop(U)
left, pending = voice_stream.take(U, 0)
check(left == [] and not pending, "cancelled turn has no collectable audio left")

print("7. a new turn cannot inherit the previous turn's speech")
voice_stream.begin(U)
voice_stream.feed(U, REPLY)
voice_stream.finish(U, REPLY)
drain(U)
voice_stream.begin(U)
check(voice_stream.take(U, 0)[0] == [], "begin() starts from silence")

print("8. one REAL render, to pin the wire shape the client parses")
# Everything above stubs the renderer, which is right - but it means nothing
# above would notice if a chunk stopped carrying the fields data/voice.ts needs,
# or stopped being JSON at all. So: one genuine edge-tts render through the real
# path, checked as the client sees it.
import json                                                         # noqa: E402
import importlib                                                    # noqa: E402

importlib.reload(voice)                     # undo the stub
voice_stream.begin(U)
voice_stream.finish(U, "Der Deploy ist blockiert.")
real = drain(U, timeout=30)
if not real:
    print("  SKIP  edge-tts unavailable (offline?) - wire shape unverified")
else:
    c = real[0]
    check(all(k in c for k in ("seq", "mime", "b64", "id")),
          "chunk carries seq + the VoiceClip fields voice.ts destructures")
    check(c["mime"] == "audio/mpeg",
          "mime stayed audio/mpeg - iOS matches the data:audio/ prefix literally")
    check(len(c["b64"]) > 500, "real audio came back (%d b64 chars)" % len(c["b64"]))
    try:
        json.dumps({"voice": real, "voice_pending": False})
        ok = True
    except (TypeError, ValueError):
        ok = False
    check(ok, "the whole /chat/live payload serialises as JSON")

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print(" - " + f)
    sys.exit(1)
print("VOICE STREAM OK")
