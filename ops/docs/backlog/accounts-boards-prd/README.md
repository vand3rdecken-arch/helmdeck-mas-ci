# PRD: Accounts, Boards & the Settings Untangling

**Owner decrees 2026-09-01** (chat, this order): (1) "Each user should be able
to register and save their own config in db. They can set lanes, labels etc.
HelmDeck is just rendering." (2) "Best is to let users create account, log in
and then save all config cleanly." (3) "Should be done right at setup." (4)
Clarified via Q&A: learn from Jira, don't reinvent; minimal setup but the end
state is at least one working board; keep invite+name+password auth; v1 must
untangle the settings that are currently meddled together.

**Absorbs** `ops/docs/backlog/settings-ia-redesign/` (the 6-door hub becomes
this PRD's presentation layer) and **supersedes the column model** of
`ops/docs/backlog/per-user-ui-config/` (personal boards replace per-user
column overlays, per the Jira decision).

---

## 1. Goals

- G1 A person creates an account (invite), logs in, and every preference they
  set is saved to that ACCOUNT in the daemon's DB - log in anywhere (phone,
  web, desktop, watch), same experience. Device storage keeps only credentials
  and an offline cache.
- G2 Boards the Jira way: one shared **default board** (owner-configured
  columns) plus **personal boards** any user can create (name + card filter +
  column layout) over the same card pool. Boards are saved views; cards exist
  once.
- G3 Setup ends in a WORKING board: owner first-run seeds the default board
  with one guided example card; an invited user's first login lands on the
  default board (role-filtered), never an empty screen.
- G4 Settings stop being one meddled blob: every knob has exactly one owner
  (Profile=account / Board=board / Workspace=policy / System=machine), one
  storage location, one edit surface - the 6-door hub renders that split.

## 2. Non-goals

- No new auth surface: invite + name + password + sessions + device tokens
  stay as-is; owner resets forgotten passwords from the Users panel. No
  email, no OAuth (revisit only with a real external-user ambition).
- No per-user WORKFLOW: the station graph (backlog→working→gate→review→done),
  gate-before-review, merge rails, worktree isolation stay law-in-code. Jira
  parallel: admins define workflows, users define boards - here the workflow
  is the harness itself.
- No per-user workspace POLICY: auto_accept_green, WIP, dispatch priority,
  repo hooks command the one shared daemon - they stay owner-scoped.
