# -*- coding: utf-8 -*-
"""Real-model benchmark: streamed dictation vs decode-everything-after-stop.

Renders a spoken German paragraph (edge-tts, needs network), then feeds it to
the REAL manager + REAL parakeet in two ways:

  batch    wait for "stop", decode the whole utterance      (what /voice/transcribe
           costs on the PC, upload excluded)
  stream   feed 0.5 s chunks paced at real time while "speaking", then finish()

and prints stop-to-text latency for each plus whether the texts agree. The
number that matters is `stop->text`: the user's wait after letting go.

Run: py -3.12 ops/tools/dictation_stream_bench.py [seconds_of_speech_min]
"""
import asyncio
import io
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEXTS = {
    "short": "Verschiebe die Karte bitte auf Review und starte danach einen neuen Build für die App.",
    "long": ("Henry, fass mir bitte kurz zusammen, was gestern in der Android Recherche passiert ist. "
             "Welche Karten warten gerade auf mein Feedback, und gibt es etwas, das heute noch raus muss? "
             "Falls der Build schon durch ist, schieb ihn bitte aufs Telefon und sag mir Bescheid, "
             "sobald das Update dort angekommen ist."),
}
VOICE = "de-DE-KatjaNeural"


def render(text):
    import edge_tts
    from faster_whisper.audio import decode_audio
    path = os.path.join(tempfile.gettempdir(), "dict_bench_%d.mp3" % abs(hash(text)))

    async def go():
        await edge_tts.Communicate(text, VOICE).save(path)
    asyncio.run(go())
    x = decode_audio(path, sampling_rate=16000)
    import numpy as np
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def main():
    from spine.media import dictation_stream as ds, stt
    stt.transcribe_pcm16(b"\0\0" * 16000)                       # warm the model once
    print("model warm: %s" % stt._MODEL_NAME)
    CH = int(0.5 * 16000) * 2
    for label, text in TEXTS.items():
        pcm = render(text)
        secs = len(pcm) / 32000.0
        t = time.time()
        base = stt.transcribe_pcm16(pcm)
        batch_ms = (time.time() - t) * 1000

        did = "bench-" + label
        ds.start("bench", did)
        n = 0
        t0 = time.time()
        for i in range(0, len(pcm), CH):
            ds.chunk("bench", did, n, pcm[i:i + CH])
            n += 1
            # real time: the owner is still talking
            wait = t0 + (n * 0.5) - time.time()
            if wait > 0:
                time.sleep(wait)
        t = time.time()
        out = ds.finish("bench", did, n - 1)["text"]
        stream_ms = (time.time() - t) * 1000
        print("\n[%s] %.1f s of speech" % (label, secs))
        print("  batch  stop->text %7.0f ms   (decode of the whole utterance)" % batch_ms)
        print("  stream stop->text %7.0f ms   (finish() after real-time feed)" % stream_ms)
        print("  texts equal: %s" % (out == base))
        print("  batch : " + base)
        print("  stream: " + out)


if __name__ == "__main__":
    main()
