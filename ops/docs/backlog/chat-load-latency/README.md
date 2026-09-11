# Chat-Load-Latency — Karten-Chat & Henry laden träge (Spinner/Leer-Zustand)

**Anlass (Owner-Report + Code-Trace, 2026-09-11):** Karten-Chat zeigt beim
Öffnen lange Spinner, dann "Noch keine Nachrichten." obwohl Nachrichten
existieren; Henry-Chat ebenso träge. Screenshot: Karte D Token-Burn-Hardening,
mid-turn. Vier verifizierte Ursachen (Quellcode geprüft, eine Fehlhypothese
bereits aussortiert — es gibt KEINEN /me→/chat/history-Waterfall,
`enabled: me?.role !== "client"` ist bei undefined true):

1. **Doppelter Voll-Transkript-Fetch beim Karten-Öffnen** — `card/[id].tsx:642`
   (useQuery `api.transcript`) UND der erste Live-Loop-Call mit `have=0`
   (Zeile 658) liefern BEIDE das volle Transkript (100–227 KB laut
   routes_tracks.py:124), NaCl-versiegelt über den Relay, bevor irgendetwas
   rendert.
2. **`relayReq` hat KEINEN Client-Timeout** (`client.ts:49-75`, bare fetch) —
   ein hängender Request hält den Spinner bis zum Relay-504 nach 120s
   (REPLY_TIMEOUT), statt 8s/30s wie im Direct-Mode-Ladder (client.ts:126-128).
3. **`timeline_store.read` parst die GESAMTE timeline.jsonl pro Request**
   (`spine/agent/timeline_store.py:64-95`, Fold über alle Zeilen, `[-limit:]`
   erst NACH dem Parse). Reale Karten: 1.2–2.4 MB. Schlimmster Fall = genau
   der Screenshot-Fall: laufender Turn schreibt permanent, jeder
   0.35s-Change-Tick des /transcript/live-Long-Polls löst den Voll-Parse aus.
4. **Leer-Zustand lügt während des Ladens** — `card/[id].tsx:525` rendert
   "Noch keine Nachrichten." solange der Transkript-Fetch noch in flight ist.

Verstärker (out of scope, separat getrackt): Relay läuft seit 2026-09-08 auf
dem Owner-PC via Cloudflare-Tunnel (Memory helmdeck-relay-local-fallback) —
jede Runde zahlt Edge→Tunnel→relay.py→Loopback + Seal/Open; Oracle-Migration
ist ein eigener Track. Stream-Reconnect-Backoff nur anfassen, wenn Phase 0
dort Churn zeigt.

---

## Phase 0 — Messen (½h, VOR jedem Fix)

Je einmal timen: `/tracks`, `/tracks/:id/transcript` (die 2.4-MB-Karte),
`/chat/history` — direkt gegen `127.0.0.1:8140` UND durch
`relay.helmdeck.de`. Trennt Tunnel-Tax von Daemon-Compute mit Zahlen; wenn
der Tunnel dominiert, wird Phase B deferred (nicht gestrichen), Zahlen in den
Card-Log.

## Phase A — App (JS-only, OTA-fähig, daemon-versionsunabhängig)

1. **Laden ≠ Leer:** `card/[id].tsx:525` — Spinner/Skeleton solange die
   Transkript-Query `isPending`; "Noch keine Nachrichten." erst nach settled
   empty. Reine UI, kein Protokoll.
2. **Delta-Resume statt Doppel-Fetch:** die separate Voll-useQuery
   (`api.transcript`, Zeile 642) entfällt; der Live-Loop wird der einzige
   Loader und seedet `have` aus der Länge des persistierten React-Query-Caches
   (AsyncStorage, PERSIST_STEPS_PER_CARD=200). Erster Paint sofort aus dem
   Cache, Netz holt nur den Tail (base-aware Merge existiert schon,
   Zeile 663-666). Kalter Cache → have=0 → EIN Voll-Fetch (heutiges Verhalten
   minus Duplikat). `/transcript/live?have=N` kann das serverseitig bereits.
