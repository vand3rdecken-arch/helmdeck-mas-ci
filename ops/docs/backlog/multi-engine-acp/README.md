# Multi-engine: full Paseo-equivalent breadth — build cards ready to dispatch

**Filed 2026-08-24.** Analysis: `ops/docs/multi-engine-support.md`. Build plan with
per-card scope + verify criteria: `ops/docs/multi-engine-build-plan.md`. Read both;
every card additionally reads the real Paseo source (`~/Downloads/_paseo_src`)
at the file:line refs the plan names.

**2026-08-24 owner decision: full Paseo-equivalent breadth, not ACP alone.**
Generic ACP (reaches ~30 engines) stays the default; native adapters are added
on top for the three Paseo treats specially — Codex, OpenCode (via Paseo's own
DEDICATED-server mode, not its shared default — see analysis §6.6.2), Pi/OMP.
See analysis §6.6 for the full reasoning.

**2026-08-24, second owner decision, same day: "do all like Paseo. Test
accounts later."** All four native adapters (omp, codex, opencode, pi) now
exist as real, tested code, built directly off Cards 1+2 — none needed
Card 5's originally-planned queue in practice. Only omp has actually been
run against a live account (via credential reuse, see below); the other
three are complete, gate-green, unit-tested modules waiting on an account
per engine before their "Verify" step can run — not more code.

Nine cards, ~22–27.5 days total. **Code-complete: 7 of 9** (1, 2, 6, 7, 8-both-
halves — 9 needs 5 first). **Live-verified: 3 of 9** (1, 2, the omp half of 8).
The ACP-only subset — Cards 1–5, ~12–16 days — is a complete, coherent
stopping point on its own, reaching ~30 engines with zero native-adapter
accounts:

| Card | What | Size | Status |
|---|---|---|---|
| 1 | Engine seam: CLAUDE constant dedup, parent-session env scrub (registry deferred — no 2nd engine to design it against yet) | M | ✅ SHIPPED 2026-08-24 |
| 2 | Event-time timeline store (pays the NO-MONKEY-PATCHES feed debt; worth it even engine-less) | L | ✅ SHIPPED 2026-08-24 |
| 3 | ACP transport + Stage-0 spike + brief-adherence probe (GO/NO-GO) | L | blocked on owner step below |
| 4 | ACP full feed + cancel parity | M–L | needs 3 + probe GO |
| 5 | Econ honesty ("n/a", never €0) + UI picker/badges | M | needs 4 |
| 6 | Codex native adapter (structured approval, no ACP token-loss) | M | **code ✅**, LIVE VERIFY open (owner step below) |
| 7 | OpenCode native adapter, **dedicated-server mode** (real cost reporting) | M–L | **code ✅**, LIVE VERIFY open (owner step below) — REST paths inferred, highest risk of the three |
| 8 | omp native adapter (LIVE-VERIFIED) + pi native adapter (**code ✅**, unverified) | S–M | omp ✅ SHIPPED+VERIFIED; pi code ✅, LIVE VERIFY open |
| 9 | Wire native engines' real cost into Card 5's econ scaffolding | S | needs 5; omp already qualifies once it lands |

See each card's section in `ops/docs/multi-engine-build-plan.md` for what
actually landed, how it's tested, and exactly what "not yet verified" covers
for each of Codex/OpenCode/Pi — the confidence levels genuinely differ:
Codex is closest (full JSON-RPC shapes read from Paseo's source), Pi is next
(built on omp's PROVEN event-handling, but pi's own stream has never been
observed), OpenCode carries the most risk (REST paths are inferred, not
source-confirmed — `@opencode-ai/sdk` isn't vendored in this checkout).
Card 8's own section also records a real wire-protocol bug the ORIGINAL
plan's scope text got wrong (Paseo's TS types didn't warn that one prompt
can produce multiple internal `turn_end` events) — found by testing omp
live, then applied proactively (not yet confirmed) to pi's driver too.

## Owner steps — one per native engine, none blocking the others

Card 3 (ACP, unblocks Cards 3–5 and thus the ACP-only stopping point):
```
npm i -g @google/gemini-cli
gemini        # once, interactively: Google login, free tier, no card needed
```
Gemini CLI is the default ACP probe target because it is the only candidate
with a real free tier. Verified 2026-08-24: no candidate engine is currently
installed on this box.

Card 6 (Codex): an OpenAI account with Codex CLI access, installed +
authenticated once interactively.

Card 7 (OpenCode): OpenCode installed + a model provider configured
(OpenCode itself is free/open-source; the cost is whatever backend it drives).

Card 8, omp half (DONE): NONE was needed — `omp.exe` was already installed on
this box, and its `ANTHROPIC_OAUTH_TOKEN` env var accepts the SAME OAuth
token `~/.claude/.credentials.json` already holds, so it drove real turns on
the owner's existing Claude subscription with zero new login.

Card 8, pi half (code shipped, not yet verified): pi's own account/install
step — not assumed identical to omp's just because Paseo groups them.

None of these block each other — dispatch whichever engine's prerequisite the
owner completes first; each card's own "Verify (STILL OPEN)" line is the
concrete list of what that live turn needs to prove.

## Kill-switches

Card 3's probe report (`ops/docs/acp-probe-report.md`) is the GO/NO-GO for the
ACP path: if the engine cannot be made to follow the `<helmdeck-ask>` /
DELIVERED protocol reliably, stop after Card 2 and revisit engine choice.
Cards 1–2 are independently valuable refactors either way. Cards 6/7/8-pi
are each independently verifiable (or droppable) whenever their account
shows up, without affecting the others or Card 9's applicability to omp
(already qualifies today).
