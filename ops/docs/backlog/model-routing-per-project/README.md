# Model-Routing als Projekt-Policy — wann welches Modell, sichtbar und pro Projekt

> **Karten 1+2 SHIPPED 2026-09-04** (direct, ungatet): `routing.auto_model` /
> `routing.escalate_value` / `routing.escalate_urgent` als `scope: "project"`
> Rules in `spine/registry/behavior.py` (neuer Block "routing", `reads` zeigt
> auf `cells/engineer/cards/turnrunner.py::_routing_policy` → `cell_of()`
> attribuiert korrekt an **engineer**, nicht spine). `turnopts.pick_model`/
> `resolve_model` nehmen jetzt einen optionalen `policy`-Parameter
> (`DEFAULT_ROUTING_POLICY` = heutiges Verhalten bei Aufruf ohne Policy).
> `turnrunner._routing_policy(t)` (Karten, `for_card`) und
> `copilot._chat_routing_policy(card)` (Chat, `for_chat`) lösen die drei Rows
> am Event auf. Renderer/Endpoint/i18n sind der bestehende Harness-Layer
> (`behavior.describe()`, `/harness/config`, `harness_rules.tsx`) — keine
> neue UI nötig, die Tür zeigt die Gruppe automatisch. Verifiziert: write→
> project-layer→turnrunner→pick_model→revert end-to-end, `test_turn_model_
> routing` (neuer Fall: Projekt-Override gewinnt, anderes Repo bleibt beim
> Workspace-Default), `test_harness_config_route`/`test_behavior_rules`/
> `run_gate.py` grün. **Karte 3 (visibility-Zusammenfassungszeile) offen.**

Owner-Entscheid (2026-09-04, Chat): "Das ist doch Logik von Henry oder engineer,
nicht auf spine-Ebene. Je nach Projekt und Situation braucht man doch
verschiedene Flows und Modelle." Vorgeschichte: Auto routete faktisch immer
Opus (prio-high/turns/_HARD-Trigger, gefixt fa54463 + 33a2412); seitdem ist
Sonnet 5 der Auto-Default — aber als Code-Konstante, unsichtbar, workspace-weit.

## Zielbild

- **Spine = Mechanismus, unverändert**: Server-Whitelist (`_allowed_ids`),
  Kontextfenster-Gesetz (`fits_window`), "explizite Wahl gewinnt"
  (`resolve_model`). Harte Invarianten, kein Knopf.
- **Routing-Policy = Daten im bestehenden Layer-Chain**
  (`spine/storage/projectconfig.py`: code default → seed → workspace →
  project, später gewinnt, absent = geerbt). Pro Projekt andere Modelle/Flows,
  mit ehrlichem Herkunfts-Badge ("Geerbt vom Workspace" / "Für dieses Projekt
  gesetzt").
- **Cells wenden an**: engineer (`turnrunner`) löst via `for_card(track)` auf,
  Henry (`copilot`) via `for_chat(repo)` — am Event, an je einem Owner, kein
  gespeichertes "current project" (No-Monkey-Patch).
- **Judgement → Henry**: die messbaren Situations-Schalter (gate-fail, urgent,
  Wert, Attachment) bleiben deterministisch; Henry darf die Policy per
  `configure` PRO PROJEKT umstellen (auditierter `projectconfig.write()`),
  entscheidet aber nie pro Turn per LLM-Urteil das Modell.

## Policy-Shape (Defaults = heutiges Verhalten nach 33a2412)

```
model_routing:
  auto_default:          claude-sonnet-5   # Alltagsmodell für Karten auf Auto
  strong:                claude-opus-5     # Eskalationsstufe
  cheap:                 claude-haiku-4-5  # nur Chatter (_EASY)
  escalate_value:        100.0             # ab diesem Kartenwert -> strong
  escalate_on_gate_fail: true              # Retry nach Gate-Fail -> strong
  escalate_urgent:       true
  escalate_attachments:  true
```

## Karten (sequenziell)

1. **policy-plumbing**: Shape als `_config_schema`-Knöpfe mit `project: True`
   deklarieren (Tür 3 Agenten/Autonomie, Gruppe "Modell-Routing";
   `auto_default` basic, Rest advanced). Modell-Selects aus `/models`
   (`turnopts.list_models`), Schreib-Validierung gegen `_allowed_ids` —
   nie eine rohe Client-Id speichern. i18n de/en (`test_harness_layer.py`
   hält Schema/Labels vollständig).
2. **cell-resolution**: `turnrunner` (Karten) und `copilot`-Chat lösen die
   Policy am Event auf (`projectconfig.resolve()` mit `for_card`/`for_chat`)
   und reichen sie an `pick_model`, das von Konstanten auf übergebene Policy
   umstellt (Signatur-Erweiterung, Mechanismus bleibt). `pm.py`-Verify pinnt
   weiter explizit opus. Tests: `test_turn_model_routing` um
   "Projekt-Override gewinnt über Workspace" erweitern.
3. **visibility**: Projekt-/Automatik-Tür zeigt die EFFEKTIVEN Regeln als
   read-only Zeile aus den Live-Werten (analog /loop/map für die fixen
   Gesetze): "Auto → Sonnet 5 · Opus bei: urgent, ≥100 €, Anhang, Gate-Fail ·
   Haiku nur Chatter · Fenster-Check immer". Pro Turn steht das gewählte
   Modell schon im Kartendetail (Technik → Models) — verlinken, nicht
   duplizieren.

## Nicht in Scope / Wachlinien

- Kein LLM-Call im Routing-Pfad (Latenz + Nichtdeterminismus am heißesten
  Pfad).
- Fenster-Gesetz und Whitelist bleiben Code — ein Projekt-Override kann kein
  Modell erzwingen, das die Session nicht halten kann.
- Voice-Pfad (`routes_copilot` pinnt haiku) und Copilot-warm-switch-Keying
  nicht anfassen; nur der Auto-Zweig liest die Policy.
- Generalisierung (fast_track-Default, perm, driver pro Projekt) ist dieselbe
  Bewegung, aber EIGENE Karte — hier nur Modell-Routing.
