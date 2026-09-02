import type { Dict } from "../core";

/**
 * HENRY'S RULES, in the owner's words (harness-config-ui phase 3).
 *
 * Every labelKey/descKey declared in spine/registry/behavior.py lives here.
 * Phase 2 declared all 64 of them and shipped none, so every row would have
 * rendered its own key - which is exactly what test_harness_layer's
 * two-language contract exists to catch.
 *
 * TWO RULES THE WORDING FOLLOWS, both from the design doc:
 *
 *  - NO INTERNAL JARGON (section 7.1). Stations are Karte/Arbeit/Abnahme, never
 *    Lane/Gate/Worktree. Henry's own brief forbids him those words in the
 *    owner's chat (tone.jargon); the screen that shows that rule holds itself
 *    to it too. "Snapshot", "Broker", "Overlay" and "Slot" do not appear below.
 *
 *  - ONE SENTENCE SAYING WHAT IT DOES, mandatory. A row without it is a switch
 *    the owner has to flip to find out - and the whole complaint this card
 *    answers was "his rules are somewhere and I cannot see them". The
 *    description says what changes, in the concrete, not what the knob is
 *    called again in longer words.
 *
 * The `why` sentence and the source file are NOT here: they are the rule's own,
 * declared beside it in the daemon and passed through, so the reason a lock is
 * a lock cannot drift away from the lock.
 */
