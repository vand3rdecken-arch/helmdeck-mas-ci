# Hyperframes Composition Brief: HelmDeck

## Objective
Create a short, polished launch-style brag video for HelmDeck — a Kanban
board whose cards are actually worked by an AI agent running on the owner's
own PC, driven from the owner's phone.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 21.5 seconds

## Source Material
- Project root: `swarmdeck` (HelmDeck)
- Primary files read: `README.md`, `ARCHITECTURE.md`,
  `surfaces/app/src/ui/board.tsx`, `surfaces/app/src/ui/card_composer.tsx`,
  `surfaces/app/src/ui/sign_off.tsx`, `surfaces/app/src/theme/tokens.ts`
- Product name: HelmDeck
- Tagline / strongest claim: "Never sit in front of a PC again unless you
  want to." (hook). Secondary claim used as outro: "No account. No ads. No
  servers. Because there are none."
- Key UI or visual moment to recreate: the Kanban board's lane crossing
  (Backlog → Working → Review → Done) with the app's real lane colors, and
  the sign-off dialog's three verdict pills (Approved / Reviewed /
  Rejected).
- Copy that must appear verbatim:
  - "Never sit in front of a PC again."
  - "unless you want to."
  - "A task board where the tickets get done."
  - "No account. No ads. No servers. Because there are none."
  - Lane labels: Backlog, Working, Review, Done
  - Sign-off labels: Approved, Reviewed, Rejected
  - Status labels: queued, running, gating

## Creative Direction
- Tone preset: polished
- Creative direction: quiet, premium dev-tool film; restraint over hype
- Interpretation: slow confident holds, soft crossfades/slides, mixed-case
  type, one claim per scene; 5 short scenes (not the usual 3-4) so the real
  UI flow gets room to read — "show the thing" outranks scene-count here
- Angle: HelmDeck inverts the usual task-board promise — the board isn't
  just tracking work, it's where the work happens, unattended, on hardware
  the owner already owns, with no company servers in the loop
- Hook: full black, "Never sit in front of a PC again." / "unless you want
  to." (verbatim, split across two beats)
- Outro / punchline: HelmDeck wordmark + "No account. No ads. No servers.
  Because there are none."
- Avoid:
  - Generic SaaS language ("streamline your workflow", etc.)
  - Abstract filler visuals — every scene must be either real UI or verbatim
    copy
  - Any redesign of the app's real palette or lane semantics

## Visual Identity
- Background / canvas: `#0E0F10`
- Card surface: `#141515`
- Primary text: `#E4E6E6`
- Secondary text: `#AFB3B6`
- Accent / AI-working lane: `#3D9BD6`
- Accent 2 / human-review lane: `#967AF0`
- Success / done / approved: `#5CB572`
- Warn: `#E59C4B`
- Danger / rejected: `#EA6A66`
- Display font: no custom brand font exists in the app — use a clean system
  sans stack (system-ui / -apple-system / "Segoe UI" / sans-serif); do not
  invent a display font identity that isn't in the product
- Visual references from the project: `theme/tokens.ts` (the palette
  above, generated from OKLCH primitives), `board.tsx` (lane columns +
  status chips), `card_composer.tsx` (text input + photo attachment chip),
  `sign_off.tsx` (three verdict pills, `meaningTone()` color mapping)

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. Hook — 4.0s — "Never sit in front of a PC again." / "unless you want to."
2. Reveal: compose a task — 4.0s — typed task text + photo-attachment chip,
   HelmDeck wordmark + tagline
3. Key action: the board works it — 6.0s — card crosses Backlog → Working →
   Review with 3 status chips (queued → running → gating) and real lane
   colors
4. Result: sign-off — 4.0s — Approved/Reviewed/Rejected pills, tap Approved,
   card locks into Done
5. Outro — 3.5s — HelmDeck wordmark + privacy line, hold to black

