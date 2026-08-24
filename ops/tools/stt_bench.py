# -*- coding: utf-8 -*-
"""STT pipeline quality benchmark (owner ask 2026-08-23: "teste verschiedene
Pipelines, teste auf Qualitaet").

One German test set - HelmDeck's real command vocabulary, anglicisms included -
rendered with three edge-tts voices, run through every candidate ear in two
conditions:

  clean16k  the phone-mic live pipeline (16 kHz)
  hfp8k     the GLASSES case: resampled to 8 kHz and back (telephone band),
            what an SCO-routed glasses mic would deliver

Engines:
  fw-tiny / fw-base / fw-small     faster-whisper int8 on the PC (relay path)
  sherpa-whisper-tiny              the EXACT on-device model of build 57
  sherpa-zipformer-de-kroko        dedicated German streaming zipformer
  sherpa-canary-180m               NeMo Canary 180M int8 (de) - device-plausible
  sherpa-parakeet-0.6b-v3          NeMo Parakeet TDT 0.6B v3 int8 - quality ref

Scores: WER (jiwer, casefolded, punctuation-stripped) + warm per-utterance
latency on this PC. HONESTY NOTE printed with the results: edge-tts is clean
studio speech - real-mic numbers will be worse across the board; the RANKING
is what transfers, not the absolute WER.
"""
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MODELS = os.path.join("daemon", "models_stt")

SENTENCES = [
    "Verschiebe die Karte bitte auf Review.",
    "Was ist der Stand der Android-Recherche?",
    "Henry, starte einen neuen Build für die App.",
    "Wie viele Karten warten gerade auf mein Feedback?",
    "Deploye die Änderung auf das Telefon.",
    "Erkläre mir das Zombie-Sweep-Problem in der Worktree-Karte.",
    "Lege eine neue Aufgabe für die Brillen-Integration an.",
    "Wie viel vom wöchentlichen Budget haben wir verbraucht?",
    "Brich den laufenden Turn ab und fang neu an.",
    "Fasse die drei wichtigsten Blocker kurz zusammen.",
    "Der Gate-Check ist rot, woran liegt das?",
    "Schick mir das Ergebnis als Push aufs Handy.",
]
VOICES = ["de-DE-KatjaNeural", "de-DE-ConradNeural", "de-DE-AmalaNeural"]


def render_set():
    """[(ref_text, voice, mp3_bytes)] via edge-tts."""
    import asyncio
    import edge_tts

    async def one(text, voice):
        c = edge_tts.Communicate(text, voice)
        b = b""
        async for ch in c.stream():
            if ch["type"] == "audio":
                b += ch["data"]
        return b

    async def all_():
        out = []
        for t in SENTENCES:
            for v in VOICES:
                out.append((t, v, await one(t, v)))
        return out

    return asyncio.run(all_())


def decode_16k(mp3_bytes):
    """mp3 -> float32 mono 16k via PyAV (ships with faster-whisper)."""
    import numpy as np
    from faster_whisper.audio import decode_audio
    return np.asarray(decode_audio(io.BytesIO(mp3_bytes), sampling_rate=16000),
                      dtype="float32")


def to_hfp8k(x16):
    """Telephone-band sim: 16k -> 8k -> 16k with a crude FFT brickwall at
    3.4 kHz first (CVSD's band), pure numpy - no scipy dependency."""
    import numpy as np
    X = np.fft.rfft(x16)
    freqs = np.fft.rfftfreq(len(x16), d=1 / 16000)
    X[(freqs < 300) | (freqs > 3400)] = 0
    band = np.fft.irfft(X, n=len(x16)).astype("float32")
    x8 = band[::2]                       # decimate to 8k (band-limited already)
    up = np.repeat(x8, 2)                # naive upsample back to 16k
    return up.astype("float32")


def norm(s):
    s = s.lower()
    s = re.sub(r"[^a-zäöüß0-9\s-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---- engines ---------------------------------------------------------------

def eng_faster_whisper(size):
    from faster_whisper import WhisperModel
    m = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4,
                     download_root=MODELS)

    def run(x16):
        segs, _ = m.transcribe(x16, language="de", beam_size=1,
                               condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs)
    return run


def eng_sherpa_whisper_tiny():
    import sherpa_onnx
    d = os.path.join(MODELS, "sherpa-onnx-whisper-tiny")
    r = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=os.path.join(d, "tiny-encoder.int8.onnx"),
        decoder=os.path.join(d, "tiny-decoder.int8.onnx"),
        tokens=os.path.join(d, "tiny-tokens.txt"),
        language="de", task="transcribe", num_threads=2)

    def run(x16):
        s = r.create_stream()
        s.accept_waveform(16000, x16)
        r.decode_stream(s)
        return s.result.text
    return run


