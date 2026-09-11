# netdance CDP-hardening read-note - MACHINE card (owner decided 2026-09-11)

**Filed 2026-09-11**, follow-up to token-burn-hardening Karte C (five bounded
browser verbs, `spine/media/browsercap.py` + `ops/tools/browser_mcp.py`,
commit `e88f662`). Karte C's own spec asked for a first-commit "read-note" on
netdance's CDP hardening layer before implementing, because the effort was
unknown until that comparison happened. It never ran: Karte C shipped as a
**worktree** card, and worktree isolation (a fixed-harness law, checked
live - both Read and Bash refused any path outside the worktree) blocks
reading anywhere outside the card's own tree by construction. netdance sits
under the owner's home folder, structurally unreachable from a worktree
card. Registered as debt `browser-verbs-netdance-hardening-unread`
(`spine/registry/debt.py`, order 66). Owner decision (asked via
`<helmdeck-ask>`, answered 2026-09-11): **dispatch a machine card now** to
do the read a worktree card structurally cannot.

## Why this needs a MACHINE card specifically

A machine card runs in the owner's own working directory with full
filesystem access (`cells/engineer/cards/dispatch.py new_machine_task`) -
no worktree, no branch, no isolation boundary. That is the ONLY HelmDeck
surface that can reach `Documents/Private Project/netdance` (the owner's
OTHER project - see memory `netdance-browser-harness`: a mature raw-CDP
browser layer exposed to its own agent as MCP, with Chrome-147+ WS
discovery, a port token, and anti-automation hardening HelmDeck's
`browsercap.py` does not have).

## Task for the dispatched machine card

Workplace: `Documents/Private Project/netdance` (read-only pass first), then
the HelmDeck repo root to write the follow-up.

1. Read netdance's CDP-attach layer - however it locates/launches Chrome,
   discovers the debug WebSocket, and whatever port-token / anti-automation
   measures it applies. Take notes; do not copy code verbatim without
   understanding it (different project, different license/assumptions).
2. Compare against `spine/media/browsercap.py` (`_chrome_exe`, `_cdp_up`,
   `ensure_chrome`, `AgentBrowser.__init__`) and the two open debt items it
   already carries:
   - `browser-attach-real-chrome` (order 14) - no origin allowlist, no
     per-run debug-port token, no anti-automation hardening on the attached
     Chrome.
   - `browser-find-not-viewport-scoped` (order 65) - not netdance-related,
     listed here only so the machine card has full context on what's
     already tracked.
3. Write the read-note: what netdance does that `browsercap.py` doesn't,
   and for each technique, a one-line verdict - PORT IT (with why it closes
   part of `browser-attach-real-chrome`), or SKIP IT (with why it doesn't
   apply - e.g. netdance may assume a different threat model, a different
   Chrome version floor, or a use case HelmDeck's single-owner-machine
   model doesn't share).
4. If anything is worth porting, file a follow-up HelmDeck card (worktree,
   normal gate) implementing it against `browsercap.py`, and flip
   `browser-attach-real-chrome` (and `browser-verbs-netdance-hardening-
   unread`) to `paid` in `spine/registry/debt.py` in that follow-up's
   commit - not this read-note's.
5. If nothing is worth porting (netdance solves a different problem),
   still flip `browser-verbs-netdance-hardening-unread` to `paid` with the
   read-note as the "why" - the debt is "the comparison never happened",
   not "netdance's techniques must be adopted".

## Non-goals

- Copying netdance code into HelmDeck wholesale - it's the owner's other
  project with its own scope; this is a read-and-judge pass, not a merge.
- Blocking on this before Karte C's five verbs are usable - they already
  shipped (commit `e88f662`) and work today; this only closes the
  hardening gap `browser-attach-real-chrome` already tracked before Karte C
  existed.
