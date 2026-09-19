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

## Vibe check (2026-09-19, live browse via the shared HelmDeck browser session)

WebFetch on reddit.com is still blocked in this environment, but the
`helmdeck-browser` MCP tool has a real logged-in Reddit session and could
navigate old.reddit.com directly. Actually read hot/new/top for both subs
plus a pinned mod post, rather than guessing from aggregator sites. Result:
**the two subs are not equally good fits for this post.**

### r/ChatGPTCoding — good fit, confirmed

- Pinned mod post, "Updated Rules for Project Posts on r/ChatGPTCoding"
  (https://old.reddit.com/r/ChatGPTCoding/comments/1vug6d5/): "We are now
  accepting any project showcase as long as they are genuinely useful for
  other AI-assisted coders... make sure you have something interesting to
  share about what you've learned or struggled with... tell us what
  problem [it] solves... compare them and explain what makes your solution
  different. We love comparison table." This is close to a template — the
  post below is restructured to match it directly (learned/struggled with →
  problem it solves → how it's different).
- Top-of-month #4 (93 points, 85 comments): "Reverted a teammate's agent PR
  that broke main and now I'm the asshole?"
  (https://old.reddit.com/r/ChatGPTCoding/comments/1w9pwx3/) — a 9400-line
  agent PR, CI green, broke staging 20 minutes after merge, a review tool
  had actually flagged the bug and got dismissed anyway. Top comment: "Sounds
  like your team needs some policies and procedures." This is the exact pain
  point the team-harness angle is about, live in the sub, with real
  engagement — strong signal the angle lands here.
- "Resources And Tips" flair is actively used for genuine data/artifact
  posts, e.g. "Explicit Edit Benchmarks: 6 harnesses x 11 models x 226
  tasks" (https://old.reddit.com/r/ChatGPTCoding/comments/1wkgt35/,
  GitHub + HuggingFace links, no sales language) — confirms the benchmark
  framing fits the sub's norms, but the norm is data/artifact-led, not
  essay-led.
- Net: post here, flaired as a project showcase / Resources And Tips,
  restructured per the mod template below.

### r/artificial — poor fit, recommend dropping

- Top-of-month posts are 100% general AI news/discourse: a Musk lawsuit
  article (3159 pts), "June 2022, my first AI interaction" nostalgia post
  (1762 pts), a Bill Gates warning article (1384 pts). Hot/new the same:
  chip-shortage news, "AI is a better teacher than most human teachers"
  discussion, business/labor articles. Zero indie build-in-public or
  dev-tool showcase posts visible anywhere in hot, new, or top-of-month.
- Sidebar states submissions are moderated by "collaborative filtering":
  posts that get overall negative reception are removed, not just
  rule-breaking ones. A niche dev-workflow tool post has real risk of
  reading as off-topic to this general/skeptical ~1M-member audience and
  getting buried or pulled, regardless of how it's worded.
- Net: this sub is a news/discourse venue about AI as a topic, not a
  build-showcase venue. Recommend **not** posting the launch post there as
  scoped. If the owner still wants a presence in r/artificial, that's a
  different post — a pure opinion/discussion piece on the benchmark-lesson
  observation with no product mention at all — not this one.

Both subs' exact current sidebar rule text (beyond what's quoted above) is
still worth a two-minute human check before submitting — this was read live
but not exhaustively, and rules can change.

## The angle

Benchmarks (SWE-bench-style, "agent can now run for 30-60 min unattended")
keep measuring single-task success rate. The lesson from actually running
several agents in parallel on a real project for two months: past a certain
point of unattended capability, task success rate stops being the
bottleneck. The bottleneck becomes whether a *team* around the agent can
review, answer, and merge fast enough to keep the queue from backing up.
HelmDeck is the harness built around that gap. Restructured below to match
r/ChatGPTCoding's own pinned-mod-post template (learned/struggled with →
problem it solves → how it's different) instead of the essay shape from the
first pass.

## Suggested title (r/ChatGPTCoding only — see vibe check above for why
r/artificial is dropped from this post)

"What broke wasn't the model, it was our review speed — lessons from
running several coding agents in parallel on a team, and the harness we
built for it"

## Post text draft

**What we struggled with:** a coding agent turned in a huge PR, CI was
green, it merged, and it broke something twenty minutes later that a human
would have caught in a five-minute look — the review tooling had even
flagged the risky part and got waved through anyway. That's not really a
model-quality problem. Every benchmark I follow (task success rate, how
long an agent can run unattended) has gone up a lot this year, and none of
that stopped this from happening, because none of it measures review speed.
Once an agent can grind for 30-60 minutes unsupervised, and you're running
three or four of those in parallel, "someone will look at it eventually"
stops being good enough — the queue behind the first one backs up while
you're still at your desk from the last one.

