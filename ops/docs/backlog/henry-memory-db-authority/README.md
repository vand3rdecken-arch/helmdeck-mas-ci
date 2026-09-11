# Henry-Memory: DB wird authoritative, Dateien werden Wegwerf-Cache

Owner-Review (2026-09-11): Henrys Memory ist **Governance-Config, kein
Laufzeit-Müll** — jede Notiz wird per Digest in jeden Turn injiziert und
formt sein Verhalten wie der Brief. Trotzdem ist heute das git-ignorierte,
maschinenlokale Verzeichnis `daemon/content/henry_memory/` die Autorität
und die DB nur ein Spiegel. Das ist die falsche Richtung.

## Befund (verifiziert im Code)

1. **Autorität invertiert.** `_fold_memory_to_db()`
   (`cells/copilot/chat/copilot.py:975-1006`) spiegelt dir → db und
   **löscht jede DB-Zeile ohne Datei** (Z. 1002-1004). Restore von
   `helmdeck.db` auf eine Maschine mit leerem Verzeichnis ⇒ der erste
   Save-Turn wischt das komplette Memory. Config, deren dauerhafte Kopie
   ein ignorierter Ordner neben Logfiles ist, hat keine Backup-Story.
2. **Kein Auth, kein Audit — Injection-Vektor.** Der Fold ingestiert
   alles auf der Platte und stempelt `actor="henry"`, egal wer schrieb.
   Jeder Prozess mit Disk-Zugriff (Card-Worker, prompt-injizierter Turn)
   kann eine Datei droppen, die ab dann in JEDEM Henry-Turn als stehende
   Instruktion mitfährt. Memory-Mutationen erzeugen zudem KEIN Event —
   verhaltensändernde Config am append-only-Audit vorbei.
3. **Token-Verschwendung.** Der Digest (`_memory_digest`, copilot.py:828)
   wird in JEDEN Turn injiziert — auch in `--resume`te Sessions, deren
   Transkript den Inhalt längst enthält. Nötig ist er nur bei
   Session-Etablierung (frischer Spawn, Rotation, Post-Compaction — die
   `session_chain`-Maschinerie aus e8ce14f weiß exakt wann).
4. **Portabilität.** `helmdeck.db` ist überall sonst die Migrationseinheit;
   Memory ist die Ausnahme, die sie bricht.

Vorbild im eigenen Haus: `policy_doc` (DB-Zeile, ein Owner, `policy.swap()`
unter Lock; die getrackte Datei ist nur Seed). Memory bekam das Dekret
("muss exportierbar sein"), aber nie die Disziplin.

## Ziel-Design (Plan v4, gescort 34/35 im Review)

**DB ist Autorität. Dateien sind abgeleiteter Read-Cache. Schreiben geht
über Henrys eigenen Turn-Output, nicht über die Platte.**

- **Schreiben = Sentinel-Protokoll.** Der Save-Turn emittiert gefencte
  `<memory-save name="...">…</memory-save>` / `<memory-delete name="..."/>`
  Blöcke am Turn-Ende; `copilot.py` parst STRIKT (Längen-Cap, bei
  Malformed: reject + Event, nie raten), ruft `db.memory_put/delete`,
  emittiert **ein Event pro Mutation**. Provenienz ist strukturell: Memory
  existiert nur, wenn Henrys authentifizierter Turn es gesagt hat.
  Präzedenz: das ASK-Sentinel-Protokoll (headless claude hat kein
  AskUserQuestion).
- **Injektion nur bei Session-Etablierung.** Digest geht in den ersten
  Prompt einer frischen/rotierten/kompaktierten Session — resumede Turns
  bekommen NICHTS (das Transkript hat es schon). Token-Delta über den
  Stats-Fold messen.
- **Dateien = Wegwerf-Cache.** Bei Session-Etablierung (lazy, nur wenn
  ohnehin ein Digest injiziert wird) wird `henry_memory/` aus der DB
  **geclobbert** neu geschrieben, damit Henry Read-on-demand behält.
  Nie zurückgefoldet, nie vertraut — eine gepflanzte Datei überlebt
  höchstens bis zum nächsten Spawn und erreicht die DB nie.
  (`policy_seed.json`-Verhältnis; Git-Checkout-Shape.)
- **Owner-Schreibpfad:** authentifizierter Daemon-Endpoint + Settings-UI
  (passt in den 6-Türen-Hub), evented wie jeder Harness-Config-Write.
- **Löschen:** `_fold_memory_to_db()` und die Wipe-Logik entfallen
  ersatzlos (netto-negativer Code).

## Phasen

1. Sentinel-Schreibpfad + Events + Delete-Semantik; Brief
   (`cells/copilot/harness/agents/board-copilot.md`) lehrt Sentinel statt
   "schreibe Dateien". Fold bleibt übergangsweise als Fallback.
2. Session-scoped Digest-Injektion (session_chain/Compaction-Marker als
   Schlüssel); Token-Delta messen.
3. Cache-Regeneration db→dir + Vertrauens-Flip: Fold löschen,
   Boot-Import (`spine/storage/db.py:459`) wird zur einmaligen Migration.
4. Owner-Endpoint + UI-Tür.
5. Debt: neuen Eintrag `henry-memory-file-authority` als `paid` führen;
   `henry-memory-parallel-to-cli-automemory` halb geschlossen (die
   File-Surface trägt nichts mehr).

## Gefahren / Traps

- Sentinel-Parser: gefencte Blöcke, last-in-output, Cap; Malformed ⇒
  Reject-Event, NIE Silent-Drop und NIE Best-Effort-Raten (sonst neuer
  Monkey-Patch).
- Reihenfolge Phase 1 vor 3: erst der neue Schreibpfad, dann den alten
  töten — sonst ein Fenster ohne funktionierendes Speichern.
- Post-Compaction MUSS re-injizieren, sonst vergisst Henry nach /compact
  still (Klasse "Session rotation = vanished chat").
- Tests, die `events.SET` patchen, schreiben die LIVE-DB (zweimal
  gebissen, siehe config-consolidation) — Test-Sandbox prüfen.
