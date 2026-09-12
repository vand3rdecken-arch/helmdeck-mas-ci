# state-into-db - one store of record: audit the db, version it, move every runtime record into it

**Owner, 2026-09-12:** "Why are things like this not saved in the db but as
file. Need full refactor." Then: "Check what's already in the db, whether it's
rightly structured. Fix it, do migration and then refactor all things
mentioned above."

This card is the revised implementation plan (v2, scored below; v1 was the
file inventory + phases only and is superseded, its inventory is section 3).

**Status:** phase A shipped (this commit); B-I open.

---

## 1. Audit of `daemon/helmdeck.db` as found (2026-09-12)

| # | finding | verdict |
|---|---|---|
| A1 | `PRAGMA user_version = 0`. Every table is `CREATE TABLE IF NOT EXISTS` at boot; the only column migration ever done is a one-off `ALTER TABLE events ADD COLUMN id` guarded by `PRAGMA table_info`. No install can say what shape it is on. | **fix first**: a migration ledger |
| A2 | `tracks`, `projects`, `processes`, `connector_state` are `(id, data TEXT)` blobs. Owner, repo, `project_id`, lane, status, archived, created, updated all live inside the JSON. Every board query loads all 217 rows and filters in Python; every touch rewrites the whole row including `last_reply`, `bg_tasks`, `checkpoints`, `attachments`. | **fix**: generated columns + indexes (no writer change), see 2.3 |
| A3 | `events`: 4128 of 8183 rows have `id = NULL` (pre-id era), `ts` is local wall time as text, `at_utc` sits only inside the blob, no `actor` column. Still file-first: `emit()` appends to `events.jsonl`, then a best-effort db insert inside `except: pass`, healed on the next boot by re-scanning the file. | phase G (owner gate): db-first |
| A4 | `workspace_config` (23 rows) mixes CONFIG (`policy`, `pm`, `prices`), machine STATE (`relay` incl. `sk`, `room`, `phone_pub`; `glance_origin`; `worktree_seed`), SECRETS (`glance_token`, `relay.sk`, `jira.api_token`) and a DEAD ROW: `users` with the owner's plaintext token, which `events.py` documents as "a dead mirror, nothing reads it" since phase 4 but was never deleted. | **fix**: delete `users`; classify keys; export masks secrets |
| A5 | `boards`: one row `default` with `owner=''`. `memory`: 47 rows, all `actor=henry`, no account column. `policy_doc`: one row, `CHECK(id='live')`. `project_config`: empty. `user_config`: two rows for `owner`. The tenancy chain exists only for boards and user_config; everything else is workspace-global by construction. | **fix**: data model in 2.1, columns added by ledger |
| A6 | Three in-memory cursors (`_version`, `_chat_version`, `_glass_version`) are correct and stay. | keep |
| A7 | `_migrate()` refuses to run when `dirname(DBPATH) != ROOT` (sandbox guard). Correct, keep; the ledger inherits it. | keep |
| A8 | 60 MB of records sit beside the db as files: 134 `timeline.jsonl` (54.6 MB), 320 `actions.jsonl`, `escalations.jsonl` (386 KB, full re-parse per read), Henry's chat log (rolling window of 80 messages per user, whole-file rewrite per turn), PM plans (one file per day), auth sessions, invites, devices, harness versions. | phases C-F |

## 2. Target design

### 2.1 Data model (the scoping chain every table follows)

```
workspace  (one row today; a column, never a rewrite, when there are two)
 └─ account        user name (auth.py owns credentials in users.json; the db owns everything else about the account)
     ├─ board       saved view over the card pool (exists)
     ├─ chat        Henry transcript, per account (NEW table)
     ├─ session     auth session, device, invite (NEW tables)
     └─ memory      gains `account` (default 'owner'); Henry's notes stop being shared by accident
 └─ project        repo (exists: projects + project_config)
     ├─ card        tracks (exists) + generated columns project_id/repo/lane/status/archived/updated
     │   └─ run     recordings/<run> (NEW runs table) -> timeline, actions, escalations, attachments(paths)
     └─ connector   connector_state (exists), connector_versions (later)
 └─ workspace-level records
     ├─ events      (exists) gains actor + at_utc columns, db-first in phase G
     ├─ pm_plans / pm_activity / runtime_doc   (NEW)
     ├─ harness_versions, checkpoints, audit_ops, workorders   (NEW, phase F)
     └─ policy_doc, workspace_config   (exist; config keys classified)
```

Rules: payload stays JSON in `data`; scoping and ordering keys are real
columns (`account`, `project`, `track`, `run_id`, `seq`, `ts`); append-only
tables have no UPDATE/DELETE code path and a guard test proves it; every new
table declares its scope column or the guard test fails.

