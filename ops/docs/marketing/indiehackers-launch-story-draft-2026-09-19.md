# Indie Hackers launch story draft (2026-09-19)

Preparation only. Nothing here is submitted or published. The owner decides
timing, edits freely, and posts it himself under his own Indie Hackers
account (no IH credentials or API access in this environment). Tone and
positioning follow the same line as the two committed Reddit drafts
(`reddit-rclaudecode-draft-2026-09-16.md`,
`reddit-chatgptcoding-artificial-draft-2026-09-19.md`): honest build-in-public
story, no pricing language, no purchase pitch, HelmDeck framed as a solo/free
side project. If that stance has since changed (e.g. a pricing page is now
live), the "free, no pricing page" lines below need editing before posting.

## Where this fits on Indie Hackers

Two reasonable homes for this text, pick one before posting:

1. **A general Indie Hackers post** (Starting Up / main feed) — the body
   below is written for this; no product page required first.
2. **A Product page "Milestone" update** — if HelmDeck already has (or gets)
   an IH product listing, this reads well as the launch milestone post on
   that page instead, and the last paragraph's link becomes redundant with
   the product page itself.

IH's audience rewards specific numbers and an honest "here's what actually
happened" tone over polish — closer to the Reddit draft's voice than to the
landing page's marketing copy.

## Suggested title

"I shipped HelmDeck in about two months by answering Claude Code from my
phone instead of my desk"

Shorter alternative:
"My AI coding agent doesn't wait for me anymore — I built the board that
makes that possible"

## Post text draft

Two months ago I noticed the hard part of using Claude Code had quietly
changed. It stopped being "can it do this." It'll now happily grind on a
task for 10, 20, 30+ minutes completely unattended. The hard part became how
fast I could answer when it stopped and asked me something, or finished a
diff that needed a look. If the only place I could answer was sitting at my
desk, the agent was effectively paused until I sat back down. The bottleneck
wasn't the model anymore. It was me.

So I built HelmDeck: a small board that sits in front of Claude Code. Every
task becomes a card with its own git worktree and branch, so several agents
can work in parallel without stepping on each other. Every question Claude
Code asks, or every diff it finishes, becomes a push notification. I answer
from my phone, the agent keeps going, and before anything merges a gate
checks that the build, types and tests still pass.

The proof point I keep coming back to: HelmDeck itself got built and shipped
in about two months, mostly by answering Claude Code from my phone in the
evenings, kids in the next room, instead of waiting at the PC for it. It's
live now at https://helmdeck.de (Android and iPhone app, a small operator you
install on the machine that already builds your code, Windows and macOS).
Still a solo, free side project. No pricing page yet, because right now I
care more about whether this solves a real problem for anyone besides me
than about charging for it.

If you're running coding agents that can go unattended for a while, I'd
genuinely like to know how you handle the same moment: do you just accept
being desk-bound while it runs, or did you land on something else already
(SSH from a phone, Anthropic's own remote/channel tooling, something
homegrown)? Happy to answer anything about how it's built, worktree
isolation, the review gate, all of it.

## Notes for the owner

- The "free, no pricing page" framing matches the Reddit drafts' stance as of
  2026-09-16/19. Re-check this is still current before posting — it's the
  one line in this draft most likely to have gone stale.
- Actual publishing needs the owner's own Indie Hackers login; there is no
  IH API/MCP access available in this worktree to post automatically.
- Once posted, log the URL for tracking with the existing per-post campaign
  tool: `py -3.12 ops/tools/campaign_link.py --platform indiehackers
  --campaign launch --label ih-launch-story --url <post URL once live>`
  (note: `indiehackers` is not yet in `PLATFORM_MEDIUM` in
  `ops/tools/campaign_link.py` — add a row there, e.g. `"community"`, in the
  same commit as the first real use).
- Keep the closing question genuine and answer comments in the owner's own
  voice, same norm as the Reddit drafts — IH's community reacts badly to
  anything that reads like a drive-by announcement.
- Report the live post URL back once published, same as requested for the
  dev.to article.
