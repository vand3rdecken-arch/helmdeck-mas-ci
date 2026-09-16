# Brag Plan: HelmDeck

## What is this app?
HelmDeck is a Kanban board where the cards actually get worked: you file a
task from your phone (with a photo if it helps), a Claude-powered agent runs
on your own Windows/Mac box and drives it through Backlog → Working →
Review → Done, and you approve or reject the result from your phone — the
PC never has to be in front of you.

## The angle
Play it straight and confident (polished, not jokey): this is real
infrastructure, not a toy demo. The angle is the inversion of the normal
task-board promise — most boards just *track* work, HelmDeck's board is
where the work *happens*, unattended, on hardware the owner already owns,
with zero servers in between. The hook borrows the site's own boldest line
verbatim because it already earns the reaction; nothing invented on top.

## Hook (first 2-3 seconds)
Full black. The real README line, split for a beat of tension:
"Never sit in front of a PC again." ... "unless you want to."
Confidence through restraint — no logo yet, just the claim.

## Key moments (the middle)
- A real card composer: typing a task with an attached screenshot
  ("Fix the login crash" + a photo chip), sent from the phone.
- The board itself: the card crossing real lane columns (Backlog → Working →
  Review → Done) with real status chips (queued → running → gating) in the
  app's real lane colors (blue = AI working, purple = needs a human, green
  = done).
- The sign-off dialog: the three real verdict pills — Approved / Reviewed /
  Rejected — with a tap landing on Approved and the card locking into Done.

## Outro / punchline
HelmDeck wordmark, then the other real claim that earns its own reaction:
"No account. No ads. No servers. Because there are none." — the privacy
line from the README, verbatim, as the quiet mic-drop.

## User flow worth showing
The real entry → key action → result loop, pulled straight from the
composer/board/sign-off components (`card_composer.tsx`, `board.tsx`,
`sign_off.tsx`):
1. Entry — owner types a task and attaches a screenshot from the phone.
2. Key action — the card runs through the board: queued → running (agent
   actively working) → gating, moving from Backlog into Working into
   Review.
3. Result — the owner taps Approved in the sign-off dialog; the card lands
   in Done.

## Tone
- Preset: polished
- Creative direction: quiet, premium dev-tool film — the product is real
  infrastructure, treated with restraint, not a joke.
- Interpretation: slow, confident holds; mixed-case type; soft crossfades;
  one claim per scene; the "flow" scenes replace polished's usual single
  hero shot because the creative law ("show the thing") outranks the
  scene-count guideline here — 5 short, calm scenes rather than 3-4 longer
  ones, so the real UI gets room to read.

## Format: landscape — 1920x1080
## Duration: 21.5 seconds

## Visual identity (from the project)
- Background / canvas: `#0E0F10` (dark theme `canvas`)
- Surface (cards): `#141515` (`surface1`)
- Primary text: `#E4E6E6` (`txtPrimary`)
- Secondary text: `#AFB3B6` (`txtTertiary`)
- Accent (AI / working lane): `#3D9BD6` (`ai`)
- Accent 2 (human / review lane): `#967AF0` (`human`)
- Success (done lane / approved): `#5CB572` (`ok`)
- Warn (needs you): `#E59C4B`
- Danger (rejected): `#EA6A66`
- Display/body font: no custom webfont is declared in the app (React
  Native default system stack) — use a clean system sans (system-ui /
  -apple-system / Segoe UI stack) rather than inventing a brand font.
- Strongest visual element: the dark board with the blue "working" glow
  crossing into the purple "review" glow into the green "done" glow — the
  app's own lane-color semantics, not an invented palette.

## Share copy (draft)
HelmDeck: file a task from your phone, an agent runs it on your own PC
end-to-end encrypted, you approve from bed. No account, no ads, no servers.

