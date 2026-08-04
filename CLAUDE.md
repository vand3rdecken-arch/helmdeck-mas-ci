# HelmDeck - agent runbook

Read `ARCHITECTURE.md` first: **the harness is code, policy is data**, and
everything buildable walks charter → card → gate → accept.

## The build loop (enforced by hooks)

This repo has the same loop control as the glass harness. State is computed
from disk by `python tools/loop_state.py`; a Stop hook blocks resting while an
agent-actionable state remains; a SessionStart hook re-orients fresh context.

States: `COMPILE → TYPES → VERIFY → DEBT → WIP/COMMIT → DONE`
(fix syntax → fix web types → fix daemon wiring → keep the debt register
well-formed → propose the commit when work goes quiet).

## Laws (do not violate)

- Never weaken the fixed harness: auth, append-only audit/events,
  gate-before-review, measured economics, worktree isolation, driver
  commands, the charter core (`daemon/charter.py`).
- New load-bearing shortcut? Register it in `daemon/debt.py` in the same
  commit. Paying debt: file the fix card, flip status to `paid`, keep it listed.
- Secrets (`settings.json`, `users.json`, `helmdeck.db`, tokens) are
  git-ignored - never commit them.
- UI changes: screenshot and JUDGE (readability, centering, theming,
  collisions), don't just confirm rendering. The owner reviews UI hard.

## Run / verify

```
cd daemon && py -3.12 swarm.py serve        # API :8140
cd web && npm run dev -- --port 3300        # UI
py -3.12 -m py_compile daemon/*.py          # quick daemon check
cd web && npx tsc --noEmit                  # web types
```
E2E smoke: Playwright against :3300 (login owner; password in owner's hands).

## Deploy / ship to the phone

**Read `DEPLOY.md` before shipping** - it is the runbook for getting a change to
the phone/desktop and the traps that cost hours. In short:
- JS/React/asset change → OTA: `bash deploy/push_update.sh` (seconds).
- Native change (native module, permission, app.json plugin, runtimeVersion) →
  APK rebuild (needs JDK 17, forward-slash `local.properties`), then
  `deploy/push_relay.sh` AND a matching OTA (else the old relay bundle reverts
  the JS). Emulator-verify with `adb exec-out screencap -p > shot.png`.
