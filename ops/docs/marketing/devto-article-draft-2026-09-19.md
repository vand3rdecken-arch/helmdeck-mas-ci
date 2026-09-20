# dev.to article draft (2026-09-19)

Preparation only. Nothing here is submitted or published. The owner decides
timing, edits freely, and posts it himself under his own dev.to account (no
dev.to credentials or API access in this environment). Positioning matches
the Indie Hackers draft in this same folder
(`indiehackers-launch-story-draft-2026-09-19.md`) and the committed Reddit
drafts: honest build-in-public story, no pricing language, free solo side
project. dev.to's audience is more technical than IH's, so this piece leans
into mechanism (worktree-per-card, gate-before-merge) rather than the founder
narrative, per the standard split already used across channels.

## Suggested title

"Worktree-per-card: how I stopped my coding agents from stepping on each
other (and on me)"

Shorter alternative:
"Gate-before-merge: the review step that lets Claude Code run more than one
task at once"

## Suggested tags

`ai`, `productivity`, `opensource`, `buildinpublic` (dev.to caps at 4 tags;
swap `opensource` for `webdev` if the piece reads more as a build log than an
OSS pitch — HelmDeck's source repo is public but this isn't primarily an OSS
launch post).

## Article body draft

Claude Code got a lot better at working unattended this year. Point it at a
task and it'll happily run for 10, 20, 30+ minutes without you, planning,
editing, running tests, fixing what breaks. That's a real capability jump.
It also created a problem nobody was talking about much: what happens when
it stops and asks you something, or finishes, and you're not there?

For a while my answer was "wait at the desk." That doesn't scale past one
task at a time, and it turns a tool that's supposed to save your evening
into a tool that chains you to your chair for it. So I built HelmDeck, and
the two pieces of it worth writing up are the two that actually solve this:
**worktree-per-card**, and **gate-before-merge**.

### The problem with running more than one agent at once

The obvious next step once an agent can run unattended is to run several of
them at once. The obvious way to break that is to let them share a working
tree. Two agents editing the same checkout will stomp on each other's
uncommitted changes, half-applied edits, and build artifacts, and you won't
find out until something is inexplicably broken.

HelmDeck's fix is unglamorous on purpose: every task is a **card**, and every
card gets its own `git worktree` and its own branch the moment it's created.
The agent working that card only ever sees its own tree. It can `git status`,
run the build, run tests, all inside a directory nothing else touches. When
the card is done, that's a normal branch ready for a normal merge, nothing
exotic about it. The isolation is boring, cheap (worktrees share the object
store), and it's the reason running four or five cards in parallel doesn't
feel like tempting fate.

The trap worth naming: worktrees are cheap to create and easy to forget.
Left alone, a pile of dead worktrees from finished or abandoned cards will
eventually fill a disk. Reclaiming them (on accept, on archive, and with a
sweep as a backstop) turned out to be its own small feature, not an
afterthought.

### The problem with trusting an unattended diff

Unattended agents finish tasks whether or not the result actually builds.
Multiply that by several agents running in parallel and "did this one
actually work" stops being something you can eyeball. HelmDeck's answer is a
**gate**: before a card's branch can merge, an automated check runs the
build, the type checker, and the test suite against that branch. Only a
green gate can go to review. A card that finishes with a broken build just
sits there, visibly failing, instead of quietly landing on `main`.

Two lessons from actually running this for a couple of months:

- **Keep the gate light.** The instinct is to make the gate as thorough as
  possible: full test suite, every check you can think of, every time. In
  practice a fast gate (a syntax/type/import check that runs in a couple of
  seconds) that runs on *every* card beats a slow, thorough gate that people
  start skipping or running less often. Heavier checks (a full end-to-end
  smoke test) still matter, but they belong before a release build, not on
  every single card.
- **The gate has to run against a synced base.** An early bug let a card's
  gate pass against a stale copy of `main`, so "gate green" didn't always
  mean "green against what you're about to merge into." Worth checking this
  explicitly if you build something similar: sync the base into the
  worktree *before* the gate runs, not after.

### Closing the loop: the phone

Isolation and a gate solve "can multiple agents run safely." They don't
solve the original problem: an agent still stops and asks something, and you
still might not be at your desk. The last piece is just a notification and a
chat surface on the phone: a card's question becomes a push notification,
you answer from wherever you are, the agent keeps going. It sounds almost
too simple to be the actual unlock, but it's the reason HelmDeck itself got
built and shipped in about two months, mostly by answering Claude Code from
a phone in the evenings instead of at a desk.

HelmDeck is a free, solo side project, live at https://helmdeck.de (Android
and iPhone app, a small operator for the machine that already builds your
code, Windows and macOS). If you're running coding agents that go
unattended for a while, I'd like to hear how you're handling the same
problem, whatever you landed on.

## Notes for the owner

- Mechanism-heavy piece on purpose (worktree isolation, gate-before-merge,
  the base-sync bug, the light-gate lesson) to match dev.to's more technical
  readership, versus the founder-story framing used for Indie Hackers.
- No internal identifiers, file paths, commit hashes, or proprietary detail
  from this repo appear above; check the final draft again before posting in
  case an edit reintroduces any.
- The "free, no pricing page" framing matches the other channel drafts as of
  2026-09-16/19; re-check it's still current before posting.
- Actual publishing needs the owner's own dev.to login; there is no dev.to
  API/MCP access available in this worktree to post automatically. Canonical
  URL field (if cross-posting from a personal blog first) is the owner's
  call.
- Once posted, log the URL with the existing per-post campaign tool:
  `py -3.12 ops/tools/campaign_link.py --platform devto --campaign launch
  --label devto-worktree-gate --url <post URL once live>` — `devto` is
  already registered in `PLATFORM_MEDIUM` (`ops/tools/campaign_link.py`), no
  code change needed there.
- Report the live post URL back once published, same as requested for the
  Indie Hackers story.