## Audio direction
- Role: cinematic support, restrained (polished — minimal but present)
- Music: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` ("steady
  and clean", recommended for polished/cinematic), ~110 BPM
- Music treatment: enters at 0 under the hook at low volume (0.18), rises
  to 0.30 under the board sequence, ducks back to 0.15 under the outro for
  a clean final hold, hard stop just after the last SFX rings out
- Music cue guidance: bundled preset
  `assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json`
  (109.96 BPM). Strong cues in this video's 0-21.5s window worth targeting:
  8.74s (0.99) and 9.29s (0.97) for the card's move into Working, 17.47s
  (0.99) for the Approved tap. No strong cue exists near the outro (next
  one is 22.93s, past the video) — use natural timing there instead.
  Beat-grid window for the 3 sequential status chips (queued/running/
  gating): start near 8.74s, reveal the first two quickly on consecutive
  beats (8.74, 9.29) since they're short one-word labels, then hold the
  full set rather than chasing every beat with a third chip.
- Audio-reactive treatment: subtle — the ambient background glow behind the
  hook text and outro wordmark breathes gently with music RMS. No
  waveform/equalizer visuals.
- SFX posture: sparse, motion-matched (polished energy: 2-3 audible cues,
  everything else is a very soft accent under the interaction it matches)
- Audio-coupled moments: the composer types with soft randomized keypress
  ticks; the card's lane moves get one soft card-slide sound each; the
  Approved tap gets one restrained success chime
- Restraint rule: never louder than the dialogue-free voice of the video
  itself — no aggressive hits, no glitch/chaos SFX, nothing stacked

## Storyboard

### Scene 1 — Hook — 4.0s
Full-bleed `#0E0F10`. Centered line 1 fades/settles: "Never sit in front of
a PC again." Beat. Line 2 settles beneath, smaller weight: "unless you want
to." Both lines fully readable (verbatim README copy). A very soft blue
ambient glow breathes behind the text.
Sequential/interaction: yes — line 1 settles first (~1.4s), line 2 follows
at ~2.4s, both hold to 4.0s.
Audio intent: quiet confidence, not a joke setup — the claim should feel
stated, not sold.
Audio-coupled idea: none (let the line land in silence-adjacent music, no
typing here — this isn't UI yet)
Music: enters here at low volume, steady clean bed
Transition mood: soft crossfade → Scene 2

### Scene 2 — Reveal (compose a task) — 4.0s
Recreate the real card composer: a dark `surface1` panel with a text input
mid-type: "Fix the login crash" with a small photo-attachment chip appearing
beside it (`card_composer.tsx`'s attach affordance). Small HelmDeck wordmark
top-left. Tagline underneath the panel, the real one-liner: "A task board
where the tickets get done."
Sequential/interaction: yes — the sentence types character by character,
photo chip pops in right after the text settles.
Audio intent: hands-on, tactile — this is the owner, on their phone.
Audio-coupled idea: soft randomized keyboard keypress ticks while typing;
one gentle drop sound when the photo chip lands.
Music: steady bed continues, still low
Transition mood: clean slide → Scene 3

### Scene 3 — Key action (the board works it) — 6.0s
Recreate the real board: four lane columns, real labels (Backlog / Working
/ Review / Done). The card slides from Backlog into Working — beat-locked
to 8.74s — glowing `ai` blue, with a "running" status chip. Two more status
chips arrive in quick succession (queued → running → gating, snapped to
8.74s/9.29s then held), then the card slides into Review, glowing `human`
purple.
Sequential/interaction: yes — 3 status chips arrive one by one, then a lane
move (Backlog→Working→Review), each move a distinct slide.
Audio intent: the product doing the thing, unattended and calm — no
urgency, just visible progress.
Audio-coupled idea: one soft card-slide sound per lane move; chip arrivals
get a much quieter tick, not a full SFX each (restraint per polished tone).
Music: rises slightly to 0.30, the fullest point of the bed
Transition mood: clean slide → Scene 4

### Scene 4 — Result (sign-off) — 4.0s
Recreate the real sign-off dialog: three pills, real labels and real
colors — Approved (green `ok`), Reviewed (purple `human`), Rejected (red
`danger`). A cursor taps Approved, beat-locked to 17.47s. The card locks
into the Done column, green glow.
Sequential/interaction: yes — simulated tap on the Approved pill, then the
card's lane move into Done.
Audio intent: quiet payoff — relief/completion, not celebration.
Audio-coupled idea: one restrained success chime exactly on the tap; the
final lane-move gets the same soft card-slide as Scene 3 for consistency.
Music: still steady, begins to duck under the coming outro
Transition mood: soft crossfade → Scene 5

### Scene 5 — Outro / punchline — 3.5s
Cut to `#0E0F10`. HelmDeck wordmark settles center. Beneath it, the real
privacy line: "No account. No ads. No servers. Because there are none."
Ambient glow breathes once more, then everything holds still.
Sequential/interaction: none — one settle, then stillness.
Audio intent: the mic-drop, delivered quietly.
Audio-coupled idea: none beyond the ambient glow breathing with the music;
let the line sit in near-silence.
Music: ducks to 0.15, fades out under the hold
Transition mood: hold to black (end)

**Music mood for this video:** polished / steady, clean, corporate-adjacent
restraint throughout — never chaotic, never triumphant.
**Audio summary:** A single low, steady bed runs the whole video, breathing
subtly with the ambient glow behind text; three sparse, motion-matched SFX
(typing ticks, a card-slide per lane move, one soft success chime on
Approved) are the only accents, and the bed ducks out quietly under the
final privacy line rather than swelling to a finish.
