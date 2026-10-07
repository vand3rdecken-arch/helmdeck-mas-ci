# -*- coding: utf-8 -*-
"""Capped, RESTORABLE output for Henry's readers (board_state, henry_inbox,
henry_memory_get, ship_facts, henry_brief_get).

The pattern every popular harness converged on (OpenCode: 2,000 lines / 50 KB
per tool output, archived; Cursor: long tool outputs become files; Manus:
"restorable compression" - drop the content, keep the path): a reader never
floods the context, and nothing is lost, because the FULL output sits in a
file the model can Read/Grep when it actually needs the rest. Measured
2026-10-07: Henry's chat averaged 341k tokens per message, most of it old
tool output re-read on every step.

Head + tail, not head only: the end of a board listing or a log is where the
newest line sits. The cut note names the file and the size, so the model
KNOWS it saw a part (silent truncation is the documented failure mode).

Budget per reader is the caller's choice (`cap`, chars); HELMDECK_CTX_CAP
overrides every budget (0 = never cut, for a terminal user).
"""
import io
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

DEFAULT_CAP = 12_000          # chars, ~3k tokens
TAIL_SHARE = 0.25             # of the cap that is the tail


def _ctx_dir():
    from daemon.paths import DATA_ROOT
    return os.path.join(DATA_ROOT, "state", "ctx", "out")


def _store(name, text):
    """Full text -> file path (forward slashes, so it pastes into Read/Grep on
    every shell), or None when writing fails - the cut still happens, the
    note then says so."""
    try:
        d = _ctx_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "%s-%s.txt" % (name, time.strftime("%Y%m%d-%H%M%S")))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return path.replace("\\", "/")
    except OSError:
        return None


def cut(text, name, cap=DEFAULT_CAP):
    """(shown_text, path_or_None). Under the cap the text passes untouched."""
    env = os.environ.get("HELMDECK_CTX_CAP")
    if env is not None:
        try:
            cap = int(env)
        except ValueError:
            pass
    if cap <= 0 or len(text) <= cap:
        return text, None
    path = _store(name, text)
    tail_n = int(cap * TAIL_SHARE)
    head = text[:cap - tail_n].rstrip()
    tail = text[-tail_n:].lstrip() if tail_n else ""
    note = ("\n\n[... gekürzt: %d von %d Zeichen gezeigt (Kopf + Ende). Voll: %s - "
            "bei Bedarf Read/Grep darauf ...]\n\n"
            % (cap, len(text), path or "(Datei konnte nicht geschrieben werden)"))
    return head + note + tail, path


def run(main, argv, name, cap=DEFAULT_CAP):
    """Run a reader's main(argv) with stdout captured, print the capped
    version, return main's exit code. Errors the reader prints to stderr pass
    through live."""
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        rc = main(argv)
    except SystemExit as e:
        rc = e.code
    finally:
        sys.stdout = real
    shown, _ = cut(buf.getvalue(), name, cap)
    sys.stdout.write(shown)
    sys.stdout.flush()
    return rc or 0
