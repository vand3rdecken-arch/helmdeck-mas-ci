---
id: documents
label: Dokumente & Inhalte
who: Texte, Angebote, Freigaben. Kein Build, leichte Review.
summary: Kein Deploy · Gate läuft leer · Entwürfe allein, Senden nicht · Abnahme bleibt Pflicht
stations: backlog, working, gate, review
card_kind: new_direct_task
deploy_hook: ""
gate_cmd: ""
settings.policy.auto_accept_green: false
settings.policy.auto_dispatch_modes: ["do", "prepare"]
note.gate: Läuft leer - dieses Repo deklariert keinen Gate-Befehl, es wird nichts geprüft.
---

Fuer Repos, in denen geschrieben statt gebaut wird: Angebote, Vertraege,
Dokumentation, Freigabe-Unterlagen.

**Keine Deploy-Station.** Es gibt nichts auszuliefern, also faellt der Schritt
weg - ein leerer `repo_hooks.<repo>.deploy` heisst schlicht, dass er nicht
passiert (`lanemachine.py:648`).

**Direkt im Ordner statt im Worktree.** `card_kind: new_direct_task` ist der
Repo-Default dieser Vorlage, und er wird jetzt auch gelesen: eine Karte, die
fuer dieses Repo entsteht, ohne dass jemand die Art ausdruecklich waehlt,
arbeitet im echten Ordner statt in einer Kopie (`dispatch.new_track`).
Voraussetzung ist, dass `policy.machine.enabled` an ist und der Ordner in der
erlaubten Wurzel liegt - sonst faellt die Karte hoerbar auf den Worktree
zurueck, statt still etwas anderes zu tun, als die Vorlage verspricht.

**Das Gate bleibt an - und das ist kein Versehen.** Es laesst sich nicht
abschalten (Harness-Gesetz), aber in einem Text-Repo gibt es keinen
Code-Check: `gate_cmd` ist hier bewusst leer. Die Station laeuft, schreibt
ausdruecklich *"dieses Repo deklariert keinen Gate-Befehl - es wurde NICHTS
geprueft"* auf die Karten-Timeline und laesst die Karte durch. Die Karte
beschriftet die Station deshalb als *"laeuft leer"*, statt so zu tun, als waere
sie aus - und statt so zu tun, als haette sie etwas geprueft. Der Unterschied
zwischen einer ehrlichen Anzeige und einem Gesetzesbruch.

**Entwuerfe darf der Agent allein anfangen, senden nicht.**
`policy.auto_dispatch_modes` steht auf `do` und `prepare`: vorbereiten ja, der
Schritt mit Aussenwirkung wartet auf dich. Deine Abnahme bleibt Pflicht.
