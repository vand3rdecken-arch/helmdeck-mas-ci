# i18n_lint is RED on the base branch - every worker card bounces at Review

**Filed 2026-08-20 from card `req-worktree-base-sync`.** Not that card's work
(its diff touches zero `surfaces/app/src` files); found while gating it and split off on
the owner's call so a UI-copy change gets its own screenshot review instead of
riding along on a harness change.

## Why this is urgent, not cosmetic

`ops/tools/run_gate.py` runs `ops/tools/i18n_lint.py` as a gate check, and it currently
**fails with 20 violations**. Verified on the CLEAN base checkout
(`C:\Users\Tien Duy Vo\Downloads\swarmdeck`, `expo-migration` @ `1810b33`,
`git status` clean) - so it is the base that is red, not any one card.

Consequence: `lanemachine._gate` runs the repo's gate for EVERY card, so every
worktree card bounces at Review with an i18n punch list about code it never
touched. The board is jammed for classic worker cards until this lands.

Note this is NOT the `gate-base-lag` class and the new `_sync_base` cannot help:
base-sync closes *drift* (card behind base). Here the base itself is red, so
merging it in changes nothing. Fixing the lint IS the fix.

Fast-track/direct cards are unaffected - they never gate (debt
`fast-track-no-gate`).

## The punch list (`py -3.12 ops/tools/i18n_lint.py`)

Rule B - German prose literal in `surfaces/app/src` outside the dicts (14):

```
surfaces/app/src/app/(tabs)/modules.tsx:97   'Agent-Backends hinter einem Kontrakt (Claude / Copilot / Dee…'
surfaces/app/src/app/(tabs)/modules.tsx:102  'verfügbar'
surfaces/app/src/app/(tabs)/modules.tsx:102  'aus'
surfaces/app/src/app/(tabs)/modules.tsx:107  '${surfaces.length} registrierte Oberflächen (Nav aus der Reg…'
surfaces/app/src/app/(tabs)/modules.tsx:111  'Standard = heutiger Charter. Umschalten schreibt einen getra…'
surfaces/app/src/app/(tabs)/modules.tsx:114  'Suite muss grün sein, bevor reviewt wird'
surfaces/app/src/app/(tabs)/modules.tsx:118  'Gemessene Ökonomie'
surfaces/app/src/app/(tabs)/modules.tsx:119  'Aus = Human-Bestätigung nötig'
surfaces/app/src/app/(tabs)/modules.tsx:120  'laufende Karten'
surfaces/app/src/app/(tabs)/modules.tsx:125  'Agentische Systeme (Rolle + Route + UI-Surface + Enable-Flag…'
surfaces/app/src/app/(tabs)/modules.tsx:147  'Quelle: ${charter.source} — selbst ein tauschbares Modul.'
surfaces/app/src/app/(tabs)/modules.tsx:154  'Jede Modul-/Regeländerung, mit Urheber (die einzige Invarian…'
surfaces/app/src/app/(tabs)/modules.tsx:156  'von ${e.actor}${e.replaced ? …'
surfaces/app/src/ui/cell_diagram.tsx:39      'keine Routen'
```

Rule D - JSX text node with real prose, unwrapped (6):

```
surfaces/app/src/app/(tabs)/modules.tsx:90   'Module & Regeln'
surfaces/app/src/app/(tabs)/modules.tsx:104  'Kein Kernel — Fallback aktiv.'
surfaces/app/src/app/(tabs)/modules.tsx:135  'Keine Cells geladen.'
surfaces/app/src/app/(tabs)/modules.tsx:157  'Noch keine Einträge.'
surfaces/app/src/app/kernel-demo.tsx:20      'no renderable surface'
surfaces/app/src/ui/login_screen.tsx:84      'Konto erstellen'
```

17 of 20 sit in the plugin-kernel `modules.tsx` screen (see memory
`helmdeck-plugin-kernel`); it shipped with its copy hardcoded.

**Treat this list as the current output, not a closed set** - re-run the lint
after each pass. Neighbouring prose exists that this run did not flag (e.g. the
subtitle at `modules.tsx:91`), and moving literals into the dict can change what
rules B/D see on the following lines. Done means the lint exits 0, not that
these 20 lines were edited.

## How to fix

Add keys to a dict in `surfaces/app/src/i18n/dict/` (`screens.ts` is the right home for
`modules.tsx` / `cell_diagram.tsx` / `kernel-demo.tsx`; `login_screen.tsx`
belongs with the onboarding chrome) and call the translator. Entry shape:

```ts
"modules.title": { de: "Module & Regeln", en: "Modules & rules" },
```

**TRAP that probably caused this in the first place:** in `modules.tsx` and
`cell_diagram.tsx` the identifier `t` is ALREADY bound to `useTheme()`. Do not
shadow it - alias the translator the way `surfaces/app/src/ui/board.tsx:15` does:

```ts
import { t as tt, useT } from "@/i18n";
```

`kernel-demo.tsx:20`'s `'no renderable surface'` is English developer-facing
text in a demo screen - decide whether it is real UI copy (translate) or a
debug string (rule D may need the literal restructured); do not just German-ify
it to silence the lint.

## Verify

```
py -3.12 ops/tools/i18n_lint.py                 # must print "i18n lint: N keys" and exit 0
cd surfaces/app && npx tsc --noEmit                  # dict keys are typed
```

Then, per `CLAUDE.md`, **screenshot and JUDGE** the Module screen in BOTH
languages - the English labels are mostly longer than the German ones, so check
the stat rows and the section subtitles for overflow/wrapping, not just that it
renders.
