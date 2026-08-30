---
id: software-dev
label: Software-Entwicklung
who: Code-Repos. Alles läuft, nichts landet ungeprüft.
summary: Worktree je Karte · Gate vor der Review · Deploy nach deiner Abnahme
stations: backlog, working, gate, review, deploy
card_kind: new_track
deploy_hook: ""
settings.policy.auto_accept_green: false
settings.policy.auto_dispatch_modes: ["do"]
---

Der Normalfall fuer ein Repo, aus dem etwas gebaut wird.

**Alle fuenf Stationen sind aktiv.** Jede Karte bekommt einen isolierten
git-worktree, vor der Review laeuft der Gate (py_compile ueber `daemon/`,
`spine/`, `cells/` plus die Import-Verdrahtung), deine Abnahme merged wirklich
nach main und faehrt danach den Deploy-Hook.

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
