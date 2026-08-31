---
id: software-dev
label: Software-Entwicklung
who: Code-Repos. Alles läuft, nichts landet ungeprüft.
summary: Worktree je Karte · Gate vor der Review · Deploy nach deiner Abnahme
stations: backlog, working, gate, review, deploy
card_kind: new_track
deploy_hook: ""
gate_cmd: py -3.12 "%HELMDECK_HOME%/ops/tools/repo_gate.py"
settings.policy.auto_accept_green: false
settings.policy.auto_dispatch_modes: ["do"]
---

Der Normalfall fuer ein Repo, aus dem etwas gebaut wird.

**Alle fuenf Stationen sind aktiv.** Jede Karte bekommt einen isolierten
git-worktree, vor der Review laeuft der Gate, deine Abnahme merged wirklich
nach main und faehrt danach den Deploy-Hook.

**Der Gate-Befehl richtet sich nach DEINEM Repo, nicht nach HelmDecks.**
`gate_cmd` zeigt auf `ops/tools/repo_gate.py`: das schaut nach, welche
Marker-Dateien dein Repo wirklich hat, und prueft entsprechend - `py_compile`
ueber die Python-Dateien, `npm run typecheck`/`tsc --noEmit` bei einer
`package.json`, `cargo check` bei `Cargo.toml`, `go build ./...` bei `go.mod`.
Was es nicht findet, prueft es nicht und sagt das auch (`uebersprungen: ...`)
statt stillschweigend gruen zu melden. Leicht bleibt es trotzdem: ein
Code-Check, keine Testsuite (Dekret `gate-light`).

Legt dein Repo eine eigene `helmdeck.gate` an, gewinnt IMMER die Datei - die
Vorlage springt nur fuer ein Repo ein, das nichts eigenes erklaert.

**Der Deploy-Befehl ist absichtlich leer vorbelegt.** Ein geratener Build-Befehl
waere schlimmer als keiner: er liefe bei der ersten Abnahme los und faende
irgendetwas. Sag Henry einen Satz - *"Deploy fuer dieses Repo ist `bash
ops/deploy/push_update.sh`"* - und die Station geht an.

**Was diese Vorlage bewusst NICHT anfasst:**

- `capacity.wip_limit`. Wie viele Karten gleichzeitig laufen duerfen, ist eine
  Eigenschaft dieses PCs, nicht dieses Repo-Typs. Das gehoert an den
  Autonomie-Regler.
- `worktreeIsolation`, `gateBeforeReview` und die uebrigen Governance-Flags aus
  `policy_live.json`. Die werden heute noch von niemandem gelesen
  (ARCHITECTURE.md:160-162) - eine Vorlage, die sie setzt, meldet Erfolg und
  bewirkt nichts.
- Das Gate. Gate-before-review ist Harness-Gesetz; keine Vorlage und kein
  Chat-Satz schaltet es ab.
