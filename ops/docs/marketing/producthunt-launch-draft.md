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

Live site H1, verbatim (34 chars):

> Mobile AI orchestration for teams.

## Description (product page intro)

> You set goal, budget and deadline. HelmDeck plans the work, agents do it
> on your own PC, and every decision lands with the right person on your
> team, on the phone. The agent belongs at the desk. You don't.

(Built from the live H1, sub and the three theses on helmdeck.de.)

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
> I'm Tien. HelmDeck is a hobby project I build beside my main job, to
> test three theses about how work with AI is going to feel.
>
> 1. Mobile is the interface. The agent belongs at the desk. You don't.
> I never touched the Play Store listing, the App Store listing or the
> certificates. An agent did it in the browser, I answered its questions
> and cleared its blockers from wherever I was.
>
> 2. Goals replace prompts. You set goal, budget and deadline. Henry, the
> planner inside HelmDeck, lays out timeline and scope against my measured
> velocity, and pushed back when the Android review turned out to take
> fourteen days.
>
> 3. Teams, not individuals. Every decision lands with the one person who
> should make it. A friend in another time zone takes the helm when I go
> to sleep, and sees at once what moved and what waits on him.
>
> It runs on your own machine: no cloud account, nothing on a server I
> control, end to end encrypted even over the relay. No account, no ads.
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
