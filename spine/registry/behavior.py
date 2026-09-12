# -*- coding: utf-8 -*-
"""HENRY'S RULES AS DATA - the table the briefs are rendered FROM.

Phase 2 of ops/docs/backlog/harness-config-ui (owner complaint 2026-09-02:
"Henrys eigene Verhaltensregeln - Ton, Trigger, was er selbst tun darf - stehen
als Fliesstext und sind nirgends sichtbar oder einstellbar").

THE MECHANIC, in one sentence: the brief stays a file and stays prose; the
paragraphs that really carry a VALUE become SLOTS, and the values render into
them. `{{rule:tone.length}}` in cells/copilot/harness/agents/board-copilot.md is
substituted here. The pattern is not new - harness.py already splices
`{{ask_protocol}}` for exactly the same reason (prompt and parser have to ship
together).

WHY THIS TABLE LIVES NEXT TO THE LOADER
---------------------------------------
Same reason LANE_FLOW sits next to move_lane() and _config_schema is importable
at module level: a contract nothing can import is a contract nothing can check.
ops/tests/test_behavior_rules.py reads BEHAVIOR_RULES from here and holds it to
the two acceptance criteria the card was written around.

ONE VALUE PER SURFACE, AND WHY THAT IS THE WHOLE MODELLING PROBLEM
------------------------------------------------------------------
The length law is stated FOUR times with FOUR different numbers today: 3
sentences in chat (board-copilot.md:93), 2 spoken (VOICE_STYLE), 2 on the watch
(WEAR_BRIEF), 2 sentences / 240 chars on automatic notices (notice.py:36). None
of them is a knob. A model with ONE global value could only squash the four
into one and would silently change Henry's behaviour on three surfaces. So a
rule holds a value PER SURFACE (`surfaces` below), the stored path is
`rule.<key>.<surface>`, and phase 2 UNIFIES NOTHING: every current value is
preserved exactly and merely made visible. Whether they belong merged is an
owner decision he can only make once he sees them side by side - which is the
point of the card.

The surface keys are harness.SURFACES', not a second list.

THE TWO ACCEPTANCE CRITERIA (design doc section 4.1)
----------------------------------------------------
1. SLOT EQUALITY. Every rule wired as `slot` has exactly one slot in the brief
   of each surface it declares, and every slot in a brief has exactly one rule.
   A rule with no slot changes nothing and CLAIMS to - precisely the class of
   bug this renderer exists to prevent.
2. BYTE IDENTITY AT DEFAULTS. With every value at its default, all rendered
   briefs are byte-for-byte what they are today. That is the acceptance that
   keeps "structured" from meaning "quietly changed". The briefs grew over
   months and every line has a date and a cause; the diff of this commit must
   therefore be markers-for-text and nothing else.

HOW A VALUE REACHES A TURN (design doc section 3)
--------------------------------------------------
Henry's 1.6s warm turns exist because the base brief rides along ONCE at spawn
(copilot.py's --append-system-prompt). So:
  scope "workspace" rules render into the BASE brief. Changing one changes the
    config fingerprint, the warm process is dropped, the next turn spawns with
    the new brief. That mechanism already exists (_persist_drop).
  scope "project" rules ride as a TURN OVERLAY on the existing extra_system
    path, exactly like VOICE_STYLE does today. No respawn per project switch,
    no cold Henry after every edit.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
The brief is 28 KB of REASONING, not rulebook. Only part of it is
parametrizable; the rest (the do/don't examples, the decree derivations) stays
prose and is shown read-only. This module does not claim the whole system
prompt becomes a form - that would be the dishonest version. Rules marked
`kind: "fixed"` are the other half of that honesty: they render as slots the
brief editor CANNOT overwrite (harness.write_agent enforces it), which is how
making the rules visible RAISES the safety floor instead of softening it.
"""
import re

# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------
SLOT_RE = re.compile(r"\{\{rule:([a-z0-9_.]+)\}\}")

# A slot that sits ALONE on its line is a BLOCK slot: rendering it empty removes
# the whole line and the blank line that followed it, so switching a paragraph
# off leaves no stranded whitespace. An inline slot renders in place. Both are
# byte-identical to today at defaults - the difference only shows once a value
# moves off its default.
BLOCK_SLOT_RE = re.compile(r"^\{\{rule:([a-z0-9_.]+)\}\}\n(\n)?", re.M)


# ---------------------------------------------------------------------------
# The left navigation's blocks, in order. Server-owned like DOORS, for the same
# reason: the screen reads the order off the payload instead of re-declaring it.
# ---------------------------------------------------------------------------
BLOCKS = (
    {"key": "tone", "labelKey": "harness.blk.tone", "descKey": "harness.blk.tone.desc"},
    {"key": "initiative", "labelKey": "harness.blk.initiative", "descKey": "harness.blk.initiative.desc"},
    {"key": "hands", "labelKey": "harness.blk.hands", "descKey": "harness.blk.hands.desc"},
    {"key": "report", "labelKey": "harness.blk.report", "descKey": "harness.blk.report.desc"},
    {"key": "memory", "labelKey": "harness.blk.memory", "descKey": "harness.blk.memory.desc"},
    {"key": "routing", "labelKey": "harness.blk.routing", "descKey": "harness.blk.routing.desc"},
)

# How a rule is wired to reality. The distinction is load-bearing: it is what
# stops the table from claiming a knob that changes nothing.
#   slot     - renders into one or more briefs (slot-equality applies)
#   code     - read at runtime by a named module (`reads`), no brief text
#   readonly - shown with its source, never editable (kind is always "fixed")
WIRINGS = ("slot", "code", "readonly")

