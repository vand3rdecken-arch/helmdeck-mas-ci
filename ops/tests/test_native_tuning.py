# -*- coding: utf-8 -*-
"""native_tuning: the defaults sit inside their own bounds, and the front door refuses junk."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spine.ops import native_tuning as nt
from spine.storage import events

d = events.DEFAULTS["native_tuning"]
assert set(d) == set(nt.BOUNDS), set(d) ^ set(nt.BOUNDS)
assert nt.validate(d) is None, nt.validate(d)
assert nt.validate({"vad_snr": 3.0}) is None
for bad in ({"nope": 1}, {"vad_snr": "3"}, {"vad_snr": True}, {"vad_snr": 99},
            {"glass_decide_total_ms": 1}, [], "x"):
    assert nt.validate(bad), bad
print("PASS test_native_tuning")
