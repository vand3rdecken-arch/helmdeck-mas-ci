import type { Dict } from "../index";

/** Keys for the composer surface. Owned by that area - keep additions here so the
 *  dict never becomes a merge bottleneck. Every key needs BOTH languages.
 *
 *  Also carries the surfaces that hang off the composer: the board copilot chat
 *  (chat.*), the new-card sheet (new.*), the command palette (palette.*) and the
 *  attachment pipeline's user-facing refusals (attach.*). Chrome vocabulary
 *  (nav.* / status.* / ui.*) is reused from dict/chrome.ts, not duplicated. */
export const composer: Dict = {
  // -- composer ------------------------------------------------------------
  "composer.placeholder": { de: "Nachricht an den Agenten…", en: "Message to the agent…" },
  "composer.seeAttachment": { de: "Siehe Anhang.", en: "See attachment." },
  "composer.attach": { de: "Anhang", en: "Attachment" },
  "composer.addAttachment": { de: "Anhang hinzufügen", en: "Add attachment" },
  "composer.removeAttachment": { de: "{name} entfernen", en: "Remove {name}" },
  "composer.notAttached": { de: "Nicht angehängt", en: "Not attached" },
  "composer.queued": { de: "In Warteschlange — jetzt senden / bearbeiten",
                       en: "Queued — send now / edit" },
  "composer.sendNow": { de: "Jetzt senden", en: "Send now" },

  // attachment source sheet
  "composer.takePhoto": { de: "Foto aufnehmen", en: "Take photo" },
  "composer.pickImage": { de: "Aus Fotos wählen", en: "Choose from photos" },
  "composer.pickImageWeb": { de: "Bild wählen", en: "Choose image" },
  "composer.pickFile": { de: "Datei wählen", en: "Choose file" },
  "composer.attachLimits": { de: "max. {n} Anhänge · {mb} MB pro Datei",
                             en: "max. {n} attachments · {mb} MB per file" },
  "composer.attachPasteDrop": { de: " · Einfügen und Ablegen gehen auch",
                                en: " · paste and drop work too" },

  // model picker
  "composer.model": { de: "MODELL", en: "MODEL" },
  "composer.modelAutoShort": { de: "Auto", en: "Auto" },
  "composer.modelAuto": { de: "Auto (nach Aufgabe wählen)", en: "Auto (route by task)" },

  // thinking budget (the ids stay technical - these are only the button labels)
  "composer.thinkOff": { de: "aus", en: "off" },
  "composer.thinkOn": { de: "denken", en: "think" },
  "composer.thinkHard": { de: "hart", en: "hard" },
  "composer.thinkUltra": { de: "ultra", en: "ultra" },

  // -- attachments (thrown/returned from data/attachments.ts, shown as alerts) --
  "attach.noPhotoAccess": { de: "Kein Zugriff auf die Fotos erlaubt.",
                            en: "No access to the photo library." },
  "attach.noCameraAccess": { de: "Kein Zugriff auf die Kamera erlaubt.",
                             en: "No access to the camera." },
  "attach.tooBig": { de: "{names}: über {mb} MB", en: "{names}: over {mb} MB" },
  "attach.tooMany": { de: "{n} weitere: max. {max} Anhänge",
                      en: "{n} more: max. {max} attachments" },

  // -- Henry (board agent) chat --------------------------------------------------
  "chat.title": { de: "Henry", en: "Henry" },
  "chat.placeholder": { de: "Frage…", en: "Question…" },
  "chat.empty": { de: "Frag Henry über die Arbeit.", en: "Ask Henry about the work." },
  "chat.teamOnly": { de: "Henry ist nur für das Team.", en: "Henry is for the team only." },
  "chat.thinking": { de: "denkt nach", en: "thinking" },
  "chat.noReply": { de: "(keine Antwort)", en: "(no reply)" },
  "chat.latest": { de: "Neueste", en: "Latest" },
  "chat.close": { de: "Chat schließen", en: "Close chat" },
  // {cost} arrives pre-rendered: planLabel() on the flat plan ("KI ~x % vom
  // Abo" / "KI 34k Tok"), the measured "AI $x.xx" on a metered plan.
  "chat.usage": { de: "PM-Session · {turns} Turns · {cost}", en: "PM session · {turns} turns · {cost}" },

  // -- voice mode (ui/voice_mode.tsx) ---------------------------------------
  // Deliberately SHORT: these are read at a glance, or not at all — the surface
  // is meant to be listened to. The state line replaces itself constantly, so a
  // sentence there would never be finished reading before it changed.
  "voice.title": { de: "Sprachmodus", en: "Voice mode" },
  "voice.open": { de: "Sprachmodus", en: "Voice mode" },
  "voice.close": { de: "Sprachmodus beenden", en: "End voice mode" },
  "voice.orb": { de: "Sprechen oder unterbrechen", en: "Speak or interrupt" },
  "voice.you": { de: "Du", en: "You" },
  "voice.listening": { de: "Ich höre zu…", en: "Listening…" },
  "voice.thinking": { de: "Henry denkt nach…", en: "Henry is thinking…" },
  "voice.thinkingSecs": { de: "Henry denkt nach… {s}s", en: "Henry is thinking… {s}s" },
  "voice.speaking": { de: "Henry antwortet", en: "Henry is answering" },
  "voice.tapToTalk": { de: "Tippen und sprechen", en: "Tap and speak" },
  "voice.transcript": { de: "Verlauf", en: "Transcript" },
  "voice.transcriptEmpty": { de: "Noch nichts gesprochen.", en: "Nothing spoken yet." },
  "voice.handsOn": { de: "Freihändig — Henry hört nach jeder Antwort weiter zu",
                     en: "Hands-free — Henry keeps listening after each answer" },
  "voice.handsOff": { de: "Zum Sprechen tippen", en: "Tap to speak" },
  "voice.hintHands": { de: "Läuft weiter. Tippen unterbricht Henry.",
                       en: "Keeps going. Tap to interrupt Henry." },
  "voice.hintPush": { de: "Tippen zum Sprechen, nochmal tippen zum Senden.",
                      en: "Tap to speak, tap again to send." },
  // Failure copy: each says what is still possible, never only what broke.
  "voice.denied": { de: "Kein Mikrofonzugriff — in den Systemeinstellungen erlauben.",
                    en: "No microphone access — allow it in system settings." },
  "voice.failed": { de: "Spracherkennung hat nicht geklappt. Nochmal tippen.",
                    en: "Speech recognition failed. Tap to retry." },
  "voice.noAudio": { de: "Antwort da, aber ohne Ton — sie steht im Verlauf.",
                     en: "Answer received, but silent — it is in the transcript." },
  "voice.speakOnly": { de: "Dieses Gerät kann noch nicht zuhören — Henry liest nur vor.",
                       en: "This device cannot listen yet — Henry only reads aloud." },

  // -- new card ------------------------------------------------------------
  "new.title": { de: "Neue Karte", en: "New card" },
  "new.rejected": { de: "Abgelehnt", en: "Rejected" },
  "new.taskRequired": { de: "Bitte gib zuerst eine Aufgabe ein.", en: "Please enter a task first." },
  "new.willFork": { de: "→ wird abgezweigt", en: "→ will be forked" },
  "new.examples": { de: "beispiel-aufgaben", en: "example tasks" },
  "new.adoptSession": { de: "Bestehende Claude-Session übernehmen",
                        en: "Adopt an existing Claude session" },
  "new.readingSessions": { de: "lese ~/.claude…", en: "reading ~/.claude…" },
  "new.noSessions": { de: "keine Sessions gefunden.", en: "no sessions found." },
  "new.session": { de: "Session", en: "session" },
  "new.noText": { de: "(kein Text)", en: "(no text)" },
  "new.firstInstruction": { de: "erste anweisung (optional)", en: "first instruction (optional)" },
  "new.taskLabel": { de: "was soll getan werden?", en: "what should be done?" },
  "new.taskPlaceholder": { de: "Beschreibe die Aufgabe…", en: "Describe the task…" },
  "new.repo": { de: "repo", en: "repo" },
  "new.repoPlaceholder": { de: "Pfad / default", en: "path / default" },
  "new.priority": { de: "priorität", en: "priority" },
  "new.due": { de: "fällig (YYYY-MM-DD)", en: "due (YYYY-MM-DD)" },
  "new.value": { de: "wert (€)", en: "value (€)" },
  "new.client": { de: "kunde", en: "customer" },
  "new.clientPlaceholder": { de: "Kunde", en: "Customer" },
  "new.driver": { de: "driver", en: "driver" },
  "new.adopt": { de: "Übernehmen", en: "Adopt" },

  // example chips - the label AND the task text they seed into the input
  "new.ex.bugfix": { de: "Bugfix", en: "bug fix" },
  "new.ex.bugfixTask": {
    de: "Fix: Die Kapazitätsanzeige im Dashboard zeigt 0 %, wenn das Touch-Budget 0 ist - fange die Division ab und zeige stattdessen einen Hinweis.",
    en: "Fix: the dashboard capacity gauge shows 0% when touch budget is 0 - guard the division and show a hint instead.",
  },
  "new.ex.feature": { de: "Feature", en: "feature" },
  "new.ex.featureTask": {
    de: "Füge der Arbeitstabelle im Dashboard einen CSV-Export-Button hinzu (alle Spalten, aktuelle Filter angewendet).",
    en: "Add a CSV export button to the dashboard work table (all columns, current filters applied).",
  },
  "new.ex.desktop": { de: "Desktop-Aufgabe", en: "desktop task" },
  "new.ex.desktopTask": {
    de: "Öffne das Rechnungstool, exportiere Juni als PDF nach Downloads und prüfe, dass die Datei existiert.",
    en: "Open the invoice tool, export June as PDF into Downloads, and verify the file exists.",
  },
  "new.ex.browser": { de: "Browser-Aufgabe", en: "browser task" },
  "new.ex.browserTask": {
    de: "Geh ins Lieferantenportal, lade die aktuelle Preisliste herunter und fasse zusammen, was sich gegenüber data/prices.csv geändert hat.",
    en: "Go to the supplier portal, download the latest price list, and summarize what changed vs the file in data/prices.csv.",
  },
  "new.ex.research": { de: "Recherche", en: "research" },
  "new.ex.researchTask": {
    de: "Lies die drei Wettbewerber-Changelogs, die in docs/watchlist.md verlinkt sind, und schreibe eine einseitige Zusammenfassung, was diesen Monat ausgeliefert wurde.",
    en: "Read the three competitor changelogs linked in docs/watchlist.md and write a one-page summary of what shipped this month.",
  },

  // -- command palette -----------------------------------------------------
  "palette.placeholder": { de: "Karte oder Ansicht springen…  ( > für Henry-Befehl )",
                           en: "Jump to a card or view…  ( > for a Henry command )" },
  "palette.copilotThinking": { de: "Henry denkt…", en: "Henry is thinking…" },
  "palette.copilotHint": { de: "Enter sendet an Henry",
                           en: "Enter sends to Henry" },
  "palette.nothingFound": { de: "Nichts gefunden.", en: "Nothing found." },
  "palette.footer": { de: "↑↓ wählen · Enter öffnen · > Henry · Esc schließen",
                      en: "↑↓ select · Enter open · > Henry · Esc close" },
  "palette.newRequest": { de: "Neue Anfrage", en: "New request" },

  // view hints (the labels reuse nav.*)
  "palette.hint.board": { de: "Kanban", en: "Kanban" },
  "palette.hint.dashboard": { de: "Ökonomie", en: "Economics" },
  "palette.hint.history": { de: "Git-Verlauf", en: "Git history" },
  "palette.hint.processes": { de: "Pipelines", en: "Pipelines" },
  "palette.hint.sessions": { de: "Claude-Sessions", en: "Claude sessions" },
  "palette.hint.automation": { de: "Loop / Night-Shift", en: "Loop / night shift" },
  "palette.hint.new": { de: "Karte anlegen", en: "Create card" },
};
