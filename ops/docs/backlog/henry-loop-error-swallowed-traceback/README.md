# Henry broker loop errors constantly, but the traceback is swallowed

**Filed 2026-08-31**, found while diagnosing "warum kaputt Henry" /
"desktop+phone verbinden konstant neu" (unrelated relay flapping investigated
same session). `daemon/daemon.out.log` is full of:

```
henry: loop error: <class 'OSError'> returned a result with an exception set
henry: loop error: <built-in function fspath> returned a result with an exception set
henry: loop error: <built-in function kill> returned a result with an exception set
```

20+ occurrences in the last ~3 hours of log, recurring on essentially every
`_loop()` tick (`cells/copilot/henry_broker.py:643`). One adjacent line in the
same log window: a real `PermissionError: [WinError 5] Access is denied` on
`copilot_log.json.tmp` -> `copilot_log.json` - plausibly the same root cause
(a locked file during rename), but not confirmed, because...

## Root cause: unknown - the handler hides it

```python
except Exception as e:
    print("henry: loop error:", str(e)[:200])
```

`str(e)` on a `SystemError` ("`<built-in function X>` returned a result with
an exception set") gives you the *wrapper* message, not the *inner* exception
that CPython caught while calling a C-level builtin (`os.kill`, `os.fspath`,
etc.). This is CPython's own signal that a C API call raised without setting
a Python exception downstream, and it always has a real `__cause__`/
`__context__` chain worth reading. The current handler discards it every
time, so the actual failure driving Henry's escalation loop into constant
errors has never been observed. Guess for the underlying issue (Windows file
lock, likely Defender/indexer contention on daemon/*.json, given the sibling
PermissionError) but not verified.

## Fix

- Log the full traceback (`traceback.format_exc()`), not `str(e)[:200]`, at
  `cells/copilot/henry_broker.py:657`.
- Once the real cause is visible, fix that - not this line. This card exists
  because "never be silent" (the broker's own stated purpose, see the comment
  right above `_loop`) is currently only half true: it logs *that* it failed
  on every tick, never *why*.

## Non-goals

- Guessing and patching the Defender/file-lock theory blind. Get the real
  traceback first.
