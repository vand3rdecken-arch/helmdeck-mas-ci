# -*- coding: utf-8 -*-
"""Pins BEST PRACTICE FIRST on EVERY brief an engineering card can run under.

The 2026-09-23 decree landed only in card-worker.md, but direct builds - the
default build path since 460b2f7 - run on machine-worker.md (machine=True ->
drivers.MACHINE_AGENT). So most engineering never saw it. This reads the
RENDERED briefs through harness.brief (what the spawn actually passes) and
fails if either loses the rule or the owner-facing "Vorbild:" line.

Run: py -3.12 ops/tests/test_worker_best_practice.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import drivers
from spine.registry import harness

for agent in (drivers.CARD_AGENT, drivers.MACHINE_AGENT):
    b = harness.brief(agent)
    assert "BEST PRACTICE FIRST" in b, agent + ": rule missing"
    assert "Vorbild:" in b, agent + ": owner-facing reference line missing"
    print("  ok: %s carries BEST PRACTICE FIRST + Vorbild line" % agent)
print("PASS")