### 2.2 Migration ledger (phase A)

- `schema_migrations(version INTEGER PK, name TEXT, applied_at TEXT)` plus
  `PRAGMA user_version` set to the highest applied version.
- `db.MIGRATIONS = [(1, "ledger", fn), (2, "tracks-generated-columns", fn), ...]`
  in `spine/storage/db.py`; `init()` creates base tables, then applies every
  version above `user_version` inside one transaction each, in order.
- A file import is a migration step: read, verify the row count, insert,
  then `_archive()` the file to `backups/<name>.imported` (existing helper,
  never clobbers). The old writer is deleted in the same commit.
- The A7 sandbox guard stays: ledger steps that touch files under `ROOT`
  are skipped with the same loud message when `DBPATH` and `ROOT` disagree.
- `ops/tools/db_export.py` (`--account`, `--project`, `--all`, secrets
  masked) and `db_import.py` land with the ledger: that is what makes the
  "exportable" decree checkable.

### 2.3 Card scoping without touching writers

SQLite virtual generated columns over the blob:
`ALTER TABLE tracks ADD COLUMN lane TEXT GENERATED ALWAYS AS (json_extract(data,'$.lane')) VIRTUAL`
for `project_id`, `repo`, `lane`, `status`, `archived`, `updated`, `created`,
then indexes on `(lane, status)`, `project_id`, `updated`. `track_put` is
unchanged; `tracks_all()` grows `tracks_where(...)` for the hot filters. Same
for `processes(status, client)` and `projects(repo)`.

## 3. Inventory (from v1, unchanged) - what moves, what stays

**MOVE (records/config, no external reader):** `recordings/<run>/timeline.jsonl`,
`actions.jsonl`, `meta.json`; `state/escalations.jsonl`; `state/copilot_log.json`;
`pm/plan-*.json`, `pm/activity.jsonl`, `pm/loop.json`; `state/copilot_sessions.json`,
`copilot_stats.json`, `copilot_models.json`, `models_cache.json`; `state/sessions.json`,
`invites.json`, `devices.json`; `asc_review_watch.json`; `backups/reset-log.jsonl`;
`ops/harness/.versions/**`; `checkpoints/<id>/settings.json`; `.loop/workorder.md`
+ `history/`; `events.jsonl` (phase G); low priority: `connectors/_versions/`,
`signkeys/*/pubkeys/`.

**DELETE THE MECHANISM (scratch):** `daemon/board_full.txt` (PM planner shell
redirect, traced to 2026-09-11T22:01Z: `board_state.py --full` dumped and
grepped because the tool answered a query with 105k chars, the prefix
allowlist cannot see `>`, and cwd was the repo); `live_partial.txt`,
`live_session.txt`, `copilot_runs/<user>/live_*.txt` (same-process streaming
buffers, and a SECOND owner of the session pointer); `recordings/_henry/`;
`.loop/*.log|*.txt|artifacts/*.aab`.

**STAYS A FILE (justified):** pid and lock files; gpg home, TLS certs,
chrome profile, `~/.claude/.credentials.json`, opencode home (foreign
programs); claude CLI brief/settings/mcp files in `%TEMP%`; `relay_feed.json`
(SQLite-less Node updater); desktop `daemon-dir.txt` (bootstrap pointer);
`board_directives.json`, `policy_seed.json`, `app.json`, generated tokens
(tracked source); `users.json` (credentials, unchanged); `*.log`;
`.attachments/`, media, STT models, update staging; app SecureStore /
AsyncStorage, glasses localStorage; `*.imported` markers.

## 4. Phases (each ships alone, atomic per store, no dual-writer period)

