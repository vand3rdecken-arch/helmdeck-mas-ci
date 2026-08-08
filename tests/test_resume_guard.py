# -*- coding: utf-8 -*-
"""The session-pointer invariant: it only moves forward to a session that
DEMONSTRABLY contains the conversation (Paseo: session identity is verified
from the runtime's own signals, never assumed). resume_detached() judges the
first turn after a --resume spawn: the init event's id ECHO confirms an attach
for certain; otherwise the first API call's context is the witness - a real
continuation carries >= the prior context, a silent fresh start only the brief.
Pins the exact numbers of the 'Voellig falscher Kontext' incident."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "daemon"))
import db
db.init()
import sessions as S

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def m(first_ctx=None, echo=False, resumed="x"):
    meta = {"resumed_from": resumed, "resume_echo": echo}
    if first_ctx is not None:
        meta["ctx_first"] = {"cache_read_input_tokens": first_ctx}
    return meta


# the real incident: prev 49k conversation, fresh boot carried only ~14k brief
check(S.resume_detached(49000, m(14000)) is True,
      "the incident is caught (49k prev, 14k first, no echo)")
# a healthy continuation carries at least the prior context
check(S.resume_detached(49000, m(50000)) is False,
      "healthy continuation not flagged")
# the init echo is definitive - never flagged even with a small first call
check(S.resume_detached(49000, m(14000, echo=True)) is False,
      "init echo confirms attach - never flagged")
# small histories are never judged (fresh boot is indistinguishable)
check(S.resume_detached(10000, m(5000)) is False, "small history never flagged")
# CLI-side compaction on resume shrinks legitimately - not flagged
check(S.resume_detached(160000, m(85000)) is False, "resume compaction not flagged")
# no witness -> never flag on absence of evidence
check(S.resume_detached(49000, m(None)) is False, "no first-call witness -> no flag")
# not a resume spawn -> never
check(S.resume_detached(49000, {"ctx_first": {"cache_read_input_tokens": 100}}) is False,
      "non-resume turn never flagged")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("resume-guard: all pinned - PASS")
