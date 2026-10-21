# -*- coding: utf-8 -*-
"""The closed set of native tunables and their bounds (settings key `native_tuning`).

The native side clamps again (LiveMicModule.configure, GlassVoiceService.tuneLong) -
this is the front door: an owner write with an unknown key, a non-number or an
out-of-range value is refused here, loudly, instead of being silently clamped on a
phone nobody is looking at.
"""

# key -> (min, max). Mirrors the native clamps.
BOUNDS = {
    "vad_preroll_frames": (0, 100), "vad_min_speech_frames": (1, 200),
    "vad_end_silence_frames": (5, 300), "vad_max_utterance_frames": (50, 3000),
    "vad_abs_floor": (10.0, 5000.0), "vad_snr": (1.1, 20.0),
    "dictation_chunk_samples": (1600, 32000),
    "glass_max_empty_turns": (1, 20), "glass_decide_total_ms": (10000, 600000),
    "glass_capture_timeout_ms": (5000, 120000),
}


def validate(doc):
    """None when `doc` is an acceptable native_tuning patch, else the reason."""
    if not isinstance(doc, dict):
        return "native_tuning must be an object"
    for k, v in doc.items():
        if k not in BOUNDS:
            return "unknown native_tuning key: %s" % k
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "native_tuning.%s must be a number" % k
        lo, hi = BOUNDS[k]
        if not lo <= v <= hi:
            return "native_tuning.%s out of range %s..%s" % (k, lo, hi)
    return None