- No swimlanes, WIP-per-column, board sharing/permissions in v1 (personal
  boards are private to their account; the default board is everyone's).

## 3. The model (five layers, each with one owner)

| Layer | Owner | Store | Examples |
|---|---|---|---|
| Workflow (law) | code | `sessions.LANE_FLOW` | stations, gate, transitions |
| Card pool | trackstore | `helmdeck.db` tracks | one card, one row, role-filtered reads |
| Boards | board row | `helmdeck.db` `boards` | default board (owner-edited) + personal boards (creator-edited): columns→station mapping, filter, order |
| Profile | account | `helmdeck.db` `user_config` | language, appearance, notifications, dashboard tiles, last-open board |
| Workspace policy + System | owner | `settings.json` (unchanged) | automation knobs, drivers, connectors, prices |

**Board record:** `{id, name, owner: user|"", columns: [{id, label, station,
filter?}], filter?, created}` - `owner: ""` marks the default board (only
owner-role edits it; it cannot be deleted). Column invariant: every station
must be covered by ≥1 column OR the client renders an automatic overflow
column - **a card can never become invisible on a board that claims to show
it**. Moving a card between columns translates to `move_lane` when the
station changes (full rails: gate on review entry) and is a no-op/re-sort
within a station.

**Client role:** visibility law unchanged (own cards only, enforced
server-side as today). Clients see the default board rendered over their
subset and may create personal boards over that subset. Nothing new invented
(Jira/JSM convention: same data, narrower slice).

## 4. Setup & onboarding flows

### 4.1 System first-run (owner)
Existing create-owner screen (`POST /auth/setup`) gains two seeded artifacts
in the same transaction:
1. The **default board** (columns = the four stations with the current
   default labels).
2. One **guided example card** in backlog: title "So funktioniert HelmDeck",
   body walks the lanes (dispatch → worktree → gate → review → done), clearly
   marked deletable, `example: true` so it never dispatches an agent and is
   excluded from economics/PM planning.
Acceptance: a fresh daemon + fresh app shows a rendered board with one card
30 seconds after setup, before any configuration.

### 4.2 Invited user first login
Invite code → name + password → login (all existing). New: first-login
completes a **minimal profile step** (language; theme optional, skippable)
written to `user_config`, then lands on the **default board**. If their
role-filtered view is empty, the example card is visible to every role.
No wizard beyond that one step - personalization lives in Settings/board
editing where it's discoverable when wanted.

### 4.3 Returning login on a new device
`GET /me` hydrates profile + board list; the device renders the user's
last-open board. One-time migration: if the account has NO stored profile
but the device has legacy local prefs, push them up (never overwrite an
account that has values - nobody's setup resets).

## 5. Settings untangling (absorbed settings-ia-redesign)

The 6-door hub ships as designed there (doors, schema-first `SettingsPage`
renderer, search, autonomy dial, Mehr-tab shrink, nightshift/WIP dedup - all
of it stays valid), with these amendments from this PRD:

- **Door 1 "Allgemein" becomes "Mein Profil"** and is ACCOUNT-backed
  (`user_config` via `PUT /me/config`), not a workspace/device mix. Every row
  that was device-local view preference migrates here. Scope badge "Konto"
  replaces the old Gerät/Workspace ambiguity for these rows; genuinely
  device-bound rows (pairing, LAN hosts) move to Tür 5/6 with "Gerät" badges.
- **New Door: "Boards"** (between 1 and 2): list of my boards + the default
  board; each opens the board editor (rename, columns, mapping, filter).
  Default board editable by owner only; visible read-only to others.
- The schema metadata per knob grows `scope: profile|board|workspace|device|
  system` - the renderer places and badges rows from it; the ts-contract test
  extends to the new scopes.

## 6. Storage & API

- `spine/storage/db.py`: tables `user_config(user, key, value, updated_at,
  PK(user,key))` and `boards(id, name, owner, json, updated_at)`. Writes bump
  `_version` (existing SSE cursor) so other open devices re-render live.
- `GET /me` grows: `profile` (resolved user_config over defaults), `boards`
  (their list + default). Stays the one whitelisted every-role endpoint.
- New routes (all self-scoped by session user, no new capability needed):
  - `PUT /me/config` - own profile rows; server-side key whitelist + size cap
  - `POST/PUT/DELETE /boards/<id>` - own boards; default board owner-only
  - every write emits an audit event (append-only law) 
- Migration at daemon start: `policy.lane_labels` (if set) becomes the
  default board's column labels; the settings key stays readable one release
  as fallback, then retires (debt entry if shortcut needed).
- App: `client.ts` types for profile/boards; board.tsx renders the active
  board's columns instead of the hardcoded `LANES`; board switcher in the
  header; the drag handler translates columns→stations.

## 7. Phases (each a dispatchable card, in order)

| # | Card | Contents | Acceptance |
|---|---|---|---|
| 1 | accounts-config-store | db tables, /me resolution, PUT /me/config, first-login language step, device→account migration, "Mein Profil" door (minimal render, full hub comes in 4) | two accounts on two devices hold different languages/labels; new device hydrates on login; legacy device pushes up once |
| 2 | boards-model | boards table + routes, default-board seed + migration from lane_labels, board.tsx renders active board, switcher, overflow-column invariant | rename a column on a personal board on device A, device B re-renders within one SSE tick; drag through a custom column still gates on review entry |
| 3 | setup-seeds | first-run seeds default board + example card (`example: true`, never dispatches, excluded from economics); invited-user landing flow | fresh daemon → working board with example card; new client-role login lands on board, sees example |
| 4 | settings-hub — **DONE** | the settings-ia-redesign phases (hub, doors, schema renderer, cleanups) on top of the new scopes; Boards door | old settings.tsx/modules/automation dissolve; dummy-knob-with-scope appears in the right door with the right badge, no client change |

**Phase 4 as shipped.** `DOORS`/`SCOPES` are declared once in
`spine/http/apimeta.py` and mirrored in `surfaces/app/src/data/settings_schema.ts`
(held equal by `test_settings_hub_vocabularies`). Every knob carries
`door/group/groupKey/level/scope`, and the generic `SchemaDoor` renderer
(`surfaces/app/src/ui/settings_schema_page.tsx`) places, badges and SAVES from
that metadata alone — `scope` decides both the badge and the write target
(profile → `PUT /me/config`, everything else → `POST /settings`). Acceptance is
proved twice: `surfaces/app/src/data/__settings_hub_selftest__.ts` (the
placement rule, no browser) and `ops/tests/e2e_settings_hub.py` (a dummy knob
injected daemon-side, drawn by an unmodified bundle in door 5 with its badge).

Three things the plan did not foresee, all measured rather than reasoned:
- Profile rows had to ride on **`GET /me`**, not `/automation`: the latter is
  `settings.read` (owner-only), and door 1 exists for the roles that are not
  the owner. `_profile_schema()` is therefore a second list with the same
  entry shape; the client concatenates and never learns there were two.
- The `/settings` ROUTE had to lose its `cap`. `(tabs)/_layout.tsx` builds its
  navigator with `useOnlyUserDefinedScreens=true`, so a capability-gated tab is
  not merely unlisted, it is **unregistered** — a client navigating to
  `/settings` silently landed back on the dashboard. The owner-only DOORS are
  hidden inside the hub instead, and every owner-only route it calls is still
  gated server-side.
- `/automation` and `/modules` stay registered as `hidden` nav entries (a new
  `Surface.nav.hidden` flag) for the same reason: dropping them from the nav
  tables would have unregistered the redirect routes and broken the deep links
  this card promised to keep.

Deferred with a debt entry: `policy.lane_labels` is badged "Board" but still
stored in `settings.json` (`board-scope-still-in-settings-json`) — section 6's
migration into the board row is the fix.

Phase 1+2 are independent of 4 (the hub); 3 needs 2. The old
per-user-ui-config card is superseded by 1+2; settings-ia-redesign by 4 -
both get pointer notes, not deletion (their research stays referenced).

## 8. Risks / open items (the honest 5%)

- **Example card semantics**: `example: true` must be inert everywhere
  (dispatcher, PM planning, economics, Henry's snapshot) - one flag checked
  in ~4 read sites; missing one means a demo card burns tokens. Phase-3
  acceptance must grep-verify every consumer.
- **Watch/glasses surfaces** read /me but render fixed lanes today - they
  follow in a later card (render default board only); noted, not blocking.
- **users.json vs db**: accounts stay in users.json (auth law untouched);
  user_config keys on the NAME. A rename in the Users panel must cascade or
  be blocked while config rows exist - decide in Phase 1 implementation
  (recommendation: block rename, it's an identity).
- **Concurrent edits** to the same board from two devices: last-write-wins on
  the whole board row is acceptable for v1 (personal boards are one person);
  the default board is owner-only - collision surface is one human.
