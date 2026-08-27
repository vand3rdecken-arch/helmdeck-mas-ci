# Background tasks can be marked "completed" without ever being observed running

**Filed 2026-08-27**, found while investigating a card where the UI's
"Hintergrund-Tasks" section showed a task as finished while the actual work
(a subagent/tool call) was still running.

## Root cause

`spine/agent/drivers.py:953-964`, inside `_on_event` on
`typ=="system" and subtype=="task_notification"` (the between-turn
completion path):

```python
st = ev.get("status") or "completed"
if st not in ("completed", "failed", "canceled"):
    st = "completed"
```

If the event is missing `status`, or carries a status this code doesn't
recognize (CLI wording drift, an intermediate/progress status), it is
coerced to `"completed"` instead of staying `running`/unknown. This is an
assumption, not a derivation from an observed signal - the exact thing
`CLAUDE.md`'s "NO MONKEY PATCHES" law forbids.

It's also asymmetric with the in-turn completion path
(`drivers.py:867-877`), which only writes `"completed"` if
`self._bg_open.pop(uid, None) is not None` - i.e. only if this process
actually tracked the task as running first. The between-turn path has no
such guard, so it can mark "completed" for a task this process never saw
start. `self._bg_open`/`_bg_candidates` reset to `{}` on driver-instance
recreation (`drivers.py:604-605`, `621-622`, e.g. session rotation), which
widens the window where this fires wrongly.

Secondary, lower-severity finding in the same area: `_scan_bg`
(`drivers.py:844-877`) only classifies a tool_use as a tracked background
task ("running") via a substring match on tool_result text
(`"Async agent launched"` / `"run_in_background"` / `"background"`,
line 859-860) instead of a structured field - fragile against CLI wording
changes.

## Fix

- In the `task_notification` handler, require an explicit recognized
  terminal status (`completed`/`failed`/`canceled`); on missing/unrecognized
  status, leave the task's prior state alone (or mark `unknown`) rather than
  defaulting to `completed`.
- Consider gating the between-turn completion write the same way the
  in-turn path is gated (only complete what this process tracked as open),
  or otherwise reconcile against a structured signal instead of assuming.
- Not fixing today: the `_scan_bg` substring-match launch detection: register
  it in `spine/registry/debt.py` if it isn't tracked as a known shortcut
  already.

Not a race in the UI or persistence layer - `sessions_bg.bg_upsert`/
`reconcile_bg` (`cells/engineer/sessions_bg.py:29-91`) and
`surfaces/app/src/ui/card_background.tsx` correctly read only the persisted
`status` field.