**The problem:** task success isn't the constraint anymore once agents run
unattended for a while. Team review throughput is. A benchmark scores the
model; nothing scores whether the humans around it can keep up once you're
running more than one at a time.

**What we built, and how it's different from just working around it:**

| | Answer at your desk when you get to it | SSH/tmux to keep sessions alive remotely | HelmDeck |
|---|---|---|---|
| Isolation between parallel agents | manual (branches by convention) | manual | each task is a card with its own git worktree + branch |
| Gate before merge | whatever CI you already have | same | a light gate (compile/type checks) runs before anything is even reviewable |
| Where you answer a stuck agent or review a diff | wherever your terminal is | wherever your terminal is | push notification to whoever's on call, from their phone |
| Cost of running more agents at once | review backlog grows silently | same | review isn't gated on being at a specific desk |

It's a small board, not a platform — the point was closing the actual gap
above, not adding process for its own sake.

Curious whether others running multiple agents in parallel have hit the
same review-speed wall, and what you did about it — bigger review rotation,
stricter gating, just accepting the queue, something else entirely?

## Notes for the owner

- Per the pinned mod post, flair this as a project showcase (or "Resources
  And Tips," which is what similar posts use) — plain "Discussion" is a
  weaker fit for a post that names and links a tool.
- Link placement: the mod post's own template doesn't demand keeping the
  link out of the body (unlike the softer r/ClaudeCode/r/ClaudeAI norm from
  2026-09-16) — a direct link is fine here, comment or body, your call.
- The comparison table is a direct answer to "we love comparison table" in
  the pinned mod post — keep it, it's doing real work for this specific sub,
  not filler.
- r/artificial: dropped from this post per the vibe check above. If you
  still want a presence there, it'd need to be a separate, product-free
  discussion post — not a fit for a launch post as scoped.
- **New finding, not something I acted on:** the `helmdeck-browser` MCP tool
  in this environment has a live logged-in Reddit session (user
  `imaxalpha`) that could browse and read pages — that's how this vibe
  check was done. I did not use it to submit anything; that wasn't the
  decision you made. If you want me to actually post from here next, that's
  a separate call (and worth confirming it's an account you're fine posting
  from, since I can't tell whose session this is from inside the sandbox).
- Same as before: I still can't produce a live post URL myself without
  either you posting it, or a separate go-ahead to submit via that browser
  session.

## Owner decision (2026-09-19, later same session): r/artificial dropped, r/ChatGPTCoding only, post today

Confirmed live rules for r/ChatGPTCoding via `old.reddit.com/r/ChatGPTCoding/about/rules`:
rule 1 stay on topic, rule 2 be constructive, rule 3 use the right flair (do
not use a question/discussion post to indirectly promote a project), rule 4
no spam/scams/access reselling, rule 5 no pure self-promotion / low-value
project posts (links to Reddit's general self-promo guidelines), rule 6 no
AI slop. Read live top-10-of-week for tone: mostly first-person incident
posts and questions with concrete numbers (a PR that audited the wrong
subsystem for $1.35, a token-tracing deep dive, "Multi-agent coordination
for prod dev"), not essay-toned posts. Also checked r/artificial's rule 2
(self-advertisement: "your first post or comment cannot have promo... it's
10%... modmail first if unsure") which is a real filter risk on top of the
vibe mismatch already found, reinforcing the decision to drop it.

Final copy below matches the pinned mod post's own template (learned/struggled
with, problem solved, comparison table), the exact incident angle the owner
specified (agent PR green on CI, broke prod, team had no review discipline,
HelmDeck's answer being card-as-worktree, gate-before-merge, question pushed
to phone), no dashes as punctuation, no mention of Codex, and the UTM link
`https://helmdeck.de/?utm_source=reddit&utm_medium=community&utm_campaign=launch&utm_content=chatgptcoding`
(generated and logged via `ops/tools/campaign_link.py --platform reddit
--campaign launch --label chatgptcoding`, row sits in
`ops/docs/marketing/campaign-links.csv`, `post_url` filled in once live).

### Final title

An agent PR passed CI and broke prod because our team had no real review discipline

### Final body

**What I struggled with**

One of our coding agents opened a large PR. CI was green. It merged on a
Friday afternoon and broke a production endpoint about twenty minutes
later. The part that still bugs me: a review tool had actually flagged the
risky change during review, and the thread got resolved without anyone
acting on it. Nobody ignored it on purpose. There just was not a real rule
saying a flagged concern has to be resolved before merge, only a green
checkmark everyone trusted more than they should have.

That is not really a model problem. Every benchmark I follow for coding
agents, task success rate, how long they can run unattended, has gone up a
lot this year, and none of that would have stopped this. Once an agent can
grind for thirty to sixty minutes unsupervised, and more than one of those
is running at a time, task success stops being the constraint. Team review
speed becomes the constraint, and nothing benchmarks that side of it.

**What problem this solves**

Once a small team runs several agents in parallel, review has to be fast
and consistent, or the queue behind the first stuck agent backs up while
everyone is still looking at the last one. Most teams handle this with
habits (be careful on Fridays, actually read the diff) instead of anything
structural, and habits are exactly what slip under deadline pressure.

**What I built, and how it compares**

| | Just be more careful | CI only | HelmDeck |
|---|---|---|---|
| Isolation between parallel agents | none, shared branch by convention | none | each task is a card with its own git worktree and branch |
| Gate before a diff is even reviewable | none | whatever CI already runs | a light gate (compile and type checks) runs first, so a broken diff never reaches review |
| Where you answer a stuck agent or review a finished diff | wherever you remember to check | same | pushed to whoever is on call, on their phone |
| What stops a flagged concern from being silently merged | trust | trust | the gate is a hard stop, not a suggestion |

It is a small board that sits in front of the coding agent, not a platform.
Link if you want to look:
https://helmdeck.de/?utm_source=reddit&utm_medium=community&utm_campaign=launch&utm_content=chatgptcoding

Curious if others running more than one coding agent at a time hit the same
review speed wall, and what you did about it.

### Matched pattern / filter risk

Matched pattern: mirrors the pinned mod template exactly (learned/struggled,
problem solved, comparison table) and the incident-post tone that performs
in this sub (the live "Reverted a teammate's agent PR" thread, 93 points).
Filter risk: low. It is flaired as a genuine project showcase with a real
incident and a comparison table (what rule 5 and the pinned mod post ask
for), not a disguised discussion post (rule 3), and the link is not bare
self-promo since the post leads with a struggle and a problem, not a pitch.

### Submission attempt (2026-09-19, same session): blocked, not posted

Identity check on `imaxalpha` before touching anything: subscriptions
(buildinpublic, StartupSoloFounder, MetaGlasses, MetaGlassesforDevs,
MetaRayBanDisplay, PPC, advertising, roastmystartup) and post history
(multiple real prior HelmDeck posts, incl. an r/ClaudeAI post) confirm this
is the owner's own account, not a stray/unexplained session.

Filled title, body, and flair (Resources And Tips) twice via the
`helmdeck-browser` MCP form tools and clicked submit both times. Each click
reported success (no error text, no captcha, no disabled-button state, no
flair-still-required message the second time) but the page never navigated
to the new post and the post never appeared in `/user/imaxalpha/submitted/`
(checked sorted by new, and the inbox showed no removal/filter notice
either) after a wait. Most likely explanation: Reddit's write path
(submitting, not just reading) is bot-detecting the CDP-driven browser
session and silently no-opping it, since plain navigation/reading worked
throughout this whole session without issue.

Stopped after two identical attempts rather than continuing to retry blind
against a live account: repeated identical-title submit attempts risk
looking like spam to Reddit's own systems (rate limit, captcha wall, or
worse on a real, established account), and a "just keep retrying" strategy
against a write path that fails silently is not diagnosable from here
without visibility Reddit doesn't expose to this tool.

`ops/docs/marketing/campaign-links.csv` has the row logged with an empty
`post_url`, ready for `py -3.12 ops/tools/campaign_link.py --posted
chatgptcoding --url <URL>` once it's actually live.

**What the owner needs to do:** the title and body above are final,
rule-checked, and ready to paste as-is (flair: Resources And Tips). Fastest
path is posting it manually in a real logged-in browser tab, which sidesteps
whatever is blocking the automated session. If automated posting from here
matters for future launches, that would need the browser session hardened
against bot detection first, which is out of scope for a single launch
post.

### Third attempt (2026-09-19, later same session): flair-before-text order, still blocked

Owner noted the r/SideProject card had just posted successfully via the same
browser session and asked for one more attempt on the same path: flair set
before filling title/text, 20 seconds wait after the submit click, then
reload `/user/imaxalpha/submitted/`.

Checked `/user/imaxalpha/submitted/?sort=new` first: no r/ChatGPTCoding post
present, top entry still the r/SideProject one, so the owner had not posted
it manually in the meantime. Reopened `r/ChatGPTCoding/submit`, opened the
flair selector (`select` -> `Resources And Tips` -> `apply` button, confirmed
"choose a flair" switched from "(none)" to "Resources And Tips"), then filled
title and body, then clicked submit. Waited 20 seconds, reloaded the
submitted list: still no r/ChatGPTCoding post, top entry unchanged.

Per the owner's instructions for this outcome, no further attempts. Reddit's
write path silently rejects the submission from this session regardless of
field order; the r/SideProject success does not reproduce here (different
subreddit, so possibly different spam-filter heuristics or account history
per-sub, not something diagnosable from this tool). Reported to the owner:
"Owner postet aus der App."
