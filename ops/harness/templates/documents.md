---
id: documents
label: Dokumente & Inhalte
who: Texte, Angebote, Freigaben. Kein Build, leichte Review.
summary: Kein Deploy · Gate läuft leer · Entwürfe allein, Senden nicht · Abnahme bleibt Pflicht
stations: backlog, working, gate, review
card_kind: new_direct_task
deploy_hook: ""
settings.policy.auto_accept_green: false
settings.policy.auto_dispatch_modes: ["do", "prepare"]
note.gate: Läuft leer - hier gibt es nichts zu kompilieren, der Gate meldet PASS.
---

Fuer Repos, in denen geschrieben statt gebaut wird: Angebote, Vertraege,
Dokumentation, Freigabe-Unterlagen.

**Keine Deploy-Station.** Es gibt nichts auszuliefern, also faellt der Schritt
weg - ein leerer `repo_hooks.<repo>.deploy` heisst schlicht, dass er nicht
passiert (`lanemachine.py:648`).

**Direkt im Ordner statt im Worktree - angemeldet, noch nicht automatisch.**
`card_kind: new_direct_task` steht als Repo-Default in dieser Vorlage, aber
gelesen wird er noch von niemandem: ob eine Karte einen Worktree bekommt,
entscheidet bis heute die Karte, nicht das Repo. Deshalb verspricht die Vorlage
es hier NICHT - sag es weiter pro Karte, bis die Schuld
`repo-template-card-kind-unwired` bezahlt ist.

**Das Gate bleibt an - und das ist kein Versehen.** Es laesst sich nicht
abschalten (Harness-Gesetz), aber es findet in einem Text-Repo nichts zu
kompilieren und meldet `"gate: nothing to run on this branch - PASS"`
(`run_gate.py:68-70`). Die Karte beschriftet die Station deshalb als *"laeuft
leer"*, statt so zu tun, als waere sie aus. Der Unterschied zwischen einer
ehrlichen Anzeige und einem Gesetzesbruch.

**Entwuerfe darf der Agent allein anfangen, senden nicht.**
`policy.auto_dispatch_modes` steht auf `do` und `prepare`: vorbereiten ja, der
Schritt mit Aussenwirkung wartet auf dich. Deine Abnahme bleibt Pflicht.
