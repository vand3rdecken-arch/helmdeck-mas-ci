// Public pages for the Jira app "Label-Doktor", served under /apps/label-doktor/.
//
// Why here: the Atlassian Marketplace requires a paid app to point at public
// support, documentation, privacy and terms pages on the vendor's own domain.
// The shape is the one this worker already uses for /datenschutz and /impressum:
// a pathname route per page, one HTML string per page, no <script> and no
// analytics on them, DE first and EN below the same #en anchor. Nothing here
// needs JavaScript, so these pages inherit the worker's strict CSP for free.
//
// Every statement about what the app does is taken from the app source in
// Documents/Private Project/jira-label-doktor/app/src (manifest scopes,
// logic/normalize.js, logic/ai.js, logic/undo.js, forge/llm.js,
// services/license.js, services/cleanup.js, services/settings.js).
// Do not add a claim here that the code does not back.

// Mirrors LEGAL_STYLE in index.js so the app pages read as the same product.
const STYLE = `body{background:#0E0F10;color:#E4E6E6;font:16px/1.6 system-ui,sans-serif;
max-width:720px;margin:0 auto;padding:40px 20px}h1{font-size:26px}h2{font-size:19px;
margin-top:32px}h3{font-size:16px}a{color:#6CB2EC}hr{border:0;border-top:1px solid #222425;
margin:40px 0}.muted{color:#959A9D}code{background:#1A1C1D;padding:1px 5px;border-radius:3px}
ul{padding-left:22px}li{margin:4px 0}`;

const NAV = `<p class=muted><a href="/apps/label-doktor/">Label-Doktor</a> &middot;
<a href="/apps/label-doktor/docs">Doku / Docs</a> &middot;
<a href="/apps/label-doktor/support">Support</a> &middot;
<a href="/apps/label-doktor/privacy">Datenschutz / Privacy</a> &middot;
<a href="/apps/label-doktor/terms">Nutzungsbedingungen / Terms</a></p>`;

const STAND = "Stand: 10. Oktober 2026, App-Version 2.0.0.";
const ASOF = "Last updated: 10 October 2026, app version 2.0.0.";

function page(title, body) {
  return `<!doctype html><html lang=de><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>${STYLE}</style>
${NAV}
<hr>
${body}
</html>`;
}

// ---------------------------------------------------------------- overview

const INDEX_HTML = page("Label-Doktor für Jira Cloud: Übersicht", `
<h1>Label-Doktor für Jira Cloud</h1>
<p class=muted>${STAND} <a href="#en">English version below</a></p>

<p>Label-Doktor findet Labels in Jira Cloud, die dasselbe bedeuten, und führt sie
nach Bestätigung durch eine Jira Administratorin oder einen Jira Administrator
zusammen. Die App ist eine Atlassian Forge App. Sie läuft vollständig auf der
Infrastruktur von Atlassian und schickt keine Daten an eigene Server.</p>

<h2>Seiten</h2>
<ul>
<li><a href="/apps/label-doktor/docs">Dokumentation</a>: Installation, Scan,
Vorschau, Zusammenführen, Rückgängig, KI, Einstellungen, Berechtigungen.</li>
<li><a href="/apps/label-doktor/support">Support</a>: wie Sie Hilfe bekommen.</li>
<li><a href="/apps/label-doktor/privacy">Datenschutz</a>: welche Daten die App
verarbeitet und wie lange.</li>
<li><a href="/apps/label-doktor/terms">Nutzungsbedingungen</a>.</li>
</ul>

<h2>Kontakt</h2>
<ul>
<li>Support: <a href="mailto:support@helmdeck.de">support@helmdeck.de</a></li>
<li>Datenschutz: <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a></li>
<li>Sicherheitsmeldungen: <a href="mailto:security@helmdeck.de">security@helmdeck.de</a></li>
</ul>

<hr>
<h1 id=en>Label-Doktor for Jira Cloud</h1>
<p class=muted>${ASOF}</p>

<p>Label-Doktor finds Jira Cloud labels that mean the same thing and merges them
after a Jira administrator confirms. The app is an Atlassian Forge app. It runs
entirely on Atlassian infrastructure and sends no data to any server of our own.</p>

<h2>Pages</h2>
<ul>
<li><a href="/apps/label-doktor/docs">Documentation</a>: install, scan, preview,
merge, undo, AI, settings, permissions.</li>
<li><a href="/apps/label-doktor/support">Support</a>: how to get help.</li>
<li><a href="/apps/label-doktor/privacy">Privacy</a>: what the app processes and
for how long.</li>
<li><a href="/apps/label-doktor/terms">Terms of use</a>.</li>
</ul>

<h2>Contact</h2>
<ul>
<li>Support: <a href="mailto:support@helmdeck.de">support@helmdeck.de</a></li>
<li>Privacy: <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a></li>
<li>Security reports: <a href="mailto:security@helmdeck.de">security@helmdeck.de</a></li>
</ul>
`);

