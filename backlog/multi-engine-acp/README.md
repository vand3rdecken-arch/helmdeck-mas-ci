# Multi-engine: full Paseo-equivalent breadth — build cards ready to dispatch

**Filed 2026-08-24.** Analysis: `docs/multi-engine-support.md`. Build plan with
per-card scope + verify criteria: `docs/multi-engine-build-plan.md`. Read both;
every card additionally reads the real Paseo source (`~/Downloads/_paseo_src`)
at the file:line refs the plan names.

**2026-08-24 owner decision: full Paseo-equivalent breadth, not ACP alone.**
Generic ACP (reaches ~30 engines) stays the default; native adapters are added
on top for the three Paseo treats specially — Codex, OpenCode (via Paseo's own
DEDICATED-server mode, not its shared default — see analysis §6.6.2), Pi/OMP.
See analysis §6.6 for the full reasoning.

Nine cards, ~22–27.5 days total, **3 shipped (1, 2, 8)** (the ACP-only subset
— Cards 1–5, ~12–16 days — is a complete, coherent stopping point on its own):

| Card | What | Size | Status |
|---|---|---|---|
| 1 | Engine seam: CLAUDE constant dedup, parent-session env scrub (registry deferred — no 2nd engine to design it against yet) | M | ✅ SHIPPED 2026-08-24 |
| 2 | Event-time timeline store (pays the NO-MONKEY-PATCHES feed debt; worth it even engine-less) | L | ✅ SHIPPED 2026-08-24 |
| 3 | ACP transport + Stage-0 spike + brief-adherence probe (GO/NO-GO) | L | blocked on owner step below |
| 4 | ACP full feed + cancel parity | M–L | needs 3 + probe GO |
| 5 | Econ honesty ("n/a", never €0) + UI picker/badges | M | needs 4 |
| 6 | Codex native adapter (structured approval, no ACP token-loss) | M | needs 5 + owner step (OpenAI/Codex account) |
| 7 | OpenCode native adapter, **dedicated-server mode** (real cost reporting) | M–L | needs 5 + owner step (OpenCode + model provider) |
| 8 | omp native adapter (Pi half deferred) | S–M | ✅ SHIPPED 2026-08-24 |
| 9 | Wire native engines' real cost into Card 5's econ scaffolding | S | omp already qualifies once 5 lands |

Card 8 shipped OUT OF ORDER (built directly off Cards 1+2, no Card 5
dependency in practice) because omp needed no new owner step at all - see
below. See each card's section in `docs/multi-engine-build-plan.md` for what
actually landed vs. what was scoped, and how it was verified - Card 8's
section in particular records a real wire-protocol bug the plan's original
scope text got wrong (multiple internal turn_end events per prompt) and how
it was caught.

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

Card 8 (omp): NONE - `omp.exe` was already installed on this box, and its
`ANTHROPIC_OAUTH_TOKEN` env var accepts the SAME OAuth token
`~/.claude/.credentials.json` already holds, so it drove real turns on the
owner's existing Claude subscription with zero new login. The Pi half of
Card 8 still needs its own account/step and its own live protocol
measurement - not assumed identical to omp just because Paseo groups them.

None of these block each other — dispatch whichever engine's prerequisite the
owner completes first.

## Kill-switches

Card 3's probe report (`docs/acp-probe-report.md`) is the GO/NO-GO for the
ACP path: if the engine cannot be made to follow the `<helmdeck-ask>` /
DELIVERED protocol reliably, stop after Card 2 and revisit engine choice.
Cards 1–2 are independently valuable refactors either way. Cards 6/7 are
each independently droppable without affecting the other or Card 9's
applicability to omp (already shipped).
