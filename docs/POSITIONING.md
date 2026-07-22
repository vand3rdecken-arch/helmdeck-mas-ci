# SwarmDeck — positioning

**One-liner:** The board where work does itself — and proves it.

**Definition:** A work-management system whose tickets *execute*: agents do
the work on real repos and real machines, humans do only the steps that need
a human, every action is screen-recorded and priced, and the workspace itself
is built by talking to it.

**Formula:** Jira × Lovable × n8n × UiPath — with Claude as the workforce.

| Parent | Contributes | Fatal gap alone |
|---|---|---|
| Jira | System of record: tickets, clients, priorities, roles, audit | Tracks work, can't do it |
| Lovable | Build-by-chat: the workspace is conversationally malleable | Builds software, has no notion of ongoing work |
| n8n | Orchestration: requests become step chains that auto-advance | No clients, no board, humans aren't first-class steps |
| UiPath | Hands on real desktops/browsers | Brittle robots nobody can watch |

**Why the merge never happened before — and what the product actually is:**
every pairwise merge fails on TRUST. Tickets may execute themselves only if
the work is verifiable (the quality gate). Users may build integrations by
chatting only if built things are screened, versioned, reversible (charter,
checkpoints, rollback). Agents may drive your machines only if you can watch
and replay their hands (flight recorder, live thumbnails). **The trust loop —
gate → accept → audit → rollback — is the platform; the four categories are
surfaces mounted on it.**

**Second moat: native unit economics.** Every ticket knows its value, AI
cost, human touch-units, margin, and completion mode (auto vs assisted).
The dashboard is the customer's ROI statement; the product sells itself with
its own telemetry. No parent category can price a unit of work.

**Category:** agentic operations platform — "the operating system for a
business that employs AI."

**ICP, in order of wedge:** solo operators & agencies delivering client work
→ SMB service firms → internal ops teams currently duct-taping
Jira + n8n + RPA.

**What it is NOT:** not a chatbot with buttons, not RPA scripting, not
another PM tool skin. If nothing executes, records itself, and reports its
margin, it isn't this category.