| phase | scope | test that fails on old code |
|---|---|---|
| **A. Ledger + audit fixes** | `schema_migrations`, `MIGRATIONS` runner, generated columns + indexes on tracks/processes/projects, delete `workspace_config.users`, `memory.account`, `events.actor/at_utc` columns, `db_export`/`db_import`, guard test (every table has a scope column; append-only tables have no UPDATE/DELETE) | `test_db_schema.py`: fresh db reaches `user_version == N`; an old-shape db (fixture without the columns) upgrades and keeps every row; the dead `users` row is gone; export masks `token`/`sk`/`api_token` |
| **B. Planner hole (the trigger)** | `pm.py`: planner cwd = `tempfile.mkdtemp("hd-pm-")`, tools by absolute path, `EVIDENCE_TOOLS` names only `--find/--card/--live`; `board_state.py` caps every planner-facing mode; `loop_state.py` flags untracked non-ignored files under `daemon/` | `test_pm_evidence.py`: fake `claude` that runs `> leak.txt` leaves the repo tree byte-identical |
| **C. Escalations** | `escalations(seq, id, ts, event, kind, track, data)`; `fold()` = one query; import + archive `escalations.jsonl` | `test_escalations.py` on the real `emit/record_*/fold` path against a sandbox db; the jsonl is archived with count verified |
| **D. PM artifacts + runtime docs** | `pm_plans(day PK, data)`, `pm_activity(seq, ts, kind, card, msg)`, `runtime_doc(key PK, data, updated_at)` (loop state, copilot sessions/stats/models, models_cache, asc_review); one transaction per loop-state write pays `pm-loopstate-races` | `test_pm_plans.py`: `latest_plan`/`_recent_plans` over the table; loop-state concurrent writers lose nothing |
| **E. Henry chat** | `chat(seq, account, ts, date, role, data)`; `_append_log` = INSERT; `history(account, have=N)` = range; window of 80 becomes a query limit (full history kept) | `test_chat_store.py`: two threads append 200 entries each, all 400 present; `history(have=n)` returns only the tail |
| **F. Runs, actions, timeline** | `runs(id PK, kind, title, status, started, ended, track, data)`, `actions(seq, run_id, ts, ta, kind, detail, data)`, `timeline(seq, run_id, step_id, patch)`; `timeline_store.read` = fold over `WHERE run_id=? AND seq>?` with the existing per-run cache keyed by seq; media stays on disk; boot import streams every `recordings/<run>/*.jsonl` (count-verified) then archives | `test_timeline_store.py` (existing shape) on the table; `compare_timeline.py` shows an empty diff on a live turn |
| **G. Auth records, harness versions, workorders, checkpoints, reset audit** | `auth_sessions`, `invites`, `devices`, `harness_versions`, `workorders(tree_key, ts, data)`, `checkpoints(id, data)` (config rows snapshot; connectors dir copy unchanged), `audit_ops` | per-store tests on the real paths; `loop_state.py` SessionStart stays sub-second with a db read (measure) |
| **H. Events db-first** (OWNER DECISION) | `emit()` inserts first, raises on failure; `events.jsonl` retired to an export; `_reconcile_events` + `.synced` deleted | `test_events_reconcile.py` inverted: a failed insert is an error, not a silent drop |
| **I. Streaming buffers in memory** | `LiveBuffer` registry keyed by run/user replaces the four `live_*.txt`; `live_session.txt` removed (pointer already owned by `sessions.resume_detached`) | transcript live route serves the buffer; no file under `recordings/<run>/live_*` after a turn |

Debt: `state-into-db` registered open in phase A; each phase that ships
partially adds `state-into-db-<phase>`; paid entries stay listed.

## 5. Done means

- `PRAGMA user_version` equals the ledger head on every install after one boot.
- `git status` after a PM plan turn and a Henry turn: nothing untracked.
- `daemon/` after phase G: db, certs, signkeys, connectors (code), content/
  (artifacts), recordings/ (media + `*.imported`), state/ (pids), logs.
- `/chat/history` and `/transcript/live` bounded by `have`, not by history.
- `db_export.py --all` round-trips through `db_import.py` into an empty db
  with identical row counts and no secret in the export.

## 6. Scoring log (criteria 1-5: root-cause fidelity, law compliance, migration safety, test proof, scope discipline, measurability)

**v1 (4.6):** phases over the file inventory. Owner review exposed the gap:
no audit of the store the files were moving INTO, no schema versioning, no
tenancy model, no export. Re-scored against that: migration safety 3, law
compliance 4 (exportability decree unverifiable), measurability 4.

**v2 draft 1 (4.2):** added the audit and a data model that put `account`
and `project` foreign-key columns on every table, including tracks, with
writers rewritten to split the blob into columns. Migration safety 3: a
rewrite of `track_put` and 200+ readers of the blob is exactly the multi-day
dual-shape window the no-dual-writer rule forbids; test proof 4; scope 3
(rewriting card storage is not what was asked).

**v2 draft 2 (4.7):** generated columns instead of writer rewrites (tracks
scoping and indexes with zero call-site change), ledger with file imports as
numbered steps, export/import as the decree's proof, the dead `users` row
found and scheduled for deletion, secrets classified. Deductions:
measurability 4 (the SessionStart latency for phase G and the chat window
change are designed, not yet measured); events flip still an owner gate.

**v2 final (4.8, this document):** phase order set by risk and proof value
(A proves the ledger on existing tables, C proves the import-archive pattern
on the smallest jsonl, F is the bulk), each phase names the failing-on-old-code
test, done-criteria are all commands or counts. Remaining 0.2: phase H needs
the owner, phase G latency needs a measurement.
