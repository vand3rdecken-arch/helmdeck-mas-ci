# -*- coding: utf-8 -*-
"""Headless unit tests - stdlib + pytest only, no daemon, no network, no
claude CLI. daemon/ modules import each other flat (`import sessions`), so
daemon/ goes on sys.path; tests that need `sessions`/`events` inject fakes
into sys.modules instead of importing the real ones."""
import os
import sys

DAEMON = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "daemon"))
if DAEMON not in sys.path:
    sys.path.insert(0, DAEMON)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