BEHAVIOR_RULES = [
    # ---------------------------------------------------------------- tone --
    {"key": "tone.length", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "single", "options": ["knapp", "normal", "ausfuehrlich"],
     "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.length", "descKey": "rule.tone.length.desc",
     "why": "Der Owner liest Henry auf dem Handy und hoert ihn auf Brille und "
            "Uhr. Laenge ist deshalb kein Geschmack, sondern die Frage, ob eine "
            "Antwort ueberhaupt ankommt - und sie faellt pro Oberflaeche anders "
            "aus.",
     "surfaces": {
         "pm": {"default": "knapp", "renders": {
             "knapp": "AT MOST 3 short sentences",
             "normal": "AT MOST 6 short sentences",
             "ausfuehrlich": "as long as the answer genuinely needs"}},
         "voice": {"default": "knapp", "renders": {
             "knapp": "At most TWO short sentences (~8 seconds spoken)",
             "normal": "At most FOUR short sentences (~16 seconds spoken)",
             "ausfuehrlich": "As long as the answer genuinely needs"}},
         "wear": {"default": "knapp", "renders": {
             "knapp": "at most 2 short sentences",
             "normal": "at most 4 short sentences",
             "ausfuehrlich": "as long as the answer genuinely needs"}},
         "glass": {"default": "knapp", "renders": {
             "knapp": "at most 2 short sentences",
             "normal": "at most 4 short sentences",
             "ausfuehrlich": "as long as the answer genuinely needs"}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:93"},

    {"key": "tone.address", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "single", "options": ["du", "Sie"],
     "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.address", "descKey": "rule.tone.address.desc",
     "why": "Die Anrede steht heute als Prosa im Brief und war damit nur durch "
            "Umschreiben des Briefes zu aendern.",
     "surfaces": {
         "pm": {"default": "du", "renders": {
             "du": 'always "du"', "Sie": 'always "Sie"'}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:17"},

    {"key": "tone.language", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "single", "options": ["de", "en"],
     "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.language", "descKey": "rule.tone.language.desc",
     "why": "policy.lang existiert seit langem und hatte NIE einen Bezug zum "
            "Brief - die Oberflaeche war deutsch, Henrys Sprachregel eine "
            "unabhaengige Zeile Prosa.",
     "surfaces": {
         "pm": {"default": "de", "renders": {
             "de": "German", "en": "English"}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:17"},

    {"key": "tone.humor", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.humor", "descKey": "rule.tone.humor.desc",
     "why": "Henrys Charakter ist Absicht, aber nicht jeder will trockene "
            "Kommentare in einer Statusmeldung.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "Mild dry humor is allowed; cheerleading is not.",
             False: "Neither humor nor cheerleading; state it plainly."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:20"},

    {"key": "tone.jargon", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.jargon", "descKey": "rule.tone.jargon.desc",
     "why": "Dieselbe Regel, an die sich auch dieser Bildschirm haelt: "
            "Stationen heissen Karte/Arbeit/Abnahme, nicht Lane/Worktree.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "and never internal jargon (Snapshot,\n   Lane, Gate, Worktree) in the owner's chat",
             False: "and internal terms are fine when they are\n   the precise word"}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:73"},

    {"key": "tone.house_rules", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "text", "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.houseRules", "descKey": "rule.tone.houseRules.desc",
     "why": "policy.house_rules existiert seit Monaten und hatte NIE eine "
            "Oberflaeche. Additiv wie in charter.py:12 - hinzufuegen ja, "
            "abschwaechen nie.",
     "surfaces": {"pm": {"default": "", "renders": None}},
     "source": "spine/auth/charter.py:12"},

    {"key": "tone.examples", "block": "tone", "wire": "readonly", "kind": "fixed",
     "control": "prose", "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.examples", "descKey": "rule.tone.examples.desc",
     "why": "\"examples are the law\" - die Do/Don't-Paare sind die eigentliche "
            "Tonvorgabe. Sie zu parametrisieren hiesse, den Ton zu loeschen.",
     "surfaces": {"pm": {"default": None, "renders": None}},
     "source": "cells/copilot/harness/agents/board-copilot.md:25-42"},

    # ---------------------------------------------------------- initiative --
    {"key": "initiative.estimate", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": ["backlog"],
     "labelKey": "rule.init.estimate", "descKey": "rule.init.estimate.desc",
     "why": "SPEED OF FIRST WORD: der Owner wartet auf den ersten Satz. Die "
            "Dauerschaetzung ist das, was ihn vom Warten befreit.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: 'And release him from waiting: "dauert\n   ~10 Minuten, du musst nicht warten - ich meld mich" (true: the daemon\n   pushes your Rueckmeldung onto his phone).',
             False: "Do not promise to report back unless he asks."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:69"},

    {"key": "initiative.progress", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": ["working"],
     "labelKey": "rule.init.progress", "descKey": "rule.init.progress.desc",
     "why": "Der zurueckkehrende Owner soll nie \"und, wie weit?\" fragen "
            "muessen.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "The owner should never have to ask \"und, wie weit?\" -\n   a returning owner gets the Zwischenmeldung unprompted.",
             False: "Report progress only when he asks for it."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:80"},

    {"key": "initiative.finish", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": ["review", "done"],
     "labelKey": "rule.init.finish", "descKey": "rule.init.finish.desc",
     "why": "Owner-Decree 2026-08-21 (\"he doesn't push the card through the "
            "gates\"). Der Gate prueft weiterhin - das hier entscheidet nur, ob "
            "Henry auf einen menschlichen Zug wartet.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "When a card's work is done, DRIVE it home instead of\nparking it: move it to review (runs the gate), and when the verdict is green\nand cleanly mergeable, move it to done yourself - the harness gates, merges\nand deploys; you never bypass any of that, you just stop waiting for a human\ndrag.",
             False: "When a card's work is done, move it to review and STOP -\nthe owner accepts it himself."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:256"},

    {"key": "initiative.questions", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "number", "scope": "project", "binds": ["backlog"],
     "labelKey": "rule.init.questions", "descKey": "rule.init.questions.desc",
     "why": "Ein falscher Schuss auf einen grossen Build kostet Stunden "
            "Agentenzeit; eine Frage kostet Sekunden. Aber die QUICK-Klasse "
            "darf nie verhoert werden - das kehrt den Sinn um.",
     # A dial with prose per step, not a bare number spliced into a sentence:
     # "ask the 0 questions" is not a sentence, and a slot that can render
     # nonsense is a slot that will.
     "surfaces": {"pm": {"default": 2, "renders": {
         0: "file with what the message already gives you, and ask nothing that",
         1: "ask the ONE question that",
         2: "ask the 2-3 questions that",
         3: "ask the 3-4 questions that"}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:225"},

    {"key": "initiative.stale_check", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": [],
     "labelKey": "rule.init.stale", "descKey": "rule.init.stale.desc",
     "why": "Gemessen 2026-09-01: eine veraltete Karte wurde woertlich als "
            "aktuelle Lage zitiert, der Owner bekam einen glatt falschen "
            "Status.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "A card's lane/status in the DB is not proof its\ntext still holds - the newer evidence wins.",
             False: "Cite a card's own text as it stands."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:336"},

    {"key": "initiative.repo_default", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "single", "options": ["direkt", "worktree"],
     "scope": "project", "binds": ["backlog", "working"],
     "labelKey": "rule.init.repoDefault", "descKey": "rule.init.repoDefault.desc",
     "why": "Owner-Decree 2026-08-29: Solo-Arbeit landet direkt, der "
            "Worktree-Umweg kostete 30+ Minuten pro Fix. Ein Doku-Repo will "
            "das womoeglich anders als ein Code-Repo - deshalb pro Projekt.",
     "surfaces": {
         "pm": {"default": "direkt", "renders": {
             "direkt": "This is the DEFAULT for repo fixes and small/medium features the owner asks for",
             "worktree": "Use it only when the owner asks for the live tree explicitly"}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:121"},

    # --------------------------------------------------------------- hands --
    {"key": "hands.own_hands", "block": "hands", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": ["working"],
     "labelKey": "rule.hands.own", "descKey": "rule.hands.own.desc",
     "why": "Owner-Decree 2026-08-21 (\"do stuff directly instead of "
            "waiting\"). Aus heisst: Henry delegiert auch den Einzeiler.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "You HAVE HANDS (owner decree 2026-08-21: \"do\nstuff directly instead of waiting\"): for a SMALL, immediate fix - read a log,\ncorrect a config value, restart a stuck script, patch an obvious one-file bug -\nuse your own tools in this turn and tell the owner what you did. Do NOT file a\ncard for something you can finish yourself in under a few minutes.",
             False: "You have NO hands of your own: every change, however small,\ngoes to an agent you dispatch."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:205"},

    {"key": "hands.protected_files", "block": "hands", "wire": "slot", "kind": "fixed",
     "control": "list", "scope": "workspace", "binds": ["working"],
     "labelKey": "rule.hands.protected", "descKey": "rule.hands.protected.desc",
     "why": "Nur additiv, dieselbe Regel unter der house_rules schon steht: "
            "hinzufuegen ja, abschwaechen nie. Eine Permission-Grenze falsch zu "
            "setzen ist eine andere Risikoklasse als ein Feature-Bug - der "
            "Feature-Bug faellt auf, wenn er bricht.",
     "surfaces": {
         "pm": {"default": ["card_tool_guard.py", "spine/auth/auth.py",
                            "spine/auth/charter.py", "spine/auth/policy.py",
                            "spine/auth/gxp.py", "ops/tools/run_gate.py"],
                "renders": None}},
     "source": "cells/copilot/harness/agents/board-copilot.md:246"},

    {"key": "hands.configure_allowlist", "block": "hands", "wire": "slot", "kind": "fixed",
     "control": "prose", "scope": "workspace", "binds": [],
     "labelKey": "rule.hands.allowlist", "descKey": "rule.hands.allowlist.desc",
     "why": "Bis Phase 2 zaehlte der Brief zwoelf Keys VON HAND auf - eine "
            "zweite Liste neben dem Schema, die auseinanderlaufen KANN und "
            "wird. Jetzt rendert der Absatz AUS dem Schema: was die Seite "
            "editieren kann, kann der Chat editieren, per Konstruktion "
            "dieselbe Menge.",
     "surfaces": {"pm": {"default": None, "renders": None}},
     "source": "spine/http/apimeta.py:_config_schema"},

    {"key": "hands.delete_asks", "block": "hands", "wire": "readonly", "kind": "fixed",
     "control": "prose", "scope": "workspace", "binds": [],
     "labelKey": "rule.hands.delete", "descKey": "rule.hands.delete.desc",
     "why": "Zerstoerendes ohne klaren Auftrag bleibt beim Menschen. Das ist "
            "keine Einstellung.",
     "surfaces": {"pm": {"default": None, "renders": None}},
     "source": "cells/copilot/harness/agents/board-copilot.md:238"},

    {"key": "hands.permission_mode", "block": "hands", "wire": "code", "kind": "policy",
     "control": "single", "options": ["auto", "plan", "acceptEdits", "bypassPermissions"],
     "scope": "project", "binds": ["working"],
     "labelKey": "rule.hands.pmode", "descKey": "rule.hands.pmode.desc",
     "why": "settings.henry_permission_mode existiert und hatte nie eine "
            "Oberflaeche. Gilt fuer Chat UND Broker.",
     "reads": "cells/copilot/copilot.py::henry_pmode",
     "surfaces": {"all": {"default": "auto", "renders": None}},
     "source": "cells/copilot/copilot.py:343"},

    # READONLY, not a toggle - and that is a deliberate refusal, not an
    # oversight (harness-config-ui phase 3). The value that really gates an
    # agent-initiated swap lives in the POLICY PLANE as `policies.agentMaySwap`
    # and is written only by spine/auth/policy.py::swap. A rule row storing
    # `rule.hands.agent_may_swap.all` in settings.json would therefore save
    # cleanly, badge itself "gesetzt", and change NOTHING - the dummy switch
    # this table exists to refuse, and a dummy on the one row that reads "Henry
    # darf Regeln selbst aendern" is the worst possible place for one.
    # The design doc asks for a real toggle here; giving it one needs a write
    # path into the policy plane, which is an owner decision because it touches
    # who may change the rules. Registered as [agent-may-swap-readonly].
    {"key": "hands.agent_may_swap", "block": "hands", "wire": "readonly", "kind": "fixed",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.hands.maySwap", "descKey": "rule.hands.maySwap.desc",
     "why": "Henry ist der Ausnahme-Broker - vorschlagen ist sein Job, "
            "ausfuehren ohne menschliche Bestaetigung nicht. Steht heute auf "
            "aus. Der Wert lebt in der Policy-Ebene und wird nur ueber "
            "policy.swap gesetzt; diese Seite zeigt ihn, sie schreibt ihn "
            "(noch) nicht - ein Schalter hier wuerde speichern und nichts "
            "bewirken.",
     "reads": "spine/auth/policy.py::swap",
     "surfaces": {"all": {"default": False, "renders": None}},
     "source": "daemon/policy_seed.json:policies.agentMaySwap"},

    # -------------------------------------------------------------- report --
    # Henry's JUDGEMENT MANDATE - the prose the escalation broker opens every
    # judgement turn with. It was already "policy is data" (henry_broker.py's
    # own docstring says so), but as a RAW GLOBAL KEY: settings.json
    # `henry_policy`, read straight in _decide, with no row in any table - so no
    # scope, no validator, no size bound, no badge and no screen. It is the most
    # behaviour-defining value in the copilot cell and it was the one value
    # nothing could show you.
    #
    # THE DEFAULT IS "" AND THAT IS DELIBERATE. The mandate itself stays in
    # henry_broker.DEFAULT_POLICY, version-controlled next to the code that
    # reasons about it; restating those lines here would be a second home for
    # the text and the two would drift the first time either is edited. ""
    # means "use the built-in mandate" - which is exactly what the legacy key
    # already meant (`(...) or DEFAULT_POLICY`), so byte identity at defaults
    # holds: an installation that sets nothing gets today's prompt to the
    # character.
    #
    # scope "project" is the honest blast radius: the mandate talks about
    # landing work, budget and this box's resources, and a workspace driving two
    # very different repos has every reason to brief Henry differently for each.
    # A turn that names no repo resolves the workspace layer underneath, which
    # is where the legacy global value migrates to (spine/storage/legacypolicy.py).
    {"key": "report.judgement_policy", "block": "report", "wire": "code", "kind": "policy",
     "control": "text", "scope": "project", "binds": [],
     "labelKey": "rule.report.judgement", "descKey": "rule.report.judgement.desc",
     "why": "Bis hierher settings.json `henry_policy` - ein globaler Schluessel "
            "ohne Zeile, ohne Scope, ohne Schranke und ohne Screen. Der Wert "
            "bestimmt, wie Henry JEDE Eskalation beurteilt; leer heisst weiter "
            "'nimm das eingebaute Mandat'.",
     "reads": "cells/copilot/henry_broker.py::_decide",
     "surfaces": {"all": {"default": "", "renders": None}},
     "source": "cells/copilot/henry_broker.py:71 (DEFAULT_POLICY)"},

    {"key": "report.followup_interval", "block": "report", "wire": "slot", "kind": "policy",
     "control": "number", "scope": "project", "binds": ["working"],
     "labelKey": "rule.report.interval", "descKey": "rule.report.interval.desc",
     "why": "Bis hierher hartkodiert als _INTERVAL_S. Der Wert steht auch im "
            "Brief (\"within ~90s\") - eine Zahl an zwei Orten, die "
            "auseinanderlaufen konnte.",
     "reads": "cells/copilot/henry_broker.py::_INTERVAL_S",
     "surfaces": {"pm": {"default": 90, "renders": "%s"}},
     "source": "cells/copilot/henry_broker.py:40"},

    {"key": "report.followup_attempts", "block": "report", "wire": "code", "kind": "policy",
     "control": "number", "scope": "project", "binds": [],
     "labelKey": "rule.report.attempts", "descKey": "rule.report.attempts.desc",
     "why": "Bis hierher hartkodiert als _MAX_ATTEMPTS. Danach weckt der Broker "
            "den Owner - das ist die Grenze zwischen Selbsthilfe und Stoerung.",
     "reads": "cells/copilot/henry_broker.py::_MAX_ATTEMPTS",
     "surfaces": {"all": {"default": 2, "renders": None}},
     "source": "cells/copilot/henry_broker.py:39"},

    {"key": "report.dedupe_window", "block": "report", "wire": "code", "kind": "policy",
     "control": "number", "scope": "workspace", "binds": [],
     "labelKey": "rule.report.dedupe", "descKey": "rule.report.dedupe.desc",
     "why": "Bis hierher hartkodiert als chat_dedupe.WINDOW. Der Owner hatte "
            "\"mindestens 10 Minuten\" verlangt; gemessen wurden Replays bis "
            "176s.",
     "reads": "cells/copilot/chat_dedupe.py::WINDOW",
     "surfaces": {"all": {"default": 600, "renders": None}},
     "source": "cells/copilot/chat_dedupe.py:65"},

    {"key": "report.notice_chars", "block": "report", "wire": "code", "kind": "policy",
     "control": "number", "scope": "workspace", "binds": [],
     "labelKey": "rule.report.noticeChars", "descKey": "rule.report.noticeChars.desc",
     "why": "Die vierte Fassung des Laengengesetzes - fuer nicht scrollbare "
            "Kanaele. Bis hierher hartkodiert als notice.MAX_CHARS.",
     "reads": "spine/comms/notice.py::MAX_CHARS",
     "surfaces": {"notice": {"default": 240, "renders": None}},
     "source": "spine/comms/notice.py:36"},

    {"key": "report.notice_sentences", "block": "report", "wire": "code", "kind": "policy",
     "control": "number", "scope": "workspace", "binds": [],
     "labelKey": "rule.report.noticeSentences", "descKey": "rule.report.noticeSentences.desc",
     "why": "Dasselbe Gesetz, in Saetzen. Steht hier neben den drei anderen "
            "Fassungen, damit der Owner ueberhaupt entscheiden KANN, ob sie "
            "zusammengehoeren.",
     "reads": "spine/comms/notice.py::MAX_SENTENCES",
     "surfaces": {"notice": {"default": 2, "renders": None}},
     "source": "spine/comms/notice.py:37"},

    {"key": "report.never_dead_end", "block": "report", "wire": "readonly", "kind": "fixed",
     "control": "prose", "scope": "workspace", "binds": [],
     "labelKey": "rule.report.deadEnd", "descKey": "rule.report.deadEnd.desc",
     "why": "Owner-Decree: Henry ist die eine Schnittstelle zu Maschine und "
            "Board. Ein \"kann ich nicht\" ist dort ein Defekt, keine Antwort.",
     "surfaces": {"pm": {"default": None, "renders": None}},
     "source": "cells/copilot/harness/agents/board-copilot.md:204"},

    # -------------------------------------------------------------- memory --
    {"key": "memory.enabled", "block": "memory", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.memory.enabled", "descKey": "rule.memory.enabled.desc",
     "why": "Owner-Entscheidung 2026-08-30 (\"Kompaktieren und ins Speicher\"). "
            "Aus heisst: nach dem Verdichten ist der Verlauf nur noch "
            "Zusammenfassung.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "Faellt dir im Gespraech etwas Dauerhaftes zu -\neine Owner-Entscheidung, eine Vorliebe, ein laufendes Vorhaben, eine Zusage,\neine offene Frage, ein harter Fakt ueber ein Repo oder ein Geraet - haeng SOFORT\neinen <memory-save>-Block an deine Antwort und zieh den Index nach.",
             False: "Lege KEINE neuen Notizen an (kein <memory-save>-Block); lies nur, was schon dort steht."}}},
     "source": "cells/copilot/harness/agents/board-copilot.md:304"},
    # memory.index_path (a "here's the machine-local cache path" fixed rule)
    # removed 2026-09-11: memory has no filesystem path anymore - db-only,
    # a full note is read via ops/tools/henry_memory_get.py - so there is
    # nothing left to display.

    # ------------------------------------------------------------- routing --
    # WHICH MODEL, WHEN - owner decree 2026-09-04 ("das ist doch Logik von
    # Henry oder engineer, nicht auf spine-Ebene. Je nach Projekt und Situation
    # braucht man doch verschiedene Flows und Modelle"). Until here this was
    # THREE bare constants in spine/agent/turnopts.py (HIGH_VALUE,
    # "claude-opus-5", "claude-sonnet-5") - workspace-wide, invisible, and
    # measured to starve Sonnet by accident three times over (fa54463,
    # 33a2412: prio-high/turns/keyword triggers all fired on ordinary cards).
    # turnopts.py KEEPS the mechanism (server whitelist, context-window law,
    # "explicit wins") - that is a harness invariant, not a preference. These
    # three rows are the POLICY half: which model Auto picks, and the one
    # measured-evidence signal (a card's own value) that escalates it. Each
    # `reads` names the CELL that actually calls turnopts with this value -
    # cell_of() therefore attributes ownership to engineer/copilot, not spine,
    # exactly the split the owner asked for.
    {"key": "routing.auto_model", "block": "routing", "wire": "code", "kind": "policy",
     "control": "single", "options": ["claude-sonnet-5", "claude-opus-5"],
     "scope": "project", "binds": [],
     "labelKey": "rule.routing.autoModel", "descKey": "rule.routing.autoModel.desc",
     "why": "Sonnet 5 ist heute der Auto-Default fuer Karten (Owner-Decree "
            "2026-09-04). Ein Kundenprojekt mit hoeherem Risiko will "
            "moeglicherweise durchgaengig die staerkere Stufe - pro Projekt, "
            "nicht workspace-weit.",
     "reads": "cells/engineer/cards/turnrunner.py::_routing_policy",
     "surfaces": {"all": {"default": "claude-sonnet-5", "renders": None}},
     "source": "spine/agent/turnopts.py:pick_model"},

    {"key": "routing.escalate_value", "block": "routing", "wire": "code", "kind": "policy",
     "control": "number", "scope": "project", "binds": [],
     "labelKey": "rule.routing.escalateValue", "descKey": "rule.routing.escalateValue.desc",
     "why": "Ab diesem Kartenwert (Waehrung: value_per_card) eskaliert Auto "
            "auf die starke Stufe, unabhaengig vom Text. Ein Projekt mit "
            "durchweg hohen Werten will die Schwelle vielleicht anders "
            "ziehen als der Workspace-Default.",
     "reads": "cells/engineer/cards/turnrunner.py::_routing_policy",
     "surfaces": {"all": {"default": 100, "renders": None}},
     "source": "spine/agent/turnopts.py:HIGH_VALUE"},

    {"key": "routing.escalate_urgent", "block": "routing", "wire": "code", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": [],
     "labelKey": "rule.routing.escalateUrgent", "descKey": "rule.routing.escalateUrgent.desc",
     "why": "An: Prioritaet 'urgent' eskaliert immer auf die starke Stufe. "
            "Aus, fuer ein Projekt, das Prioritaet fuer die Reihenfolge in "
            "der Warteschlange nutzt statt fuer Modell-Risiko.",
     "reads": "cells/engineer/cards/turnrunner.py::_routing_policy",
     "surfaces": {"all": {"default": True, "renders": None}},
     "source": "spine/agent/turnopts.py:pick_model"},
]


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
_BY_KEY = {r["key"]: r for r in BEHAVIOR_RULES}


def rule_path(key, surface=None):
    """The dotted config path a rule's value is stored under.

    Per-surface by construction (`rule.tone.length.pm`), because the whole
    modelling point is that one rule holds several values. Called with no
    surface it returns the rule's namespace prefix - useful for grouping, but
    NOT a storable path: nothing reads it, because every read names a surface.
    projectconfig.overridable() therefore registers the per-surface paths."""
    return "rule.%s.%s" % (key, surface) if surface else "rule.%s" % key


def by_key(key):
    return _BY_KEY.get(key)


def split_path(path):
    """(rule, surface) for a `rule.<key>.<surface>` path, else (None, None).

    Exact, and it resolves the SURFACE too - which is the half by_path() cannot
    give and every layer below needs. Reporting a rule without its surface makes
    a four-surface rule answer with the first surface's default for all four,
    which is precisely the collapse `per_surface` exists to prevent."""
    if not path.startswith("rule."):
        return None, None
    rest = path[5:]
    head, _, tail = rest.rpartition(".")
    rule = _BY_KEY.get(head)
    if rule is not None and tail in (rule.get("surfaces") or {}):
        return rule, tail
    return None, None


def by_path(path):
    """The rule owning a `rule.<key>[.<surface>]` path, else None. Tolerates
    both forms so a caller holding either can resolve without re-parsing."""
    if not path.startswith("rule."):
        return None
    rest = path[5:]
    if rest in _BY_KEY:
        return _BY_KEY[rest]
    head, _, tail = rest.rpartition(".")
    return _BY_KEY.get(head)


def cell_of(rule):
    """The registered cell this rule governs, or None for a spine-owned rule.

    DERIVED, never hand-kept: a rule already names the code that consumes it
    (`reads`) and the file it came from (`source`), and the cell registry
    already declares which folder and which brief belong to which cell
    (cells/<id>/ and Cell.harness_file). This resolves one against the other at
    read time - the same string references the table always carried, now with
    ONE owner answering "whose rule is this" instead of every screen guessing.
    ops/tests/test_behavior_rules.py holds the strings to the registry, so a
    renamed cell or a moved file breaks a test instead of silently un-grouping
    a rule."""
    try:
        from spine.registry import cells
    except Exception:                                        # noqa: BLE001
        return None
    for ref in (rule.get("reads") or "", rule.get("source") or ""):
        # "cells/copilot/henry_broker.py::_decide" / "...board-copilot.md:93"
        # -> the bare file path the registry can recognise.
        path = ref.split("::")[0].split(":")[0].strip().replace("\\", "/")
        if not path:
            continue
        for c in cells.CELLS:
            if path.startswith("cells/%s/" % c.id):
                return c.id
            if c.harness_file and path == c.harness_file.replace("\\", "/"):
                return c.id
    return None


def surfaces_of(rule):
    return list((rule or {}).get("surfaces") or {})


def default_of(rule, surface=None):
    """The declared default for a rule on a surface. With no surface, the first
    declared one - which is the only one for every single-surface rule."""
    surf = (rule or {}).get("surfaces") or {}
    if surface is None:
        surface = next(iter(surf), None)
    return (surf.get(surface) or {}).get("default")


def editable_rules():
    """Rules that carry a real control. `readonly` rules are shown with their
    source and never written - a screen that offered them a control would be
    offering a dummy, which is the exact thing SWITCHABLE_STATIONS refuses to
    do for stations."""
    return [r for r in BEHAVIOR_RULES if r["wire"] != "readonly"]


# Rules that are `fixed` and yet carry a control, because the control can only
# ever TIGHTEN them. Today that is the protected-file list, under exactly the
# rule house_rules already lives under (charter.py:12 - adding yes, weakening
# never). Keeping this as a named set rather than a `kind` of its own is
# deliberate: the lock in the UI is honest either way ("you may extend this,
# not shorten it"), and inventing a third kind would make every consumer learn
# a distinction only one rule has.
ADDITIVE_RULES = ("hands.protected_files",)


def writable(path):
    """(rule, surface, error) for a write to one rule path.

    THE ONE GATE, so the HTTP route, the chat verb and any future caller refuse
    the same set for the same stated reason. `fixed` is refused BY NAME with the
    why-sentence the row shows, which is what the brief already promises Henry
    does ("the action refuses it BY NAME with the route that IS open")."""
    rule, surface = split_path(path)
    if rule is None:
        return None, None, "no such rule: %s" % str(path)[:80]
    if rule["wire"] == "readonly":
        return None, None, "%s is shown, never set: %s" % (path, rule["why"])
    if rule["kind"] == "fixed" and rule["key"] not in ADDITIVE_RULES:
        return None, None, "%s is fixed: %s" % (path, rule["why"])
    return rule, surface, None


def check_value(rule, surface, val):
    """None when `val` is a legal value for this rule, else why it is not.

    Held against the rule's OWN declaration (control + options + the additive
    law), not against a per-caller idea of what is sane - the same reason
    _config_schema declares `control`: a value the renderer cannot produce is
    still a value an API client can send."""
    ctl = rule.get("control")
    if ctl == "toggle":
        if not isinstance(val, bool):
            return "%s takes true or false" % rule["key"]
    elif ctl == "number":
        if isinstance(val, bool) or not isinstance(val, int):
            return "%s takes a whole number" % rule["key"]
        if val < 0:
            return "%s cannot be negative" % rule["key"]
    elif ctl == "single":
        opts = rule.get("options") or []
        if val not in opts:
            return "%s takes one of: %s" % (rule["key"], ", ".join(map(str, opts)))
    elif ctl == "text":
        if not isinstance(val, str):
            return "%s takes text" % rule["key"]
    elif ctl == "list":
        if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
            return "%s takes a list of strings" % rule["key"]
    else:
        return "%s has no editable control" % rule["key"]
    if rule["key"] in ADDITIVE_RULES:
        # ADDITIVE, checked against the DECLARED default rather than the current
        # effective value: chaining "remove one, save" edits would otherwise walk
        # the list down to empty one legal step at a time.
        missing = [x for x in (default_of(rule, surface) or []) if x not in val]
        if missing:
            return "%s may only be extended; still required: %s" % (
                rule["key"], ", ".join(missing))
    # A rule that renders into a brief must render to SOMETHING for the value it
    # is given, or the slot silently empties and the paragraph disappears from
    # Henry's brief - the exact failure the slot-equality test exists to catch,
    # arriving at runtime instead of at test time.
    spec = ((rule.get("surfaces") or {}).get(surface) or {})
    ren = spec.get("renders")
    if isinstance(ren, dict) and val not in ren:
        return "%s has no wording for %r on %s" % (rule["key"], val, surface)
    return None


def writable_paths():
    """Every `rule.<key>.<surface>` path a caller may set, {path: scope}.

    Derived from the table, so a rule added in the daemon becomes settable with
    no second list to update - and a rule turned `fixed` stops being settable in
    the same edit."""
    out = {}
    for r in BEHAVIOR_RULES:
        for s in r.get("surfaces") or {}:
            p = rule_path(r["key"], s)
            if writable(p)[2] is None:
                out[p] = r.get("scope")
    return out


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
def value(key, surface=None, project=""):
    """The effective value of one rule on one surface.

    Resolved through the full chain (projectconfig), so a project overlay wins
    over the workspace which wins over the declared default. NEVER raises: a
    broken store degrades to the declared default, which is today's shipped
    behaviour, rather than to None - a None here would render as an empty slot
    and quietly delete a rule from Henry's brief."""
    rule = _BY_KEY.get(key)
    if rule is None:
        return None
    if surface is None:
        surface = next(iter(rule.get("surfaces") or {}), None)
    fallback = default_of(rule, surface)
    try:
        from spine.storage import projectconfig
        scope_project = project if rule.get("scope") == "project" else ""
        got = projectconfig.resolve(rule_path(key, surface), scope_project)
        if got["layer"] != "default" or got["value"] is not None:
            return got["value"] if got["value"] is not None else fallback
    except Exception:                                        # noqa: BLE001
        pass
    return fallback


def values(project=""):
    """{path: value} over every rule/surface pair. One call, one shape - the
    harness screen and the turn overlay read the same thing so they cannot
    drift."""
    out = {}
    for r in BEHAVIOR_RULES:
        for s in r.get("surfaces") or {}:
            out[rule_path(r["key"], s)] = value(r["key"], s, project)
    return out


def fingerprint(project=""):
    """A cheap digest of every effective rule value.

    THE CACHE KEY for Henry's warm process. The base brief rides along once at
    spawn, so a rule edit has to be OBSERVED for the next turn to see it. This
    is that observation, and it is derived from the values themselves at one
    owner - not from a stored "config changed" flag and not from db._version
    (which also bumps when a card moves, and would cold-start Henry constantly).
    Design doc section 9's prompt-cache risk is exactly this."""
    import hashlib
    import json
    try:
        blob = json.dumps(values(project), sort_keys=True, default=str)
    except Exception:                                        # noqa: BLE001
        return ""
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render_one(rule, surface, val):
    """The text one rule contributes to one surface's brief.

    `renders` is a value->text map for closed vocabularies, a %s template for
    numbers, and None for the rules whose text is BUILT rather than chosen
    (the allowlist, the protected-file list, the free-text house rules)."""
    spec = ((rule.get("surfaces") or {}).get(surface) or {})
    ren = spec.get("renders")
    if isinstance(ren, dict):
        if val in ren:
            return ren[val]
        return ren.get(spec.get("default"), "")
    if isinstance(ren, str):
        return ren % (val,)
    return _built(rule["key"], val)


def _built(key, val):
    """Rules whose slot text is composed, not picked."""
    if key == "tone.house_rules":
        txt = str(val or "").strip()
        if not txt:
            return ""
        body = "\n".join("- " + ln.strip() for ln in txt.splitlines() if ln.strip())
        return "\n\nHAUSREGELN (vom Owner gesetzt, zusaetzlich zu allem oben):\n" + body
    if key == "hands.protected_files":
        # textwrap, NOT a hand-kept line break: the list is additive, so a
        # seventh file must re-wrap the paragraph by itself. Width 70 is the
        # brief's own wrap and reproduces today's two lines exactly - which is
        # what the byte-identity check holds it to.
        import textwrap
        return textwrap.fill(", ".join(val or []), width=70)
    if key == "hands.configure_allowlist":
        return ALLOWLIST_PROSE
    return ""


def allowlist_keys():
    """The top-level keys the configure PROSE claims Henry may touch.

    Parsed from the rendered paragraph rather than kept as a second list, so
    this function and the brief can never disagree about what the brief says."""
    out = []
    for line in ALLOWLIST_PROSE.splitlines():
        line = line.strip()
        if not line or line.startswith(("tiles ", "panels ")):
            continue
        # Brace/bracket groups are the VALUE shape, not more keys - without
        # dropping them first, "capacity {wip_limit, touch_budget_day, ...}"
        # parses as three top-level keys and the drift check reports six
        # differences that do not exist.
        prev = None
        while prev != line:
            prev = line
            line = re.sub(r"\{[^{}]*\}|\[[^\[\]]*\]", "", line)
        for part in line.split(" - ")[0].split(","):
            token = part.strip().split(" ")[0].strip()
            root = token.split(".")[0]
            if root and root.isidentifier() and root not in out:
                out.append(root)
    return sorted(out)


def allowlist_drift():
    """[] when the prose above names exactly the keys copilot_actions actually
    ENFORCES, else the difference.

    Design doc section 5.5 asks for this paragraph to be RENDERED from the
    schema so "what the page can edit is what the chat can edit, by
    construction". It cannot be, yet, without changing what Henry is told - the
    prose and the enforced set genuinely differ today - and changing that is an
    owner decision, not a refactor. So the drift is MEASURED here and reported
    by the contract test instead of being papered over in either direction.
    That is the honest half of the same goal: the two lists may differ, but
    they can no longer differ SILENTLY."""
    try:
        from cells.copilot.chat import copilot_actions
        enforced = set(copilot_actions.ALLOWED_CONFIG)
    except Exception:                                        # noqa: BLE001
        return []
    prose = set(allowlist_keys())
    out = []
    for k in sorted(enforced - prose):
        out.append("enforced but not in the brief: %s" % k)
    for k in sorted(prose - enforced):
        out.append("in the brief but not enforced: %s" % k)
    return out


# The shipped paragraph, byte for byte. It is a `fixed` slot: the brief editor
# cannot overwrite it (harness.write_agent refuses), which is the point of the
# card - these sentences LOOKED like invariants and were merely prose until now.
ALLOWLIST_PROSE = """  policy.lane_labels {backlog,working,review,done: "label"} - rename lanes
  policy.auto_dispatch_modes ["do","prepare",...] - which step modes the chain starts alone
  policy.auto_accept_green true|false - green gate auto-accepts (autonomy) vs human accepts (control)
  policy.auto_dispatch_priority ""|"urgent"|"high" - backlog at/above this priority self-dispatches within WIP headroom
  capacity {wip_limit, touch_budget_day, tariff{steer,review,bounce}}
  value_per_card, default_repo, registration {open} - `open` lets anyone sign up WITHOUT an invitation, always as a client. To invite ONE person with a chosen role, do not touch this: create an invitation (Einstellungen > Team & Geraete > Mitglied einladen, or POST /invites {role}).
  currency "EUR"|"USD"
  prices {<model-substring>: {in: $/Mtok, out: $/Mtok}, default: {...}} - AI cost table
  jira {base, email, api_token, default_jql} - the Jira connection import_jira reads. It holds a TOKEN: set it only from credentials the owner gives you in that message, never invent or guess one, and never repeat it back in chat.
  appearance {backdrop: "mesh"|"aurora"|"ember"|"forest"|"mono"} - ambient background theme
  dashboard {tiles: [...], panels: [...]} - what the economics dashboard shows, in order.
    tiles vocabulary: value_delivered, ai_spend, margin, yield, automation, leverage
    panels vocabulary: capacity, gates, work"""


def slots_in(text):
    """Every rule key referenced by `text`, in order of appearance. The
    slot-equality test reads this - it is the only parser, so the test and the
    renderer can never disagree about what a slot is."""
    return SLOT_RE.findall(text or "")


def render(text, surface, project=""):
    """Substitute every `{{rule:...}}` slot in `text` for `surface`.

    NEVER RAISES and never leaves a marker behind. A slot naming an unknown
    rule renders empty, and any failure falls back to the declared default -
    so the worst case is today's shipped brief, never a brief with visible
    machinery in it or a rule silently dropped."""
    if not text or "{{rule:" not in text:
        return text

    def _value(key):
        try:
            rule = _BY_KEY.get(key)
            if rule is None:
                return ""
            return _render_one(rule, surface, value(key, surface, project))
        except Exception:                                    # noqa: BLE001
            rule = _BY_KEY.get(key)
            if rule is None:
                return ""
            try:
                return _render_one(rule, surface, default_of(rule, surface))
            except Exception:                                # noqa: BLE001
                return ""

    def _block(m):
        out = _value(m.group(1))
        return (out + "\n" + (m.group(2) or "")) if out else ""

    text = BLOCK_SLOT_RE.sub(_block, text)
    return SLOT_RE.sub(lambda m: _value(m.group(1)), text)


# ---------------------------------------------------------------------------
# The Henry track (design doc section 5.4.3)
# ---------------------------------------------------------------------------
# What Henry DOES at a station, in the owner's words. Only the label is declared
# here; WHICH stations appear is derived from the rules' `binds`, so a rule
# added in the daemon lights its station up with no client change at all - the
# dummy-knob test of the pipeline PRD, carried over to rules.
#
# Deliberately owner-language and jargon-free, the same rule Henry's own brief
# holds him to (tone.jargon): "legt an", not "dispatched into the backlog lane".
HENRY_VERBS = {
    "backlog": "harness.track.backlog",
    "working": "harness.track.working",
    "gate": "harness.track.gate",
    "review": "harness.track.review",
    "done": "harness.track.done",
    "deploy": "harness.track.deploy",
}


def track(project=""):
    """The band under the pipeline: one segment per station Henry acts at.

    Aggregated HERE, not in the client - the client holds no station list and
    no rule list, exactly as repo_pipeline.tsx already holds none. Each segment
    carries the rules responsible, so the screen can route a tap to the rows
    that made the segment appear instead of guessing."""
    by_station = {}
    for r in BEHAVIOR_RULES:
        for st in r.get("binds") or []:
            by_station.setdefault(st, []).append(r["key"])
    out = []
    for st, keys in by_station.items():
        if st not in HENRY_VERBS:
            continue          # a bind naming no known station draws nothing
        out.append({"station": st, "labelKey": HENRY_VERBS[st],
                    "rules": sorted(keys), "count": len(keys)})
    order = list(HENRY_VERBS)
    out.sort(key=lambda s: order.index(s["station"]))
    return out


def segments(text, surface, project=""):
    """The same render as render(), but as [{kind, text, rule?}] instead of one
    string (design doc section 4.3, "Brief ansehen").

    THE POINT IS THAT IT IS THE SAME RENDER. The brief view shows the owner
    exactly the artefact Henry is started with, with the values highlighted
    where they act - the Mailchimp merge-tag pattern. A second renderer built
    for the screen could drift from the one that feeds the agent, and then the
    page would be reassuring him about a brief that is not the brief. So this
    walks the identical markers with the identical substitution and only
    records WHERE each value went.

    `kind` is "prose" (fixed text, dimmed, not tappable) or "rule" (a value,
    chipped, tapping it opens the row that sets it). Block slots keep their
    trailing newline handling so the prose reads the same as the string form.
    """
    out = []
    if not text:
        return out

    def _emit(kind, chunk, key=None):
        if not chunk:
            return
        if out and out[-1]["kind"] == "prose" and kind == "prose":
            out[-1]["text"] += chunk
            return
        row = {"kind": kind, "text": chunk}
        if key:
            row["rule"] = key
        out.append(row)

    pos = 0
    for m in SLOT_RE.finditer(text):
        _emit("prose", text[pos:m.start()])
        key = m.group(1)
        rule = _BY_KEY.get(key)
        val = ""
        if rule is not None:
            try:
                val = _render_one(rule, surface, value(key, surface, project))
            except Exception:                                # noqa: BLE001
                val = ""
        # A block slot that renders empty takes its line with it, exactly as
        # render() does - otherwise the prose view would show a blank line the
        # real brief does not have.
        _emit("rule", val, key)
        pos = m.end()
        # BLOCK SLOT ONLY. render() drops the line (and the blank line after it)
        # for a marker that sits ALONE on its line and renders empty - see
        # BLOCK_SLOT_RE. An inline slot that happens to render empty keeps its
        # surroundings, and eating a newline there is how this view first
        # disagreed with the brief by one character: tone.house_rules is empty
        # by default, and the join stopped matching brief() byte for byte.
        alone = (m.start() == 0 or text[m.start() - 1] == "\n") and text[pos:pos + 1] == "\n"
        if not val and alone:
            pos += 1
            if text[pos:pos + 1] == "\n":
                pos += 1
    _emit("prose", text[pos:])
    return out


def overlay(project=""):
    """The TURN OVERLAY: what this project's rules say that the base brief does
    not. Empty string when nothing differs, which is the normal case.

    WHY AN OVERLAY AND NOT A RE-RENDER (design doc section 3). The base brief
    rides along once at spawn - that is what makes Henry's warm turns 1.6s. A
    project-scoped rule therefore cannot render into it: doing so would mean a
    respawn on every project switch, and Henry answers about several repos in
    one conversation. So the base brief carries the WORKSPACE values and this
    adds only the deltas, on the existing extra_system path that VOICE_STYLE
    already uses.

    Only rules that actually DIFFER appear. An overlay that restated every
    project rule would be a second copy of half the brief, and the two copies
    would be identical in the common case and contradictory in the interesting
    one - the later instruction winning by accident rather than by design."""
    out = []
    for r in BEHAVIOR_RULES:
        if r.get("scope") != "project" or r["wire"] == "readonly":
            continue
        for s in r.get("surfaces") or {}:
            here, base = value(r["key"], s, project), value(r["key"], s, "")
            if here == base:
                continue
            txt = _render_one(r, s, here)
            out.append("- %s" % txt.strip().replace("\n", " ")
                       if txt else "- %s: %s" % (r["key"], here))
    if not out:
        return ""
    return ("FUER DIESES PROJEKT GELTEN ABWEICHENDE REGELN. Sie ersetzen die "
            "entsprechende Stelle oben:\n" + "\n".join(out))


def describe(project=""):
    """The rule table as the app receives it: every rule with its effective
    value per surface, its provenance and its lock. Server-owned end to end -
    the screen renders what arrives and holds no rule list of its own, the same
    contract repo_pipeline.tsx already lives under."""
    from spine.storage import projectconfig
    out = []
    for r in BEHAVIOR_RULES:
        surfs = []
        for s in r.get("surfaces") or {}:
            path = rule_path(r["key"], s)
            try:
                got = projectconfig.resolve(
                    path, project if r.get("scope") == "project" else "")
            except Exception:                                # noqa: BLE001
                got = {"value": None, "layer": "default", "inherited": True}
            surfs.append({"surface": s, "path": path,
                          "value": value(r["key"], s, project),
                          "default": default_of(r, s),
                          "layer": got["layer"], "inherited": got["inherited"]})
        out.append({
            "key": r["key"], "block": r["block"], "wire": r["wire"],
            "kind": r["kind"], "control": r["control"],
            "options": r.get("options"), "scope": r.get("scope"),
            "binds": r.get("binds") or [], "labelKey": r["labelKey"],
            "descKey": r["descKey"], "why": r["why"], "source": r["source"],
            "reads": r.get("reads"), "surfaces": surfs,
            # WHOSE rule this is (derived, see cell_of) - the settings hub's
            # cells door groups by it, so a cell and its rules finally arrive
            # on one screen instead of the rule table knowing the cell only as
            # a string nobody resolved.
            "cell": cell_of(r),
        })
    return out
