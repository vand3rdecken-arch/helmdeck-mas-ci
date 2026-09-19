# Product Hunt launch — draft (2026-09-19, PREPARE, NOT submitted)

Preparation only. Nothing here is posted, scheduled, or uploaded to Product
Hunt. The owner reviews, edits freely, and submits it himself. Sourced from
copy already live/approved elsewhere in the repo — nothing invented from
scratch (`feedback-copy-established-apps` / `feedback-site-copy-no-dashes-no-hiding`
rules: reuse established copy, no em dashes as punctuation).

Target launch: **Tuesday, 00:01 PT** (standard PH best practice — full 24h
launch-day window from the moment the queue opens).

## Sources used

- Tagline/positioning: live H1 + kicker + sub on `helmdeck.de`
  (`ops/deploy/waitlist/src/index.js:554-557`).
- Founder quote: `ops/deploy/waitlist/src/index.js:579` (already public on
  the site, same voice as the maker comment below).
- Gallery images 1-4: existing store screenshots
  (`ops/docs/store/screenshots/01-board.png` … `04-uebersicht.png`, also at
  `.../play/*-1920.png` and `.../appstore/{iphone-6.9,macos-1280x800}/`),
  demo data only, no real customer data (confirmed in
  `ops/docs/store/LISTING.md`).
- Demo video: `brag.mp4`, already produced and live on the site
  (`ops/deploy/waitlist/public/brag.mp4`, poster `brag.jpg`), source project
  in `brag-output/` (`brag-plan.md`, `share-copy.txt`).

## Tagline (max 60 chars)

**Recommended — reuses the live site H1 verbatim (44 chars):**

> The harness for your team's coding agents.

Alternates, if the owner wants something punchier/less sentence-shaped for a
PH audience:

> A board where Claude Code agents actually finish the work (56 chars)
> Answer your coding agent from your phone, not your desk (54 chars)

## Description (product page intro)

> For teams running Claude Code. Every task becomes a card, each card gets
> its own agent working in an isolated copy of your codebase. Your team
> follows along and approves from the phone, nobody has to open a terminal.
> No cloud account, no code leaves your machine, works with the Claude
> subscription your team already has.

(247 characters — adapted directly from the live kicker/sub/objection lines,
`index.js:554-557`.)

## Gallery (5 images + demo video)

PH recommends landscape gallery images/GIFs around 1270x760 (up to
3000x2250); the four store screenshots below are phone-portrait
(1080x2400/1920px). They read fine as PH gallery images (PH accepts portrait
uploads and letterboxes them), but if the owner wants full-bleed landscape
tiles, the fix is a quick re-crop/re-shoot at 16:9 before upload — not done
here since it wasn't asked for and the existing assets are already
store-approved.

1. **Demo video first** — `brag.mp4` (poster `brag.jpg`). PH gallery accepts
   video as the first item; this is the 21.5s "compose → board → approve"
   clip already live on the site.
2. `01-board.png` — the board itself, the hero shot (queued/working/review
   lanes).
3. `02-card-verlauf.png` — a card's live turn-by-turn history (the agent
   working, step by step).
4. `03-wartet-auf-dich.png` — "Wartet auf dich": answering the agent's
   question right in the chat, the core mobile-steering moment.
5. `04-uebersicht.png` — the overview tab (value delivered / AI cost /
   margin, real numbers).

No 5th distinct image existed in the current set beyond the four store
shots, so I picked one candidate rather than inventing a new screenshot:
`ops/docs/shots/flatcost_dash.png` — the desktop web overview (goal /
budget / timeline / scope triangle, plan-gate green). It shows the desktop
surface (the four phone shots are all mobile) and a different feature
(planning against budget/timeline) than image 4's cost dashboard, so it adds
information rather than repeating it. Flagging it rather than just dropping
it in: it's a desktop screenshot in a mostly-phone set, and it's an older
capture (visible "Demo-Modus" banner + a demo goal referencing
"Play-Store-Release") — both fine as demo data per the store-listing
precedent, but the owner may prefer a fresher desktop capture instead.

## First maker comment (draft)

> Hey Product Hunt 👋
>
> I'm Tien, I built HelmDeck alone over the last couple of months.
>
> It started from a dumb, specific annoyance: Claude Code got good enough to
> grind on a task for 20-30 minutes unattended, but the moment it hit a
> fork and asked a question, I was stuck at my desk until I noticed. I'd sit
> there in the evening waiting for the next question, kids in the next
> room, PC tying me to one spot for no good reason.
>
> So HelmDeck turns every task into a card. Each card gets its own agent,
> working in an isolated copy of your codebase (its own git worktree, so
> nothing bleeds into another card). The board shows what every agent is
> doing, step by step, live. When an agent has a question or finishes a
> diff, it's a push notification, and I answer from my phone. A quality
> gate runs automatically before anything merges, so approving from a
> phone still means reviewing, not blindly tapping yes.
>
> HelmDeck itself got built this way, mostly answered from my phone instead
> of waiting at my desk for it.
>
> It's a companion app for your own HelmDeck installation: it talks only to
> your own machine, nothing runs on a server I control, content is
> end-to-end encrypted even over the relay that lets you reach it from
> outside your LAN. No account, no ads.
>
> I'd genuinely like to hear how the rest of you handle this today: do you
> just accept being desk-bound while an agent runs, or did you land on
> something else (tmux + phone SSH, Anthropic's own remote control, a
> custom script)? Happy to answer anything about how it's built.

(Voice matches the founder quote already live on the site and the
r/ClaudeCode draft in this same directory: personal, no pricing/pitch
language, ends on a genuine question rather than a CTA.)

## Topics (max 3)

Recommended: **Developer Tools**, **Productivity**, **Artificial
Intelligence** — matches the product's actual shape (a dev-facing board for
coding-agent work) rather than reaching for a broader consumer topic.

## Open questions for the owner

- Gallery images are portrait phone shots; landscape re-crops are a
  same-day follow-up if wanted, not done here.
- `flatcost_dash.png` as image 5 is a suggestion, not a lock-in — it's an
  older capture with a demo-mode banner; swap it for a fresher desktop shot
  if one exists by launch day.
- PH lets you name a hunter separate from the maker if someone else posts
  it first thing in the morning PT for visibility — solo launch (owner
  posts as both) is assumed here unless he wants someone else to hunt it.