3. **relayReq bounden, PER PATH:** AbortController analog zum
   Direct-Mode-Ladder (client.ts:126-128): Long-Polls **35s** (> 22s
   Daemon-Hold + Tunnel-Marge), normale Requests **20s**, `POST /chat`
   **KEIN Client-Abort** — dort bleibt der Relay-REPLY_TIMEOUT 120s die
   Grenze, weil ein Client-Abort den Send un-ackt und den
   chat_dedupe-Replay-Pfad triggert (Duplikat-Bug, schon einmal bezahlt).
   Distinkte TransportError-Meldungen beibehalten.

## Phase B — Daemon (braucht Restart → nur bei idle, Restart killt Live-Turns)

4. **Inkrementeller Fold-Cache in `timeline_store.read`:** In-Memory-Cache
   `{byte_offset, folded, order}` pro run_dir-Pfad, Lock-guarded. Pro Read:
   stat; Größe gewachsen → nur angehängte Bytes parsen und einfalten; Größe
   geschrumpft (Truncation/Recreate) → Rebuild von 0. EXAKT dieselbe
   Fold-Semantik (spätere Zeilen patchen frühere _ids, First-Seen-Ordnung),
   O(delta) pro Live-Tick statt O(Gesamthistorie). Gesetzeskonform (derived
   from the runtime's own signal, folded at event time, one owner) — KEIN
   Debt-Eintrag nötig. Memory-Bound: Cache hält gefoldete Transkripte pro
   aktivem Run — im Commit-Text einen Satz dazu.

**NICHT machen (Round-1-Fehlanalysen, verifiziert falsch):** blanket
relayReq-Timeout (killt /chat-Turns → Replay-Duplikate); Byte-Tail-Read der
timeline.jsonl (bricht Fold-Semantik: verliert frühe Felder gepatchter Steps
+ First-Seen-Ordnung — Monkey-Patch); /me→/chat/history "Waterfall" fixen
(existiert nicht).

## Verify (adversarial, pro Feature)

- 2.4-MB-Karte kalt über Relay öffnen, MID-TURN (der Screenshot-Fall):
  Sub-Sekunden-First-Paint aus Cache + Tail-Merge sichtbar.
- Daemon mid-request killen: Spinner löst sich in ≤35s in distinkte
  Fehlermeldung auf, nicht 120s.
- `POST /chat` übersteht einen 3-Minuten-Turn un-aborted (kein Duplikat im
  copilot_log).
- Cache-geseedete Öffnung: alte Steps sofort, Tail merged korrekt (base>0-Pfad).
- Timeline-Cache: Truncation-Fall (run_dir recreate) rebuildet sauber;
  laufender Turn streamt weiter live.
- `py -3.12 ops/tools/run_gate.py` + App-tsc; UI-Zustände screenshotten und
  JUDGEN (Laden vs. Leer vs. Fehler), nicht nur rendern.

## Ship

Phase A = OTA (`bash ops/deploy/push_update.sh`) als Henry-Ship-Decision,
nie automatisch (d66084f). Phase B landet mit Daemon-Restart in einem
Idle-Moment. A und B sind unabhängig deploybar und einzeln revertierbar.

## Traps

- Timeout-Ladder ist GEMESSEN, Ordnung halten: 22s Daemon-Hold < 35s Client
  < 115s _local < 120s REPLY_TIMEOUT (server.py:279, routes_tracks.py:100).
- Worktree-tsc via `C:\hd\app` node_modules-Junction (Memory
  helmdeck-app-verify-recipe); Junction mit `rmdir` lösen, nie `rm -r`.
- Demo-Seam: der Live-Loop-Spin-Guard (1500ms Pause bei unverändertem v,
  card/[id].tsx:670-677) darf den Delta-Resume-Umbau überleben — ohne ihn
  fror die Demo jeden Card-Screen ein.