// ---------------------------------------------------------------- docs

const DOCS_HTML = page("Label-Doktor: Dokumentation / Documentation", `
<h1>Label-Doktor, Dokumentation</h1>
<p class=muted>${STAND} <a href="#en">English version below</a></p>

<h2>1. Was die App macht</h2>
<p>In Jira sammeln sich über die Zeit Labels, die dasselbe meinen: andere
Schreibweise, Trennzeichen, Mehrzahl, Tippfehler oder ein Synonym in einer
anderen Sprache. Label-Doktor liest die vorhandenen Labels mit ihrer Anzahl an
Vorgängen, schlägt Gruppen vor, zeigt eine Vorschau und schreibt erst nach
Bestätigung. Die App ändert ausschließlich das Feld Labels.</p>

<h2>2. Installation und erster Scan</h2>
<ul>
<li>Die App wird aus dem Atlassian Marketplace in eine Jira Cloud Instanz
installiert. Es gibt nichts zu hosten und nichts zu konfigurieren.</li>
<li>Die Oberfläche liegt in der Jira Administration unter Apps, Eintrag
Label-Doktor. Nur Benutzer mit Jira Administrationsrechten sehen sie.</li>
<li>Der Scan liest die Labels der Instanz. Bei vielen Labels läuft er als
Hintergrundauftrag weiter, Sie können die Seite verlassen.</li>
</ul>

<h2>3. Vorschläge, Vorschau, Zusammenführen, Rückgängig</h2>
<p>Jeder Vorschlag ist eine Gruppe: ein Ziellabel und die Labels, die darin
aufgehen sollen. Dazu gehört eine Begründung und eine Sicherheitsangabe.</p>
<ul>
<li><b>Regelstufe 1, Sicherheit hoch</b>: gleiches Wort, es unterscheiden sich
nur Groß und Kleinschreibung, Trennzeichen wie Leerzeichen, Unterstrich,
Bindestrich oder Punkt, Umlaute und Akzente, oder eine einfache englische
Mehrzahl. Beispiel: <code>Payment</code>, <code>payment</code>,
<code>pay_ment</code>, <code>payments</code>.</li>
<li><b>Regelstufe 2, Sicherheit mittel</b>: sehr ähnliche Schreibweise, also ein
möglicher Tippfehler. Erlaubt ist ein Abstand von einem Zeichen bei kurzen
Labels und zwei Zeichen ab acht Zeichen Länge. Labels, die sich nur in Ziffern
unterscheiden, werden nie zusammengelegt, <code>test1</code> und
<code>test2</code> bleiben also getrennt.</li>
<li><b>KI Vorschläge</b>: Synonyme und Übersetzungen, die keine Regel findet.
Siehe Abschnitt 4.</li>
</ul>
<p>Als Ziellabel schlägt die App das Label mit den meisten Vorgängen vor. Sie
können jede Gruppe ablehnen und das Ziel ändern. Die Vorschau zeigt vor dem
Schreiben, welche Vorgänge betroffen sind.</p>
<p>Rückgängig: die App schreibt zuerst ein Protokoll und ändert dann die
Vorgänge. Innerhalb von 30 Tagen können Sie einen Lauf zurücknehmen. Dabei wird
ein Vorgang nur dann zurückgesetzt, wenn seine Labels seit dem Lauf unverändert
sind. Vorgänge, die inzwischen jemand anders geändert hat, bleiben unangetastet
und werden als übersprungen aufgeführt.</p>

<h2>4. KI im Detail</h2>
<ul>
<li>Die KI läuft über Forge LLM, also innerhalb der Atlassian Plattform. Es gibt
keinen eigenen Zugang zu einem KI Anbieter und keinen eigenen Serverweg.</li>
<li>Die KI bekommt ausschließlich Labelnamen und die Anzahl der Vorgänge je
Label, dazu eine feste Anweisung. Sie bekommt keine Vorgangsinhalte, keine
Kommentare, keine Namen von Personen und keine Anhänge.</li>
<li>Die Antwort wird geprüft: unbekannte oder doppelte Labels werden verworfen,
Gruppen mit weniger als zwei Labels ebenso. Die KI darf nur vorschlagen, nie
schreiben.</li>
<li>Die KI kann in den Einstellungen abgeschaltet werden. Fällt der KI Aufruf
aus, bleiben die Regelvorschläge erhalten.</li>
<li>Die KI Vorschläge sind der Teil, der eine aktive Lizenz braucht. Alles
andere ist kostenfrei nutzbar.</li>
</ul>

<h2>5. Einstellungen</h2>
<ul>
<li><b>KI aktiv</b>: ein oder aus. Voreinstellung ein.</li>
<li><b>KI Läufe pro Tag</b>: Obergrenze, Voreinstellung 5, höchster Wert 50. Der
Wert begrenzt die Kosten und wird täglich zurückgesetzt.</li>
<li><b>Ausgenommene Projekte</b>: Liste von Projektschlüsseln, die der Scan und
das Zusammenführen auslassen.</li>
</ul>

<h2>6. Berechtigungen</h2>
<p>Die App fragt genau diese Rechte an:</p>
<ul>
<li><code>read:jira-work</code> und <code>read:label:jira</code>: Labels und die
betroffenen Vorgänge lesen.</li>
<li><code>write:jira-work</code>: Labels an Vorgängen schreiben. Nur dieses Feld
wird geändert.</li>
<li><code>storage:app</code>: Einstellungen, Aufträge und das Rückgängig
Protokoll im Speicher der App innerhalb von Atlassian ablegen.</li>
</ul>

<h2>7. Datenschutz</h2>
<p>Siehe <a href="/apps/label-doktor/privacy">Datenschutzseite</a>.</p>

<h2>8. Nutzungsbedingungen</h2>
<p>Siehe <a href="/apps/label-doktor/terms">Nutzungsbedingungen</a>.</p>

<h2>9. Fehlersuche</h2>
<ul>
<li><b>Ich sehe die App nicht</b>: die Oberfläche liegt in der Jira
Administration unter Apps und ist nur für Jira Administratoren sichtbar.</li>
<li><b>Keine Vorschläge</b>: dann gibt es keine Labels, die nach den Regeln
zusammenpassen. Prüfen Sie, ob die betroffenen Projekte in den Einstellungen
ausgenommen sind.</li>
<li><b>Keine KI Vorschläge</b>: KI in den Einstellungen abgeschaltet, Tageslimit
erreicht, oder keine aktive Lizenz.</li>
<li><b>Ein Vorgang wurde beim Rückgängig übersprungen</b>: seine Labels haben
sich seit dem Lauf geändert. Das ist Absicht, damit die App keine fremde
Änderung überschreibt.</li>
<li><b>Scan oder Lauf hängt</b>: lange Läufe arbeiten als Hintergrundauftrag.
Laden Sie die Seite neu, um den Stand zu sehen. Bleibt er stehen, schreiben Sie
an <a href="mailto:support@helmdeck.de">support@helmdeck.de</a>.</li>
</ul>

<h2>10. Versionshinweise</h2>
<ul>
<li><b>2.0.0</b>, 10. Oktober 2026: Blättern, Suche und Sortierung für lange
Label-Listen, Vorschau als Dialog, Lizenzprüfung für die KI Vorschläge.</li>
</ul>

<h2>11. Kontakt</h2>
<p>Support <a href="mailto:support@helmdeck.de">support@helmdeck.de</a>,
Datenschutz <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a>,
Sicherheit <a href="mailto:security@helmdeck.de">security@helmdeck.de</a>.</p>

<hr>
<h1 id=en>Label-Doktor, documentation</h1>
<p class=muted>${ASOF}</p>

<h2>1. What the app does</h2>
<p>Over time a Jira site collects labels that mean the same thing: a different
spelling, a separator, a plural, a typo, or a synonym in another language.
Label-Doktor reads the existing labels with the number of issues per label,
proposes groups, shows a preview and writes only after you confirm. The app
changes the labels field and nothing else.</p>

<h2>2. Install and first scan</h2>
<ul>
<li>Install the app from the Atlassian Marketplace into a Jira Cloud site.
There is nothing to host and nothing to configure.</li>
<li>The screen sits in Jira administration under Apps, entry Label-Doktor. Only
users with Jira administration rights can see it.</li>
<li>The scan reads the labels of the site. With many labels it continues as a
background job, so you can leave the page.</li>
</ul>

<h2>3. Suggestions, preview, merge, undo</h2>
<p>Every suggestion is a group: one target label and the labels that should be
folded into it, plus a reason and a confidence level.</p>
<ul>
<li><b>Rule stage 1, confidence high</b>: the same word, differing only in upper
and lower case, in separators such as space, underscore, hyphen or dot, in
umlauts and accents, or in a simple English plural. Example:
<code>Payment</code>, <code>payment</code>, <code>pay_ment</code>,
<code>payments</code>.</li>
<li><b>Rule stage 2, confidence medium</b>: a very similar spelling, so a
possible typo. One character of distance is allowed for short labels and two
from a length of eight characters. Labels that differ only in digits are never
merged, so <code>test1</code> and <code>test2</code> stay separate.</li>
<li><b>AI suggestions</b>: synonyms and translations that no rule can find. See
section 4.</li>
</ul>
<p>The app proposes the label with the most issues as the target. You can reject
any group and change the target. The preview shows which issues are affected
before anything is written.</p>
<p>Undo: the app writes a log first and changes the issues after. Within 30 days
you can take a run back. An issue is only reverted if its labels are unchanged
since the run. Issues that somebody else has changed in the meantime are left
alone and reported as skipped.</p>

<h2>4. AI in detail</h2>
<ul>
<li>The AI runs through Forge LLM, so inside the Atlassian platform. There is no
own account with an AI provider and no own network path.</li>
<li>The AI receives label names and the number of issues per label only, plus a
fixed instruction. It receives no issue content, no comments, no person names
and no attachments.</li>
<li>The answer is validated: unknown or duplicate labels are discarded, and so
are groups with fewer than two labels. The AI can only propose, never write.</li>
<li>The AI can be switched off in the settings. If an AI call fails, the rule
based suggestions remain.</li>
<li>AI suggestions are the part that needs an active licence. Everything else is
free to use.</li>
</ul>

<h2>5. Settings</h2>
<ul>
<li><b>AI enabled</b>: on or off. Default on.</li>
<li><b>AI runs per day</b>: upper limit, default 5, highest value 50. The limit
caps the cost and resets daily.</li>
<li><b>Excluded projects</b>: a list of project keys that the scan and the merge
skip.</li>
</ul>

<h2>6. Permissions</h2>
<p>The app requests exactly these scopes:</p>
<ul>
<li><code>read:jira-work</code> and <code>read:label:jira</code>: read labels
and the affected issues.</li>
<li><code>write:jira-work</code>: write labels on issues. No other field is
touched.</li>
<li><code>storage:app</code>: keep settings, jobs and the undo log in the app
storage inside Atlassian.</li>
</ul>

<h2>7. Privacy</h2>
<p>See the <a href="/apps/label-doktor/privacy">privacy page</a>.</p>

<h2>8. Terms</h2>
<p>See the <a href="/apps/label-doktor/terms">terms of use</a>.</p>

<h2>9. Troubleshooting</h2>
<ul>
<li><b>I cannot see the app</b>: the screen is in Jira administration under Apps
and is visible to Jira administrators only.</li>
<li><b>No suggestions</b>: then no labels match under the rules. Check whether
the projects in question are excluded in the settings.</li>
<li><b>No AI suggestions</b>: AI switched off in the settings, daily limit
reached, or no active licence.</li>
<li><b>An issue was skipped during undo</b>: its labels changed after the run.
That is deliberate, so the app does not overwrite somebody else's change.</li>
<li><b>Scan or run seems stuck</b>: long runs work as a background job. Reload
the page to see the current state. If it stays put, write to
<a href="mailto:support@helmdeck.de">support@helmdeck.de</a>.</li>
</ul>

<h2>10. Release notes</h2>
<ul>
<li><b>2.0.0</b>, 10 October 2026: paging, search and sorting for long label
lists, preview as a dialog, licence check for the AI suggestions.</li>
</ul>

<h2>11. Contact</h2>
<p>Support <a href="mailto:support@helmdeck.de">support@helmdeck.de</a>, privacy
<a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a>, security
<a href="mailto:security@helmdeck.de">security@helmdeck.de</a>.</p>
`);

