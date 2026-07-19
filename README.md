# SwarmDeck

Run a swarm of coding/browser/desktop agents on your PC — with a **flight recorder**: every
action an agent (or you) takes in the browser or in Windows is logged as a timestamped step
timeline and recorded as video. Review the timeline, drill into the footage, watch live from
your glasses, or **teach** a task by doing it once yourself.

## The two ways to define a task

1. **Describe → drive.** Write the task in words; an agent executes it with its own hands
   (Playwright browser, Windows input). The run is recorded.
2. **Demonstrate → learn.** Hit record, do the task yourself once, stop. The same recorder
   captures your demonstration; the distiller turns it into a reusable **playbook**
   (goal, steps, selectors, checkpoints) that agents execute later — recorded the same way,
   so you can diff "what I showed" against "what it did".

## Review model (locked decision)

The **action timeline is the primary review artifact** — always captured, never optional
(teach-mode depends on it; audit trails don't get off-switches). Video is the drill-down
evidence behind each step. Glasses get the step feed + live glance; phone/desktop get full
replay and scrubbing.

## Architecture — the APK rule

**All important logic lives in the phone APK.** The phone is the hub: auth, pairing,
recording index, playbook storage, review serving, decisions. The cloud worker is a thin
relay (rendezvous + newest live frame + tiny signaling rows) — never the brain. The desktop
daemon is hands + capture only; the glasses webapp is a pure viewer.

```
DESKTOP daemon (hands + capture)      PHONE APK (the brain)            GLASSES (viewer)
────────────────────────────────      ─────────────────────            ────────────────
agents: Playwright browser            auth + pairing secrets           track/step feed
        + Windows input               recording & playbook index       "watch live" glance
recorder: mp4 + action log            pulls recordings from daemon        │
teach: your demo → log + video        review UI + player                  │
   │                                     ▲                                │
   └────── LAN (direct) ─────────────────┘                                │
   └────── worker relay (thin: newest frame + rows) ──────────────────────┘
```

## Layout

- `daemon/` — Python. Capture pipeline, teach recorder, distiller, swarm runner, local server.
- `apk/` — Android hub (Kotlin; bootstrapped from the glass-companion architecture).
- `worker/` — thin Cloudflare relay (not deployed until explicitly asked).
- `glasses/` — viewer webapp (600×600, additive styling: bright accents on black).

## Quick start (daemon)

```
cd daemon
pip install -r requirements.txt
python swarm.py wincap-test          # 5s desktop capture -> recordings/<id>/screen.mp4
python swarm.py browser-demo        # scripted browser run -> video + action log
python swarm.py teach "name"        # record YOUR demo (Ctrl+Esc stops)
python swarm.py distill <id>         # demo -> playbook via claude -p
python swarm.py serve                # local index: recordings, timelines, live.jpg
```

Recordings live in `daemon/recordings/<run-id>/` — `screen.mp4` / `browser.webm`,
`actions.jsonl` (the timeline), `meta.json`. Keep-all retention (owner decision).
