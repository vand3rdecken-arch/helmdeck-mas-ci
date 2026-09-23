# -*- coding: utf-8 -*-
"""A device overlay (watch / glasses / voice) rides INSIDE the turn text of
Henry's persistent session, so it stays in the transcript. Without a revocation
the next TYPED turn inherits it - measured 2026-09-23: one "you MUST end every
reply with an ask block" shaped three content-free "Noch etwas?" questions in
a row on the phone (card henry-lookup-and-ask-discipline). This pins the one
writer of that state: _surface_switch()."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.copilot.chat import copilot as c

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


c._device_ovl_last.clear()
K = "owner"

# 1) a plain typed turn on a fresh process: nothing to revoke
check(c._surface_switch(K, "", fresh=True) == "", "fresh typed turn -> no revocation")

# 2) watch turn, then typed turn: the typed turn revokes the watch rules
check(c._surface_switch(K, "wear", fresh=False) == "", "device turn itself gets no revocation")
line = c._surface_switch(K, "", fresh=False)
check(line.startswith("GETIPPTER TURN") and "wear" in line,
      "typed after watch -> revocation names the wear overlay")

# 3) and only ONCE - the next typed turn is clean again
check(c._surface_switch(K, "", fresh=False) == "", "second typed turn -> no repeat")

# 4) device -> device (voice after watch): each carries its own overlay, no line
c._surface_switch(K, "wear", fresh=False)
check(c._surface_switch(K, "voice", fresh=False) == "", "voice after watch -> no revocation")
check(c._surface_switch(K, "", fresh=False).startswith("GETIPPTER TURN"),
      "typed after voice -> revocation")

# 5) a fresh process forgets: the old transcript is gone with it
c._surface_switch(K, "glass", fresh=False)
check(c._surface_switch(K, "", fresh=True) == "", "fresh process after glass -> nothing to revoke")

# 6) sessions do not leak into each other
c._surface_switch("owner\x00card:abc", "wear", fresh=False)
check(c._surface_switch("other", "", fresh=False) == "", "another skey stays clean")

# 7) the revocation text itself says what the board turn needs
check("Tools" in c._DEVICE_OVL_REVOKE and "Rueckfrage" in c._DEVICE_OVL_REVOKE,
      "revocation restores tools + question discipline explicitly")

print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