// ---------------------------------------------------------------- support

const SUPPORT_HTML = page("Label-Doktor: Support", `
<h1>Label-Doktor, Support</h1>
<p class=muted>${STAND} <a href="#en">English version below</a></p>

<p>Support läuft per E-Mail an
<a href="mailto:support@helmdeck.de">support@helmdeck.de</a>. Es gibt kein
Ticketportal und keine Telefonnummer. Die Sprachen sind Deutsch und Englisch.</p>

<h2>Antwortzeit</h2>
<p>Ziel ist eine Antwort innerhalb von zwei Werktagen, Montag bis Freitag. Das
ist ein Ziel und keine zugesicherte Reaktionszeit. Label-Doktor wird von einer
Einzelperson entwickelt und betreut.</p>

<h2>Bevor Sie schreiben</h2>
<p>Die <a href="/apps/label-doktor/docs">Dokumentation</a> beantwortet die
häufigen Fälle, besonders Abschnitt 9, Fehlersuche.</p>

<h2>Was in die Nachricht gehört</h2>
<ul>
<li><b>Frage zur Bedienung</b>: was Sie erreichen wollen und an welcher Stelle
es nicht weitergeht.</li>
<li><b>Fehlermeldung</b>: was Sie getan haben, was Sie erwartet haben, was
passiert ist, der Wortlaut einer Fehlermeldung, Datum und Uhrzeit mit Zeitzone,
und die Adresse Ihrer Jira Instanz.</li>
<li><b>Datenschutz oder Löschanfrage</b>: an
<a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a>, mit der Adresse
Ihrer Jira Instanz.</li>
<li><b>Sicherheitslücke</b>: an
<a href="mailto:security@helmdeck.de">security@helmdeck.de</a>. Bitte melden Sie
uns zuerst und veröffentlichen Sie nicht sofort.</li>
</ul>

<h2>Was nicht in die Nachricht gehört</h2>
<p>Schicken Sie keine Passwörter, keine API Schlüssel und keine Inhalte aus
Vorgängen. Für die Fehlersuche genügen Labelnamen und die Adresse Ihrer Jira
Instanz. Wir brauchen keinen Zugang zu Ihrer Instanz.</p>

<h2>App deinstallieren</h2>
<p>Die App kann jederzeit in der Jira Administration unter Apps entfernt werden.
Zusammengeführte Labels bleiben danach zusammengeführt, denn sie stehen in Ihren
Vorgängen. Das Rückgängig Protokoll wird mit der App gelöscht, ein Lauf lässt
sich danach nicht mehr über die App zurücknehmen.</p>

<hr>
<h1 id=en>Label-Doktor, support</h1>
<p class=muted>${ASOF}</p>

<p>Support runs by email to
<a href="mailto:support@helmdeck.de">support@helmdeck.de</a>. There is no ticket
portal and no phone line. Languages are German and English.</p>

<h2>Response time</h2>
<p>The aim is an answer within two business days, Monday to Friday. That is a
target and not a guaranteed response time. Label-Doktor is built and maintained
by one person.</p>

<h2>Before you write</h2>
<p>The <a href="/apps/label-doktor/docs">documentation</a> covers the common
cases, in particular section 9, troubleshooting.</p>

<h2>What to put in the message</h2>
<ul>
<li><b>Question about using the app</b>: what you want to achieve and where it
stops working.</li>
<li><b>Bug report</b>: what you did, what you expected, what happened, the
wording of any error message, date and time with time zone, and the address of
your Jira site.</li>
<li><b>Privacy or deletion request</b>: write to
<a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a> with the address of
your Jira site.</li>
<li><b>Security issue</b>: write to
<a href="mailto:security@helmdeck.de">security@helmdeck.de</a>. Please report to
us first rather than publishing straight away.</li>
</ul>

<h2>What not to put in the message</h2>
<p>Do not send passwords, API keys or issue content. Label names and the address
of your Jira site are enough to investigate. We do not need access to your
site.</p>

<h2>Uninstalling</h2>
<p>You can remove the app at any time in Jira administration under Apps. Merged
labels stay merged, because they live in your issues. The undo log is deleted
with the app, so a run can no longer be taken back through the app.</p>
`);

