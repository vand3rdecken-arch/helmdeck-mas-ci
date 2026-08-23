# -*- coding: utf-8 -*-
"""Server-side speech-to-text - the STT stage of the LIVE voice pipeline.

The phone's LiveMic module (app/modules/livemic) cuts utterances with its own
VAD and sends each one as a small WAV blob over the sealed relay - the same
whole-small-blobs transport voice_stream.py uses for TTS, in reverse. This
module turns one blob into text.

WHY SERVER-SIDE AND NOT ON-DEVICE: Android's platform recognizer cannot eat
external audio, and on-device Whisper is either poor (tiny) or heavy (~500 MB
+ battery). The daemon runs on the owner's PC where a real model is cheap -
the same split as TTS (daemon renders, phone plays), applied to the ear.

FAILS SOFT, but LOUDLY TYPED: a missing faster-whisper is a 501 with the exact
install command, never a silent empty transcript - a voice mode that "hears
nothing" without saying why is the worst failure shape this layer knows.

Model choice is a SETTING (voice_stt_model, default "small" - fine for German
commands on CPU), the first call pays the model download + load once; the
loaded model is cached for the daemon's lifetime, one owner (_MODEL).
"""
import io
import os
import threading

_MODEL = None
_MODEL_NAME = None
_LOCK = threading.Lock()

#: refuse blobs beyond this - a VAD segment is <= 15 s of 16 kHz PCM16 (~480 KB
#: + header); ten times that is not an utterance, it is a mistake or an attack.
MAX_WAV_BYTES = 5 * 1024 * 1024


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _model():
    global _MODEL, _MODEL_NAME
    from daemon.spine.storage import events
    from daemon.paths import DAEMON_ROOT
    name = (events.settings().get("voice_stt_model") or "small").strip() or "small"
    with _LOCK:
        if _MODEL is not None and _MODEL_NAME == name:
            return _MODEL
        from faster_whisper import WhisperModel
        # int8 on CPU: ~4x smaller, negligible WER cost for command-length
        # utterances; download_root keeps the weights beside the daemon's other
        # caches instead of a surprise directory in %USERPROFILE%.
        _MODEL = WhisperModel(name, device="cpu", compute_type="int8",
                              download_root=os.path.join(DAEMON_ROOT, "models_stt"))
        _MODEL_NAME = name
        return _MODEL


def transcribe(wav_bytes, lang=None):
    """WAV blob -> (text, info dict). Raises RuntimeError with a human-readable
    reason on anything the caller should surface (missing package, bad blob)."""
    if not available():
        raise RuntimeError(
            "faster-whisper fehlt: py -3.12 -m pip install faster-whisper")
    if not wav_bytes or len(wav_bytes) > MAX_WAV_BYTES:
        raise RuntimeError("audio missing or too large")
    m = _model()
    segments, info = m.transcribe(
        io.BytesIO(wav_bytes),
        language=(lang or None),
        beam_size=5,
        vad_filter=False,          # the phone's VAD already cut the utterance
        condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, {"lang": getattr(info, "language", None),
                  "p": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
                  "dur": round(float(getattr(info, "duration", 0.0) or 0.0), 2)}
