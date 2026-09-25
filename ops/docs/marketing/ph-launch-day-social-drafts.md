# Product Hunt launch day, X draft (PREPARE, NOT posted)

Preparation only. Nothing here is posted. The owner reviews, edits freely,
and posts it himself. Copy reused from `producthunt-launch-draft.md` and the
live site (`ops/deploy/waitlist/src/index.js:554-579`), same rule as that
draft: no invented copy, no em dashes.

Per `plan-launch-2026-09-20.md` section "Mi, 23.09.": X goes out as a reply
under an existing own post, not a new standalone post.

Campaign links (generated, logged in `campaign-links.csv`):

- PH page itself: `https://helmdeck.de/?utm_source=producthunt&utm_medium=launch&utm_campaign=launch&utm_content=ph-launch-day`
- X: `https://helmdeck.de/?utm_source=x&utm_medium=social&utm_campaign=launch&utm_content=x-ph-launch-day`

## X (reply under an existing own post)

> Update: HelmDeck is live on Product Hunt today.
>
> Mobile AI orchestration for teams. You set the goal, agents do the
> work, every decision lands on the right phone. A hobby project I build
> beside my main job.
>
> Would mean a lot if you took a look: [PH LINK]

## After posting

Attach the live URLs to the logged rows so the CSV closes the loop:

```
py -3.12 ops/tools/campaign_link.py --posted x-ph-launch-day --url <live X post URL>
py -3.12 ops/tools/campaign_link.py --posted ph-launch-day --url <live PH page URL>
```

## PH comment replies during the day

Per the day's instruction: every PH comment gets a drafted reply from Henry,
posted only after the owner approves it. No standing script for this, it is
a live back-and-forth in this session: paste the comment, get a draft back.
Voice to match: the maker comment already drafted in
`producthunt-launch-draft.md` (personal, no pricing/pitch language, answers
the actual question asked).
