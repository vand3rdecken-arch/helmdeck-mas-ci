# Per-user view config: each registered user owns their board's look; HelmDeck renders

> **SUPERSEDED 2026-09-01 by `ops/docs/backlog/accounts-boards-prd/`** (owner Q&A:
> Jira model - personal BOARDS replace per-user column overlays; account-first
> onboarding). This card's research/data-model notes remain referenced there;
> dispatch from the PRD's phase table, not from here.


**Filed 2026-09-01, owner decree:** "Each user should be able to register and
save their own config in db. They can set lanes, labels etc. HelmDeck is just
rendering." Refined same day: "Best is to let users create account, log in
and then save all config cleanly."

## Account-first (the refinement, and what it buys)

The account is the config's home, not the device. Consequences:

- **Log in anywhere, same view.** Today the app's view preferences live in
  each device's local storage, so phone/web/desktop drift apart per device.
  After this card, everything view-shaped is saved to the account via
  `PUT /me/ui` and hydrated from `GET /me` on login - a fresh browser on a
  new machine renders YOUR board the moment you sign in. Device-local
  storage keeps only a cache of the last-known account config (offline
  render) that re-syncs on connect.
- **Registration -> login -> config is one clean path**: the sign-in screen
  and invite-code registration already exist (routes_auth.py,
  `registration` settings block); this card adds nothing to auth itself -
  the auth law stays fixed. A fresh `default_role: client` account starts
  with the workspace defaults and may immediately personalize its own view.
- **What stays on the device, deliberately:** pairing material (relay room,
  keypairs, tokens in expo-secure-store) - that is device identity and
  secret material, not preference; it must never travel to the server. The
  boundary: config = account, credentials = device.

## The load-bearing distinction (do not blur it)

Three layers, and only the first becomes per-user:

1. **VIEW (per-user, this card):** labels, language, column layout, ordering,
   visibility, appearance, dashboard composition. Pure rendering - two users
   with different views of the same board are both right.
2. **WORKSPACE POLICY (stays global, owner/role-gated):** auto_accept_green,
   WIP limit, dispatch priority, repo hooks. These command the ONE shared
   daemon and its machine - two users with different auto-accept on the same
   board is not personalization, it is incoherence.
3. **LAW (stays code):** the station graph backlog→working→gate→review→done,
   worktree isolation, gate-before-review, merge rails. Also a security
   boundary: settings are chat-reachable (HARNESS.md §3) - a data-defined
   graph would let a chat turn delete the quality gate.

Per-user LANES are therefore a **view mapping onto the fixed stations**, not
new machine states (the GitHub-Projects model: status field is canonical,
columns are presentation).

## What already exists (measured, not assumed)

- `board.tsx:67` already resolves `me?.ui?.lane_labels ?? settings.policy...`
  - the app PREFERS a per-user ui config that no backend provides yet.
- `/me` (routes_misc.py:34) already ships a `ui` object - today faked from
  the global `policy.lane_labels`. The wire shape (`types.ts` `Me.ui`) exists.
- Registration exists: `registration` settings block (open/invite_code/
  default_role), routes_auth.py serves it, users.json + roles + caps matrix
  (`permissions.matrix()`, served as `me.caps`) are live.
- `spine/storage/db.py`: SQLite WAL, per-write `_version` bump that the SSE
  long-poll wakes on - exactly the live-update mechanism a config write needs.

## Phase 1 - per-user storage + API (small; unblocks everything)

- `db.py`: table `user_config(user TEXT, key TEXT, value TEXT/JSON,
  updated_at)`, PK (user, key). Writes bump `_version` so open boards
  re-render live. Migration on first start, same pattern as tracks/events.
- `GET /me`: resolve `ui` = user rows overlaid OVER the workspace defaults
  (global `policy.lane_labels` becomes the default layer, not the answer).
- New `PUT /me/ui` (or `/me/config`): ANY authenticated user, writes ONLY
  their own rows - self-scope IS the authorization check, no new capability
  needed; the global `POST /settings` stays owner-only, untouched. Server-side
  whitelist of keys (lang, lane_labels, appearance, dashboard, board_columns)
  + size bound; emit an `events.emit("user_config", ...)` line per write
  (audit law: who changed their view when - cheap, append-only).
- App: Settings gets a "Meine Ansicht" section writing to `/me/ui`; the
  existing owner-global controls stay where they are. `client.ts` Me.ui type
  grows the new keys (the ts-contract test in test_harness_layer.py will
  hold both sides to it).
- App hydration order (account-first): local cache renders instantly ->
  `GET /me` on login/reconnect overwrites it -> user edits write through to
  `PUT /me/ui` AND the cache. Every device-local view preference the app
  holds today migrates into this flow (one-time: on first login after the
  update, push the device's current values up IF the account has none - so
  nobody's existing setup resets to defaults).

## Phase 2 - per-user lanes as a view mapping (the real "set lanes")

- `me.ui.board_columns`: ordered `[{id, label, station, filter?}]`. Default =
  the classic four. A user can rename, reorder, hide (e.g. no backlog),
  split a station into multiple columns by card criteria (working →
  "Doing"/"Blocked" via status/needs_you), merge stations into one column.
- `board.tsx`: replace the hardcoded `LANES` const with columns from
  `me.ui.board_columns`; drag between columns translates to `move_lane` when
  the station changes, no-op/reorder within a station. move_lane semantics
  (gate on review entry, accept on done) unchanged - rendering only.
- **Invariant: no card may become invisible.** Server keeps every card
  addressable regardless of view; client renders an automatic overflow
  column for cards whose station no user column covers. A view that hides
  work must degrade loudly, not silently.
- Chat/verbs: `station_id()` aliases stay the canonical vocabulary; user
  column names are NOT added to the alias table automatically (a user
  calling a column "done" that maps to working must not confuse the mover) -
  the chat resolves stations, the board resolves columns.

## Phase 3 - polish

- Per-user language actually per-user (today `pol.lang` is global).
- Watch/glasses surfaces read the same `me.ui` (they already hit /me).
- Owner-side admin view: "view as user X" for support (read-only render of
  another user's columns; owner cap only).

## Explicitly rejected

- **Full per-user settings blob**: forks daemon behavior per viewer on one
  shared machine - incoherent and a privilege-escalation surface.
- **Per-user machine lanes**: would make lane ids user-data; the gate law and
  every `move_lane` transition key off them. View mapping gives the same UX
  without touching law.

## Verify

- Two accounts, same board: different labels/columns render, drag in a
  custom column still runs the real gate on review entry; a hidden station
  with cards shows the overflow column; global settings write by a client
  role still 403s; `_version` bump makes a second open device re-render the
  renamed lane within one SSE tick.
