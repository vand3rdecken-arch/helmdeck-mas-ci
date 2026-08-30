# -*- coding: utf-8 -*-
"""REPO TEMPLATES - "which kind of repo is this", as data.

The owner's complaint that started this: *"Settings zu komplex, muss idiot-proof
sein."* The answer of the decree is **sehen statt konfigurieren** - when a repo is
onboarded you choose a TYPE, not twenty switches, and the pipeline picture then
shows you what that type actually does.

A template is a file in `ops/harness/templates/<id>.md`, exactly the shape the
agent briefs already use (YAML frontmatter + prose), loaded through the same
primitive: re-read on change, and on ANY failure fall back to the built-in.
`spine/auth/charter.py:21` sanctions the whole idea in as many words, under MAY
BE BUILT: *"TEMPLATES: views chosen from the reviewed catalog, driven by declared
data."*

THE ONE LAW, INHERITED: a broken file may never break a card.
Every public function here is total. A mangled template costs the customisation,
never the spawn - and the failure is not swallowed either, it lands in
harness.errors() which /loop/map already renders.

WHAT A TEMPLATE MAY AND MAY NOT SAY
-----------------------------------
May: which stations are ACTIVE (display), the deploy hook (real, per repo), the
default card kind, and a few global `policy.*` starting values.

May not, and this is the part that took the research to establish:
  * It may not switch off a station that is LAW. Four of the five stations are
    fixed or the entrance (PRD §4.3.1); only `deploy` is genuinely switchable,
    because an empty `repo_hooks.<repo>.deploy` simply means the step does not
    happen (lanemachine.py:648). A template offering five switches would be a
    lie that surfaced months later.
  * It may not set the level-B governance flags (`worktreeIsolation`,
    `gateBeforeReview`, `sod_accept`). ARCHITECTURE.md:160-162 records that
    nothing reads them yet, so a template setting them would report success and
    change nothing. Finger weg - PRD §6.5.
  * It does not set `capacity.wip_limit`. That is a property of the MACHINE
    (how much load this PC takes), not of the repo type - PRD §9 A, resolved
    the way the PRD's own author leaned: out of the template, into the dial.

FRONTMATTER IS FLAT, ON PURPOSE
-------------------------------
PyYAML is used when importable, but the loader must work on a box where it was
never installed - there the mini parser handles a flat `key: value` subset only.
So nesting is expressed by DOTTED KEYS (`settings.policy.auto_accept_green`) and
list/object values are written as JSON, which _coerce() decodes on both paths.
That way the same file parses identically with and without PyYAML, instead of
degrading into a subtly different template on a machine nobody tested.
"""
import json
import os

from spine.registry import harness

DIR = os.path.join(harness.HARNESS, "templates")

# ---------------------------------------------------------------------------
# BUILT-IN DEFAULTS - the floor. If ops/harness/templates/ is deleted, mangled or
# shipped without, the owner still gets both repo types (PRD §3.1 / §3.2), and
# every value below is one that was verified to EXIST in the code.
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "software-dev": {
        "id": "software-dev",
        "label": "Software-Entwicklung",
        "who": "Code-Repos. Alles laeuft, nichts landet ungeprueft.",
        "stations": ["backlog", "working", "gate", "review", "deploy"],
        "card_kind": "new_track",
        "deploy_hook": "",
        "settings": {"policy.auto_accept_green": False,
                     "policy.auto_dispatch_modes": ["do"]},
        "notes": {},
        "body": ("Isolierter Worktree je Karte, Gate vor der Review, deine Abnahme "
                 "merged nach main und faehrt den Deploy-Hook."),
    },
    "documents": {
        "id": "documents",
        "label": "Dokumente & Inhalte",
        "who": "Texte, Angebote, Freigaben. Kein Build, leichte Review.",
        # no `deploy`: nothing to ship. The gate stays in the list because it is
        # law - in a text repo it finds nothing to compile and reports PASS
        # (run_gate.py:68-70), which the map labels honestly instead of hiding.
        "stations": ["backlog", "working", "gate", "review"],
        "card_kind": "new_direct_task",
        "deploy_hook": "",
        "settings": {"policy.auto_accept_green": False,
                     "policy.auto_dispatch_modes": ["do", "prepare"]},
        "notes": {"gate": "Laeuft leer - in einem Text-Repo gibt es nichts zu "
                          "kompilieren, der Gate meldet PASS.",
                  "working": "Direkt im Ordner, ohne Worktree."},
        "body": ("Direkt im Ordner statt im Worktree, kein Deploy. Das Gate laeuft "
                 "leer durch - deine Abnahme bleibt Pflicht."),
    },
}

