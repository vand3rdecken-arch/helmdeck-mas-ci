---
id: documents
label: Dokumente & Inhalte
who: Texte, Angebote, Freigaben. Kein Build, leichte Review.
stations: backlog, working, gate, review
card_kind: new_direct_task
deploy_hook: ""
settings.policy.auto_accept_green: false
settings.policy.auto_dispatch_modes: ["do", "prepare"]
note.gate: Laeuft leer - in einem Text-Repo gibt es nichts zu kompilieren, der Gate meldet PASS.
note.working: Direkt im Ordner, ohne Worktree.
---

Fuer Repos, in denen geschrieben statt gebaut wird: Angebote, Vertraege,
Dokumentation, Freigabe-Unterlagen.

**Keine Deploy-Station.** Es gibt nichts auszuliefern, also faellt der Schritt
weg - ein leerer `repo_hooks.<repo>.deploy` heisst schlicht, dass er nicht
passiert (`lanemachine.py:648`).

**Direkt im Ordner statt im Worktree.** Ein Worktree pro Karte kostet hier nur
Umweg: es gibt keinen Merge-Konflikt zwischen zwei Angeboten, und der Owner will
die Datei da sehen, wo sie hingehoert.

**Das Gate bleibt an - und das ist kein Versehen.** Es laesst sich nicht
abschalten (Harness-Gesetz), aber es findet in einem Text-Repo nichts zu
kompilieren und meldet `"gate: nothing to run on this branch - PASS"`
(`run_gate.py:68-70`). Die Karte beschriftet die Station deshalb als *"laeuft
leer"*, statt so zu tun, als waere sie aus. Der Unterschied zwischen einer
ehrlichen Anzeige und einem Gesetzesbruch.

**Entwuerfe darf der Agent allein anfangen, senden nicht.**
`policy.auto_dispatch_modes` steht auf `do` und `prepare`: vorbereiten ja, der
Schritt mit Aussenwirkung wartet auf dich. Deine Abnahme bleibt Pflicht.
