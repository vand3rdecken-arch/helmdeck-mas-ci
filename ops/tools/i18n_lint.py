# -*- coding: utf-8 -*-
"""Keep HelmDeck in ONE language.

The product used to be half German, half English - German prose under English
chrome. Translating it once fixes today; this keeps it fixed, because the next
hardcoded label is what quietly puts the mix back. Run by ops/tools/run_gate.py.

Rules:
  A  every dict key carries BOTH languages, non-empty (a missing side would
     silently fall back and reintroduce the mix)
  B  no German prose literal (umlaut/ß) anywhere in surfaces/app/src outside the dicts -
     that is leftover text the language switch cannot reach
  C  the daemon's owner-facing calls (_say_card, _say, push_fcm titles) must go
     through i18n.t(), never a literal
  D  JSX text nodes with real prose must be wrapped in a translator call

The AUDIT trail is deliberately exempt: events.emit, ActionLog technical lines,
gate output and git messages stay English everywhere (see daemon/i18n.py).
"""
import os
import re
import sys

# This tool prints the very strings it is hunting, so it must not die on the
# Windows console's cp1252 - the umlauts ARE the payload.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "app", "src")
DICT_DIR = os.path.join(APP, "i18n", "dict")
DAEMON = os.path.join(ROOT, "daemon")

problems = []

# Files whose German is data/evidence, not UI copy.
SKIP_APP = ("i18n" + os.sep, "node_modules")
# Daemon prose that is a fixed protocol string or quotes a tool, not owner copy.
ALLOW_DAEMON_LITERAL = ("i18n.t(", "_i18n.t(", "t(\"", "t('")


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def walk(base, exts):
    for dirpath, dirnames, files in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "node_modules"]
        for f in files:
            if f.endswith(exts):
                yield os.path.join(dirpath, f)


BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def code_lines(src):
    """The file with COMMENTS BLANKED, line numbers preserved.

    Comments explain the German they mention ("only offer \"Datei\" here"), so
    scanning them reports a bug that does not exist - and a linter that cries
    wolf is one people switch off. Newlines are kept so a finding still points
    at the right line."""
    src = BLOCK_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return [ln.split("//")[0] for ln in src.splitlines()]


# -- A: both languages present, non-empty ------------------------------------
ENTRY = re.compile(r'"([\w.]+)"\s*:\s*\{\s*de:\s*("(?:[^"\\]|\\.)*"|`[^`]*`)\s*,\s*'
                   r'en:\s*("(?:[^"\\]|\\.)*"|`[^`]*`)\s*,?\s*\}', re.S)
keys = {}
if os.path.isdir(DICT_DIR):
    for path in sorted(walk(DICT_DIR, (".ts",))):
        src = open(path, encoding="utf-8").read()
        found = ENTRY.findall(src)
        for key, de, en in found:
            if key in keys:
                problems.append("A duplicate key %r (also in %s)" % (key, keys[key]))
            keys[key] = rel(path)
            if len(de.strip("\"`").strip()) == 0:
                problems.append("A %s: key %r has an empty German string" % (rel(path), key))
            if len(en.strip("\"`").strip()) == 0:
                problems.append("A %s: key %r has an empty English string" % (rel(path), key))
        # a dict entry the regex could not parse is a silent hole
        declared = len(re.findall(r'^\s{2}"[\w.]+"\s*:', src, re.M))
        if declared != len(found):
            problems.append("A %s: %d entries declared but %d parsed as {de,en} - "
                            "one is malformed or missing a language"
                            % (rel(path), declared, len(found)))

# -- B: no German prose left outside the dicts -------------------------------
# Umlauts alone are NOT enough - "Relay nicht erreichbar", "Fehler 500" and
# "Kein Code eingegeben" have none, and those all slipped through the first
# version of this rule. Match umlauts OR a German function word, which English
# UI copy does not contain.
#
# Still not airtight, and it cannot be: "Konto erstellen", "Benutzername",
# "Anmeldung fehlgeschlagen" carry neither. ui/login_screen.tsx was hardcoded
# German end to end and this rule saw NONE of it (rule D caught one JSX node).
# So a finding here means READ THE FILE - the flagged line is a symptom, and
# fixing only it ships "Create account" next to "Anmelden", the exact mix this
# tool exists to prevent.
GERMAN_WORDS = (r"\b(nicht|kein[e]?[nmrs]?|und|oder|der|die|das|des|dem|den|ein[e]?[nmrs]?|"
                r"ist|sind|wird|werden|wurde|hat|haben|sich|noch|schon|nur|auch|"
                r"mit|ohne|f[uü]r|von|vom|zum|zur|beim|im|am|auf|aus|bei|"
                r"Fehler|Karte[n]?|Aufgabe[n]?|Anhang|Anh[aä]nge|Datei[en]?|"
                r"Einstellungen|Sprache|Abbrechen|Speichern|L[oö]schen)\b")
