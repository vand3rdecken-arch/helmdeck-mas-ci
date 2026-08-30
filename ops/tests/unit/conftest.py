# -*- coding: utf-8 -*-
"""Headless unit tests - stdlib + pytest only, no daemon, no network, no
claude CLI. Tests that need `sessions`/`events` inject fakes into sys.modules
instead of importing the real ones.

This put "<repo>/daemon" on sys.path, from the era when modules imported their
neighbours flat (`import sessions`). The four-folder split ended that and took
the WHOLE unit suite with it: all three tests died at collection with
ModuleNotFoundError and nothing said so, because the gate is LIGHT by decree
(CLAUDE.md) and deliberately runs no suite. A dead test is worse than a missing
one - it still compiles, so the folder goes on looking maintained.

STATUS 2026-08-30 after the repair: 29 pass, 6 fail. The suite is USEFUL again,
and the six reds are honest signal, not noise - none is a product regression,
and each is named here so nobody has to re-derive it:

  test_debt::test_orders_are_unique_ints - a REAL finding, and not new: five
    duplicate `order` values (-4, 0, 1, 16, 29) piled up in the debt register
    while this guard was dead. Exactly the rot a dead test permits. Left red on
    purpose - renumbering entries that other cards are editing is a merge
    conflict waiting to happen, and the red keeps saying it until someone does.
  test_drivers (x4) - stale ASSERTIONS, checked against the product: the meta
    dict legitimately grew a `ctx_usage` key, and the argv/cancel expectations
    describe an older _ClaudeSession. `--resume` was verified directly against
    drivers.build_argv and IS emitted, so the one regression that would have
    mattered (the cmd-shim bug that ate --resume and cost every worker its
    context) is NOT back.
  test_nightshift::test_claim_failure_does_not_raise - one fake still thinner
    than the code it stands in for.

Closing those six means updating fixtures to match evolved behaviour: a card,
not a sweep - tracked as `e2e-harnesses-stale-after-split` in
spine/registry/debt.py."""
import os
import sys

ROOT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
