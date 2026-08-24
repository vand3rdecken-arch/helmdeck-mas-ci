# archive/ — the pre-Expo frontends (kept, not deleted)

`web/` (Next.js SPA) and `apk/` (Kotlin/Jetpack Compose) were the two hand-written
frontends before the migration to a single Expo/React-Native codebase in `app/`
(one codebase → Android · Web · Desktop; see `.claude/plans/piped-crafting-goose.md`).

They are **archived, not removed** — recoverable if the Expo app needs a fallback
or a reference. They are no longer built or shipped. The active frontend is `app/`;
the desktop (`surfaces/desktop/`) now serves the Expo web export.

Do **not** delete this folder until the Expo app is confirmed at full parity in
production. The build/ops/deploy/loop wiring that still references these paths is
tracked as debt `expo-cutover-pipeline` in `daemon/debt.py`.