export const harnessRules: Dict = {
  // ------------------------------------------------------ the screen itself --
  "harness.page": { de: "Harness", en: "Harness" },
  "harness.pageSub": { de: "So arbeitet dieses Projekt.", en: "How this project works." },
  "harness.navStations": { de: "Stationen", en: "Stations" },
  "harness.navHenry": { de: "Henry", en: "Henry" },
  "harness.navMachine": { de: "Die Maschine", en: "The machine" },
  "harness.navLaws": { de: "Grundgesetze", en: "Ground rules" },
  "harness.navBuild": { de: "Build-Loop", en: "Build loop" },
  "harness.navBriefs": { de: "Briefe", en: "Briefs" },
  "harness.knobCount": { de: "{n} Knöpfe", en: "{n} settings" },
  "harness.knobOne": { de: "1 Knopf", en: "1 setting" },
  "harness.noKnobs": {
    de: "Diese Station hat keine Knöpfe — sie läuft, wie sie läuft.",
    en: "This station has no settings — it runs the way it runs.",
  },
  "harness.projectScope": {
    de: "Du siehst die Werte für dieses Projekt. Ohne Projekt gelten die des Arbeitsbereichs.",
    en: "You are seeing this project's values. With no project the workspace values apply.",
  },
  "harness.saveFailed": { de: "Nicht übernommen", en: "Not applied" },

  // Section headings for the knobs that MOVED onto a station page (section 6).
  // Their own, not the ones they wore in Automation/System: a group id that
  // straddled a door and a station would draw one heading in two places and
  // imply the rows still belong together.
  "harness.grp.backlog": { de: "Wann eine Karte losläuft", en: "When a card starts" },
  "harness.grp.review": { de: "Wenn die Arbeit fertig ist", en: "When work is done" },

  // The badge vocabulary. "Geerbt" and "Für dieses Projekt gesetzt" are the
  // GitHub org->repo wording, which is where the owner has already learned it.
  "rule.layer.default": { de: "Standard", en: "Default" },
  "rule.layer.seed": { de: "Grundeinstellung", en: "Seed" },
  "rule.layer.workspace": { de: "Geerbt vom Arbeitsbereich", en: "Inherited from workspace" },
  "rule.layer.project": { de: "Für dieses Projekt gesetzt", en: "Set for this project" },
  "rule.reset": { de: "zurücksetzen", en: "reset" },
  "rule.locked": { de: "Fest", en: "Fixed" },
  "rule.perSurface": { de: "Pro Oberfläche ({n})", en: "Per surface ({n})" },
  "rule.additiveOnly": {
    de: "Du kannst Dateien hinzufügen, aber keine streichen.",
    en: "You may add files, but not remove any.",
  },
  "rule.proseOnly": {
    de: "Steht als Text in seinem Brief.",
    en: "Stated as prose in his brief.",
  },
  "rule.freeTextHint": { de: "Eine Regel pro Zeile", en: "One rule per line" },
  "rule.needsProject": {
    de: "Diese Regel gilt pro Projekt — wähle oben ein Projekt, um sie hier zu setzen.",
    en: "This rule is per project — pick a project above to set it here.",
  },

  // ---------------------------------------------------------------- blocks --
  "harness.blk.tone": { de: "Ton & Länge", en: "Tone & length" },
  "harness.blk.tone.desc": {
    de: "Wie Henry klingt und wie viel er schreibt, wenn du nichts anderes sagst.",
    en: "How Henry sounds, and how much he writes when you say nothing else.",
  },
  "harness.blk.initiative": { de: "Eigeninitiative", en: "Initiative" },
  "harness.blk.initiative.desc": {
    de: "Was er von sich aus tut, statt auf deinen Zug zu warten.",
    en: "What he does on his own instead of waiting for your move.",
  },
  "harness.blk.hands": { de: "Was er selbst darf", en: "What he may do himself" },
  "harness.blk.hands.desc": {
    de: "Wo er selbst zugreift — und wo eine Grenze fest ist, auch für ihn.",
    en: "Where he acts himself — and where a limit is fixed, for him too.",
  },
  "harness.blk.report": { de: "Melden & Fragen", en: "Reporting & asking" },
  "harness.blk.report.desc": {
    de: "Wann er sich meldet, wie oft er nachfasst und wie knapp eine Meldung ist.",
    en: "When he reports in, how often he follows up, how terse a notice is.",
  },
  "harness.blk.memory": { de: "Gedächtnis", en: "Memory" },
  "harness.blk.memory.desc": {
    de: "Was er sich über Gespräche hinweg merkt.",
    en: "What he remembers across conversations.",
  },

  // ------------------------------------------------------------------ tone --
  "rule.tone.length": { de: "Antwortlänge", en: "Answer length" },
  "rule.tone.length.desc": {
    de: "Wie viel Henry schreibt, wenn du nichts anderes sagst. Pro Oberfläche verschieden — gesprochen und auf der Uhr ist er knapper als im Chat.",
    en: "How much Henry writes by default. Different per surface — spoken and on the watch he is terser than in chat.",
  },
  "rule.tone.address": { de: "Anrede", en: "Form of address" },
  "rule.tone.address.desc": {
    de: "Ob Henry dich duzt oder siezt.",
    en: "Whether Henry addresses you informally or formally.",
  },
  "rule.tone.language": { de: "Sprache", en: "Language" },
  "rule.tone.language.desc": {
    de: "Die Sprache, in der Henry antwortet.",
    en: "The language Henry answers in.",
  },
  "rule.tone.humor": { de: "Trockener Humor", en: "Dry humour" },
  "rule.tone.humor.desc": {
    de: "An: ein trockener Kommentar ist erlaubt. Aus: er sagt es schlicht.",
    en: "On: a dry aside is allowed. Off: he states it plainly.",
  },
  "rule.tone.jargon": { de: "Interne Begriffe vermeiden", en: "Avoid internal terms" },
  "rule.tone.jargon.desc": {
    de: "An: er schreibt Karte, Arbeit, Abnahme — nicht die internen Wörter dafür.",
    en: "On: he writes card, work, acceptance — not the internal words for them.",
  },
  "rule.tone.houseRules": { de: "Eigene Hausregeln", en: "Your own house rules" },
  "rule.tone.houseRules.desc": {
    de: "Freitext, den Henry zusätzlich zu allem anderen befolgt. Eine Regel pro Zeile. Er kann damit nur strenger werden, nie nachlässiger.",
    en: "Free text Henry follows on top of everything else. One rule per line. It can only make him stricter, never laxer.",
  },
  "rule.tone.examples": { de: "Beispiel-Dialoge", en: "Example dialogues" },
  "rule.tone.examples.desc": {
    de: "Die Gut/Schlecht-Paare in seinem Brief. Sie sind die eigentliche Tonvorgabe und bleiben Prosa.",
    en: "The good/bad pairs in his brief. They are the actual tone spec and stay prose.",
  },

  // ------------------------------------------------------------ initiative --
  "rule.init.estimate": { de: "Dauer schätzen und dich freigeben", en: "Estimate, and release you" },
  "rule.init.estimate.desc": {
    de: "An: er sagt, wie lange es dauert, und dass du nicht warten musst — die Rückmeldung kommt aufs Handy.",
    en: "On: he says how long it takes and that you need not wait — the reply reaches your phone.",
  },
  "rule.init.progress": { de: "Zwischenstand ungefragt", en: "Unprompted progress" },
  "rule.init.progress.desc": {
    de: "An: wenn du zurückkommst, sagt er von selbst, wie weit es ist.",
    en: "On: when you come back he says where things stand, unasked.",
  },
  "rule.init.finish": { de: "Fertige Karten selbst abschließen", en: "Finish cards himself" },
  "rule.init.finish.desc": {
    de: "An: ist die Arbeit fertig und die Prüfung grün, nimmt er sie selbst ab. Aus: er legt sie dir zur Abnahme hin. Die Prüfung läuft in beiden Fällen.",
    en: "On: when work is done and the check is green he accepts it himself. Off: he hands it to you. The check runs either way.",
  },
  "rule.init.questions": { de: "Rückfragen bei unklarem Auftrag", en: "Questions when unclear" },
  "rule.init.questions.desc": {
    de: "Wie viele Fragen er bei einem großen oder vagen Auftrag stellt, bevor er anfängt. 0 heißt: er legt mit dem los, was dasteht.",
    en: "How many questions he asks on a big or vague request before starting. 0 means he starts with what he was given.",
  },
  "rule.init.stale": { de: "Alte Karten gegen Neueres prüfen", en: "Check old cards against newer facts" },
  "rule.init.stale.desc": {
    de: "An: der neuere Befund gewinnt, statt dass er den alten Kartentext als Lage zitiert.",
    en: "On: newer evidence wins instead of him quoting an old card's text as the current state.",
  },
  "rule.init.repoDefault": { de: "Standardweg für Änderungen am Code", en: "Default route for code changes" },
  "rule.init.repoDefault.desc": {
    de: "Direkt: er ändert im Projekt selbst. Getrennt: er arbeitet in einer eigenen Kopie und legt sie dir zur Durchsicht vor.",
    en: "Direct: he changes the project itself. Separate: he works in his own copy and submits it for review.",
  },

  // ----------------------------------------------------------------- hands --
  "rule.hands.own": { de: "Eigene Hände für Kleinkram", en: "His own hands for small things" },
  "rule.hands.own.desc": {
    de: "An: einen Einzeiler, einen falschen Wert, ein hängendes Skript erledigt er sofort selbst. Aus: er gibt auch das ab.",
    en: "On: a one-liner, a wrong value, a stuck script he fixes himself on the spot. Off: he hands even that on.",
  },
  "rule.hands.protected": { de: "Geschützte Dateien", en: "Protected files" },
  "rule.hands.protected.desc": {
    de: "Dateien, die Henry nie selbst anfasst. Du kannst welche hinzufügen, aber keine streichen.",
    en: "Files Henry never touches himself. You may add to this list, never shorten it.",
  },
  "rule.hands.allowlist": { de: "Was er per Chat einstellen darf", en: "What he may configure by chat" },
  "rule.hands.allowlist.desc": {
    de: "Die Einstellungen, die Henry auf Zuruf ändern darf. Fest — der Server prüft dieselbe Liste noch einmal.",
    en: "The settings Henry may change on request. Fixed — the server checks the same list again.",
  },
  "rule.hands.delete": { de: "Löschen ohne Auftrag", en: "Deleting unasked" },
  "rule.hands.delete.desc": {
    de: "Zerstörendes ohne klaren Auftrag bleibt bei dir. Das ist keine Einstellung.",
    en: "Destructive work without a clear request stays with you. This is not a setting.",
  },
  "rule.hands.pmode": { de: "Schreibrechte im Gespräch", en: "Write access during a turn" },
  "rule.hands.pmode.desc": {
    de: "Ob Henry im laufenden Gespräch wirklich schreiben darf oder erst einen Plan vorlegt. Gilt auch, wenn er sich selbst meldet.",
    en: "Whether Henry may really write during a turn or must present a plan first. Also applies when he reports in himself.",
  },
  "rule.hands.maySwap": { de: "Henry darf Regeln selbst ändern", en: "Henry may change rules himself" },
  "rule.hands.maySwap.desc": {
    de: "Aus: er darf eine Änderung vorschlagen, ausführen musst du sie. An: er darf sie selbst setzen.",
    en: "Off: he may propose a change, you carry it out. On: he may set it himself.",
  },

  // ---------------------------------------------------------------- report --
  "rule.report.interval": { de: "Nachfass-Abstand", en: "Follow-up interval" },
  "rule.report.interval.desc": {
    de: "Sekunden, die er auf eine Antwort wartet, bevor er noch einmal nachfasst.",
    en: "Seconds he waits for an answer before following up again.",
  },
  "rule.report.attempts": { de: "Nachfass-Versuche", en: "Follow-up attempts" },
  "rule.report.attempts.desc": {
    de: "Wie oft er es allein versucht, bevor er dich weckt.",
    en: "How often he tries alone before waking you.",
  },
  "rule.report.dedupe": { de: "Doppelmeldungen unterdrücken", en: "Suppress duplicate notices" },
  "rule.report.dedupe.desc": {
    de: "Sekunden, in denen dieselbe Meldung nicht ein zweites Mal kommt.",
    en: "Seconds within which the same notice will not arrive twice.",
  },
  "rule.report.noticeChars": { de: "Meldung: Zeichen", en: "Notice: characters" },
  "rule.report.noticeChars.desc": {
    de: "Wie lang eine automatische Meldung höchstens ist — für Kanäle, in denen du nicht scrollen kannst.",
    en: "The longest an automatic notice may be — for channels you cannot scroll.",
  },
  "rule.report.noticeSentences": { de: "Meldung: Sätze", en: "Notice: sentences" },
  "rule.report.noticeSentences.desc": {
    de: "Dasselbe in Sätzen. Steht neben den anderen Längen, damit du sie überhaupt vergleichen kannst.",
    en: "The same in sentences. Sits beside the other lengths so you can compare them at all.",
  },
  "rule.report.deadEnd": { de: "Nie „kann ich nicht“", en: "Never “I can't”" },
  "rule.report.deadEnd.desc": {
    de: "Henry endet nie in einer Sackgasse: er nennt den Weg, der offen ist, oder was du entscheiden musst.",
    en: "Henry never dead-ends: he names the route that is open, or what you must decide.",
  },

  // ---------------------------------------------------------------- memory --
  "rule.memory.enabled": { de: "Notizen anlegen", en: "Keep notes" },
  "rule.memory.enabled.desc": {
    de: "An: was dauerhaft wichtig ist — eine Entscheidung, eine Vorliebe, ein laufendes Vorhaben — schreibt er sich auf.",
    en: "On: what matters lastingly — a decision, a preference, ongoing work — he writes down.",
  },
  "rule.memory.path": { de: "Wo die Notizen liegen", en: "Where the notes live" },
  "rule.memory.path.desc": {
    de: "Der Ordner auf diesem Rechner. Er ergibt sich aus dem Prozess, nicht aus einer Einstellung.",
    en: "The folder on this machine. It follows from the process, not from a setting.",
  },
};
