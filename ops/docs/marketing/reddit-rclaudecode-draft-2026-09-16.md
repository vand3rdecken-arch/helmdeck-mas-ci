# Reddit draft: r/ClaudeCode / r/ClaudeAI (2026-09-16)

Preparation only. Nothing here is submitted or published. The owner decides
timing, edits freely, and posts it himself. Tone follows `plan-2026-09.md`
section 0 (private hobby/research project, no pricing, no purchase language)
and section 1 (positioning/ICP: solo devs and small teams already using
Claude Code). Channel context: `plan-2026-09.md` section 3, rank 1
("r/ClaudeCode and r/ClaudeAI... but only if without ad tone, owner posts and
answers in own voice"). Core message matches the X thread draft
(`x-thread-mobile-steering-2026-09-16.md`): agents keep getting more capable
at running unattended, so the bottleneck quietly shifts to how fast and from
where you can steer them — HelmDeck itself got built and launched in about
two months by answering Claude Code from a phone instead of waiting at a
desk.

## Research note on subreddit rules/flair (2026-09-16)

Direct fetch of reddit.com is blocked in this environment (`WebFetch`
refuses the domain), and web search did not surface the verbatim numbered
rule text for either subreddit. What could be confirmed via search
aggregators (gummysearch subreddit stats) and general Reddit norms:

- Both subreddits have a **"Built with Claude" post flair** — the natural
  fit for this post in either sub. r/ClaudeCode's other common flairs are
  Help/Question, Tips & Workflows, Bug/Issue, Discussion. r/ClaudeAI's other
  common flairs are Humor, News, Claude Workflow, Productivity.
- Both subreddits are large (r/ClaudeCode ~395k members, r/ClaudeAI ~1.1M)
  and general reporting (gotcontext.ai coverage of the Claude subreddit
  ecosystem) notes rising bot/promotional spam in this space in 2026 — a
  reason to lean extra hard into "genuine build story, technical specifics,
  answer questions honestly" rather than anything that reads as a launch
  announcement.
- Generic Reddit-wide self-promo norms (not sub-specific, but worth
  respecting anyway): keep the post majority-value/story rather than a pitch,
  don't post the same link across many subs same day, expect mods to remove
  anything that reads as an ad even if technically flaired correctly.
- **Before posting, the owner should open each subreddit's sidebar/About
  page in his own logged-in browser** and check the actual current rules and
  flair list — this could not be verified from here and subreddit rules
  change. Two minutes of reading beats guessing wrong and getting removed.

## Suggested title (works for both subs)

"Claude Code can now grind for 30+ min unattended — so I built a way to
steer it from my phone instead of waiting at my desk"

Shorter alternative:
"The bottleneck moved from 'can Claude Code do this' to 'how fast can I
answer it' — so I built a phone-first board for it"

## Post text draft

Something shifted for me this year: the hard part of using Claude Code
stopped being "can it do this." It'll happily grind on a task for 10, 20,
30+ minutes on its own now. The hard part became how fast I could answer
when it stopped and asked something, or finished a diff that needed a look.
If the only place I could answer was my desk, the agent was effectively
paused until I sat back down. The bottleneck wasn't the model anymore, it
was me.

So I built HelmDeck: a small board that sits in front of Claude Code. Every
task becomes a card (own worktree, own branch), every question or finished
diff from Claude Code lands as a push notification, and I answer from my
phone. The agent keeps going, I don't have to be at the PC.

The proof point I keep coming back to: HelmDeck itself got built and shipped
in about two months, mostly by answering Claude Code from my phone instead
of waiting at my desk for it. Still a solo, free side project, not a company
— I'm posting this because I'd genuinely like to hear how the rest of you
handle the same thing. Do you just accept the desk-bound sessions, or did
you land on something else (Anthropic's own Remote Control / Channels,
something custom, tmux + a phone SSH client, etc.)?

Happy to go into how it's built if anyone's curious — worktree-per-card,
review-before-merge, no shared credentials if someone else on the team
answers a card. Link's in my profile/a comment if you want to poke at it,
no pressure either way.

## Notes for the owner

- The last paragraph deliberately keeps the link out of the main body (soft
  self-promo norm: put it in a comment or profile, not the post itself) —
  match this to whatever the confirmed sidebar rule actually says once
  checked; some subs are fine with an inline link if flaired "Built with
  Claude," others aren't.
- The question in paragraph 3 ("how do you handle this?") is there on
  purpose — it makes this a discussion post, not an announcement, which is
  both more honest to the actual angle and safer against removal.
- r/ClaudeCode's audience skews more technical/daily-user; the worktree/
  review-gate detail in the last paragraph will land better there.
  r/ClaudeAI is broader; if trimming for length there, the mechanism detail
  is the first candidate to cut, not the "why."
- Reuse the same 15-second phone clip queued for X week 0
  (`plan-2026-09.md` week 0 table) as an image/video attachment if the
  subreddit's post type supports it — a card asking a question on one frame,
  a phone reply on the next, is the whole pitch in one image.
- Post r/ClaudeCode and r/ClaudeAI on different days, not simultaneously
  (cross-posting the identical text same-day reads as a campaign to both
  mods and readers who are in both subs).
