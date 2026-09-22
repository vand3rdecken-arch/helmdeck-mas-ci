# -*- coding: utf-8 -*-
"""Seed the "Einrichtung" process template.

Owner 2026-09-22: "auch bei setup soll das zu Henry. Als Prozess, setup von
agents, harness, import, suchen von Gedaechtnis etc."

THERE IS A HARD ORDERING CONSTRAINT AND IT DECIDES THE SHAPE. A HelmDeck
process is dispatched by the daemon; at first run the daemon is exactly what
does not exist yet - setup.js says so in its own source ("at first run the
daemon is exactly what does not exist: no Python, no dependencies, no owner
token"). So the bootstrap CANNOT be a process, and pretending otherwise would
produce a wizard that cannot run itself.

The line therefore falls here:
  * Phase 0, in setup.js, stays hard-coded: Python, Claude Code, a live
    daemon, an owner account. The minimum that makes a process possible.
  * Everything after is a PROCESS, because everything after is judgement:
    which harnesses are on this machine, which memories are worth taking,
    what the repo should be configured as.

That is not a compromise, it is the same chicken-and-egg the control plane
already documents - now stated once, in the place that acts on it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

STEPS = [
    {"title": "Vorhandene Agenten-Harnesse auf diesem Rechner finden",
     "desc": "Sieh nach, welche Coding-Assistenten hier schon benutzt werden "
             "(Claude Code, Cursor, Codex, Windsurf, Cline, Gemini). Die "
             "bekannten Orte pruefen die Adapter in Sekunden; fuer alles "
             "andere den Agentenlauf anstossen (POST /memory/foreign/scan). "
             "Melde, was gefunden wurde UND welche Werkzeuge gesucht und "
             "nicht gefunden wurden - eine leere Liste ohne Namen ist keine "
             "Antwort.",
     "mode": "do", "days": 1},
    {"title": "Gedaechtnis uebernehmen, nichts ueberschreiben",
     "desc": "Aus den gefundenen Quellen die uebernehmen, die dem Owner "
             "nuetzen. Vorschlagen, nicht entscheiden: Projekte, an denen er "
             "gerade arbeitet, zuerst. Der Import ueberschreibt nie - "
             "Namenskollisionen kommen als uebersprungen zurueck und gehoeren "
             "in den Bericht, weil genau die sonst wochenspaeter als "
             "'fehlt doch' auffallen.",
     "mode": "prepare", "days": 1},
    {"title": "Harness einstellen: Briefs, Regeln, Modelle",
     "desc": "Die Agenten-Briefs und Policy-Schichten auf den Owner "
             "zuschneiden. Was aus einem fremden Werkzeug uebernommen wurde "
             "(CLAUDE.md, .cursorrules, Skills) ist ein Vorschlag, keine "
             "Vorgabe - lies es und sag ihm, was du daraus uebernehmen "
             "wuerdest und was nicht hierher passt.",
     "mode": "cowork", "days": 1},
    {"title": "Erstes Repo anschliessen und einmal durch die Strecke fahren",
     "desc": "Ein Repository verbinden, Vorlage setzen, und EINE kleine Karte "
             "wirklich laufen lassen, bis sie durch Gate und Abnahme ist. "
             "Eine Einrichtung, die nie eine Karte gefahren hat, ist nicht "
             "geprueft, sondern nur konfiguriert.",
     "mode": "do", "days": 1},
    {"title": "Sicherung einrichten und den Stand belegen",
     "desc": "Ein Archiv erstellen (Einstellungen > System > Umzug) und "
             "pruefen lassen, damit von Anfang an eine Kopie existiert. Dann "
             "dem Owner in einem Satz sagen, was jetzt laeuft, was im Archiv "
             "liegt und was er von Hand mitnehmen muss - der "
             "Signierschluessel zuerst.",
     "mode": "do", "days": 1},
]


def main():
    from cells.engineer.chains import processes
    existing = processes.list_templates() or {}
    tid = "einrichtung"
    doc = processes.save_template(
        name="Einrichtung",
        description="Von der frischen Installation zum arbeitenden HelmDeck: "
                    "vorhandene Harnesse finden, Gedaechtnis uebernehmen, "
                    "Harness einstellen, erstes Repo fahren, sichern. Der "
                    "Bootstrap davor (Python, Claude Code, Daemon, Owner) "
                    "gehoert in die Ersteinrichtung - ein Prozess braucht "
                    "einen Daemon, der ihn ausfuehrt.",
        steps=STEPS, tid=tid, actor="owner")
    print("Template %s: %s (%d Schritte)%s"
          % (doc["id"], doc["name"], len(doc["steps"]),
             " [ersetzt]" if tid in existing else " [neu]"))
    for s in doc["steps"]:
        print("  - [%s] %s" % (s["mode"], s["title"]))


if __name__ == "__main__":
    main()