GERMAN = re.compile(r'["\'`]([^"\'`\n]*(?:[äöüÄÖÜß]|' + GERMAN_WORDS + r')[^"\'`\n]*)["\'`]')
for path in sorted(walk(APP, (".ts", ".tsx"))):
    r = rel(path)
    if any(s in path for s in SKIP_APP):
        continue
    for i, code in enumerate(code_lines(open(path, encoding="utf-8").read()), 1):
        # NOTE the marker is matched against the COMMENT-STRIPPED line, so an
        # `// i18n-exempt` (or a JSX `{/* i18n-exempt */}`) is already gone by
        # the time we look - it exempts nothing, silently. It only works inside
        # real code. Prefer restructuring: a genuine non-copy string hoisted to
        # a named constant stops being a JSX text node and says WHY in the name
        # (surfaces/app/src/app/kernel-demo.tsx's NO_SURFACE_DIAGNOSTIC).
        if "eslint" in code or "i18n-exempt" in code:
            continue
        for m in GERMAN.finditer(code):
            problems.append("B %s:%d untranslated German literal: %r"
                            % (r, i, m.group(1)[:60]))

# -- C: the daemon must not speak to the owner in a literal ------------------
SAY = re.compile(r'(?:_say_card\(\s*\w+\s*,|_say\(|push_fcm\()\s*("(?:[^"\\]|\\.)*")')
for path in sorted(walk(DAEMON, (".py",))):
    if os.path.basename(path) == "i18n.py":
        continue
    r = rel(path)
    for i, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        m = SAY.search(line)
        if m and not any(a in line for a in ALLOW_DAEMON_LITERAL):
            problems.append("C %s:%d owner-facing literal, use i18n.t(): %r"
                            % (r, i, m.group(1)[:60]))

# -- D: JSX prose must be translated -----------------------------------------
# >Two or more words< that are not an expression and not punctuation-only.
JSX_TEXT = re.compile(r">\s*([A-Za-zÄÖÜäöü][^<>{}\n]{3,}?)\s*<")
# A TypeScript generic reads like JSX text to the regex above
# (`=> void | Promise<void>`, `as Promise<Turn[]>`), so anchor on the tokens
# that only ever appear in a type position. Without this the lint cries wolf on
# every typed callback and people learn to ignore it.
TYPE_POS = re.compile(r"(=>|:\s*$|\bas\b|\binterface\b|\btype\b|\bextends\b|"
                      r"\bPromise\b|\bRecord\b|\bArray\b|useQuery<|useState<|useMutation<)")
for path in sorted(walk(APP, (".tsx",))):
    r = rel(path)
    if any(s in path for s in SKIP_APP):
        continue
    for i, line in enumerate(code_lines(open(path, encoding="utf-8").read()), 1):
        if "i18n-exempt" in line or TYPE_POS.search(line):
            continue
        for m in JSX_TEXT.finditer(line):
            txt = m.group(1).strip()
            if len(txt.split()) < 2 or not re.search(r"[A-Za-zÄÖÜäöü]{3}", txt):
                continue
            problems.append("D %s:%d untranslated JSX text: %r" % (r, i, txt[:60]))

print("i18n lint: %d keys in %d dict files"
      % (len(keys), len({v for v in keys.values()})))
if problems:
    by_rule = {}
    for p in problems:
        by_rule.setdefault(p[0], []).append(p)
    for rule in sorted(by_rule):
        print("\n--- rule %s (%d) ---" % (rule, len(by_rule[rule])))
        for p in by_rule[rule][:25]:
            print("  " + p[2:])
        if len(by_rule[rule]) > 25:
            print("  ... and %d more" % (len(by_rule[rule]) - 25))
    print("\ni18n lint FAILED (%d)" % len(problems))
    sys.exit(1)
print("i18n lint: one language, no leftovers - PASS")
