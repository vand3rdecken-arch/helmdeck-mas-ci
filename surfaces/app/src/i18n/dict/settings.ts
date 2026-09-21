import type { Dict } from "../index";

/** Keys for the settings surface. Owned by that area - keep additions here so the
 *  dict never becomes a merge bottleneck. Every key needs BOTH languages. */
export const settings: Dict = {
  // ---- nav bits this area owns (the shared nav.* live in chrome.ts) ----
  "nav.loopmap": { de: "Harness", en: "Harness" },
  "nav.repo": { de: "Repo einrichten", en: "Set up repo" },
  "nav.sectionWorkflow": { de: "Ablauf", en: "Workflow" },
  "nav.sectionSetup": { de: "Einrichtung", en: "Setup" },
  "nav.filter": { de: "Filter", en: "Filter" },
  "nav.filterAll": { de: "Alle Arbeit", en: "All work" },
  "nav.filterArchived": { de: "Archiv", en: "Archive" },
  "nav.clients": { de: "Clients", en: "Clients" },
  "nav.commands": { de: "⌘K · Befehle", en: "⌘K · Commands" },

  // ---- settings hub doors (ops/docs/backlog/settings-ia-redesign) ----
  // 6 doors in user-goal language (Home Assistant pattern), each a short
  // subtitle - the flat 10-panel screen + the opaque "Automatik"/"Module"
  // labels were the owner's original complaint (2026-08-26).
  // Door 1 is ACCOUNT-backed since accounts-boards-prd phase 4, so it is named
  // after WHOSE it is rather than "Allgemein" - a name that said nothing and
  // was the door everything unclassifiable ended up in.
  "hub.door.general": { de: "Mein Profil", en: "My profile" },
  "hub.door.general.sub": { de: "Sprache, Aussehen, dieses Gerät",
                            en: "Language, appearance, this device" },
  "hub.door.boards": { de: "Boards", en: "Boards" },
  "hub.door.boards.sub": { de: "Meine Boards und das geteilte Board, Spalten benennen",
                           en: "My boards and the shared one, naming the columns" },
  "hub.door.automation": { de: "Agenten & Autonomie", en: "Agents & autonomy" },
  "hub.door.automation.sub": { de: "Was die Agenten allein entscheiden dürfen, Nachtschicht, Briefs",
                               en: "What the agents may decide on their own, night shift, briefs" },
  "hub.door.cells": { de: "Zellen", en: "Cells" },
  "hub.door.cells.sub": { de: "Welche agentischen Systeme laufen und was sie tun",
                          en: "Which agentic systems run and what they do" },
  "hub.door.connections": { de: "Verbindungen", en: "Connections" },
  "hub.door.connections.sub": { de: "Jira, Import, externe Connectoren", en: "Jira, import, external connectors" },
  "hub.door.team": { de: "Team & Geräte", en: "Team & devices" },
  "hub.door.team.sub": { de: "Mitglieder einladen, Rollen, Geräte", en: "Invite members, roles, devices" },
  "hub.door.system": { de: "System", en: "System" },
  "daemon.section": { de: "Daemon", en: "Daemon" },
  "daemon.current": { de: "Läuft auf dem aktuellen Stand", en: "Running on the current code" },
  "daemon.stale": { de: "Code ist neuer als der laufende Daemon", en: "Code on disk is newer than the running daemon" },
  "daemon.stale.hint": { de: "Ein Commit hat Daemon-Code geändert. Erst nach dem Neustart ist er aktiv (Modelle, Broker, Routen).", en: "A commit changed daemon code. It only takes effect after a restart (models, broker, routes)." },
  "daemon.unreachable": { de: "Daemon antwortet nicht", en: "Daemon not responding" },
  "daemon.restarting": { de: "Neustart läuft – wartet auf den neuen Daemon", en: "Restarting – waiting for the new daemon" },
  "daemon.restarted": { de: "Neu gestartet", en: "Restarted" },
  "daemon.line.running": { de: "Läuft seit {since} · PID {pid}", en: "Up for {since} · PID {pid}" },
  "daemon.line.commit": { de: "Gestartet auf {commit} · Repo-HEAD {head}", en: "Booted on {commit} · repo HEAD {head}" },
  "daemon.line.turns": { de: "{n} Karte(n) mitten im Turn – Neustart würde sie abbrechen", en: "{n} card(s) mid-turn – a restart would cut them off" },
  "daemon.line.latencyOk": { de: "Handy-Pfad: keine Verzögerung in den letzten {min} min", en: "Phone path: no delays in the last {min} min" },
  "daemon.line.latency": { de: "Handy-Pfad: {n}× über Budget in {min} min (schlimmster Fall {worst} s)", en: "Phone path: {n}× over budget in {min} min (worst {worst} s)" },
  "daemon.restart": { de: "Daemon neu starten", en: "Restart daemon" },
  "daemon.restart.waiting": { de: "Neustart ausgelöst (≈90 s)…", en: "Restart triggered (≈90 s)…" },
  "takeout.title": { de: "Umzug und Sicherung", en: "Move and backup" },
  "takeout.hint": { de: "Packt alles in ein Archiv: Gedaechtnis, Karten, Chat, Konten, Einstellungen. Schluessel bleiben ausdruecklich hier.", en: "Packs everything into one container: memory, cards, chat, accounts, settings. Keys deliberately stay here." },
  "takeout.start": { de: "Archiv erstellen", en: "Create archive" },
  "takeout.running": { de: "Laeuft …", en: "Running …" },
  "takeout.verify": { de: "Letztes Archiv pruefen", en: "Verify latest archive" },
  "takeout.none": { de: "Noch kein Archiv. Mach eins, bevor du den Rechner neu aufsetzt.", en: "No archive yet. Make one before you rebuild the machine." },
  "takeout.latest": { de: "Letztes Archiv: {when}, {size}", en: "Latest archive: {when}, {size}" },
  "takeout.incomplete": { de: "Unvollstaendig – der Lauf wurde abgebrochen. Neu erstellen.", en: "Incomplete – the run was interrupted. Create a new one." },
  "takeout.failed": { de: "Letzter Lauf fehlgeschlagen: {why}", en: "Last run failed: {why}" },
  "takeout.failedTitle": { de: "Archiv fehlgeschlagen", en: "Archive failed" },
  "takeout.verifyOkTitle": { de: "Archiv vollstaendig", en: "Archive complete" },
  "takeout.verifyOkBody": { de: "Pruefsummen stimmen, der Vollstaendigkeitsmarker ist gesetzt.", en: "Checksums match and the completeness marker is set." },
  "takeout.verifyBadTitle": { de: "Archiv beschaedigt", en: "Archive damaged" },
  "takeout.notIncluded": { de: "NICHT im Archiv – von Hand mitnehmen", en: "NOT in the archive – carry by hand" },
  "daemon.restart.busyTitle": { de: "Karten laufen noch", en: "Cards still running" },
  "daemon.restart.busyBody": { de: "{n} Karte(n) sind mitten im Turn. Trotzdem neu starten? Die Turns werden abgebrochen, die Sessions bleiben.", en: "{n} card(s) are mid-turn. Restart anyway? The turns are cut off, the sessions survive." },
  "daemon.restart.failedTitle": { de: "Neustart nicht ausgelöst", en: "Restart not triggered" },
  "hub.door.system.sub": { de: "Geschäft, Nutzung, Updates", en: "Business, usage, updates" },

  // Henry's context chip on a door's chat (settings-ia-redesign follow-up,
  // owner directive 2026-09-04: chat is the entry point on EVERY door, not
  // only Board/Prozesse). Names the door in Henry's own vocabulary, the same
  // pattern rule.askContext (harness_rules.ts) uses for a single row - so
  // "mach das aus" resolves against THIS door's knobs instead of nothing.
  "hub.door.askContext": {
    de: "Es geht um die Tür „{label}“ in den Einstellungen.",
    en: "This is about the \"{label}\" door in settings.",
  },

  // ---- scope badges (accounts-boards-prd phase 4) ----
  // The five layers of PRD section 3, in the words a user would use for "who
  // does changing this affect". Every schema row wears one, so "why did my
  // colleague's board change" is answered before it is asked.
  "hub.scope.profile": { de: "Konto", en: "Account" },
  "hub.scope.board": { de: "Board", en: "Board" },
  "hub.scope.workspace": { de: "Workspace", en: "Workspace" },
  "hub.scope.device": { de: "Gerät", en: "Device" },
  "hub.scope.system": { de: "System", en: "System" },
  // Progressive disclosure: the count is in the label so an empty-looking
  // section never hides its contents silently.
  "hub.advanced": { de: "Erweitert ({n})", en: "Advanced ({n})" },

  // ---- schema section headings that have no older home ----
  "hub.grp.boardLabels": { de: "Stationsnamen", en: "Station names" },
  "hub.grp.machine": { de: "Diese Maschine", en: "This machine" },

  // ---- the Boards door ----
  "hub.boards.mine": { de: "Meine Boards", en: "My boards" },
  "hub.boards.hint": {
    de: "Ein Board ist eine gespeicherte Ansicht auf denselben Kartenpool – Karten gibt es nur einmal. Das geteilte Board sehen alle.",
    en: "A board is a saved view over the one card pool - cards exist once. Everyone sees the shared board.",
  },
  "hub.boards.none": { de: "Noch keine Boards.", en: "No boards yet." },
  "hub.boards.columns": { de: "{n} Spalten", en: "{n} columns" },
  "hub.boards.open": { de: "Board-Editor öffnen", en: "Open board editor" },

  // ---- my profile (accounts-boards-prd phase 1) ----
  // The hints carry the whole point of the phase, so they say WHERE a value
  // lives rather than only what it does - that is what keeps the two panels in
  // the "general" door from reading as the same control twice.
  "profile.section": { de: "Mein Profil", en: "My profile" },
  "profile.section.hint": {
    de: "Gehört zu deinem Konto, nicht zu diesem Gerät: melde dich auf Handy, Web oder Desktop an – dieselbe Ansicht.",
    en: "Belongs to your account, not to this device: sign in on phone, web or desktop and you get the same view.",
  },
  "profile.wsSection": { de: "Workspace-Standard", en: "Workspace default" },
  "profile.wsSection.hint": {
    de: "Womit Konten starten, die selbst nichts gewählt haben. Ändern verschiebt alle, die nie gewählt haben – und niemanden, der gewählt hat.",
    en: "What accounts start with until they choose. Changing it moves everyone who never picked one, and nobody who did.",
  },
  "profile.langTitle": { de: "In welcher Sprache?", en: "Which language?" },
  "profile.langHint": {
    de: "Wird auf deinem Konto gespeichert – auf jedem Gerät, auf dem du dich anmeldest.",
    en: "Saved to your account - on every device you sign in on.",
  },
  "profile.langSkip": { de: "Später entscheiden", en: "Decide later" },

  // ---- language switch ----
  "settings.lang.hint": {
    de: "Eine Sprache für alles: Oberfläche und Agenten-Antworten wechseln zusammen. Der Audit-Trail bleibt technisch (Englisch).",
    en: "One language for everything: the interface and the agents' replies switch together. The audit trail stays technical (English).",
  },

  // ---- generic ----
  "settings.ownerOnly": { de: "Nur für Owner / Desktop nicht erreichbar.",
                          en: "Owner only / desktop unreachable." },
  "settings.savedTitle": { de: "Gespeichert", en: "Saved" },
  // Was hardcoded German on the hub's door list until phase 4.
  "settings.logout": { de: "Abmelden", en: "Sign out" },
  "settings.deleteAccount": { de: "Konto löschen", en: "Delete account" },
  "settings.deleteAccount.msg": {
    de: "Das Konto {name} wird endgültig gelöscht: Anmeldungen, Geräte-Tokens, Profil und persönliche Boards. Bestätige mit deinem Passwort.",
    en: "The account {name} is deleted permanently: sign-ins, device tokens, profile and personal boards. Confirm with your password." },
  "settings.deleteAccount.confirm": { de: "Endgültig löschen", en: "Delete permanently" },
  "settings.deleteAccount.wrongPw": { de: "Passwort stimmt nicht.", en: "Wrong password." },
  "settings.deleteAccount.lastOwner": {
    de: "Das ist der letzte Owner dieses Workspaces. Mach erst ein anderes Konto zum Owner.",
    en: "This is the workspace's last owner. Make another account owner first." },
  "settings.saved.business": { de: "Business-Einstellungen.", en: "Business settings." },
  "settings.saved.policy": { de: "Policy & Aussehen.", en: "Policy & appearance." },
  "settings.saved.jira": { de: "Jira-Verbindung.", en: "Jira connection." },
  "settings.saved.night": { de: "Night-shift.", en: "Night shift." },
  "settings.saved.relay": { de: "Relay-URL.", en: "Relay URL." },

  // ---- section labels ----
  "settings.sec.business": { de: "Geschäft", en: "business" },
  "settings.sec.automation": { de: "Automatik-Policy", en: "automation policy" },
  "settings.sec.dataflows": { de: "Datenflüsse – Import", en: "data flows - import" },
  "settings.sec.night": { de: "Nachtschicht", en: "night-shift" },
  "settings.sec.mobile": { de: "Mobil – Telefon koppeln (E2E-verschlüsselt)",
                           en: "mobile - pair a phone (e2e encrypted)" },
  "settings.sec.wearPair": { de: "Wearable – Uhr koppeln (Diktier-Code)",
                             en: "wearable - pair a watch (spoken code)" },
  "settings.sec.devices": { de: "Ausführende PCs ({n})", en: "Executing PCs ({n})" },
  "settings.sec.registration": { de: "Selbstregistrierung", en: "self sign-up" },
  "settings.devices.hint": { de: "Eigene PCs deines Teams, die Karten lokal ausführen. Nur der Merge bleibt zentral.", en: "Your team's own PCs that run cards locally. Only the merge stays central." },
  "settings.devices.register": { de: "+ Gerät registrieren", en: "+ register device" },
  "settings.devices.labelPrompt": { de: "Name für dieses Gerät (z. B. mein-laptop)", en: "Name for this device (e.g. my-laptop)" },
  "settings.devices.tokenCopiedTitle": { de: "Geräte-Token kopiert", en: "Device token copied" },
  "settings.devices.tokenCopiedMsg": { de: "In die Geräte-Config (--config) einfügen. Wird nur EINMAL angezeigt.", en: "Paste into the device config (--config). Shown only ONCE." },
  "settings.devices.revoke": { de: "widerrufen", en: "revoke" },
  "settings.devices.revokeTitle": { de: "Gerät widerrufen?", en: "Revoke device?" },
  "settings.devices.revokeMsg": { de: "{label} verliert den Zugang. Ein laufender Turn wird beim nächsten Check abgebrochen.", en: "{label} loses access. A running turn is aborted on its next check." },
  "settings.devices.scopeExternal": { de: "eigenes Konto", en: "own account" },
  "settings.devices.scopeShared": { de: "geteilt", en: "shared" },
  "settings.devices.lastSeen": { de: "zuletzt gesehen {when}", en: "last seen {when}" },
  "settings.devices.neverSeen": { de: "noch nie verbunden", en: "never connected" },
  "settings.devices.reassign": { de: "neu zuweisen", en: "reassign" },
  "settings.devices.reassignPrompt": { de: "Auf welches Gerät verschieben?", en: "Move to which device?" },
  "settings.devices.reassignClear": { de: "Stattdessen zentral ausführen", en: "Run centrally instead" },

  // ---- business ----
  "settings.business.repo": { de: "Standard-Repo", en: "Default repo" },
  "settings.business.wip": { de: "WIP-Limit", en: "WIP limit" },
  "settings.business.value": { de: "Wert/Karte", en: "Value/card" },
  "settings.business.budget": { de: "Touch-Budget/Tag", en: "Touch budget/day" },
  "settings.business.tariff": { de: "Touch-Tarif (steer / review / bounce)",
                                en: "Touch tariff (steer / review / bounce)" },

  // ---- automation policy ----
  "settings.policy.hint": {
    de: "Wie Arbeit fliesst ist konfigurierbar. Was sie vertrauenswürdig macht - Auth, Audit, das Gate - ist im Code fixiert.",
    en: "How work flows is configurable. What makes it trustworthy - auth, audit, the gate - is fixed in code.",
  },
  "settings.policy.autoAccept": {
    de: "Auto-accept bei grünem Gate (Kette läuft ohne Mensch weiter)",
    en: "Auto-accept on a green gate (the chain continues without a human)",
  },
  "settings.policy.autoModes": { de: "Auto-dispatch Modi (Kette darf selbst starten)",
                                 en: "Auto-dispatch modes (the chain may start itself)" },
  "settings.policy.autoPrio": { de: "Backlog Self-dispatch (ab dieser Priorität)",
                                en: "Backlog self-dispatch (from this priority up)" },
  "settings.policy.chatRoles": { de: "Chat darf Workspace umkonfigurieren (Rollen)",
                                 en: "Chat may reconfigure the workspace (roles)" },
  "settings.policy.laneLabels": { de: "Lane-Labels (Umbenennen; Semantik bleibt fix)",
                                  en: "Lane labels (rename only; the semantics stay fixed)" },
  "settings.policy.backdrop": { de: "Backdrop-Theme (ambient, hinter dem Glas)",
                                en: "Backdrop theme (ambient, behind the glass)" },
  "settings.policy.save": { de: "Policy & Aussehen speichern", en: "Save policy & appearance" },

  // ---- data flows / import ----
  "settings.jira.caption": { de: "Jira Cloud (Base-URL · E-Mail · API-Token · Default-JQL)",
                             en: "Jira Cloud (base URL · email · API token · default JQL)" },
  "settings.jira.emailPh": { de: "E-Mail", en: "email" },
  "settings.jira.tokenPh": { de: "API-Token", en: "API token" },
  "settings.jira.jqlPh": { de: "JQL, z.B. project = ABC", en: "JQL, e.g. project = ABC" },
  "settings.jira.saveConn": { de: "Verbindung speichern", en: "Save connection" },
  "settings.jira.importNow": { de: "Jetzt importieren", en: "Import now" },
  "settings.import.title": { de: "Import", en: "Import" },
  "settings.import.jiraDone": { de: "{n} Issues in den Backlog geladen.",
                                en: "{n} issues loaded into the backlog." },
  "settings.import.urlCaption": { de: "Von einer Webseite (Agent leitet einen Prozess ab)",
                                  en: "From a web page (an agent derives a process from it)" },
  "settings.import.urlDone": { de: "Der Agent schlägt Schritte vor (siehe Processes).",
                               en: "The agent is proposing steps (see Processes)." },
  "settings.import.page": { de: "Seite importieren", en: "Import page" },

  // ---- night shift ----
  "settings.night.hint": {
    de: "Während du schläfst plant ein Scout pro Repo Verbesserungen und arbeitet sie als Karten durchs Gate - nichts merged sich selbst, Ergebnisse warten im Review.",
    en: "While you sleep one scout per repo plans improvements and works them through the gate as cards - nothing merges itself, results wait in review.",
  },
  "settings.night.enabled": { de: "aktiviert", en: "enabled" },
  "settings.night.window": { de: "Fenster (always oder z.B. 01:00-07:00)",
                             en: "Window (always, or e.g. 01:00-07:00)" },
  "settings.night.max": { de: "Max/Nacht", en: "Max/night" },
  "settings.night.idle": { de: "Idle (min)", en: "Idle (min)" },
  "settings.night.repos": { de: "Repo-Ordner (ein absoluter Pfad pro Zeile; Reihenfolge = Priorität)",
                            en: "Repo folders (one absolute path per line; order = priority)" },
  "settings.night.planNow": { de: "Plan jetzt", en: "Plan now" },
  "settings.night.planning": { de: "plant…", en: "planning…" },
  "settings.night.showPlan": { de: "Plan anzeigen", en: "Show plan" },
  "settings.night.planStartedTitle": { de: "Scouts planen", en: "Scouts are planning" },
  "settings.night.planStartedMsg": {
    de: "Die Scouts arbeiten im Hintergrund - in ein paar Minuten \"Plan anzeigen\" tippen.",
    en: "The scouts work in the background - tap \"Show plan\" in a few minutes.",
  },
  "settings.night.noPlanTitle": { de: "Kein Plan", en: "No plan" },
  "settings.night.noPlanMsg": { de: "Noch kein Plan vorhanden - erst \"Plan jetzt\".",
                                en: "No plan yet - run \"Plan now\" first." },
  "settings.night.planFrom": { de: "Plan von {when}", en: "Plan from {when}" },
  "settings.night.lastReport": { de: "Letzter Shift-Report", en: "Last shift report" },

  // ---- mobile pairing (desktop side) ----
  "settings.pair.hint": {
    de: "Das Telefon erreicht diesen Daemon über dein Relay (HTTPS). Traffic ist Ende-zu-Ende NaCl-verschlüsselt - das Relay sieht nur Chiffretext.",
    en: "The phone reaches this daemon through your relay (HTTPS). Traffic is end-to-end NaCl-encrypted - the relay only ever sees ciphertext.",
  },
  "settings.pair.relayUrl": { de: "Relay-URL (wo du das Relay hostest, HTTPS)",
                              en: "Relay URL (where you host the relay, HTTPS)" },
  "settings.pair.noRelayTitle": { de: "Relay fehlt", en: "Relay missing" },
  "settings.pair.noRelayMsg": { de: "Erst eine Relay-URL speichern.", en: "Save a relay URL first." },
  "settings.pair.pairPhone": { de: "Telefon koppeln", en: "Pair phone" },
  "settings.pair.relayFailed": { de: "Relay-Pairing fehlgeschlagen.", en: "Relay pairing failed." },
  "settings.pair.ttl": {
    de: "Der Code ist {min} Min gültig und lässt genau EIN neues Gerät herein – danach am Desktop neu erzeugen. Bereits gekoppelte Geräte bleiben verbunden.",
    en: "The code is valid for {min} min and lets in exactly ONE new device – generate a new one on the desktop afterwards. Already paired devices stay connected.",
  },
  "settings.pair.linkHint": {
    de: "Ohne Scan: diesen Link ans Telefon schicken (WhatsApp/Signal an dich selbst) und antippen — HelmDeck öffnet sich und koppelt.",
    en: "No scan needed: send this link to the phone (WhatsApp/Signal to yourself) and tap it — HelmDeck opens and pairs.",
  },
  "settings.pair.copyLink": { de: "Link kopieren", en: "Copy link" },
  "settings.pair.share": { de: "Teilen", en: "Share" },
  "settings.pair.copiedTitle": { de: "Kopiert", en: "Copied" },
  "settings.pair.linkCopied": { de: "Pairing-Link kopiert - ans Telefon senden und antippen.",
                                en: "Pairing link copied - send it to the phone and tap it." },
  "settings.pair.qrHint": { de: "Mit der Handykamera scannen — öffnet HelmDeck und koppelt automatisch.",
                            en: "Scan with the phone camera — opens HelmDeck and pairs automatically." },
  "settings.pair.codeHint": {
    de: "Kein Scan? Code kopieren und am Telefon einfügen (More → Pair). Enthält ein Einmal-Token - wie ein Passwort behandeln.",
    en: "No scan? Copy the code and paste it on the phone (More → Pair). It contains a one-time token - treat it like a password.",
  },
  "settings.pair.copyCode": { de: "Code kopieren", en: "Copy code" },
  "settings.pair.codeCopied": { de: "Pairing-Code in der Zwischenablage.", en: "Pairing code in the clipboard." },

  // ---- watch pairing (spoken device-code, no camera/keyboard on most
  // Wear OS watches - ops/docs/backlog/wear-os-integration/README.md §4.6) ----
  "settings.wearPair.hint": {
    de: "Für die Uhr muss dieser Daemon kurz von außen erreichbar sein: `bash ops/deploy/cloudflare_tunnel.sh` laufen lassen, solange du koppelst. Der Code unten ist NICHT die Adresse - die tippst/diktierst du separat auf der Uhr aus deinem Terminal ab.",
    en: "Pairing a watch needs this daemon briefly reachable from outside: run `bash ops/deploy/cloudflare_tunnel.sh` while you pair. The code below is NOT the address - dictate/type that separately on the watch from your own terminal.",
  },
  "settings.wearPair.label": { de: "Name (z. B. \"Xiaomi Watch 5\")", en: "Label (e.g. \"Xiaomi Watch 5\")" },
  "settings.wearPair.pairWatch": { de: "Uhr koppeln", en: "Pair watch" },
  "settings.wearPair.failed": { de: "Konnte keinen Code erzeugen.", en: "Could not generate a code." },
  "settings.wearPair.ttl": {
    de: "Der Code ist {min} Min gültig, einmal verwendbar. Auf der Uhr: Tunnel-Adresse + diesen Code diktieren oder eintippen.",
    en: "The code is valid for {min} min, single-use. On the watch: dictate or type the tunnel address + this code.",
  },
  "settings.wearPair.copyCode": { de: "Code kopieren", en: "Copy code" },
  "settings.wearPair.codeCopied": { de: "Uhr-Code in der Zwischenablage.", en: "Watch code in the clipboard." },

  // ---- members + devices (door: team) ----
  "settings.users.touchesToday": { de: "{n}t heute", en: "{n}t today" },
  "settings.users.revoke": { de: "widerrufen", en: "revoke" },
  "settings.users.stale": { de: ">90 Tage inaktiv", en: ">90 days unused" },
  "settings.users.addToken": { de: "+ Gerät/Skript", en: "+ device/script" },
  "settings.users.password": { de: "Passwort", en: "Password" },
  "settings.users.delete": { de: "entfernen", en: "remove" },
  "settings.users.setRole": { de: "Rolle setzen", en: "Set role" },
  "settings.users.newPwPrompt": { de: "Neues Passwort für {name} (8+ Zeichen):",
                                  en: "New password for {name} (8+ characters):" },
  "settings.users.unsupportedTitle": { de: "Nicht unterstützt", en: "Not supported" },
  "settings.users.unsupportedMsg": { de: "Passwort-Reset am Desktop/Web nutzen.",
                                     en: "Use the surfaces/desktop/web app to reset a password." },
  "settings.users.tooShortTitle": { de: "Zu kurz", en: "Too short" },
  "settings.users.tooShortMsg": { de: "Mindestens 8 Zeichen.", en: "At least 8 characters." },
  "settings.users.pwSetTitle": { de: "OK", en: "OK" },
  "settings.users.pwSetMsg": { de: "Passwort gesetzt.", en: "Password set." },
  "settings.users.delConfirm": { de: "{name} entfernen?", en: "Remove {name}?" },
  "settings.users.delMsg": { de: "Sessions und Geräte dieses Mitglieds verlieren sofort den Zugang.",
                             en: "This member's sessions and devices lose access immediately." },
  "settings.users.tokenLabelPrompt": { de: "Name des Geräts (z.B. „Build-PC\", „CI-Skript\"):",
                                       en: "Name of the device (e.g. \"build PC\", \"CI script\"):" },
  "settings.users.tokenCopiedTitle": { de: "Token kopiert", en: "Token copied" },
  "settings.users.tokenCopiedMsg": { de: "Device-Token in der Zwischenablage — er wird nur dieses eine Mal angezeigt.",
                                     en: "Device token in the clipboard - it is shown this once and never again." },
  "settings.users.revokeTitle": { de: "Gerät widerrufen?", en: "Revoke device?" },
  "settings.users.revokeMsg": { de: "Dieses Gerät verliert sofort den Zugang.",
                                en: "That device loses access immediately." },

  // ---- team: members, invitations, devices (one flow, Jira-shaped) ----
  "settings.sec.members": { de: "Mitglieder ({n})", en: "Members ({n})" },
  "settings.sec.invites": { de: "Offene Einladungen ({n})", en: "Open invitations ({n})" },
  "team.hint": {
    de: "Lade jemanden ein und wähle dabei seine Rolle. Der Code gilt einmalig und läuft ab.",
    en: "Invite someone and pick their role as you do. The code works once and expires.",
  },
  "team.inviteMember": { de: "Mitglied einladen", en: "Invite member" },
  "team.inviteRole": { de: "Rolle", en: "Role" },
  "team.role.client": { de: "Kunde", en: "Client" },
  "team.role.client.sub": { de: "Nur eigene Karten anlegen und kommentieren.",
                            en: "Files and comments on their own cards only." },
  "team.role.operator": { de: "Operator", en: "Operator" },
  "team.role.operator.sub": { de: "Arbeitet am ganzen Board mit.",
                              en: "Works the whole board." },
  "team.role.owner": { de: "Owner", en: "Owner" },
  "team.role.owner.sub": { de: "Alles, inklusive Einstellungen und Mitglieder.",
                           en: "Everything, including settings and members." },
  "team.role.quality": { de: "Qualität", en: "Quality" },
  "team.role.quality.sub": { de: "Freigeben und signieren.", en: "Approves and signs." },
  "team.role.auditor": { de: "Auditor", en: "Auditor" },
  "team.role.auditor.sub": { de: "Nur lesen.", en: "Read-only." },
  "team.inviteTtl": { de: "Gültig", en: "Valid for" },
  // Two keys, not a {n}-substitution with a plural rule: the dict has no
  // pluralisation engine, and "1 Tage" is the kind of thing the owner reads
  // as sloppiness before he reads anything else on the screen.
  "team.ttlDays": { de: "{n} Tage", en: "{n} days" },
  "team.ttlOneDay": { de: "1 Tag", en: "1 day" },
  "team.createInvite": { de: "Einladung erstellen", en: "Create invitation" },
  "team.inviteReady": { de: "Einladung für Rolle „{role}\" erstellt", en: "Invitation created for role \"{role}\"" },
  "team.inviteReadyHint": {
    de: "Teile Code oder Link. Einmal einlösbar, danach wertlos.",
    en: "Share the code or the link. Redeemable once, worthless afterwards.",
  },
  "team.copyCode": { de: "Code kopieren", en: "Copy code" },
  "team.copyLink": { de: "Link kopieren", en: "Copy link" },
  "team.copied": { de: "In der Zwischenablage.", en: "In the clipboard." },
  "team.inviteExpires": { de: "läuft ab {when}", en: "expires {when}" },
  "team.inviteUsedBy": { de: "eingelöst von {name}", en: "redeemed by {name}" },
  "team.noInvites": { de: "Keine offenen Einladungen.", en: "No open invitations." },
  "team.revokeInviteTitle": { de: "Einladung widerrufen?", en: "Revoke invitation?" },
  "team.revokeInviteMsg": { de: "Der Code funktioniert danach nicht mehr.",
                            en: "The code stops working." },
  "team.lastActive": { de: "zuletzt aktiv {when}", en: "last active {when}" },
  "team.neverActive": { de: "noch nie aktiv", en: "never active" },
  "team.devices": { de: "{n} Geräte", en: "{n} devices" },
  "team.oneDevice": { de: "1 Gerät", en: "1 device" },
  "team.noDevices": { de: "keine Geräte", en: "no devices" },
  "team.deviceNever": { de: "noch nie benutzt", en: "never used" },
  "team.deviceLastUsed": { de: "zuletzt {when}", en: "last used {when}" },
  "team.you": { de: "du", en: "you" },

  // ---- self sign-up (the one knob left of the old registration panel) ----
  "settings.reg.hint": {
    de: "Ohne Einladung: jeder mit Zugang zum Login kann sich selbst ein Konto anlegen — immer als Kunde, nie mehr. Aus lassen, wenn nur Eingeladene rein sollen.",
    en: "Without an invitation: anyone who can reach the login can create an account - always as a client, never more. Leave off if only invited people should get in.",
  },
  "settings.reg.open": { de: "Selbstregistrierung offen (kein Code nötig)",
                         en: "Open self sign-up (no code needed)" },

  // ---- native pairing gate (fresh install / reinstall, no daemon known yet) ----
  "gate.title": { de: "Mit deinem Desktop koppeln", en: "Pair with your desktop" },
  "gate.hint": { de: "Scanne den QR-Code aus Einstellungen → Team & Geräte → Telefon koppeln, oder füge den Code unten ein.",
                 en: "Scan the QR code from Settings → Team & devices → Pair phone, or paste the code below." },

  // ---- More tab (phone) ----
  "settings.more.pairSection": { de: "Mit einem Desktop koppeln", en: "pair with a desktop" },
  "settings.more.pairedRelay": { de: "● gekoppelt (Relay)", en: "● paired (relay)" },
  "settings.more.notPaired": { de: "nicht gekoppelt", en: "not paired" },
  "settings.more.pairHelp": { de: "Desktop: Settings → Mobile app → Pair phone. Code hier einfügen.",
                              en: "Desktop: Settings → Mobile app → Pair phone. Paste the code here." },
  "settings.more.scanQr": { de: "QR-Code scannen", en: "Scan QR code" },
  "settings.more.orPaste": { de: "oder Code / Link einfügen:", en: "or paste a code / link:" },
  "settings.more.pairPh": { de: "Pairing-Code / Link", en: "Pairing code / link" },
  "settings.more.pairBtn": { de: "Pair", en: "Pair" },
  "settings.more.checking": { de: "Prüfe…", en: "Checking…" },
  "settings.more.verifying": { de: "Verbindung prüfen…", en: "Verifying the connection…" },
  "settings.more.pairedRelayOk": { de: "Gekoppelt ✓ – verschlüsselt über Relay, Desktop erreichbar.",
                                   en: "Paired ✓ – encrypted via relay, desktop reachable." },
  "settings.more.pairedLanOk": { de: "Verbunden ✓ – direkt (LAN), Desktop erreichbar.",
                                 en: "Connected ✓ – direct (LAN), desktop reachable." },
  "settings.more.tokenRejected": {
    de: "Code übernommen, aber der Token wurde abgelehnt – am Desktop neuen Code erzeugen.",
    en: "Code applied, but the token was rejected – generate a new code on the desktop.",
  },
  "settings.more.noAnswer": { de: "Code übernommen, aber der Desktop antwortet nicht: {err}",
                              en: "Code applied, but the desktop does not answer: {err}" },
  "settings.more.lanSection": { de: "Direktes LAN (optional)", en: "direct lan (optional)" },
  "settings.more.lanHelp": { de: "Nur im selben Netz ohne Relay. Daemon URL + Device-Token.",
                             en: "Same network only, no relay. Daemon URL + device token." },
  "settings.more.tokenPh": { de: "Bearer-Token (optional)", en: "Bearer token (optional)" },

  // ---- PM / CTO panel ----
  "pm.title": { de: "PM / CTO", en: "PM / CTO" },
  "pm.weekdays": { de: "So,Mo,Di,Mi,Do,Fr,Sa", en: "Sun,Mon,Tue,Wed,Thu,Fri,Sat" },
  "pm.goalPh": { de: "Ziel / MVP-Definition…", en: "Goal / MVP definition…" },
  "pm.setGoal": { de: "Ziel setzen & planen", en: "Set goal & plan" },
  "pm.saving": { de: "Speichert…", en: "Saving…" },
  "pm.noGoal": { de: "Kein Ziel gesetzt — tippen, um das MVP-Ziel zu definieren.",
                 en: "No goal set — tap to define the MVP goal." },
  "pm.changeGoal": { de: "Ziel ändern", en: "Change the goal" },
  "pm.proactiveState": { de: "Proaktiv: {mode}", en: "Proactive: {mode}" },
  "pm.proactiveOffShort": { de: "Proaktiv: aus", en: "Proactive: off" },
  "pm.proactive": { de: "Proaktiv arbeiten", en: "Work proactively" },
  "pm.notify": { de: "Melden", en: "Notify" },
  "pm.ask": { de: "Fragen", en: "Ask" },
  "pm.act": { de: "Handeln", en: "Act" },
  "pm.desc.off": { de: "Aus — der PM plant nur auf Anfrage.", en: "Off — the PM only plans on request." },
  "pm.desc.notify": { de: "Melden — plant still, ändert nichts; meldet nur Blocker.",
                      en: "Notify — plans quietly, changes nothing; only reports blockers." },
  "pm.desc.ask": { de: "Fragen — legt Karten an (reversibel), startet nichts ohne dich.",
                   en: "Ask — creates cards (reversible), starts nothing without you." },
  "pm.desc.act": {
    de: "Handeln — legt an & startet im WIP/Quota-Rahmen, während du weg bist. Merge/Accept bleiben bei dir.",
    en: "Act — creates and starts within the WIP/quota limits while you are away. Merge/accept stay with you.",
  },
  "pm.progress": { de: "Fortschritt zum Ziel", en: "Progress to the goal" },
  "pm.turns": { de: "Restaufwand: ~{n} Schritte", en: "remaining: ~{n} steps" },
  "pm.perDay": { de: "Velocity ~{n}/Tag", en: "velocity ~{n}/day" },
  "pm.flatMonthly": { de: "Flat {v}/Mon", en: "Flat {v}/mo" },
  "pm.cashToGoal": { de: "{v} bis Ziel", en: "{v} to goal" },
  "pm.leverage": { de: "Leverage ~{v}", en: "Leverage ~{v}" },
  "pm.etaUnknown": { de: "noch keine Velocity gemessen", en: "no velocity measured yet" },
  "pm.stepsTurns": { de: "{steps} Schritte · {turns} Turns", en: "{steps} steps · {turns} turns" },
  "pm.nextHeading": { de: "ALS NÄCHSTES", en: "NEXT UP" },
  "pm.createCardTitle": { de: "Karte anlegen?", en: "Create a card?" },
  "pm.cardCreated": { de: "Als Karte angelegt (Backlog).", en: "Created as a card (backlog)." },
  "pm.consolidate": { de: "Karten konsolidieren", en: "Consolidate cards" },
  "pm.proposing": { de: "Schlägt vor…", en: "Proposing…" },
  "pm.consolidateTitle": { de: "Konsolidieren", en: "Consolidate" },
  "pm.noRollup": { de: "Kein sinnvolles Roll-up gefunden.", en: "No sensible roll-up found." },
  "pm.consolidateHead": { de: "{streams} Stream-Karten aus {tickets} Tickets",
                          en: "{streams} stream cards from {tickets} tickets" },
  "pm.consolidateBody": {
    de: "Die Tickets werden reversibel archiviert und in die Stream-Karten gerollt.",
    en: "The tickets are archived reversibly and rolled into the stream cards.",
  },
  "pm.apply": { de: "Anwenden", en: "Apply" },
  "pm.consolidatedTitle": { de: "Konsolidiert", en: "Consolidated" },
  "pm.consolidatedMsg": { de: "{created} Stream-Karten, {archived} Tickets archiviert.",
                          en: "{created} stream cards, {archived} tickets archived." },
  // Members the roll-up REFUSED to archive because they were not in backlog
  // (pm.apply_consolidation) - stated, never silently dropped.
  "pm.consolidatedRefused": { de: "{n} nicht archiviert (nicht im Backlog — aktive Karten bleiben auf dem Board).",
                              en: "{n} not archived (not in backlog — active cards stay on the board)." },
  "pm.asOf": { de: "Stand: {when}", en: "As of: {when}" },
  "pm.noPlan": {
    de: "Noch kein Plan. Ziel setzen und „Aktualisieren\" — der PM erstellt Milestones, Timeline und Prioritäten.",
    en: "No plan yet. Set a goal and hit \"Refresh\" — the PM builds milestones, a timeline and priorities.",
  },

  // ---- privacy / analytics (device-local, More tab) ----
  "settings.privacy.section": { de: "Datenschutz", en: "privacy" },
  "settings.privacy.analyticsToggle": { de: "Anonyme Nutzungsstatistiken senden",
                                        en: "Send anonymous usage analytics" },
  "settings.privacy.hint": {
    de: "Anonyme Ereignisse (App-Start, Karten-Aktionen, Login) via PostHog, EU-Cloud. Keine Inhalte, keine Namen, keine Karten-Titel.",
    en: "Anonymous events (app open, card actions, login) via PostHog, EU cloud. No content, no names, no card titles.",
  },

  // ---- proactive blocker voice (device-local, More tab) ----
  "settings.voice.section": { de: "Sprache", en: "voice" },
  "settings.voice.speakBlockers": {
    de: "Blockierte Karten laut ansagen",
    en: "Announce blocked cards out loud",
  },
  // ---- engines (Settings > Agents & autonomy; Paseo's Providers section) ----
  "engines.title": { de: "Engines", en: "Engines" },
  "engines.hint": { de: "Welche Coding-Agenten Karten ausführen dürfen. Status kommt vom Binary selbst.",
    en: "Which coding agents may run cards. Status comes from the binary itself." },
  "engines.st.available": { de: "verfügbar", en: "available" },
  "engines.st.notInstalled": { de: "nicht installiert", en: "not installed" },
  "engines.st.error": { de: "Fehler", en: "error" },
  "engines.st.disabled": { de: "aus", en: "off" },
  "engines.untested": { de: "ungetestet", en: "untested" },
  "engines.recheck": { de: "Neu prüfen", en: "Re-check" },
  "engines.diag": { de: "Diagnose", en: "Diagnostic" },
  "engines.diag.exe": { de: "Programm", en: "Executable" },
  "engines.diag.version": { de: "Version", en: "Version" },
  "engines.diag.driver": { de: "Treiber", en: "Driver" },
  "engines.diag.verified": { de: "hat echte Turns durch HelmDeck gefahren", en: "has run real turns through HelmDeck" },
  "engines.diag.unverified": { de: "Treiber gebaut, noch kein echter Turn - Karte darauf ist ein Test", en: "driver built, no real turn yet - a card on it is a test" },
  "engines.cfg": { de: "Konfiguration", en: "Configuration" },
  "engines.cfg.exe": { de: "Programmpfad (leer = automatisch)", en: "Executable path (empty = auto)" },
  "engines.cfg.env": { de: "Umgebung, eine Zeile je KEY=WERT", en: "Environment, one KEY=VALUE per line" },
  "engines.cfg.save": { de: "Speichern", en: "Save" },
  "engines.cfg.reset": { de: "Überschreibung entfernen", en: "Remove override" },
  "engines.cfg.saved": { de: "Gespeichert", en: "Saved" },
  "engines.install": { de: "Installieren:", en: "Install:" },
  "engines.enable": { de: "{name} einschalten", en: "Enable {name}" },
  "settings.voice.hint": {
    de: "Wenn eine Karte deine Entscheidung braucht, liest das Handy die Meldung vor - normale Audiowiedergabe, läuft also auch über eine per Bluetooth verbundene Brille. Nur solange die App läuft.",
    en: "When a card needs your call, the phone reads the notification aloud - ordinary audio playback, so it also plays through Bluetooth-connected glasses. Only while the app is running.",
  },
};