// ---------------------------------------------------------------- privacy

const PRIVACY_HTML = page("Label-Doktor: Datenschutz / Privacy", `
<h1>Label-Doktor, Datenschutz</h1>
<p class=muted>${STAND} <a href="#en">English version below</a></p>

<p>Diese Seite gilt für die Jira Cloud App Label-Doktor. Für die Website
helmdeck.de gilt die <a href="/datenschutz">Datenschutzerklärung von
HelmDeck</a>.</p>

<h2>Verantwortlich</h2>
<p>Tien Duy Vo<br>
*** 6<br>
*** Frankfurt am Main<br>
Deutschland<br>
Kontakt <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a></p>
<p class=muted>Anbieterkennzeichnung: <a href="/impressum">Impressum</a></p>

<h2>Wo die App läuft</h2>
<p>Label-Doktor ist eine Atlassian Forge App. Sie läuft vollständig in der
Forge Umgebung von Atlassian, in derselben Region wie Ihre Jira Instanz. Es gibt
keinen eigenen Server, keine eigene Datenbank, keine Weitergabe an Dritte, keine
Werbenetzwerke, keine Analysedienste und keine Cookies. Daten verlassen die
Atlassian Plattform nicht.</p>

<h2>Was die App verarbeitet</h2>
<ul>
<li><b>Labelnamen und Anzahl der Vorgänge je Label</b>, aus Ihrer Jira
Instanz.</li>
<li><b>Vorgangsschlüssel und Labellisten</b> der Vorgänge, die ein Lauf ändert,
im Rückgängig Protokoll, zusammen mit dem Zeitpunkt und der Atlassian Konto
Kennung der Person, die den Lauf bestätigt hat.</li>
<li><b>Einstellungen</b> der Instanz: KI aktiv, KI Läufe pro Tag, ausgenommene
Projekte.</li>
<li><b>Zähler</b>, wie viele KI Läufe an einem Tag stattgefunden haben.</li>
</ul>
<p>Die App liest und schreibt nur das Feld Labels. Sie liest keine
Beschreibungen, keine Kommentare, keine Anhänge und keine Benutzerprofile.</p>

<h2>Speicherdauer</h2>
<ul>
<li>Aufträge und Rückgängig Protokoll: 30 Tage, danach löscht ein täglicher Lauf
sie automatisch.</li>
<li>KI Zähler: 35 Tage.</li>
<li>Einstellungen: bis Sie sie ändern oder die App entfernen.</li>
<li>Wenn Sie die App deinstallieren, entfernt Atlassian den Speicher der App.</li>
</ul>

<h2>KI</h2>
<p>Die KI Funktion nutzt Forge LLM, einen Dienst innerhalb der Atlassian
Plattform. Übergeben werden nur Labelnamen, die Anzahl der Vorgänge je Label und
eine feste Anweisung. Vorgangsinhalte, Namen von Personen und Anhänge werden
nicht übergeben. Die KI Funktion kann in den Einstellungen abgeschaltet werden.
Für die Verarbeitung durch Forge LLM gelten die Bedingungen von Atlassian.</p>

<h2>Rechtsgrundlage und Rolle</h2>
<p>Für die Daten in Ihrer Jira Instanz sind Sie verantwortlich, die App
verarbeitet sie in Ihrem Auftrag. Grundlage der Verarbeitung ist die Erfüllung
des Nutzungsvertrags, Artikel 6 Absatz 1 Buchstabe b DSGVO.</p>

<h2>Ihre Rechte</h2>
<p>Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der
Verarbeitung, Datenübertragbarkeit und Beschwerde bei einer Aufsichtsbehörde.
Anfragen an <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a>. Eine
Löschung der von der App gespeicherten Daten erreichen Sie sofort selbst, indem
Sie die App deinstallieren.</p>

<h2>Sicherheitsmeldungen</h2>
<p><a href="mailto:security@helmdeck.de">security@helmdeck.de</a></p>

<hr>
<h1 id=en>Label-Doktor, privacy</h1>
<p class=muted>${ASOF}</p>

<p>This page covers the Jira Cloud app Label-Doktor. For the helmdeck.de website
see the <a href="/privacy">HelmDeck privacy policy</a>.</p>

<h2>Controller</h2>
<p>Tien Duy Vo<br>
*** 6<br>
*** Frankfurt am Main<br>
Germany<br>
Contact <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a></p>
<p class=muted>Legal notice: <a href="/imprint">Imprint</a></p>

<h2>Where the app runs</h2>
<p>Label-Doktor is an Atlassian Forge app. It runs entirely in Atlassian's Forge
environment, in the same region as your Jira site. There is no server of our
own, no database of our own, no sharing with third parties, no ad networks, no
analytics and no cookies. Data does not leave the Atlassian platform.</p>

<h2>What the app processes</h2>
<ul>
<li><b>Label names and the number of issues per label</b>, from your Jira
site.</li>
<li><b>Issue keys and label lists</b> of the issues a run changes, in the undo
log, together with the time and the Atlassian account id of the person who
confirmed the run.</li>
<li><b>Settings</b> of the site: AI enabled, AI runs per day, excluded
projects.</li>
<li><b>Counters</b> of how many AI runs happened on a given day.</li>
</ul>
<p>The app reads and writes the labels field only. It does not read
descriptions, comments, attachments or user profiles.</p>

<h2>Retention</h2>
<ul>
<li>Jobs and undo log: 30 days, after which a daily run deletes them
automatically.</li>
<li>AI counters: 35 days.</li>
<li>Settings: until you change them or remove the app.</li>
<li>If you uninstall the app, Atlassian removes the app storage.</li>
</ul>

<h2>AI</h2>
<p>The AI feature uses Forge LLM, a service inside the Atlassian platform. Only
label names, the number of issues per label and a fixed instruction are passed
to it. Issue content, person names and attachments are not passed. The AI
feature can be switched off in the settings. Atlassian's terms apply to the
processing by Forge LLM.</p>

<h2>Legal basis and role</h2>
<p>You are the controller for the data in your Jira site and the app processes
it on your behalf. The basis for the processing is performance of the contract,
Article 6(1)(b) GDPR.</p>

<h2>Your rights</h2>
<p>You have the right of access, rectification, erasure, restriction of
processing, data portability and complaint to a supervisory authority. Send
requests to <a href="mailto:privacy@helmdeck.de">privacy@helmdeck.de</a>. You
can achieve deletion of the data stored by the app immediately yourself by
uninstalling the app.</p>

<h2>Security reports</h2>
<p><a href="mailto:security@helmdeck.de">security@helmdeck.de</a></p>
`);

