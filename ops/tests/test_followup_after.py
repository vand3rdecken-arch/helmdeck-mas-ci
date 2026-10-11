# -*- coding: utf-8 -*-
"""Pins 2026-10-11 12:36-14:18: a conditional follow-up ("when the pages card
is done, start three apps") was attempted at once, failed twice and was given
up; nothing started the next stage until the owner typed "Ok". A follow-up with
`after` must wait while that card's turn is alive, then run. RED on old code
(no `after` field -> dispatched immediately). Run: py -3.12 ops/tests/test_followup_after.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
S = tempfile.mkdtemp(prefix="hd-fu-after-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(S, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(S, "settings.json")
_db.init()
from spine.registry import escalations
from spine.agent import drivers
from cells.copilot.broker import henry_broker as hb

ran = []
hb._run_followup = lambda esc: (ran.append(esc["id"]), hb._followups_inflight.discard(esc["id"]))
busy = {"CARD-A": True}
drivers.turn_inflight = lambda tid: busy.get(tid, False)

escalations.emit("henry-followup", card=None, detail="start next stage", after="CARD-A")
time.sleep(0.01)
escalations.emit("henry-followup", card=None, detail="plain check")
for th in hb._dispatch_pass(escalations.list_open()): th.join(2)
plain_only = len(ran) == 1
busy["CARD-A"] = False
for th in hb._dispatch_pass([e for e in escalations.list_open() if e.get("after")]): th.join(2)
ok = plain_only and len(ran) == 2
print("waits while card runs, runs after:", "OK" if ok else "FAIL", ran)
sys.exit(0 if ok else 1)
