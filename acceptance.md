# SwarmDeck - acceptance (Define round, 2026-07-19)

## Definition (owner's answers)

- Agents get their hands **on the real desktop** (own Playwright browser + real Windows desktop).
- v1 scope: **browser AND Windows both**.
- Retention: **keep all** recordings.
- **New repo, new app** (this repo), independent of glass-crud-harness.
- **The APK rule: all important logic in the APK** - phone is the hub (auth, storage, index,
  processing); cloud worker thin relay only; glasses pure viewer.
- Task definition works **two ways**: describe→drive, and demonstrate→learn (record the owner's
  own PC actions once, distill into a playbook agents can run).
- Action timeline: **always-on, primary review artifact** (video = drill-down). Not optional.

## Given / When / Then

- GIVEN the daemon is running, WHEN an agent run starts, THEN a run folder exists with
  `actions.jsonl` growing per action and a video file finalized at run end.
- GIVEN teach mode, WHEN the owner performs a task and stops recording, THEN the demo has
  screen video + input/action log, AND `distill` produces a human-readable playbook the owner
  can edit before any agent executes it.
- GIVEN a finished run, WHEN reviewing, THEN the step timeline renders first and each step
  links into the video at its timestamp.
- GIVEN the glasses viewer, WHEN a run is live, THEN a "watch" glance shows the newest frame
  (~1–2 fps is acceptable); no capture APIs are assumed on the glasses.
- GIVEN the APK, WHEN the daemon and phone pair, THEN the phone holds the pairing secret and
  the recording index; the worker never stores more than the newest frame + tiny rows.

## Surface plan

- **Glasses**: step feed per track + live glance (Herald-cast pattern). No video scrubbing.
- **Phone (APK)**: the brain - pairing, index, review player, playbook library.
- **Desktop**: daemon + full review UI (timeline-first), teach-mode start/stop.

## Empty states

- No runs yet → review UI shows "record a demo or start a task" with both entry points.
- Live view with no active run → "no agent is on the desk right now" placeholder frame.
- Playbook list empty → points at teach mode.

## Safety rails (standing)

- v1 agents run only on tasks the owner gives; recording makes them reviewable, not harmless.
- Worker deploy + any publishing: separate explicit ask. APK build: separate step.
- No secrets in this repo; pairing secrets live on the phone (APK rule).
