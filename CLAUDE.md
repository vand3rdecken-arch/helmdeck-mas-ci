# HelmDeck - agent runbook

Read `ARCHITECTURE.md` first: **the harness is code, policy is data**, and
everything buildable walks charter → card → gate → accept.

The tree reads as the architecture (two-mains split, 2026-08-24): `spine/` =
shared infrastructure no cell owns (auth, http, storage, registry, turn, ...),
`cells/<id>/` = each agentic system's own logic (engineer, pm, process,
connectors, copilot). `daemon/` is only the thin launcher + machine-local
runtime data (db, settings, events) - code does not go there. `app/` is the
ONE frontend (Expo - phone/web/desktop; the old web/ and apk/ live in
archive/). Builds belong to surfaces, never to cells: `deploy/` has one
entrypoint per surface.

Touching the agent layer - briefs, settings, spawn argv, a policy knob, the
loop/lane state machines? Read `HARNESS.md`: where that line falls in code, how
a card/machine/PM spawn resolves, and the traps that were measured rather than
reasoned (`--settings` excludes nothing; a settings file the CLI dislikes is
ignored in SILENCE).

Touching the GLASSES layer - `glasses/`, `/glance`, voice output, proactive
notification, a companion app, the Meta SDK? **`docs/glasses-reference.md` is
MANDATORY reading first** (owner decree). Two real reference projects on this
machine already paid for these answers: the glasses webview has NO
`speechSynthesis` and no background execution (both measured on-device), voice
output is SETTLED as server-rendered speech over the WhatsApp channel, and the
trap register there is dated and specific. Read the ACTUAL source it cites -
same rule as `docs/paseo-adoption-plan.md`.

## The build loop (enforced by hooks)

This repo has the same loop control as the glass harness. State is computed
from disk by `python tools/loop_state.py`; a Stop hook blocks resting while an
agent-actionable state remains; a SessionStart hook re-orients fresh context.

States: `COMPILE → TYPES → VERIFY → DEBT → WIP/COMMIT → DONE`
(fix syntax → fix app types → fix daemon wiring → keep the debt register
well-formed → propose the commit when work goes quiet).

## Laws (do not violate)

- Never weaken the fixed harness: auth, append-only audit/events,
  gate-before-review, measured economics, worktree isolation, driver
  commands, the charter core (`spine/auth/charter.py`).
- New load-bearing shortcut? Register it in `spine/registry/debt.py` in the
  same commit. Paying debt: file the fix card, flip status to `paid`, keep it
  listed.
- Secrets (`settings.json`, `users.json`, `helmdeck.db`, tokens) are
  git-ignored - never commit them.
- UI changes: screenshot and JUDGE (readability, centering, theming,
  collisions), don't just confirm rendering. The owner reviews UI hard.
- NO MONKEY PATCHES (owner-decreed, the Paseo principle): load-bearing state is
  DERIVED and VERIFIED from the runtime's own signals, folded in at EVENT TIME,
  mutated at exactly ONE owner - never assumed from a stored flag, never
  reconstructed by re-scanning artifacts, never adopted without evidence.
  Precedents to imitate: `drivers.turn_active` (lifecycle is an observation),
  `sessions.record_bg` (background registry at event time),
  `sessions.resume_detached` (the session pointer only advances on proof).
  A heuristic reconstruction that ships anyway is a SHORTCUT -> register it in
  `spine/registry/debt.py` in the same commit.

## Run / verify

```
py -3.12 -m daemon.swarm serve               # API :8140 (run from REPO ROOT - daemon/ is the thin launcher)
cd app && npm run web                        # UI (Expo web dev server)
py -3.12 tools/run_gate.py                   # quick check: py_compile daemon/spine/cells + import wiring
cd app && npx tsc --noEmit -p tsconfig.typecheck.json   # app types (incl. cells/<id>/ui)
```
E2E smoke: Playwright against the Expo web dev server (login owner; password
in owner's hands).

## Deploy / ship to the phone

**Read `DEPLOY.md` before shipping** - it is the runbook for getting a change to
the phone/desktop and the traps that cost hours. In short:
- JS/React/asset change → OTA: `bash deploy/push_update.sh` (seconds).
- Native change (native module, permission, app.json plugin, runtimeVersion) →
  APK rebuild (needs JDK 17, forward-slash `local.properties`), then
  `deploy/push_relay.sh` AND a matching OTA (else the old relay bundle reverts
  the JS). Emulator-verify with `adb exec-out screencap -p > shot.png`.