// ---------------------------------------------------------------- terms

const TERMS_HTML = page("Label-Doktor: Nutzungsbedingungen / Terms", `
<h1>Label-Doktor, Nutzungsbedingungen</h1>
<p class=muted>${STAND} <a href="#en">English version below</a></p>

<h2>1. Vertragsgrundlage</h2>
<p>Für Label-Doktor gilt die Atlassian Marketplace Standard End User License
Agreement in der jeweils geltenden Fassung, veröffentlicht von Atlassian unter
<a href="https://www.atlassian.com/legal/marketplace-end-user-agreement"
rel="noreferrer">atlassian.com/legal/marketplace-end-user-agreement</a>. Es gibt
keine eigene abweichende Lizenzvereinbarung. Die Punkte auf dieser Seite
beschreiben den Leistungsumfang der App und ergänzen die Standardvereinbarung,
sie ersetzen sie nicht. Kauf, Abrechnung, Erneuerung und Erstattung laufen über
Atlassian, nach den Marketplace Bedingungen von Atlassian.</p>

<h2>2. Leistungsumfang</h2>
<p>Label-Doktor findet Jira Labels, die dasselbe bedeuten, und führt sie nach
Bestätigung zusammen. Ohne Lizenz nutzbar sind: Scan der Labels, regelbasierte
Vorschläge, Vorschau, Zusammenführen, Rückgängig innerhalb von 30 Tagen,
Verlauf und Einstellungen. Eine aktive Lizenz braucht ausschließlich die
Funktion KI Vorschläge.</p>

<h2>3. Ihre Mitwirkung</h2>
<ul>
<li>Die App ändert Labels erst, nachdem eine Jira Administratorin oder ein Jira
Administrator die Vorschau bestätigt hat. Die Entscheidung, welche Labels
zusammengeführt werden, liegt bei Ihnen.</li>
<li>Vorschläge sind Vorschläge. Prüfen Sie sie vor der Bestätigung.</li>
<li>Für eigene Datensicherungen Ihrer Jira Instanz sind Sie zuständig. Die
Funktion Rückgängig ist auf 30 Tage begrenzt und ersetzt keine Sicherung.</li>
</ul>

<h2>4. Verfügbarkeit</h2>
<p>Die App läuft auf der Atlassian Forge Plattform. Es gibt keine zugesicherte
Verfügbarkeit und kein Service Level Agreement. Die Verfügbarkeit hängt von der
Atlassian Plattform ab.</p>

<h2>5. Support</h2>
<p>Support per E-Mail, Einzelheiten auf der
<a href="/apps/label-doktor/support">Supportseite</a>.</p>

<h2>6. Änderungen</h2>
<p>Funktionsumfang und diese Seite können sich mit neuen Versionen der App
ändern. Das Datum oben nennt den Stand.</p>

<h2>7. Datenschutz</h2>
<p>Siehe <a href="/apps/label-doktor/privacy">Datenschutzseite</a>.</p>

<hr>
<h1 id=en>Label-Doktor, terms of use</h1>
<p class=muted>${ASOF}</p>

<h2>1. Governing agreement</h2>
<p>Label-Doktor is licensed under the Atlassian Marketplace Standard End User
License Agreement as published by Atlassian at
<a href="https://www.atlassian.com/legal/marketplace-end-user-agreement"
rel="noreferrer">atlassian.com/legal/marketplace-end-user-agreement</a>, in the
version in force at the time. There is no separate, differing licence agreement.
The points on this page describe the scope of the app and add to the standard
agreement, they do not replace it. Purchase, billing, renewal and refunds run
through Atlassian under Atlassian's Marketplace terms.</p>

<h2>2. Scope</h2>
<p>Label-Doktor finds Jira labels that mean the same thing and merges them after
confirmation. Usable without a licence: scanning the labels, rule based
suggestions, preview, merging, undo within 30 days, history and settings. An
active licence is required for the AI suggestions feature only.</p>

<h2>3. What is up to you</h2>
<ul>
<li>The app changes labels only after a Jira administrator confirms the preview.
The decision which labels get merged is yours.</li>
<li>Suggestions are suggestions. Check them before confirming.</li>
<li>Backups of your Jira site are your responsibility. The undo feature is
limited to 30 days and is not a backup.</li>
</ul>

<h2>4. Availability</h2>
<p>The app runs on the Atlassian Forge platform. There is no guaranteed
availability and no service level agreement. Availability depends on the
Atlassian platform.</p>

<h2>5. Support</h2>
<p>Support by email, details on the
<a href="/apps/label-doktor/support">support page</a>.</p>

<h2>6. Changes</h2>
<p>The scope of the app and this page can change with new versions of the app.
The date above states the current version.</p>

<h2>7. Privacy</h2>
<p>See the <a href="/apps/label-doktor/privacy">privacy page</a>.</p>
`);

// One entry per public URL. index.js looks the pathname up here, so adding a
// page is one constant plus one line.
export const LABEL_DOKTOR_PAGES = {
  "/apps/label-doktor": INDEX_HTML,
  "/apps/label-doktor/": INDEX_HTML,
  "/apps/label-doktor/docs": DOCS_HTML,
  "/apps/label-doktor/support": SUPPORT_HTML,
  "/apps/label-doktor/privacy": PRIVACY_HTML,
  "/apps/label-doktor/terms": TERMS_HTML,
};