def eng_sherpa_kroko():
    import sherpa_onnx
    d = os.path.join(MODELS, "sherpa-onnx-streaming-zipformer-de-kroko-2025-08-06")
    files = os.listdir(d)

    def pick(sub):
        c = [f for f in files if sub in f and f.endswith(".onnx")]
        c.sort(key=lambda f: ("int8" not in f, f))       # prefer int8
        return os.path.join(d, c[0])
    r = sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=pick("encoder"), decoder=pick("decoder"), joiner=pick("joiner"),
        tokens=os.path.join(d, "tokens.txt"), num_threads=2)

    def run(x16):
        s = r.create_stream()
        s.accept_waveform(16000, x16)
        import numpy as np
        s.accept_waveform(16000, np.zeros(8000, dtype="float32"))  # flush tail
        s.input_finished()
        while r.is_ready(s):
            r.decode_stream(s)
        return r.get_result(s)
    return run


def _pick(d, sub, prefer_int8=True):
    files = [f for f in os.listdir(d) if sub in f and f.endswith(".onnx")]
    files.sort(key=lambda f: ("int8" not in f, f))
    return os.path.join(d, files[0])


def eng_sherpa_canary():
    import sherpa_onnx
    d = os.path.join(MODELS, "sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8")
    r = sherpa_onnx.OfflineRecognizer.from_nemo_canary(
        encoder=_pick(d, "encoder"), decoder=_pick(d, "decoder"),
        tokens=os.path.join(d, "tokens.txt"),
        src_lang="de", tgt_lang="de", num_threads=4)

    def run(x16):
        s = r.create_stream()
        s.accept_waveform(16000, x16)
        r.decode_stream(s)
        return s.result.text
    return run


def eng_sherpa_parakeet():
    import sherpa_onnx
    d = os.path.join(MODELS, "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8")
    r = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=_pick(d, "encoder"), decoder=_pick(d, "decoder"),
        joiner=_pick(d, "joiner"), tokens=os.path.join(d, "tokens.txt"),
        model_type="nemo_transducer", num_threads=4)

    def run(x16):
        s = r.create_stream()
        s.accept_waveform(16000, x16)
        r.decode_stream(s)
        return s.result.text
    return run


ENGINES = {
    "fw-tiny": lambda: eng_faster_whisper("tiny"),
    "fw-base": lambda: eng_faster_whisper("base"),
    "fw-small": lambda: eng_faster_whisper("small"),
    "sherpa-whisper-tiny (device build57)": eng_sherpa_whisper_tiny,
    "sherpa-zipformer-de-kroko (streaming)": eng_sherpa_kroko,
    "sherpa-canary-180m (de)": eng_sherpa_canary,
    "sherpa-parakeet-0.6b-v3": eng_sherpa_parakeet,
}


def main():
    from jiwer import wer
    print("rendering test set (%d utterances)..." % (len(SENTENCES) * len(VOICES)))
    testset = render_set()
    clips = []
    for ref, voice, mp3 in testset:
        x = decode_16k(mp3)
        clips.append((ref, voice, x, to_hfp8k(x)))
    results = {}
    for name, mk in ENGINES.items():
        try:
            t0 = time.time()
            run = mk()
            load_s = time.time() - t0
        except Exception as e:
            print(f"!! {name}: SETUP FAILED: {type(e).__name__}: {e}")
            continue
        for cond in ("clean16k", "hfp8k"):
            refs, hyps, lat = [], [], []
            for ref, voice, x16, x8 in clips:
                x = x16 if cond == "clean16k" else x8
                t0 = time.time()
                try:
                    hyp = run(x)
                except Exception as e:
                    hyp = ""
                lat.append(time.time() - t0)
                refs.append(norm(ref))
                hyps.append(norm(hyp))
            w = wer(refs, hyps)
            lat_sorted = sorted(lat)
            med = lat_sorted[len(lat) // 2]
            results[(name, cond)] = (w, med)
            print(f"{name:42s} {cond:8s} WER={w*100:5.1f}%  median={med:5.2f}s  (load {load_s:.1f}s)")
    out = {f"{n}|{c}": {"wer": round(w, 4), "median_s": round(m, 3)}
           for (n, c), (w, m) in results.items()}
    with open("ops/tools/stt_bench_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("\nHONESTY NOTE: edge-tts is clean studio speech; absolute WER is a")
    print("best case - the RANKING and the clean-vs-8k delta are what transfer.")


if __name__ == "__main__":
    main()
