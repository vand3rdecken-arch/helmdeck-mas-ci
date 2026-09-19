# Reddit draft: r/ChatGPTCoding + r/artificial (2026-09-19)

Preparation only. Nothing here is submitted or published. Angle for this
double-post is different from the earlier `reddit-rclaudecode-draft-2026-09-16.md`
(phone-steering-as-solo-habit): this one leads with a **benchmark lesson**
and lands on the **team harness** HelmDeck became, not the solo phone habit.
Both subs are tool-agnostic audiences (r/ChatGPTCoding = coding-assistant
users generally, not Claude-specific; r/artificial = general AI, ~1M+
members, more skeptical of anything that reads like a startup pitch) so the
copy below avoids Claude-specific framing where the previous draft could
lean on it.

## Research note on subreddit rules (2026-09-19)

Same limitation as the 2026-09-16 draft: direct reddit.com fetch is blocked
in this environment and web search doesn't surface the verbatim current
rules text. What's confirmed generically (via aggregator sites, not the
subs' own sidebars):

- r/artificial: ~1M+ members, self-promotion tolerated only under something
  like the community norm "10% rule" (be a real participant, not a
  drive-by poster) and only when framed as "built this, want feedback," not
  a pitch. Skeptical, general-AI audience — assume zero tolerance for
  anything that reads like marketing copy.
- r/ChatGPTCoding: ~380k+ members, discussion mix already includes a lot of
  self-promotion and tool show-and-tell, so a build-in-public post is a
  closer fit to what the sub already sees than in r/artificial — but that
  also means the bar for "is this actually interesting" is higher since
  readers have seen many tool launch posts.
- **Before posting, open each subreddit's current sidebar/rules in a
  logged-in browser and check flair + self-promo wording** — this could not
  be verified from here and rules change. Also: post the two subs on
  different days/times, not as an identical simultaneous cross-post — same
  norm as the 2026-09-16 draft, doubly true here since r/artificial is
  stricter.

## The angle

Benchmarks (SWE-bench-style, "agent can now run for 30-60 min unattended")
keep measuring single-task success rate. The lesson from actually running
several agents in parallel on a real project for two months: past a certain
point of unattended capability, task success rate stops being the
bottleneck. The bottleneck becomes whether a *team* around the agent can
review, answer, and merge fast enough to keep the queue from backing up.
That's the benchmark blind spot — it scores the model, not the throughput of
the humans supervising it. HelmDeck is the harness we built once we noticed
that: every task is a card with its own git worktree/branch (isolation, no
collision between parallel agents), a light gate before anything merges
(compile/type checks, not a giant test suite), and every question or
finished diff pushes to whoever's on call — on their phone, not just
whoever's at a desk — so a small team can run several agents at once without
either babysitting one at a time or losing review discipline.

## Suggested titles

r/ChatGPTCoding (technical audience, comfortable with workflow detail):
"Benchmarks measure if the agent can do the task. They don't measure if
your team can review it fast enough to matter — built a small harness
around that gap"

r/artificial (broader, more skeptical — lead harder with the observation,
softer on the "built a thing"):
"The benchmark blind spot: once agents can run unattended for 30+ minutes,
the bottleneck stops being the model and becomes the humans reviewing it"

## Post text draft (core, tune per sub — see notes)

Every benchmark I follow for coding agents is basically a single-task,
single-runner scoreboard: can it solve this, how long can it go unattended.
Those numbers have genuinely moved a lot this year. What they don't measure
is what happens once you put more than one agent to work at the same time
on a real project, with a real team behind it.

Once an agent can grind for 30, 45, 60 minutes unsupervised, task success
stops being the constraint. The constraint becomes: can a human review the
diff, answer the question it got stuck on, and merge it, fast enough that
the agent isn't just sitting there finished-and-waiting? Run three or four
of these in parallel and "fast enough" stops meaning "before I forget about
it" and starts meaning "before the queue behind it stalls too." No
benchmark I've seen scores that side of the equation.

That gap is what we ended up building a small harness around: every task
becomes a card with its own isolated git worktree and branch, so parallel
agents can't step on each other; a light gate (compile + type checks, not a
full test suite) runs before anything is even reviewable; and every
question or finished diff pushes out to whoever's on call for it — on
their phone, not just whoever happens to be at a desk — so review isn't the
thing that silently caps how many agents a small team can actually run at
once.

Curious whether others running multiple agents in parallel have hit the
same wall, and what you did about it — bigger review team, stricter gating,
just accepting the queue, something else entirely?

## Notes for the owner

- Link is deliberately absent from the body (comment/profile only), same
  self-promo norm as the 2026-09-16 draft — confirm against whatever each
  sub's actual current rule says once you've checked the sidebar.
- r/artificial: consider trimming the harness mechanism paragraph
  (worktree/branch/gate) further if it still reads as a pitch once you
  reread it there — that sub's tolerance is lower than r/ChatGPTCoding's.
  The observation paragraph (benchmarks vs. team throughput) is the part
  worth keeping intact; the "what we built" paragraph is the part to cut
  first if length or tone is an issue.
- r/ChatGPTCoding: the mechanism detail (worktree-per-card, light gate,
  push-to-phone) is closer to what that sub already discusses — fine to
  leave as-is or even expand slightly if a comment asks "how."
- Both posts end on a genuine question (not a CTA) on purpose, same
  reasoning as the earlier draft: keeps it a discussion post, not an
  announcement, and is safer against mod removal in both subs.
- I do not have a logged-in Reddit session or credentials in this
  environment, so I can prepare text but cannot submit the post or produce
  the live URLs myself — same shape as the X scanner card
  (`ops/tools/x_scan_jev.mjs`, blocked on live X login). Posting needs to
  happen from the owner's own logged-in account, in his own voice, per the
  same reasoning as the 2026-09-16 draft.
