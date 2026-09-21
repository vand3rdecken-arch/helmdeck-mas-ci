# Umzug: alter PC → neuer PC

Stand 2026-09-21. Jeder Schritt hier ist auf dieser Maschine gelaufen, nicht
nur aufgeschrieben. Reihenfolge einhalten: Schritt 3 vor Schritt 2 zu machen
ist der einzige Weg, sich hier ernsthaft zu schaden.

---

## Auf dem ALTEN Rechner

### 1. Archiv erstellen

In der App: **Einstellungen → System → Umzug und Sicherung → Archiv erstellen**.
Oder auf der Kommandozeile:

```
py -3.12 ops/tools/takeout.py
py -3.12 ops/tools/takeout.py --with-recordings     # falls du die Sprachaufnahmen willst
```

Es landet unter `daemon/takeout/helmdeck-takeout-<zeitstempel>/` und enthält:

| Teil | Was |
|---|---|
| `db.json` | Gedächtnis, Karten, Chat, Konten, Prozesse, Einstellungen, Ereignisse |
| `auto-memory/` | die Notizen der Befehlszeile **samt ihrer git-Historie** |
| `manifest.json` | Formatversion, Schemaversion, Prüfsumme je Teil, Vollständigkeitsmarker |
| `NOT-INCLUDED.md` | was NICHT drin ist |

Prüfen, bevor du dich darauf verlässt:

```
py -3.12 ops/tools/takeout.py --verify daemon/takeout/<ordner>
```

Muss `vollstaendig` sagen. Sagt es etwas anderes, ist der Lauf abgebrochen -
dann neu erstellen, nicht reparieren.

### 2. Die Geheimnisse von Hand kopieren

Sie sind mit Absicht nicht im Archiv, denn das Archiv liegt herum. Die Liste
steht auch in der App unter dem Knopf und in `NOT-INCLUDED.md`.

- **`daemon/certs/apk-signing/`** - der Android-Signierschlüssel.
  **UNERSETZLICH.** Ohne ihn kann die App im Play Store nie wieder
  aktualisiert werden. Kein Support kann das reparieren.
- `daemon/fcm_service_account.json` - Push. Neu erzeugbar in der
  Firebase-Konsole, aber einfacher mitgenommen.
- `~/.claude.json` - die MCP-Konfiguration. Ohne sie findet Henry
  windows-mcp nicht.
- Apple-Zertifikate und der ASC-Key, falls du iOS baust.
- Relay-Zugangsdaten und der Autostart-Eintrag.

### 3. Das Auto-Memory zusätzlich sichern (empfohlen, dauert Minuten)

Das Verzeichnis `~/.claude/projects/<slug>/memory/` ist ein echtes
git-Repository mit Historie, aber **ohne Gegenstelle**. Es reist zwar im
Archiv mit, aber eine private Gegenstelle ist die bessere Versicherung, weil
sie auch dann hilft, wenn kein Umzug ansteht:

```
git -C "<memory-verzeichnis>" remote add origin <deine-private-url>
git -C "<memory-verzeichnis>" push -u origin HEAD
```

Den Pfad nie raten - er hängt am Hauptrepo, nicht am Arbeitsverzeichnis. Die
App zeigt ihn, und in der Datenbank steht er unter `memory_auto_dir`.

---

## Auf dem NEUEN Rechner

### 4. Grundlage herstellen

```
git clone <repo>
py -3.12 -m daemon.swarm serve     # einmal starten, dann beenden
```

Der erste Start legt die leere Datenbank mit dem aktuellen Schema an. Ohne
diesen Schritt hat der Import kein Ziel.

### 5. Einmal Henry laufen lassen

Ein einziger Turn genügt. Dabei meldet die Befehlszeile ihren eigenen
Gedächtnispfad, und der Daemon merkt ihn sich. **Das ist die Voraussetzung
dafür, dass die Notizen am richtigen Ort landen** - wir konstruieren den Pfad
nicht, wir fragen danach.

### 6. Importieren

```
py -3.12 ops/tools/takeout.py --restore <pfad/zum/archiv>
```

Was dabei passiert, in dieser Reihenfolge:

1. Archiv wird geprüft. Stimmt etwas nicht, bricht es ab und **fasst nichts
   an**. Ein halb eingespieltes Archiv ist schlimmer als keins.
2. Datenbank wird importiert - nur in eine leere. Auf eine bestehende braucht
   es ausdrücklich `--merge`.
3. Auto-Memory wird an den Ort geschrieben, den die Befehlszeile gemeldet hat.
   Liegt dort schon ein Gedächtnis **mit Historie**, wird nichts
   überschrieben: du bekommst den fertigen Befehl, um die Historie bewusst zu
   holen. Zwei Verläufe ohne jemanden, der zwischen ihnen entscheiden darf,
   führen wir nicht zusammen.
4. Am Ende steht, was du von Hand nachziehen musst.

### 7. Nachziehen

Die Geheimnisse aus Schritt 2 an ihre Plätze, Autostart einrichten, Relay
verbinden. Dann Daemon starten und in der App prüfen: Einstellungen → System
zeigt den Daemon als laufend, und das Gedächtnis zählt wieder die erwarteten
Notizen.

---

## Was der Umzug NICHT mitbringt

Gesagt, nicht entdeckt:

- **Laufende Sitzungen.** Die Rohtranskripte der Befehlszeile bleiben zurück
  (rund drei Gigabyte). Henry weiß alles, was in den Notizen steht, aber ein
  Gespräch, das gerade lief, fängt neu an.
- **Sprachmodelle** unter `daemon/content/models_stt`, rund 1,8 GB. Lädt der
  neue Rechner selbst nach.
- **Der Paseo-Ordner**, falls du Paseo nutzt. Eigenes Produkt, eigener Umzug.
- **Geheimnisse**, siehe Schritt 2.

## Der eine Fehler, den man nicht rückgängig machen kann

Den Signierschlüssel vergessen. Alles andere lässt sich neu einrichten,
nachladen oder nachfragen. Dieser nicht.
