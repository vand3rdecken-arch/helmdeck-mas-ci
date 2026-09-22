# Product Hunt launch day, X + LinkedIn drafts (PREPARE, NOT posted)

Preparation only. Nothing here is posted. The owner reviews, edits freely,
and posts it himself. Copy reused from `producthunt-launch-draft.md` and the
live site (`ops/deploy/waitlist/src/index.js:554-579`), same rule as that
draft: no invented copy, no em dashes.

Per `plan-launch-2026-09-20.md` section "Mi, 23.09.": X goes out as a reply
under an existing own post about Claude Code, not a new standalone post.
LinkedIn carries the link in the first comment, not in the post body
(LinkedIn throttles outbound links in the post itself).

Campaign links (generated, logged in `campaign-links.csv`):

- PH page itself: `https://helmdeck.de/?utm_source=producthunt&utm_medium=launch&utm_campaign=launch&utm_content=ph-launch-day`
- X: `https://helmdeck.de/?utm_source=x&utm_medium=social&utm_campaign=launch&utm_content=x-ph-launch-day`
- LinkedIn: `https://helmdeck.de/?utm_source=linkedin&utm_medium=social&utm_campaign=launch&utm_content=linkedin-ph-launch-day`

## X (reply under an existing own post about Claude Code)

> Update: HelmDeck is live on Product Hunt today.
>
> The harness for your team's coding agents. Every task becomes a card,
> each card gets its own agent, your team answers questions and approves
> from the phone instead of waiting at a desk.
>
> Would mean a lot if you took a look: [PH LINK]

## LinkedIn (post body, no link; link goes in first comment)

> HelmDeck is live on Product Hunt today.
>
> I built it because I kept sitting at the PC in the evening, waiting for
> the next question from Claude Code, while my kids were in the next room.
>
> Every task becomes a card. Each card gets its own agent, working in an
> isolated copy of the codebase. The team follows along and approves from
> the phone, nobody has to open a terminal or sit at a desk.
>
> No cloud account, no code leaves your machine, works with the Claude
> subscription your team already has.
>
> Would appreciate an upvote and any feedback, link in the first comment.

**First comment (post immediately after, carries the link):**

> [PH LINK]

## After posting

Attach the live URLs to the logged rows so the CSV closes the loop:

```
py -3.12 ops/tools/campaign_link.py --posted x-ph-launch-day --url <live X post URL>
py -3.12 ops/tools/campaign_link.py --posted linkedin-ph-launch-day --url <live LinkedIn post URL>
py -3.12 ops/tools/campaign_link.py --posted ph-launch-day --url <live PH page URL>
```

## PH comment replies during the day

Per the day's instruction: every PH comment gets a drafted reply from Henry,
posted only after the owner approves it. No standing script for this, it is
a live back-and-forth in this session: paste the comment, get a draft back.
Voice to match: the maker comment already drafted in
`producthunt-launch-draft.md` (personal, no pricing/pitch language, answers
the actual question asked).
