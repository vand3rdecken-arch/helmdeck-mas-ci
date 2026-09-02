# -*- coding: utf-8 -*-
"""HENRY'S RULES AS DATA - the table the briefs are rendered FROM.

Phase 2 of ops/docs/backlog/harness-config-ui (owner complaint 2026-09-02:
"Henrys eigene Verhaltensregeln - Ton, Trigger, was er selbst tun darf - stehen
als Fliesstext und sind nirgends sichtbar oder einstellbar").

THE MECHANIC, in one sentence: the brief stays a file and stays prose; the
paragraphs that really carry a VALUE become SLOTS, and the values render into
them. `{{rule:tone.length}}` in ops/harness/agents/board-copilot.md is
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
     "source": "ops/harness/agents/board-copilot.md:93"},

    {"key": "tone.address", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "single", "options": ["du", "Sie"],
     "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.address", "descKey": "rule.tone.address.desc",
     "why": "Die Anrede steht heute als Prosa im Brief und war damit nur durch "
            "Umschreiben des Briefes zu aendern.",
     "surfaces": {
         "pm": {"default": "du", "renders": {
             "du": 'always "du"', "Sie": 'always "Sie"'}}},
     "source": "ops/harness/agents/board-copilot.md:17"},

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
     "source": "ops/harness/agents/board-copilot.md:17"},

    {"key": "tone.humor", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.humor", "descKey": "rule.tone.humor.desc",
     "why": "Henrys Charakter ist Absicht, aber nicht jeder will trockene "
            "Kommentare in einer Statusmeldung.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "Mild dry humor is allowed; cheerleading is not.",
             False: "Neither humor nor cheerleading; state it plainly."}}},
     "source": "ops/harness/agents/board-copilot.md:20"},

    {"key": "tone.jargon", "block": "tone", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.tone.jargon", "descKey": "rule.tone.jargon.desc",
     "why": "Dieselbe Regel, an die sich auch dieser Bildschirm haelt: "
            "Stationen heissen Karte/Arbeit/Abnahme, nicht Lane/Worktree.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "and never internal jargon (Snapshot,\n   Lane, Gate, Worktree) in the owner's chat",
             False: "and internal terms are fine when they are\n   the precise word"}}},
     "source": "ops/harness/agents/board-copilot.md:73"},

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
     "source": "ops/harness/agents/board-copilot.md:25-42"},

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
     "source": "ops/harness/agents/board-copilot.md:69"},

    {"key": "initiative.progress", "block": "initiative", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "project", "binds": ["working"],
     "labelKey": "rule.init.progress", "descKey": "rule.init.progress.desc",
     "why": "Der zurueckkehrende Owner soll nie \"und, wie weit?\" fragen "
            "muessen.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "The owner should never have to ask \"und, wie weit?\" -\n   a returning owner gets the Zwischenmeldung unprompted.",
             False: "Report progress only when he asks for it."}}},
     "source": "ops/harness/agents/board-copilot.md:80"},

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
     "source": "ops/harness/agents/board-copilot.md:254"},

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
     "source": "ops/harness/agents/board-copilot.md:223"},

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
     "source": "ops/harness/agents/board-copilot.md:320"},

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
     "source": "ops/harness/agents/board-copilot.md:119"},

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
     "source": "ops/harness/agents/board-copilot.md:203"},

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
     "source": "ops/harness/agents/board-copilot.md:244"},

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
     "source": "ops/harness/agents/board-copilot.md:236"},

    {"key": "hands.permission_mode", "block": "hands", "wire": "code", "kind": "policy",
     "control": "single", "options": ["plan", "acceptEdits"],
     "scope": "project", "binds": ["working"],
     "labelKey": "rule.hands.pmode", "descKey": "rule.hands.pmode.desc",
     "why": "settings.henry_permission_mode existiert und hatte nie eine "
            "Oberflaeche. Gilt fuer Chat UND Broker.",
     "reads": "cells/copilot/copilot.py::henry_pmode",
     "surfaces": {"all": {"default": "acceptEdits", "renders": None}},
     "source": "cells/copilot/copilot.py:343"},

    {"key": "hands.agent_may_swap", "block": "hands", "wire": "code", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.hands.maySwap", "descKey": "rule.hands.maySwap.desc",
     "why": "Henry ist der Ausnahme-Broker - vorschlagen ist sein Job, "
            "ausfuehren ohne menschliche Bestaetigung nicht. Das schliesst den "
            "Kreis der Beschwerde: du siehst seine Regeln, und er darf dich um "
            "eine Aenderung bitten.",
     "reads": "spine/auth/policy.py::swap",
     "surfaces": {"all": {"default": False, "renders": None}},
     "source": "daemon/policy_seed.json:policies.agentMaySwap"},

    # -------------------------------------------------------------- report --
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
     "source": "ops/harness/agents/board-copilot.md:202"},

    # -------------------------------------------------------------- memory --
    {"key": "memory.enabled", "block": "memory", "wire": "slot", "kind": "policy",
     "control": "toggle", "scope": "workspace", "binds": [],
     "labelKey": "rule.memory.enabled", "descKey": "rule.memory.enabled.desc",
     "why": "Owner-Entscheidung 2026-08-30 (\"Kompaktieren und ins Speicher\"). "
            "Aus heisst: nach dem Verdichten ist der Verlauf nur noch "
            "Zusammenfassung.",
     "surfaces": {
         "pm": {"default": True, "renders": {
             True: "Faellt dir im Gespraech etwas Dauerhaftes zu -\neine Owner-Entscheidung, eine Vorliebe, ein laufendes Vorhaben, eine Zusage,\neine offene Frage, ein harter Fakt ueber ein Repo oder ein Geraet - schreib es\nsofort als eigene Datei dorthin und trag eine Zeile im Index nach.",
             False: "Lege KEINE neuen Notizen an; lies nur, was schon dort steht."}}},
     "source": "ops/harness/agents/board-copilot.md:272"},

    {"key": "memory.index_path", "block": "memory", "wire": "readonly", "kind": "fixed",
     "control": "prose", "scope": "workspace", "binds": [],
     "labelKey": "rule.memory.path", "descKey": "rule.memory.path.desc",
     "why": "Der Pfad ist maschinenlokal und wird vom Prozess bestimmt, nicht "
            "von Policy.",
     "surfaces": {"pm": {"default": None, "renders": None}},
     "source": "cells/copilot/copilot.py::MEMORY_DIR"},
]


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
_BY_KEY = {r["key"]: r for r in BEHAVIOR_RULES}


def rule_path(key, surface=None):
    """The dotted config path a rule's value is stored under.

    Per-surface by construction (`rule.tone.length.pm`), because the whole
    modelling point is that one rule holds several values. Called with no
    surface it returns the rule's namespace prefix, which is what
    projectconfig.overridable() registers."""
    return "rule.%s.%s" % (key, surface) if surface else "rule.%s" % key


def by_key(key):
    return _BY_KEY.get(key)


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
        from cells.copilot import copilot_actions
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
  value_per_card, default_repo, registration {open, invite_code, default_role}
  currency "EUR"|"USD"
  prices {<model-substring>: {in: $/Mtok, out: $/Mtok}, default: {...}} - AI cost table
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
        })
    return out