## Audio
- Audio role: cinematic support, restrained (polished: minimal but present)
- Audio arc: one steady bed the whole way, rising slightly under Scene 3,
  ducking out under Scene 5; 3 sparse motion-matched SFX moments total
  (typing ticks, lane-move slides, one approve chime) plus very quiet
  per-chip ticks in Scene 3
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3`
  (already copied into this composition's assets — do not fetch elsewhere)
- Music treatment: start at volume ~0.18 under Scene 1, rise to ~0.30 under
  Scene 3, duck to ~0.15 under Scene 5, fade out under the final hold
- Music cue guidance: bundled preset at
  `assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json`
  (~110 BPM). Strong cues worth targeting inside this 21.5s video: 8.74s and
  9.29s (Scene 3's move into Working / the first two status chips), 17.47s
  (Scene 4's Approved tap). No usable strong cue exists near the outro
  (next one, 22.93s, is past the video) — use natural timing there. Treat
  all of this as bias, not a fixed cue sheet — pick the exact implementation
  timing that reads best once the animation exists.
- Audio-reactive treatment: subtle — let the ambient glow behind Scene 1's
  and Scene 5's text breathe gently with music RMS/bass. No waveform or
  equalizer visuals, no strobing.
- Audio-coupled moments:
  - Scene 2 typing — soft randomized keypress ticks per character
  - Scene 2 photo chip arrival — one gentle drop sound
  - Scene 3 lane moves — one soft card-slide sound per move (Backlog→
    Working, Working→Review)
  - Scene 3 status chips — much quieter tick than the lane-move sound;
    accent the first chip clearly, let the rest be barely-there
  - Scene 4 Approved tap — one restrained, short success chime
  - Scene 4 final lane move (→Done) — same soft card-slide as Scene 3
- SFX selection guidance: keyboard/keypress-*.wav randomized per character
  for typing; casino/card-slide-*.ogg or interface/drop_*.ogg for lane
  moves and the photo chip; interface/click_*.ogg or ui/click*.ogg for the
  Approved tap simulation; impact/impactSoft_medium_*.ogg or
  interface/bong_001.ogg as the single success chime — pick whichever
  reads as "soft, precise, expensive," not playful or cheap
- SFX analysis guidance: read
  `skills/brag/assets/sfx/sfx-analysis.md` (or the installed-skill path)
  before final selection; prefer low/medium high-frequency-risk files
  since several SFX repeat (typing, chip ticks)
- Exact SFX choice: Hyperframes should choose filenames, timestamps,
  density, and volume based on the implemented animation
- Audio files: music is already copied into
  `brag-output/composition/assets/music/`; copy any chosen SFX into
  `brag-output/composition/assets/sfx/...` before wiring them in

## Hyperframes Instructions
Load the composition-building Hyperframes domain skills —
`hyperframes-core` (composition contract + `data-*` timing),
`hyperframes-animation` (motion), `hyperframes-creative` (design spec,
beats, audio-reactive), `hyperframes-keyframes` (seek-safe keyframes), and
`hyperframes-cli` (lint/check/render). `/brag` is its own workflow: do not
enter the `hyperframes` entry-point intent interview and do not route into
its generic promo / launch-video workflow. Prefer native Hyperframes
conventions over anything in `/brag`.

Requirements:
- Show at least one real UI, copy, or visual element from the source
  project — Scenes 2-4 exist specifically to satisfy this; do not soften
  them into abstract mockups.
- Keep all text readable in the final render (respect the reading-time
  floors from `brag`'s `step-2-plan.md`: short labels ~0.8s settled,
  sentences ~0.3s/word).
- Keep the video within 15-25 seconds (target 21.5s).
- Include the planned music/SFX layer unless documented as impossible.
- Treat `/brag` audio notes as guidance, not a fixed cue sheet. Choose SFX
  after the visual animation exists.
- Treat music cue metadata as optional timing hints; ignore cues that hurt
  readability, scene pacing, or the product story. Use only the 1-3 strong
  cue locks named above.
- Use SFX to support motion and interaction, with restraint (polished tone:
  2-3 audible cues, everything else nearly silent).
- Honor the planned music treatment (low start, rise under Scene 3, duck
  under Scene 5, fade to silence).
- Consider the Hyperframes audio-reactive workflow for the two ambient-glow
  moments described above; skip it without blocking the render if
  extraction is unavailable, and document that in the delivery notes.
- Use local assets for audio; do not fetch anything from the network.
- Run `hyperframes check` before render — it is brag's single gate.