# The order the picker offers them in. Built-ins first, files after - a repo type
# the owner added himself should not silently outrank the two shipped ones.
_ORDER = ["software-dev", "documents"]

_SCALARS = ("id", "label", "who", "card_kind", "deploy_hook")


def _coerce(v):
    """Frontmatter values, normalised across BOTH parse paths.

    With PyYAML `["do"]` already arrives as a list; with the mini parser it is
    still the string '["do"]'. Decoding it here is what makes a template file
    mean the same thing on a box that never installed PyYAML - the alternative
    is a template that quietly differs per machine, which is exactly the class
    of bug this whole loader exists to avoid."""
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in ("[", "{"):
            try:
                return json.loads(s)
            except ValueError:
                return v
    return v


def _parse(raw):
    """One template file -> the dict shape resolve()/the picker consume."""
    body, fm = harness.parse_frontmatter(raw)
    fm = {k: _coerce(v) for k, v in (fm or {}).items()}
    out = {k: str(fm.get(k) or "") for k in _SCALARS}
    st = fm.get("stations")
    if isinstance(st, str):
        st = [x.strip() for x in st.split(",")]
    out["stations"] = [x for x in (st or []) if x]
    # settings.<dotted.path>: value -> {"<dotted.path>": value}
    out["settings"] = {k[len("settings."):]: v for k, v in fm.items()
                       if k.startswith("settings.") and len(k) > len("settings.")}
    # note.<station>: text -> what this station MEANS under this template.
    # It exists because of the honest case the research turned up: in a document
    # repo the gate is ON (law) but finds nothing to compile and reports PASS.
    # "Active" and "does something" are not the same claim, and the difference
    # has to be DECLARED by the template rather than guessed from its id.
    out["notes"] = {k[len("note."):]: str(v) for k, v in fm.items()
                    if k.startswith("note.") and len(k) > len("note.")}
    out["body"] = body
    return out


def _file(tid):
    return harness.cached(os.path.join(DIR, "%s.md" % tid), _parse)


def _valid(t):
    """A template must at minimum name itself and one station, or it is not a
    usable choice - and an unusable choice in the picker is worse than the
    built-in it would have replaced."""
    return bool(t) and bool(t.get("label")) and bool(t.get("stations"))


def ids():
    """Every template id on offer: the built-ins plus any extra file. Sorted so
    the picker order is stable rather than filesystem order."""
    out = list(_ORDER)
    try:
        for fn in sorted(os.listdir(DIR)):
            if fn.endswith(".md") and fn[:-3] not in out:
                out.append(fn[:-3])
    except OSError:
        pass
    return out


def get(tid):
    """ONE template, file over built-in, built-in over nothing. Never raises.

    A file that exists but does not parse into a usable template loses to the
    built-in rather than to nothing: the owner keeps a working repo type and the
    reason lands in harness.errors()."""
    tid = str(tid or "").strip()
    if not tid:
        return None
    path = os.path.join(DIR, "%s.md" % tid)
    got = _file(tid)
    if _valid(got):
        got = dict(got)
        got["id"] = got.get("id") or tid
        got["source"] = "ops/harness/templates/%s.md" % tid
        harness.clear_error(path)
        return got
    # The file read and parsed but is not a usable template (no label, no
    # stations). Falling back is right; falling back QUIETLY is not - the owner
    # would edit a file, see no change, and have nothing to look at.
    if got is not None and os.path.exists(path):
        harness.note_error(path, "unbrauchbare Vorlage (label/stations fehlen) - "
                                 "es gilt der Built-in")
    base = _DEFAULTS.get(tid)
    if base:
        base = dict(base)
        base["source"] = "built-in default (spine/registry/templates.py)"
        return base
    return None


def catalog():
    """The picker's payload: every template, resolved. Total by construction -
    an id that resolves to nothing is dropped rather than rendered as a blank
    card the owner could select and get no repo type from."""
    return [t for t in (get(i) for i in ids()) if t]


if __name__ == "__main__":
    print(json.dumps(catalog(), indent=2, ensure_ascii=False))
