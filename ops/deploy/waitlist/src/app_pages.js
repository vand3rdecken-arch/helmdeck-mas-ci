// Public pages for three more Atlassian Marketplace apps, served under
// /readproof/, /seiten-review/ and /ticket-merge/. Same shape
// as label_doktor.js: one HTML string per page, no <script>, no analytics, no
// noindex (the live Label-Doktor pages carry none either).
//
// The text comes from each app repo's docs/site (the legal drafts in docs/legal
// are their source). Address, support, privacy and security mail and the
// response target are the values the live /impressum and the Label-Doktor
// pages use. Open lawyer notes in the source are left visible on purpose.

const STYLE = `body{background:#0E0F10;color:#E4E6E6;font:16px/1.6 system-ui,sans-serif;
max-width:720px;margin:0 auto;padding:40px 20px}h1{font-size:26px}h2{font-size:19px;
margin-top:32px}h3{font-size:16px}a{color:#6CB2EC}hr{border:0;border-top:1px solid #222425;
margin:40px 0}.muted{color:#959A9D}code{background:#1A1C1D;padding:1px 5px;border-radius:3px}
ul,ol{padding-left:22px}li{margin:4px 0}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #222425;padding:6px 10px;vertical-align:top;text-align:left}
blockquote{margin:16px 0;padding:4px 16px;border-left:3px solid #222425;color:#959A9D}`;

function page(slug, name, title, body) {
  const nav = `<p class=muted><a href="/${slug}/">${name}</a> &middot;
<a href="/${slug}/docs">Doku / Docs</a> &middot;
<a href="/${slug}/support">Support</a> &middot;
<a href="/${slug}/privacy">Datenschutz / Privacy</a> &middot;
<a href="/${slug}/terms">Nutzungsbedingungen / Terms</a>${slug === "readproof" ? ` &middot;
<a href="/readproof/security">Sicherheit / Security</a>` : ""}</p>`;
  return `<!doctype html><html lang=de><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>${STYLE}</style>
${nav}
<hr>
${body}
</html>`;
}

const LESENACHWEIS_INDEX = page("readproof", "ReadProof", "ReadProof for Confluence Cloud", `<h1>ReadProof</h1>
<p><strong>EN:</strong> Who confirmed which page version by when: deadlines, escalation, CSV and PDF export. An Atlassian Forge app for Confluence Cloud.</p>
<p><strong>DE:</strong> Wer hat welche Seitenversion bis wann bestätigt: Frist, Eskalation, Export als CSV und PDF. Eine Atlassian-Forge-App für Confluence Cloud.</p>
<ul>
<li>Evidence per person and page version / Nachweis je Person und Seitenversion</li>
<li>Assign a whole page tree in one step, with preview / Ganzen Seitenbaum zuweisen, mit Vorschau</li>
<li>Deadline per assignment, re-confirmation after every page change / Frist je Zuweisung, Neu-Bestätigung nach jeder Änderung</li>
<li>List of overdue people and escalation targets (no e-mails are sent) / Liste der Überfälligen mit Eskalationsziel (es werden keine E-Mails versendet)</li>
<li>Stores only IDs and timestamps; names are looked up live / Gespeichert werden nur IDs und Zeitstempel</li>
</ul>
<h2>Price / Preis</h2>
<p>Free up to 10 users. Then per user and month: 1 to 100 users USD 0.28, 101 to 250 users USD 0.20, 251 to 1000 users USD 0.10, above 1000 users USD 0.09 down to 0.04. 30-day trial via the Atlassian Marketplace. / Danach je Nutzer und Monat: 1 bis 100 Nutzer 0,28 USD, 101 bis 250 Nutzer 0,20 USD, 251 bis 1000 Nutzer 0,10 USD, ab 1000 Nutzern 0,09 bis 0,04 USD. 30 Tage Testphase über den Atlassian Marketplace.</p>
<p><a href="/readproof/compare">Price comparison, checked 18 October 2026 / Preisvergleich, Stand 18.10.2026</a></p>
<p>The app records confirmations; whether a regulation is met is for the organisation to decide. / Die App hält Bestätigungen fest; ob eine Vorschrift erfüllt ist, entscheidet die Organisation.</p>`);
const LESENACHWEIS_DOCS = page("readproof", "ReadProof", "Documentation, ReadProof", `<h1>Documentation / Dokumentation</h1>
<p>English first, deutsch darunter.</p>

<h2>English</h2>
<h3>1. What the app does</h3>
<p>ReadProof records one confirmation per person and page version. Administrators assign pages to a Confluence group with a deadline; people confirm at the very bottom of the page (ReadProof macro, required tick); when the page changes, everyone confirms the new version. Requires Confluence Cloud and at least one Confluence group.</p>
<h3>2. Installation and permissions</h3>
<p>Install from the Atlassian Marketplace. The app asks for read access only; it writes nothing into pages and sends no e-mails.</p>
<table>
<tr><th>Permission</th><th>Why</th></tr>
<tr><td>Read pages, spaces</td><td>Read the version of a page and its title for display</td></tr>
<tr><td>Read page tree</td><td>Assign a whole page tree</td></tr>
<tr><td>Read groups</td><td>Choose a group and find its members</td></tr>
<tr><td>Read users</td><td>Show names in the overview and exports</td></tr>
<tr><td>App storage</td><td>Store assignments and confirmations</td></tr>
</table>
<h3>3. Assign one page</h3>
<p>Open <em>Apps → ReadProof</em> (Confluence administrators, ReadProof managers and space administrators for their space; see Roles below). Choose the page, the group and a deadline. Optional: re-confirmation after N days, escalation after N days with an escalation group.</p>
<h3>4. Assign a page tree</h3>
<p>Choose a parent page and a group. The preview shows how many pages and people are covered. Check it, then confirm. Pages that fail are reported; the rest is assigned.</p>
<h3>5. Confirm as a reader</h3>
<p>On an assigned page, scroll to the very bottom to the ReadProof box (the author inserts the macro "ReadProof" there). Tick "I have read the whole page and understood it" and click "Read and understood". The page byline only shows your status. The proof (version, date, tick) appears in the CSV and PDF export; admins can switch the required tick off per assignment. This supports the evidence of policy acknowledgement (ISO 27001 awareness, NIS2 training). When the page gets a new version, the confirmation of the old version stays as evidence and you confirm the new one.</p>
<h3>6. Read the overview</h3>
<p>The overview lists page, group, deadline and "x of y confirmed" and marks overdue assignments.</p>
<h3>7. Deadlines and escalation</h3>
<p>The Deadlines tab lists overdue people and the number of people to escalate to. The app only lists; it sends no e-mails or notifications. You act on the list.</p>
<h3>8. Export</h3>
<p>CSV (semicolon-separated, UTF-8) and PDF as downloads. The PDF has a summary and a checksum (names are not part of the checksum). Cells starting with <code>=</code>, <code>+</code>, <code>-</code>, <code>@</code> are neutralised in the CSV. Exports contain names and account IDs; handle them accordingly.</p>
<h3>9. Licence</h3>
<p>Sites with up to 10 users use the app for free. Without an active licence (for example an expired trial) only new assignments are blocked (read-only mode); existing assignments, confirmations, overview, deadlines, removal and exports keep working.</p>
<p><strong>Roles.</strong> Confluence administrators set up ReadProof and choose the groups of "ReadProof managers" (only they can change this). Managers may assign, report and export on every page; space administrators do the same for their own space; page authors can only request a confirmation for their own page. Everyone else can only confirm. Every request is checked on the server.</p>
<h3>10. Known limits</h3>
<ul>
<li>Group membership is read when you open or assign; later changes show up the next time.</li>
<li>People without a retrievable name show as "(unknown)"; app accounts (bots) are excluded.</li>
<li>Tested with 6 pages and 4 people; very large trees are untested.</li>
<li>No e-mail reminders. The app does not prove compliance with NIS2 or ISO 27001; it records confirmations.</li>
</ul>
<h3>11. Privacy, deletion, troubleshooting</h3>
<p>See the <a href="/readproof/privacy">privacy policy</a>. Confirmations are not deleted automatically; export before you remove data. For problems see <a href="/readproof/support">Support</a>.</p>

<h2>Deutsch</h2>
<h3>1. Was die App tut</h3>
<p>ReadProof speichert eine Bestätigung je Person und Seitenversion. Administratoren weisen Seiten einer Confluence-Gruppe mit Frist zu; alle bestätigen ganz unten auf der Seite (Makro „ReadProof“, Pflicht-Haken); ändert sich die Seite, bestätigt jede Person die neue Version. Voraussetzung: Confluence Cloud und mindestens eine Gruppe.</p>
<h3>2. Installation und Berechtigungen</h3>
<p>Installation über den Atlassian Marketplace. Die App fragt nur Leserechte ab; sie schreibt nichts in Seiten und versendet keine E-Mails. Die Tabelle oben nennt, wofür jede Berechtigung gebraucht wird (Seiten und Bereiche lesen, Seitenbaum, Gruppen, Nutzernamen, App-Speicher).</p>
<h3>3. Eine Seite zuweisen</h3>
<p><em>Apps → ReadProof</em> öffnen (Administratoren, ReadProof-Manager, Space-Administratoren für ihren Space). Seite, Gruppe und Frist wählen. Optional: Neu-Bestätigung nach N Tagen, Eskalation nach N Tagen mit Eskalationsgruppe.</p>
<h3>4. Seitenbaum zuweisen</h3>
<p>Elternseite und Gruppe wählen. Die Vorschau zeigt, wie viele Seiten und Personen betroffen sind. Prüfen, dann bestätigen. Fehlgeschlagene Seiten werden gemeldet, der Rest wird zugewiesen.</p>
<h3>5. Als Leser bestätigen</h3>
<p>Auf einer zugewiesenen Seite ganz nach unten zum ReadProof-Kasten scrollen (dort fügt der Autor das Makro „ReadProof“ ein). „Ich habe die Seite vollständig gelesen und verstanden“ ankreuzen und „Gelesen und verstanden“ klicken. Die Seitenzeile zeigt nur den Stand. Der Nachweis (Version, Datum, Haken) steht im CSV- und PDF-Export; Admins können den Pflicht-Haken je Zuweisung abschalten. Das unterstützt den Nachweis der Kenntnisnahme von Richtlinien (ISO 27001 Awareness, NIS2 Schulung). Bei einer neuen Version bleibt die alte Bestätigung als Nachweis; du bestätigst die neue.</p>
<h3>6. Übersicht lesen</h3>
<p>Die Übersicht zeigt Seite, Gruppe, Frist und "x von y bestätigt" und markiert Überfälliges.</p>
<h3>7. Fristen und Eskalation</h3>
<p>Der Reiter "Fristen" listet Überfällige und die Zahl der Personen, an die eskaliert wird. Die App listet nur; sie versendet keine E-Mails oder Benachrichtigungen.</p>
<h3>8. Export</h3>
<p>CSV (Semikolon, UTF-8) und PDF als Download. Das PDF hat eine Zusammenfassung und eine Prüfsumme (Namen sind nicht Teil der Summe). Zellen, die mit <code>=</code>, <code>+</code>, <code>-</code>, <code>@</code> beginnen, werden im CSV entschärft. Exporte enthalten Namen und Konto-IDs.</p>
<h3>9. Lizenz</h3>
<p>Seiten bis 10 Nutzer nutzen die App gratis. Ohne aktive Lizenz (z. B. Testphase abgelaufen) sind nur neue Zuweisungen gesperrt (Nur-Lesen-Modus); bestehende Zuweisungen, Bestätigungen, Übersicht, Fristen, Entzug und Exporte laufen weiter.</p>
<p><strong>Rollen.</strong> Confluence-Administratoren richten ReadProof ein und wählen die Gruppen der „ReadProof-Manager“ (nur sie können das ändern). Manager dürfen auf jeder Seite zuweisen, berichten und exportieren; Space-Administratoren dasselbe für ihren eigenen Space; Seitenautoren können nur für ihre eigene Seite eine Bestätigung anfordern. Alle anderen können nur bestätigen. Jede Anfrage wird auf dem Server geprüft.</p>
<h3>10. Bekannte Grenzen</h3>
<ul>
<li>Die Gruppenmitgliedschaft wird beim Öffnen und Zuweisen gelesen; spätere Änderungen erscheinen beim nächsten Mal.</li>
<li>Personen ohne abrufbaren Namen erscheinen als "(unbekannt)"; App-Konten (Bots) werden ausgeschlossen.</li>
<li>Getestet mit 6 Seiten und 4 Personen; sehr große Bäume sind ungetestet.</li>
<li>Keine E-Mail-Erinnerungen. Die App belegt keine Konformität mit NIS2 oder ISO 27001; sie hält Bestätigungen fest.</li>
</ul>
<h3>11. Datenschutz, Löschung, Fehlersuche</h3>
<p>Siehe <a href="/readproof/privacy">Datenschutzerklärung</a>. Bestätigungen werden nicht automatisch gelöscht; vor dem Entfernen exportieren. Bei Problemen: <a href="/readproof/support">Support</a>.</p>`);
const LESENACHWEIS_SUPPORT = page("readproof", "ReadProof", "Support, ReadProof", `<h1>Support</h1>
<h2>English</h2>
<p>E-mail: <strong>support@helmdeck.de</strong></p>
<p>Please include: your Confluence site name, what you clicked, what you expected and what happened, and the language of your profile. Please do not send page content or personal data.</p>
<table>
<tr><th>Who</th><th>What you can expect</th></tr>
<tr><td>Paying sites (11 or more users)</td><td>Answer within two business days (target, not a guarantee). </td></tr>
<tr><td>Free tier (up to 10 users)</td><td>Documentation only; no response time promised.</td></tr>
</table>
<p>Security issues: <strong>security@helmdeck.de</strong>. Data processing agreement on request: privacy@helmdeck.de.</p>
<p>First read the <a href="/readproof/docs">documentation</a>, especially "Known limits".</p>
<h2>Deutsch</h2>
<p>E-Mail: <strong>support@helmdeck.de</strong></p>
<p>Bitte angeben: Name deiner Confluence-Seite, was du geklickt hast, was du erwartet hast und was passiert ist, Sprache deines Profils. Bitte keine Seiteninhalte oder personenbezogenen Daten senden.</p>
<table>
<tr><th>Wer</th><th>Was du erwarten kannst</th></tr>
<tr><td>Zahlende Seiten (ab 11 Nutzern)</td><td>Antwort innerhalb von zwei Werktagen (Ziel, keine Zusage). </td></tr>
<tr><td>Gratis-Stufe (bis 10 Nutzer)</td><td>Nur Dokumentation; keine Antwortzeit zugesagt.</td></tr>
</table>
<p>Sicherheitsprobleme: <strong>security@helmdeck.de</strong>. Auftragsverarbeitungsvertrag auf Anfrage: privacy@helmdeck.de.</p>`);
const LESENACHWEIS_PRIVACY = page("readproof", "ReadProof", "Datenschutz / Privacy, ReadProof", `<h1>Datenschutzerklärung / Privacy Policy: ReadProof</h1>
<p>Stand / Version: 20.10.2026</p>
<h1>Deutsch</h1>
<h2>1. Verantwortlicher</h2>
<p><code>Tien Duy Vo</code>, <code>{{ADDR_STREET}}</code>, <code>{{ADDR_ZIP}} Frankfurt am Main</code>, Deutschland, E-Mail: <code>privacy@helmdeck.de</code>. Der Anbieter ist eine Privatperson, kein Unternehmen.</p>
<h2>2. Was die App ist</h2>
<p>ReadProof ist eine Atlassian-Forge-App für Confluence Cloud. Sie hält fest, welche Person welche Version einer Seite bestätigt hat, und erzeugt daraus Übersichten, Fristenlisten sowie CSV- und PDF-Exporte. Die Verwaltung ist Confluence-Administratoren vorbehalten.</p>
<h2>3. Wo die Daten verarbeitet werden</h2>
<p>Die App läuft auf Atlassian Forge. Alle Daten liegen im Forge-Speicher (Key-Value-Store) deiner eigenen Confluence-Installation, also auf Atlassian-Infrastruktur. Es gibt <strong>keine eigenen Server, keine eigene Datenbank, kein Tracking, keine Analyse, keine Drittdienste</strong>. Die App ruft nur die Confluence-Schnittstelle auf. Einzige externe Berechtigung: Profilbilder, die dein Browser von <code>*.atlassian.net</code>, <code>*.atl-paas.net</code> und <code>secure.gravatar.com</code> lädt. Der Anbieter erhält und speichert keine Daten deiner Seite bei sich.</p>
<h2>4. Welche Daten die App verarbeitet</h2>
<table>
<tr><th>Daten</th><th>Zweck</th><th>Wo</th><th>Wie lange</th></tr>
<tr><td>Zuweisung: Seiten-ID, Gruppen-ID und Gruppenname, Frist, Tage bis zur Neu-Bestätigung, Eskalationstage und -gruppe, Basisversion, Konto-ID des Erstellers, Zeitstempel</td><td>Wer muss was bis wann bestätigen</td><td>Forge-Speicher deiner Seite</td><td>Bis ein Administrator die Zuweisung entfernt oder die App deinstalliert wird</td></tr>
<tr><td>Bestätigung: Seiten-ID, Version, Atlassian-Konto-ID der Person, Zeitpunkt</td><td>Nachweis</td><td>Forge-Speicher</td><td><strong>Keine automatische Löschung.</strong> Bestätigungen älterer Versionen bleiben absichtlich als Nachweis. Die Aufbewahrungsdauer entscheidest du; exportiere vorher</td></tr>
<tr><td>Eskalationsvermerk: Seiten-ID, Version, Zeitpunkt</td><td>Eskalation je Seite und Version nur einmal melden</td><td>Forge-Speicher</td><td>wie oben</td></tr>
<tr><td>Erwähnungs-Sperre: Seiten-ID, Version, Konto-ID der Person, Zeitpunkt</td><td>Dieselbe Person je Seitenversion nur einmal per Kommentar erwähnen</td><td>Forge-Speicher</td><td>wie oben</td></tr>
<tr><td>Erwähnungs-Kommentar auf der Seite: Konto-IDs der neu Zugewiesenen (als @-Erwähnung), Frist, fester Hinweistext</td><td>Zugewiesene benachrichtigen</td><td><strong>In Confluence gespeichert</strong> (als Kommentar der Seite), nicht im Forge-Speicher</td><td>Bleibt als Kommentar bestehen, bis er in Confluence gelöscht wird. Die App löscht ihn nicht</td></tr>
<tr><td>Namen von Personen</td><td>Anzeige und Export</td><td><strong>Nicht gespeichert.</strong> Werden bei Anzeige und Export live aus Confluence abgerufen</td><td>n/a</td></tr>
<tr><td>Seitentitel, Seiteninhalte, E-Mail-Adressen</td><td>n/a</td><td><strong>Nicht gespeichert.</strong> Die App liest Seiten-Metadaten (Version, Ort im Seitenbaum, Titel zur Anzeige), keine Inhalte</td><td>n/a</td></tr>
</table>
<p>Ausgetretene Personen: Ihr Name ist unter Umständen nicht mehr abrufbar; ihre Konto-ID bleibt im Nachweis. Exporte (CSV/PDF) enthalten Namen und Konto-IDs und werden von der App nicht gespeichert; sie landen in deinem Download-Ordner.</p>
<h2>5. Berechtigungen (Scopes)</h2>
<p>Lesend auf Confluence: Seiten, Bereiche, Seitenbaum (<code>read:page</code>, <code>read:space</code>, <code>read:hierarchical-content</code>), Vorfahren einer Seite für die Teilbaum-Regel (<code>read:content.metadata</code>), Seiten-Ereignisse „angelegt“ und „verschoben“ (<code>read:confluence-content.summary</code>), Gruppen und deren Mitglieder (<code>read:group</code>, <code>read:confluence-groups</code>), Nutzer-Namen (<code>read:user</code>, <code>read:confluence-user</code>), Suche (<code>search:confluence</code>), dazu <code>storage:app</code>.</p>
<p>Schreibend auf Confluence gibt es zwei Zwecke. Erstens fügt die App ihr eigenes Bestätigungs-Makro ans Ende einer zugewiesenen Seite ein und entfernt es beim Entzug wieder (<code>write:page:confluence</code>). Zweitens schreibt die App bei einer Zuweisung einen Fußzeilen-Kommentar auf die Seite, der die Zugewiesenen mit @ erwähnt (<code>write:comment:confluence</code>). Der Kommentar enthält die Konto-IDs der Zugewiesenen als Erwähnung, die Frist und einen festen Hinweistext. Die Benachrichtigung selbst versendet Confluence nach den Einstellungen der jeweiligen Person. Die App verschickt keine E-Mails und nutzt dafür keinen eigenen Server oder Dienst. Ein Administrator kann den Kommentar in der App abschalten; dann wird keiner geschrieben. Der Kommentar bleibt in Confluence gespeichert, bis er dort gelöscht wird. Weiteren Seiteninhalt ändert die App nicht.</p>
<h2>6. Keine KI</h2>
<p>Die App nutzt keine KI und kein Forge LLM.</p>
<h2>7. Rechtsgrundlage und Rollen (DSGVO)</h2>
<p>Verantwortlicher für die Daten deiner Mitarbeitenden bist du als Kunde. Soweit der Anbieter personenbezogene Daten (Konto-ID, Bestätigungszeitpunkt) im Auftrag verarbeitet, geschieht das nur im Forge-Speicher deiner Seite; der Anbieter hat keinen eigenen Zugriff darauf. Hinweise zum Auftragsverarbeitungsvertrag: <code>docs/legal/avv-hinweis.md</code>.</p>
<h2>8. Weitergabe</h2>
<p>Keine Weitergabe durch den Anbieter. Atlassian verarbeitet als Plattformbetreiber nach eigenen Bedingungen.</p>
<h2>9. Löschung und Deinstallation</h2>
<p>Du kannst Zuweisungen in der App entfernen. Bestätigungen werden von der App nicht gelöscht (Nachweis). Nach der Deinstallation löscht Atlassian die Forge-Speicherdaten der Installation automatisch nach 28 Tagen; eine Neuinstallation stellt sie nicht wieder her. Auf Anfrage bestätigen wir die Löschung.</p>
<h2>10. Deine Rechte</h2>
<p>Auskunft, Berichtigung, Löschung, Einschränkung, Widerspruch, Datenübertragbarkeit, Beschwerde bei einer Aufsichtsbehörde. Schreibe an <code>privacy@helmdeck.de</code>. Weil der Anbieter selbst keine Daten hält, werden die meisten Anfragen in deiner Confluence-Seite oder bei Atlassian erledigt.</p>
<h2>11. Sicherheit</h2>
<p>Anmeldung und Hosting liefert Atlassian Forge. Die App nutzt nur die oben genannten Berechtigungen. CSV-Exporte entschärfen Zellen, die mit <code>=</code>, <code>+</code>, <code>-</code> oder <code>@</code> beginnen (Schutz vor Formel-Einschleusung). Sicherheitsprobleme bitte an <code>security@helmdeck.de</code>.</p>
<h2>12. Änderungen</h2>
<p>Wir können diese Erklärung ändern. Die aktuelle Fassung steht unter <code>https://helmdeck.de/readproof/privacy</code>.</p>
<h1>English</h1>
<h2>1. Who is responsible</h2>
<p><code>Tien Duy Vo</code>, <code>{{ADDR_STREET}}</code>, <code>{{ADDR_ZIP}} Frankfurt am Main</code>, Germany, e-mail <code>privacy@helmdeck.de</code>. The provider is a natural person, not a company.</p>
<h2>2. What the app is</h2>
<p>ReadProof is an Atlassian Forge app for Confluence Cloud. It records which person confirmed which version of a page and produces overviews, deadline lists and CSV/PDF exports. Administration is limited to Confluence administrators.</p>
<h2>3. Where data is processed</h2>
<p>The app runs on Atlassian Forge. All data is in Forge storage (key-value store) of your own Confluence installation, on Atlassian infrastructure. There are <strong>no own servers, no own database, no tracking, no analytics and no third-party services</strong>. The app only calls the Confluence API. The only external permission is for profile pictures, which your browser loads from <code>*.atlassian.net</code>, <code>*.atl-paas.net</code> and <code>secure.gravatar.com</code>. The provider does not receive or store your site's data.</p>
<h2>4. Data the app handles</h2>
<table>
<tr><th>Data</th><th>Purpose</th><th>Where</th><th>How long</th></tr>
<tr><td>Assignment: page ID, group ID and group name, deadline, days until re-confirmation, escalation days and group, base version, creator's account ID, timestamps</td><td>Who must confirm what by when</td><td>Forge storage of your site</td><td>Until an administrator removes the assignment or the app is uninstalled</td></tr>
<tr><td>Confirmation: page ID, version, the person's Atlassian account ID, time</td><td>Evidence</td><td>Forge storage</td><td><strong>No automatic deletion.</strong> Confirmations of older versions are kept on purpose as evidence. You decide how long to keep them; export first</td></tr>
<tr><td>Escalation note: page ID, version, time</td><td>Report an escalation only once per page and version</td><td>Forge storage</td><td>as above</td></tr>
<tr><td>Mention lock: page ID, version, the person's account ID, time</td><td>Mention the same person only once per page version</td><td>Forge storage</td><td>as above</td></tr>
<tr><td>Mention comment on the page: account IDs of the newly assigned people (as @-mention), due date, fixed notice text</td><td>Notify assigned people</td><td><strong>Stored in Confluence</strong> (as a comment on the page), not in Forge storage</td><td>Stays as a comment until it is deleted in Confluence. The app does not delete it</td></tr>
<tr><td>People's names</td><td>Display and export</td><td><strong>Not stored.</strong> Looked up live from Confluence</td><td>n/a</td></tr>
<tr><td>Page titles, page content, e-mail addresses</td><td>n/a</td><td><strong>Not stored.</strong> The app reads page metadata (version, position in the page tree, title for display), not content</td><td>n/a</td></tr>
</table>
<p>Departed people: their name may no longer be available; their account ID stays in the evidence. Exports (CSV/PDF) contain names and account IDs and are not stored by the app; they go to your download folder.</p>
<h2>5. Permissions (scopes)</h2>
<p>Read access to Confluence: pages, spaces, page tree (<code>read:page</code>, <code>read:space</code>, <code>read:hierarchical-content</code>), ancestors of a page for the subtree rule (<code>read:content.metadata</code>), page events 'created' and 'moved' (<code>read:confluence-content.summary</code>), groups and members (<code>read:group</code>, <code>read:confluence-groups</code>), user names (<code>read:user</code>, <code>read:confluence-user</code>), search (<code>search:confluence</code>), plus <code>storage:app</code>.</p>
<p>There are two write purposes. First, the app adds its own confirmation macro at the end of an assigned page and removes it again when the assignment is removed (<code>write:page:confluence</code>). Second, when people are assigned, the app writes one footer comment on the page that @-mentions them (<code>write:comment:confluence</code>). The comment contains the account IDs of the assigned people as a mention, the due date and a fixed notice text. Confluence itself sends the notification, according to each person's settings. The app sends no e-mails and uses no server or service of its own for this. An administrator can switch the comment off in the app; then none is written. The comment stays stored in Confluence until it is deleted there. The app changes no other page content.</p>
<h2>6. No AI</h2>
<p>The app uses no AI and no Forge LLM.</p>
<h2>7. Legal basis and roles (GDPR)</h2>
<p>You, the customer, are the controller of your staff's data. Where the provider processes personal data (account ID, confirmation time) on your behalf, this happens only in your site's Forge storage; the provider has no access of its own. Notes on a data processing agreement: <code>docs/legal/avv-hinweis.md</code>.</p>
<h2>8. Sharing</h2>
<p>No sharing by the provider. Atlassian processes data as platform operator under its own terms.</p>
<h2>9. Deletion and uninstall</h2>
<p>You can remove assignments in the app. The app does not delete confirmations (evidence). After uninstallation, Atlassian deletes the Forge storage data of the installation automatically after 28 days; a reinstallation does not restore it. On request, we confirm deletion.</p>
<h2>10. Your rights</h2>
<p>Access, rectification, erasure, restriction, objection, portability, complaint to a supervisory authority. Write to <code>privacy@helmdeck.de</code>. Because the provider holds no data itself, most requests are handled in your Confluence site or with Atlassian.</p>
<h2>11. Security</h2>
<p>Authentication and hosting are provided by Atlassian Forge. The app uses only the permissions listed above. CSV exports neutralise cells that start with <code>=</code>, <code>+</code>, <code>-</code> or <code>@</code> (formula-injection protection). Security issues: <code>security@helmdeck.de</code>.</p>
<h2>12. Changes</h2>
<p>We may update this policy. The current version is at <code>https://helmdeck.de/readproof/privacy</code>.</p>`);
const LESENACHWEIS_TERMS = page("readproof", "ReadProof", "AGB / Terms, ReadProof", `<h1>Nutzungsbedingungen / Terms of Use (EULA): ReadProof</h1>
<p>Version: 20.10.2026</p>
<h1>English</h1>
<h2>1. Parties</h2>
<p>Provider: <code>Tien Duy Vo</code>, <code>{{ADDR_STREET}}</code>, <code>{{ADDR_ZIP}} Frankfurt am Main</code>, Germany, <code>support@helmdeck.de</code> (natural person).</p>
<p>Customer: the person or organization that installs the app on a Confluence Cloud site.</p>
<h2>2. Base agreement</h2>
<p>The Atlassian Standard EULA (Marketplace End User Agreement) in its current version applies, with the additions below.</p>
<h2>3. Additions</h2>
<h3>3.1 Licence and scope</h3>
<ul>
<li>The app is licensed through the Atlassian Marketplace. Licence status is determined by Atlassian (Forge licence context). The provider runs no licence server.</li>
<li>Sites with 1 to 10 users use the app at no charge (a 0 USD price tier). Sites with more users pay the price shown on the Marketplace listing per user and month: USD 0.28 for 1 to 100 users, USD 0.20 for 101 to 250 users, USD 0.10 for 251 to 1000 users, USD 0.09 down to 0.04 above 1000 users.</li>
<li><strong>Without an active licence</strong> (for example an expired trial or a cancelled subscription): creating <strong>new</strong> assignments (single page and page tree) is blocked. Existing assignments, confirmations by readers, the overview, deadline lists and CSV/PDF exports keep working.</li>
</ul>
<h3>3.2 Evidence, not legal advice</h3>
<p>The app records confirmations and produces exports with a checksum. It does <strong>not</strong> bring an organisation into line with NIS2, ISO 27001 or any other regulation, and the provider gives no assurance that an auditor will accept an export. The customer decides whom to assign, which deadline applies and how long to keep data.</p>
<h3>3.3 Customer responsibility</h3>
<p>The administrator checks the preview before a bulk assignment. The app lists overdue people and escalation targets; it sends no deadline reminders and no e-mails of its own. When people are assigned, the app writes one footer comment on the page that @-mentions them (administrators can switch this off), and Confluence sends the notification. The comment stays in Confluence until it is deleted there. The customer is responsible for acting on the lists. Group membership is read from Confluence at the time of the call.</p>
<h3>3.4 Data</h3>
<p>See the Privacy Policy. The app stores account IDs, page IDs, versions and timestamps in the customer's Forge storage and does not delete confirmations automatically. The mention comment on the page (account IDs of assigned people, due date) is stored in Confluence.</p>
<h3>3.5 Warranty and liability</h3>
<p>Liability for intent, gross negligence, injury to life, body or health, under mandatory product liability rules and for breach of essential contractual duties is not limited.</p>
<p>The app is provided "as is" to the extent permitted by law.</p>
<h3>3.6 Support</h3>
<p>Support via <code>https://helmdeck.de/readproof/support</code>. Target response for paying customers: two business days, no availability commitment. For the free tier (1-10 users): documentation only, no response time promised.</p>
<h3>3.7 Term and termination</h3>
<p>Subscription as per the Atlassian Marketplace. After uninstall the app processes nothing further.</p>
<h3>3.8 Governing law and venue</h3>
<p>Governing law and venue follow the Atlassian EULA that applies to the installation. These additions do not set a separate choice of law or venue. Mandatory consumer protection rules remain unaffected.</p>
<h3>3.9 Changes</h3>
<p>The provider may update these terms for future versions. Material changes are announced at <code>https://helmdeck.de/readproof/terms</code>.</p>
<h3>3.10 Contact / legal notice</h3>
<p>Provider: Tien Duy Vo, {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Germany. E-mail: support@helmdeck.de. The provider is a natural person, not a company.</p>
<h1>Deutsch (Kurzfassung der Ergänzungen, nicht rechtsverbindlich)</h1>
<ul>
<li>Basis: Atlassian-Standard-EULA; dieses Dokument ergänzt sie.</li>
<li><strong>Lizenz:</strong> Läuft über den Atlassian Marketplace. Seiten mit 1 bis 10 Nutzern nutzen die App gratis; ab 11 Nutzern gilt der Preis der Listung je Nutzer und Monat (0,28 USD bis 100 Nutzer, 0,20 USD für 101 bis 250, 0,10 USD für 251 bis 1000, darüber 0,09 bis 0,04 USD).</li>
<li><strong>Ohne aktive Lizenz</strong> (Testphase abgelaufen, Abo beendet): <strong>neue</strong> Zuweisungen sind gesperrt (einzelne Seite und Seitenbaum). Bestehende Zuweisungen, Bestätigungen der Leser, Übersicht, Fristenliste und CSV/PDF-Export laufen weiter.</li>
<li><strong>Nachweis, keine Rechtsberatung:</strong> Die App macht keine Organisation "NIS2- oder ISO-27001-konform" und sichert nicht zu, dass ein Prüfer einen Export annimmt.</li>
<li><strong>Verantwortung des Kunden:</strong> Vorschau vor der Massenzuweisung prüfen; die App listet Überfällige, versendet aber keine Fristerinnerungen und keine eigenen E-Mails. Bei einer Zuweisung schreibt sie einen Fußzeilen-Kommentar mit @-Erwähnung der Zugewiesenen auf die Seite (durch Administratoren abschaltbar); die Benachrichtigung versendet Confluence. Der Kommentar bleibt in Confluence gespeichert, bis er dort gelöscht wird.</li>
<li><strong>Daten:</strong> siehe Datenschutzerklärung; Bestätigungen werden nicht automatisch gelöscht.</li>
<li><strong>Haftung, Recht, Gerichtsstand:</strong> Es gilt die Atlassian-Standard-EULA; zwingende Haftung und Verbraucherrechte bleiben unberührt.</li>
<li><strong>Support:</strong> zahlende Kunden Ziel zwei Werktage; Gratis-Stufe nur Dokumentation.</li>
<li><strong>Impressum:</strong> Tien Duy Vo, {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, E-Mail: support@helmdeck.de.</li>
</ul>`);
const LESENACHWEIS_SECURITY = page("readproof", "ReadProof", "Security / Sicherheit, ReadProof", `<h1>Sicherheit / Security: ReadProof</h1>
<p>Stand / Version: 20.10.2026</p>
<h1>Deutsch</h1>
<h2>Architektur</h2>
<p>ReadProof ist eine Atlassian-Forge-App für Confluence Cloud. Sie läuft auf der Atlassian-Plattform. Es gibt keine eigenen Server, keine eigene Datenbank und keine Drittdienste. Alle App-Daten liegen im Forge-Speicher deiner eigenen Confluence-Installation. Der Anbieter hat keinen Zugriff darauf.</p>
<h2>Daten</h2>
<p>Gespeichert werden nur IDs und Zeitstempel (Seiten-ID, Version, Atlassian-Konto-ID, Zeitpunkt, Fristen und Einstellungen). Namen werden bei Anzeige und Export live aus Confluence abgerufen. E-Mail-Adressen, Seiteninhalte und IP-Adressen speichert die App nicht. Details: <a href="/readproof/privacy">Datenschutzerklärung</a>.</p>
<h2>Berechtigungen</h2>
<p>Die App fordert nur die Confluence-Berechtigungen an, die sie braucht: Lesen von Seiten, Bereichen, Gruppen, Nutzernamen und Suche sowie zwei Schreibzwecke (eigenes Bestätigungs-Makro auf zugewiesenen Seiten, ein Fußzeilen-Kommentar mit @-Erwähnung bei einer Zuweisung). Die vollständige Liste steht in der Datenschutzerklärung, Abschnitt 5.</p>
<h2>Zugriffskontrolle</h2>
<p>Die Rechte werden bei jeder Aktion im Backend der App geprüft, nicht nur in der Oberfläche. Verwaltung ist Confluence-Administratoren, ReadProof-Managern und Space-Administratoren (für ihren Space) vorbehalten.</p>
<h2>Eingaben und Exporte</h2>
<p>Eingaben werden im Backend geprüft. CSV-Exporte entschärfen Zellen, die mit <code>=</code>, <code>+</code>, <code>-</code> oder <code>@</code> beginnen (Schutz vor Formel-Einschleusung).</p>
<h2>Externe Verbindungen</h2>
<p>Die App ruft keine anderen Server auf als deine Confluence-Seite. Einzige externe Berechtigung: Profilbilder, die dein Browser von <code>*.atlassian.net</code>, <code>*.atl-paas.net</code> und <code>secure.gravatar.com</code> lädt. Kein Tracking, keine Analyse, keine KI.</p>
<h2>Sicherheitslücke melden</h2>
<p>Schreibe an <code>security@helmdeck.de</code> mit "Security" im Betreff. Bitte keine Zugangsdaten oder Kundendaten mitsenden. Wir bestätigen den Eingang in der Regel innerhalb von zwei Werktagen (Ziel, keine Zusage) und melden uns, sobald wir die Meldung bewertet haben.</p>
<h2>Anbieter</h2>
<p>Tien Duy Vo, {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Deutschland.</p>
<h1>English</h1>
<h2>Architecture</h2>
<p>ReadProof is an Atlassian Forge app for Confluence Cloud. It runs on the Atlassian platform. There are no servers, no database and no third-party services of our own. All app data is stored in the Forge storage of your own Confluence installation. The provider has no access to it.</p>
<h2>Data</h2>
<p>Only IDs and timestamps are stored (page ID, version, Atlassian account ID, time, deadlines and settings). Names are looked up live from Confluence for display and export. The app does not store e-mail addresses, page content or IP addresses. Details: <a href="/readproof/privacy">Privacy Policy</a>.</p>
<h2>Permissions</h2>
<p>The app requests only the Confluence permissions it needs: read access to pages, spaces, groups, user names and search, plus two write purposes (its own confirmation macro on assigned pages, and one footer comment with an @-mention when people are assigned). The full list is in the Privacy Policy, section 5.</p>
<h2>Access control</h2>
<p>Permissions are checked in the app backend for every action, not only in the user interface. Administration is limited to Confluence administrators, ReadProof managers and space administrators (for their space).</p>
<h2>Input and exports</h2>
<p>Input is validated in the backend. CSV exports neutralise cells that start with <code>=</code>, <code>+</code>, <code>-</code> or <code>@</code> (formula-injection protection).</p>
<h2>Outside connections</h2>
<p>The app calls no servers other than your Confluence site. The only external permission is for profile pictures, which your browser loads from <code>*.atlassian.net</code>, <code>*.atl-paas.net</code> and <code>secure.gravatar.com</code>. No tracking, no analytics, no AI.</p>
<h2>Reporting a vulnerability</h2>
<p>Write to <code>security@helmdeck.de</code> with "Security" in the subject. Please do not send credentials or customer data. We usually acknowledge a report within two business days (a target, not a commitment) and get back to you once we have assessed it.</p>
<h2>Provider</h2>
<p>Tien Duy Vo, {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Germany.</p>`);

const SEITEN_REVIEW_INDEX = page("seiten-review", "Seiten-Review", "Overview, Page Review / Seiten-Review", `
<blockquote><p><b>DRAFT / ENTWURF, not published, not legally reviewed. Placeholders in [[ ]] are open.</b></p></blockquote>
<h1>Page Review for Confluence</h1><h2>English</h2><p>Give pages an owner and a review date. One reminder per owner, confirm with one click. Runs on Atlassian Forge, no external servers.</p><p>Free up to 10 users, then US$0.50 per user per month (proposal, not final).</p><h2>Deutsch</h2><p>Seiten bekommen Besitzer und Prüftermin. Eine Erinnerung je Besitzer, Bestätigung mit einem Klick. Läuft auf Atlassian Forge, keine externen Server.</p><p>Bis 10 Nutzer kostenlos, danach 0,50 US-$ je Nutzer und Monat [[Preis nicht entschieden]].</p>
`);

const SEITEN_REVIEW_DOCS = page("seiten-review", "Seiten-Review", "Documentation, Page Review / Seiten-Review", `
<blockquote><p><b>DRAFT / ENTWURF, not published, not legally reviewed. Placeholders in [[ ]] are open.</b></p></blockquote>
<h1>Documentation</h1><h2>English</h2><ol><li>Open a page, click <b>Seiten-Review</b> in the page header.</li><li>Pick an interval (7, 30, 90, 180, 365 days) and click <b>Take over</b>, you become owner.</li><li>When due, the owner receives one comment with an @mention listing all due pages.</li><li>Open the page and click <b>Mark as reviewed</b>. The next date is set; the history keeps the last 20 confirmations.</li><li>The review overview (global page) lists your pages; admins also see all tracked pages and can send reminders now.</li></ol><p>Who may do what: owner or site admin confirms; owner, admin or (for a page without owner) a user who can edit the page may change owner or interval or stop tracking.</p><p>Limits: no export, no escalation. E-mail delivery depends on your Confluence notification settings.</p><h2>Deutsch</h2><ol><li>Seite öffnen, im Seitenkopf <b>Seiten-Review</b> anklicken.</li><li>Intervall wählen (7, 30, 90, 180, 365 Tage), übernehmen, Sie werden Besitzer.</li><li>Ist eine Prüfung fällig, bekommt der Besitzer einen Kommentar mit @-Erwähnung und allen fälligen Seiten.</li><li><b>Als geprüft bestätigen</b> setzt den nächsten Termin; der Verlauf behält die letzten 20 Bestätigungen.</li><li>Die Review-Übersicht zeigt Ihre Seiten; Admins sehen alle überwachten Seiten und können Erinnerungen sofort senden.</li></ol><p>Grenzen: kein Export, keine Eskalation. Die Mailzustellung hängt von Ihren Confluence-Benachrichtigungen ab.</p>
`);

const SEITEN_REVIEW_SUPPORT = page("seiten-review", "Seiten-Review", "Support, Page Review / Seiten-Review", `
<blockquote><p><b>DRAFT / ENTWURF, not published, not legally reviewed. Placeholders in [[ ]] are open.</b></p></blockquote>
<h1>Support</h1><h2>English</h2><p>E-mail: support@helmdeck.de. Target response: two business days, no guaranteed availability.</p><h2>Deutsch</h2><p>E-Mail: support@helmdeck.de. Ziel: Antwort in zwei Werktagen, keine garantierte Verfügbarkeit.</p>
`);

const SEITEN_REVIEW_PRIVACY = page("seiten-review", "Seiten-Review", "Privacy, Page Review / Seiten-Review", `
<blockquote><p><b>DRAFT / ENTWURF, not published, not legally reviewed. Placeholders in [[ ]] are open.</b></p></blockquote>
<h1>Privacy / Datenschutz</h1><p>Summary of the draft in <code>docs/legal/datenschutzerklaerung.md</code>; the full reviewed text replaces this page.</p><h2>English</h2><ul><li>Runs on Atlassian Forge; no external servers, no tracking, no egress.</li><li>Stores per tracked page: page ID, owner account ID, interval, due date, last review, history of 20 confirmations; one "reminder sent" marker per owner per day (deleted after 3 days).</li><li>Does not read page content, attachments, names or e-mail addresses; only title and link for lists and reminders (not stored).</li><li>Reminders are footer comments by the app with an @mention, visible to everyone who can read the page.</li></ul><p>Controller: Project Kaiser (Tien Duy Vo), {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Germany, privacy@helmdeck.de.</p><h2>Deutsch</h2><ul><li>Läuft auf Atlassian Forge; keine externen Server, kein Tracking, kein ausgehender Verkehr.</li><li>Gespeichert je Seite: Seiten-ID, Konto-ID des Besitzers, Intervall, Frist, letzte Prüfung, Verlauf von 20 Bestätigungen; je Besitzer und Tag eine Marke „Erinnerung gesendet“ (nach 3 Tagen gelöscht).</li><li>Liest keinen Seiteninhalt, keine Anhänge, Namen oder E-Mail-Adressen; nur Titel und Link für Listen und Erinnerungen (nicht gespeichert).</li><li>Erinnerungen sind Fußzeilen-Kommentare der App mit @-Erwähnung, sichtbar für alle Leser der Seite.</li></ul><p>Verantwortlicher: Project Kaiser (Tien Duy Vo), {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Deutschland, privacy@helmdeck.de.</p>
`);

const SEITEN_REVIEW_TERMS = page("seiten-review", "Seiten-Review", "Terms, Page Review / Seiten-Review", `
<blockquote><p><b>DRAFT / ENTWURF, not published, not legally reviewed. Placeholders in [[ ]] are open.</b></p></blockquote>
<h1>Terms / Nutzungsbedingungen</h1><h2>English</h2><p>Base: Atlassian Standard EULA [[to be confirmed]] plus additions: the app stores owners and review dates and posts reminder comments; it never edits or deletes pages; "reviewed" is a statement by the confirming user, not a compliance proof; warranty and liability [[lawyer to draft]].</p><h2>Deutsch</h2><p>Grundlage: Atlassian-Standard-EULA [[zu bestätigen]] mit Zusätzen: Die App speichert Besitzer und Prüftermine und schreibt Erinnerungskommentare; sie ändert oder löscht keine Seiten; „geprüft“ ist eine Erklärung der bestätigenden Person, kein Compliance-Nachweis; Haftung [[Anwalt]].</p>
`);

const TICKET_MERGE_INDEX = page("ticket-merge", "Ticket Merge", "Ticket Merge, Ticket Merge", `
<h1>Ticket Merge</h1>
<p><strong>English:</strong> Merge duplicate Jira tickets: comments, attachments and links are copied to the main ticket, the duplicate is closed, and you can undo within 30 days. Free up to 10 users.</p>
<p><strong>Deutsch:</strong> Doppelte Jira-Tickets zusammenführen: Kommentare, Anhänge und Links wandern ins Haupt-Ticket, das Duplikat wird geschlossen, Rückgängig 30 Tage lang. Kostenlos bis 10 Nutzer.</p>
<p>Jira Service Management features are not yet verified on a JSM site. / Funktionen für Jira Service Management sind auf einer JSM-Site noch nicht überprüft.</p>
<ul>
<li><a href="/ticket-merge/docs">Documentation / Dokumentation</a></li>
<li><a href="/ticket-merge/support">Support</a></li>
<li><a href="/ticket-merge/privacy">Privacy / Datenschutz</a></li>
<li><a href="/ticket-merge/terms">Terms / AGB</a></li>
</ul>
`);

const TICKET_MERGE_DOCS = page("ticket-merge", "Ticket Merge", "Documentation / Dokumentation, Ticket Merge", `
<h1>Documentation / Dokumentation, Ticket Merge</h1>

<h2>English</h2>
<h3>1. What the app does (and does not do)</h3>
<p>Ticket Merge adds the action <strong>Merge into another ticket</strong> to the &quot;...&quot; menu of a Jira issue. It copies the comments, attachments and links of the duplicate to the main ticket, links the two as duplicates and closes the duplicate. It <strong>does not delete</strong> any ticket. Undo is available for 30 days.
Jira has its own merge action (March 2026) for Jira Software and Jira Business projects; this app is for tickets, including service requests, where you want a preview, a log and undo.</p>
<h3>2. Install and permissions</h3>
<p>Install from the Atlassian Marketplace as a site admin. The app asks for: read and write Jira work (tickets, comments, attachments, links, status changes); read and write service desk requests (participants); app storage (the merge log). It makes no calls outside Atlassian. See the privacy policy.
Licence: free for sites with up to 10 users; above that, the price shown in the Marketplace. If the licence is not active, &quot;Merge&quot; is blocked; preview and undo still work.</p>
<h3>3. Your first merge</h3>
<ol>
<li>Open the <strong>duplicate</strong> ticket. Click &quot;...&quot; and choose <strong>Merge into another ticket</strong>.</li>
<li>Enter the key of the <strong>main</strong> ticket (for example SUP-12) and click <strong>Preview</strong>.</li>
<li>Check the numbers (comments, attachments, links, customers), the warnings and the note that the duplicate will be closed.</li>
<li>Click <strong>Merge</strong>. The dialog shows the status. You can close it; open it again later to see the result and the Undo button.
You need these permissions: on the duplicate: browse, transition, comment; on the main ticket: browse, comment, create attachments, link issues.</li>
</ol>
<h3>4. What is copied and what is not</h3>
<table>
<thead>
<tr>
<th>Item</th>
<th>Behavior</th>
</tr>
</thead>
<tbody>
<tr>
<td>Comments</td>
<td>Copied as new comments by the app, with a header line (source key, author, date, internal/public). The original stays.</td>
</tr>
<tr>
<td>Attachments</td>
<td>Copied (download and upload). Files over 10 MB are skipped and listed as a warning. A file with the same name and size already on the main ticket is not copied again.</td>
</tr>
<tr>
<td>Links</td>
<td>Links to other tickets are copied to the main ticket. A link between the two tickets is not copied.</td>
</tr>
<tr>
<td>Customers</td>
<td>For service requests: the reporter and participants of the duplicate are added to the main ticket <strong>[unverified]</strong>.</td>
</tr>
<tr>
<td>Not copied</td>
<td>Ticket fields (title, description, priority, custom fields), worklogs, watchers, history, comment reactions and edit history.</td>
</tr>
<tr>
<td>After copying, the app adds a note on the main ticket, links the tickets as &quot;Duplicate&quot;, and closes the duplicate with the first available transition to a &quot;done&quot; status. If your workflow needs a mandatory field to close, that step can fail; the app shows that it needs help.</td>
<td></td>
</tr>
</tbody>
</table>
<h3>5. Internal and public comments <strong>[unverified]</strong></h3>
<p>The app copies the internal/public flag and never makes an internal comment public. This has <strong>not been tested on a Jira Service Management site</strong>. Until it is, check the first merges yourself.</p>
<h3>6. What customers see and the email limit</h3>
<p>Copied comments and notes are created in the tickets and can trigger the notifications of your Jira Service Management project <strong>[unverified: what is sent, to whom, and when]</strong>. <strong>An email that a customer has already received cannot be taken back.</strong> Undo restores tickets, not inboxes. In the customer note the app tells the customer where updates continue.</p>
<h3>7. Undo</h3>
<p>Open the closed duplicate, open the dialog and click <strong>Undo</strong>. Available for 30 days. It deletes the comments, attachments, links, note and participants the app created and reopens the duplicate. If someone changed the status since, the status is not overwritten and the app reports it. After 30 days the log is removed and undo is no longer possible.</p>
<h3>8. &quot;Partly done&quot; and &quot;needs help&quot;</h3>
<p>If a step fails, the app retries automatically (after 60 seconds, up to 3 attempts per step). The duplicate is closed only after all copy steps worked. If a step keeps failing, the status shows &quot;Partly done&quot;; use Undo or ask a site admin. Starting a second merge of the same ticket while one is running is blocked, so double clicks do not duplicate anything.</p>
<h3>9. Who may merge and undo</h3>
<p>Any agent who can open the action and has the permissions listed above may merge. <strong>Any agent with access to the app can undo any merge</strong> (no role model yet).</p>
<h3>10. Data, privacy, retention, uninstall</h3>
<p>Merge records (keys, IDs, status) stay 30 days in your site's Forge storage; no ticket texts. Nothing leaves Atlassian. Uninstalling removes the stored data <strong>[Atlassian behavior, not verified]</strong>. Copies in your tickets stay unless undone. Details: privacy policy.</p>
<h3>11. Pricing, licence, limits, contact</h3>
<p>Free up to 10 users; above that the Marketplace price per user and month. Known limits: Service Management features not verified; sent emails not recallable; attachments over 10 MB skipped; the app does not merge fields; Atlassian may change its own merge function. Contact: see the support page.</p>
<hr>
<h2>Deutsch</h2>
<h3>1. Was die App tut (und nicht tut)</h3>
<p>Ticket-Merge ergänzt das &quot;...&quot;-Menü eines Jira-Tickets um die Aktion <strong>Merge into another ticket</strong>. Sie kopiert Kommentare, Anhänge und Links des Duplikats in das Haupt-Ticket, verknüpft beide als Duplikat und schließt das Duplikat. Sie <strong>löscht kein</strong> Ticket. Rückgängig ist 30 Tage lang möglich.
Jira hat eine eigene Merge-Aktion (März 2026) für Jira-Software- und Jira-Business-Projekte; diese App ist für Tickets, auch Service-Anfragen, bei denen du eine Vorschau, ein Protokoll und Rückgängig willst.</p>
<h3>2. Installation und Rechte</h3>
<p>Als Site-Admin im Atlassian Marketplace installieren. Die App fragt: Jira-Arbeit lesen und schreiben (Tickets, Kommentare, Anhänge, Links, Statuswechsel); Service-Anfragen lesen und schreiben (Teilnehmer); App-Speicher (das Merge-Protokoll). Sie ruft nichts außerhalb von Atlassian auf. Siehe Datenschutzerklärung.
Lizenz: kostenlos für Sites mit bis zu 10 Nutzern; darüber der im Marketplace angezeigte Preis. Ist die Lizenz nicht aktiv, ist &quot;Merge&quot; gesperrt; Vorschau und Rückgängig funktionieren weiter.</p>
<h3>3. Dein erster Merge</h3>
<ol>
<li>Öffne das <strong>Duplikat</strong>. Klicke &quot;...&quot; und wähle <strong>Merge into another ticket</strong>.</li>
<li>Gib den Schlüssel des <strong>Haupt-Tickets</strong> ein (zum Beispiel SUP-12) und klicke <strong>Vorschau</strong>.</li>
<li>Prüfe die Zahlen (Kommentare, Anhänge, Links, Kunden), die Warnungen und den Hinweis, dass das Duplikat geschlossen wird.</li>
<li>Klicke <strong>Zusammenführen</strong>. Der Dialog zeigt den Stand. Du kannst ihn schließen; später öffnest du ihn wieder und siehst Ergebnis und Rückgängig-Knopf.
Nötige Rechte: am Duplikat: Ansehen, Statuswechsel, Kommentieren; am Haupt-Ticket: Ansehen, Kommentieren, Anhänge anlegen, Tickets verknüpfen.</li>
</ol>
<h3>4. Was kopiert wird und was nicht</h3>
<table>
<thead>
<tr>
<th>Inhalt</th>
<th>Verhalten</th>
</tr>
</thead>
<tbody>
<tr>
<td>Kommentare</td>
<td>Als neue Kommentare der App kopiert, mit Kopfzeile (Quell-Schlüssel, Autor, Datum, intern/öffentlich). Das Original bleibt.</td>
</tr>
<tr>
<td>Anhänge</td>
<td>Kopiert (Download und Upload). Dateien über 10 MB werden übersprungen und als Warnung genannt. Eine Datei mit gleichem Namen und gleicher Größe, die schon am Haupt-Ticket hängt, wird nicht noch einmal kopiert.</td>
</tr>
<tr>
<td>Links</td>
<td>Verknüpfungen zu anderen Tickets werden ans Haupt-Ticket kopiert. Eine Verknüpfung zwischen den beiden Tickets nicht.</td>
</tr>
<tr>
<td>Kunden</td>
<td>Bei Service-Anfragen: Melder und Teilnehmer des Duplikats werden am Haupt-Ticket ergänzt <strong>[ungeprüft]</strong>.</td>
</tr>
<tr>
<td>Nicht kopiert</td>
<td>Ticket-Felder (Titel, Beschreibung, Priorität, eigene Felder), Arbeitszeiten, Beobachter, Verlauf, Reaktionen und Bearbeitungsverlauf von Kommentaren.</td>
</tr>
<tr>
<td>Danach ergänzt die App einen Hinweis am Haupt-Ticket, verknüpft die Tickets als &quot;Duplicate&quot; und schließt das Duplikat mit dem ersten verfügbaren Übergang in einen &quot;Erledigt&quot;-Status. Braucht dein Workflow zum Schließen ein Pflichtfeld, kann dieser Schritt scheitern; die App zeigt dann, dass sie Hilfe braucht.</td>
<td></td>
</tr>
</tbody>
</table>
<h3>5. Interne und öffentliche Kommentare <strong>[ungeprüft]</strong></h3>
<p>Die App übernimmt das Kennzeichen intern/öffentlich und macht einen internen Kommentar nie öffentlich. Das ist <strong>auf einer Jira-Service-Management-Site nicht getestet</strong>. Prüfe die ersten Merges bis dahin selbst.</p>
<h3>6. Was Kunden sehen und die E-Mail-Grenze</h3>
<p>Kopierte Kommentare und Hinweise entstehen in den Tickets und können die Benachrichtigungen deines Service-Projekts auslösen <strong>[ungeprüft: was, an wen und wann gesendet wird]</strong>. <strong>Eine E-Mail, die ein Kunde schon erhalten hat, lässt sich nicht zurückholen.</strong> Rückgängig stellt Tickets wieder her, nicht den Posteingang. Im Kunden-Hinweis sagt die App, wo die Updates weitergehen.</p>
<h3>7. Rückgängig</h3>
<p>Öffne das geschlossene Duplikat, öffne den Dialog und klicke <strong>Rückgängig</strong>. 30 Tage lang möglich. Es löscht die von der App angelegten Kommentare, Anhänge, Links, den Hinweis und die Teilnehmer und öffnet das Duplikat wieder. Hat jemand seither den Status geändert, wird er nicht überschrieben, und die App meldet es. Nach 30 Tagen wird das Protokoll entfernt, dann geht Rückgängig nicht mehr.</p>
<h3>8. &quot;Teilweise erledigt&quot; und &quot;braucht Hilfe&quot;</h3>
<p>Scheitert ein Schritt, versucht die App es selbst erneut (nach 60 Sekunden, bis zu 3 Versuche je Schritt). Das Duplikat wird erst geschlossen, wenn alle Kopierschritte geklappt haben. Scheitert ein Schritt dauerhaft, steht &quot;Teilweise erledigt&quot;; nutze Rückgängig oder frage einen Site-Admin. Ein zweiter Merge desselben Tickets, während einer läuft, ist gesperrt, Doppelklicks erzeugen also nichts doppelt.</p>
<h3>9. Wer mergen und zurücknehmen darf</h3>
<p>Jeder Agent, der die Aktion öffnen kann und die oben genannten Rechte hat, darf mergen. <strong>Jeder Agent mit Zugriff auf die App kann jeden Merge zurücknehmen</strong> (noch kein Rollenmodell).</p>
<h3>10. Daten, Datenschutz, Aufbewahrung, Deinstallation</h3>
<p>Merge-Einträge (Schlüssel, IDs, Status) liegen 30 Tage im Forge-Speicher deiner Site; keine Ticket-Texte. Nichts verlässt Atlassian. Die Deinstallation entfernt die gespeicherten Daten <strong>[Verhalten von Atlassian, nicht geprüft]</strong>. Kopien in deinen Tickets bleiben, wenn sie nicht zurückgenommen werden. Einzelheiten: Datenschutzerklärung.</p>
<h3>11. Preis, Lizenz, Grenzen, Kontakt</h3>
<p>Kostenlos bis 10 Nutzer; darüber der Marketplace-Preis pro Nutzer und Monat. Bekannte Grenzen: Service-Management-Funktionen nicht geprüft; gesendete E-Mails nicht zurückholbar; Anhänge über 10 MB übersprungen; die App führt keine Felder zusammen; Atlassian kann die eigene Merge-Funktion ändern. Kontakt: siehe Support-Seite.</p>
`);

const TICKET_MERGE_SUPPORT = page("ticket-merge", "Ticket Merge", "Support, Ticket Merge", `
<h1>Support, Ticket Merge</h1>

<h2>English</h2>
<h3>Get help</h3>
<p>Write to support@helmdeck.de. Please include:</p>
<ul>
<li>your site name (for example yourcompany.atlassian.net),</li>
<li>the ticket keys (duplicate and main ticket),</li>
<li>what you clicked and what you expected,</li>
<li>the status shown in the dialog (Done, Partly done, ...).
Do <strong>not</strong> send passwords, API tokens or customer data.</li>
</ul>
<h3>Hours and response</h3>
<p>Business days, German or English. Response target: two business days, Monday to Friday (a target, not a guaranteed response time). Free tier (up to 10 users): the same.</p>
<h3>Before you write</h3>
<ul>
<li>Read the <a href="/ticket-merge/docs">documentation</a>, especially &quot;Partly done&quot; and &quot;Undo&quot;.</li>
<li>If a merge is &quot;Partly done&quot;, wait a few minutes: the app retries by itself. Use <strong>Undo</strong> to go back.</li>
<li>A customer got an email you did not want? Sent emails cannot be taken back; undo restores tickets only.</li>
<li>&quot;Merge&quot; shows &quot;license is not active&quot;? Ask a site admin to check the subscription in the Atlassian Marketplace. Preview and undo still work.</li>
</ul>
<h3>Known limits</h3>
<p>Jira Service Management features (internal comments, customers as participants, customer note) have not been verified on a Jira Service Management site. Attachments over 10 MB are skipped. Any agent with access can undo any merge.</p>
<h3>Security reports</h3>
<p>Write to support@helmdeck.de (Security: security@helmdeck.de) with &quot;Security&quot; in the subject.</p>
<hr>
<h2>Deutsch</h2>
<h3>Hilfe bekommen</h3>
<p>Schreibe an support@helmdeck.de. Bitte nenne:</p>
<ul>
<li>den Namen deiner Site (zum Beispiel firma.atlassian.net),</li>
<li>die Ticket-Schlüssel (Duplikat und Haupt-Ticket),</li>
<li>was du geklickt hast und was du erwartet hast,</li>
<li>den Stand im Dialog (Fertig, Teilweise erledigt, ...).
Sende <strong>keine</strong> Passwörter, API-Tokens oder Kundendaten.</li>
</ul>
<h3>Zeiten und Antwort</h3>
<p>Werktage, Deutsch oder Englisch. Reaktionsziel: Antwort innerhalb von zwei Werktagen (Montag bis Freitag), keine zugesicherte Reaktionszeit. Kostenlose Stufe (bis 10 Nutzer): dasselbe.</p>
<h3>Bevor du schreibst</h3>
<ul>
<li>Lies die <a href="/ticket-merge/docs">Dokumentation</a>, besonders &quot;Teilweise erledigt&quot; und &quot;Rückgängig&quot;.</li>
<li>Ist ein Merge &quot;Teilweise erledigt&quot;, warte ein paar Minuten: die App versucht es selbst erneut. Mit <strong>Rückgängig</strong> gehst du zurück.</li>
<li>Ein Kunde hat eine unerwünschte E-Mail bekommen? Gesendete E-Mails lassen sich nicht zurückholen; Rückgängig stellt nur Tickets wieder her.</li>
<li>&quot;Merge&quot; meldet &quot;Lizenz nicht aktiv&quot;? Bitte einen Site-Admin, das Abonnement im Atlassian Marketplace zu prüfen. Vorschau und Rückgängig funktionieren weiter.</li>
</ul>
<h3>Bekannte Grenzen</h3>
<p>Funktionen für Jira Service Management (interne Kommentare, Kunden als Teilnehmer, Kunden-Hinweis) sind auf einer Jira-Service-Management-Site nicht überprüft. Anhänge über 10 MB werden übersprungen. Jeder Agent mit Zugriff kann jeden Merge zurücknehmen.</p>
<h3>Sicherheitsmeldungen</h3>
<p>Schreibe an support@helmdeck.de (Security: security@helmdeck.de) mit &quot;Security&quot; im Betreff.</p>
`);

const TICKET_MERGE_PRIVACY = page("ticket-merge", "Ticket Merge", "Privacy / Datenschutz, Ticket Merge", `
<h1>Privacy Policy / Datenschutzerklärung, Ticket Merge (working name / Arbeitsname)</h1>
<p>Stand / Version: 2026-10-10 · Entwurf, nicht anwaltlich geprüft / Draft, not reviewed by a lawyer.
Abgeleitet aus dem Code (<code>app/src</code>, <code>app/manifest.yml</code>) / Derived from the code. Offene Platzhalter in <code>[eckigen Klammern]</code> muss der Betreiber ausfüllen / Placeholders in square brackets must be filled in by the operator.</p>
<hr>
<h2>English</h2>
<h3>1. Who is responsible</h3>
<p>Operator of the app: Project Kaiser (Tien Duy Vo), {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Germany. Contact for privacy questions: privacy@helmdeck.de.
You (the customer, owner of the Jira site) are the controller of the data in your Jira site. The app processes this data on your behalf, only to perform the actions you start.</p>
<h3>2. What the app is</h3>
<p>Ticket Merge is an Atlassian Forge app. It adds the action &quot;Merge into another ticket&quot; to Jira issues. It runs on Atlassian's Forge platform. The code contains no call to any server outside Atlassian: all requests go to the Jira REST API of your own site.</p>
<h3>3. What data the app reads</h3>
<p>When an agent opens the merge dialog or starts a merge, the app reads from your Jira site, using the agent's permissions (preview) or the app's own account (background work):</p>
<ul>
<li>ticket key, title, status, project, reporter (account ID, display name);</li>
<li>comments of the source and target ticket (text, author display name, date, internal/public flag);</li>
<li>attachments (file name, size, type, and the file content while copying);</li>
<li>issue links;</li>
<li>for Jira Service Management requests: the request's participants (account IDs). <em>Not yet tested on a Jira Service Management site.</em></li>
<li>the account ID of the agent who started the merge, and the agent's permissions on both tickets.
The preview shown to the agent contains only counts, warnings and the step types, no ticket content.</li>
</ul>
<h3>4. What the app writes</h3>
<p>In your Jira site, as part of a merge: copies of comments (with a header line showing source key, author name and date), copies of attachments, issue links, a note comment on the target and, for service requests, a note for the customer and added participants; a &quot;Duplicate&quot; link; a transition that closes the source ticket. Undo removes the copies and reopens the source ticket. These contents belong to your Jira site and follow your retention rules there.</p>
<h3>5. What the app stores</h3>
<p>In Forge storage (key-value store) of your installation, one record per merge (&quot;job&quot;):</p>
<ul>
<li>job ID, source and target ticket keys, account ID of the agent, language (en/de), options, timestamps, status, undo deadline;</li>
<li>per step: type, ID of the source comment/attachment/link, ID of the created copy, link type and direction and the other ticket's key, for added participants their account IDs, the ticket's status name before and after closing, attempt count, and short error text (HTTP status and message) if a step failed.
<strong>Not stored:</strong> comment texts, ticket titles, attachment files or file names, customer names or email addresses.
Attachment files pass through the memory of the running function while they are copied and are not kept.
Queue events (Forge queue) carry the job ID, ticket keys, agent's account ID and language until processed.
Forge platform logs: the app logs only step IDs and error text of failed steps (no ticket content). Retention of Forge platform logs is set by Atlassian [not verified].</li>
</ul>
<h3>6. How long</h3>
<p>Merge records are kept for <strong>30 days</strong> after the merge (the undo period). A daily job removes expired records. The job runs once a day, so deletion can happen up to about a day after the 30 days. Copies made in your tickets stay there until you or the app (undo) delete them. When the app is uninstalled, Forge removes the app's stored data [Atlassian behavior, not verified here].</p>
<h3>7. Who gets the data</h3>
<ul>
<li>No third party, no analytics, no tracking, no advertising, no AI model. No data leaves Atlassian's Forge platform.</li>
<li>Atlassian hosts and runs the app (Forge) and the Jira site. Atlassian's own terms and privacy policy apply to that.</li>
<li>Licensing and billing: the Atlassian Marketplace gives the operator licence information (customer site, contact, number of users, licence state). The operator uses it only to manage the licence and support. [Check which fields Atlassian actually provides.]</li>
<li>Support: if you write to the support address, we process your email and what you send. Please do not send customer data or passwords.</li>
</ul>
<h3>8. Where</h3>
<p>Forge storage and functions run in Atlassian's regions. The data residency options of your Atlassian product apply to the storage [not verified for this app].</p>
<h3>9. Permissions the app requests, and why</h3>
<p><code>read:jira-work</code> (read tickets, comments, attachments, links); <code>write:jira-work</code> (create copies, links, transitions; undo deletes what the app created); <code>read:servicedesk-request</code> and <code>write:servicedesk-request</code> (read and add request participants); <code>storage:app</code> (store the merge records). Undo and background steps run under the app's account, and the app deletes only items it created itself (recorded IDs). <em>Whether this works in service projects with restricted permissions is not tested.</em></p>
<h3>10. Legal basis (EU/EEA)</h3>
<p>As processor on your instructions (the actions your agents start); the legal basis for the controller (you) is yours to determine. For support emails and licence administration: our legitimate interest in answering requests and managing licences (Art. 6(1)(f) GDPR) and, where applicable, performance of a contract (Art. 6(1)(b)). [Lawyer to confirm; add a data processing agreement if you need one.]</p>
<h3>11. Your rights</h3>
<p>You can request information, correction, deletion and restriction of your data and object to processing. Because the merge records contain only IDs and keys in your own Forge storage, deletion happens by itself after 30 days or on uninstall. Contact: privacy@helmdeck.de. You may also complain to your data protection authority.</p>
<h3>12. Changes</h3>
<p>We update this page when the code changes the data handling. Version and date are at the top.</p>
<hr>
<h2>Deutsch</h2>
<h3>1. Verantwortlicher</h3>
<p>Betreiber der App: Project Kaiser (Anschrift und Land: {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Deutschland). Kontakt für Datenschutzfragen: privacy@helmdeck.de.
Sie (der Kunde, Inhaber der Jira-Site) sind Verantwortlicher für die Daten in Ihrer Jira-Site. Die App verarbeitet diese Daten in Ihrem Auftrag, nur um die Aktionen auszuführen, die Sie starten.</p>
<h3>2. Was die App ist</h3>
<p>Ticket-Merge ist eine Atlassian-Forge-App. Sie ergänzt Jira-Tickets um die Aktion &quot;Merge into another ticket&quot;. Sie läuft auf der Forge-Plattform von Atlassian. Der Code ruft keinen Server außerhalb von Atlassian auf: Alle Anfragen gehen an die Jira-REST-API Ihrer eigenen Site.</p>
<h3>3. Welche Daten die App liest</h3>
<p>Wenn ein Agent den Merge-Dialog öffnet oder einen Merge startet, liest die App in Ihrer Jira-Site, mit den Rechten des Agenten (Vorschau) oder dem eigenen Konto der App (Hintergrundarbeit):</p>
<ul>
<li>Ticket-Schlüssel, Titel, Status, Projekt, Melder (Account-ID, Anzeigename);</li>
<li>Kommentare von Quell- und Zielticket (Text, Anzeigename des Autors, Datum, Kennzeichen intern/öffentlich);</li>
<li>Anhänge (Dateiname, Größe, Typ und beim Kopieren der Dateiinhalt);</li>
<li>Ticket-Verknüpfungen;</li>
<li>bei Jira-Service-Management-Anfragen: die Teilnehmer der Anfrage (Account-IDs). <em>Auf einer Jira-Service-Management-Site noch nicht getestet.</em></li>
<li>die Account-ID des Agenten, der den Merge startet, und seine Berechtigungen an beiden Tickets.
Die Vorschau für den Agenten enthält nur Zahlen, Warnungen und die Schrittarten, keine Ticket-Inhalte.</li>
</ul>
<h3>4. Was die App schreibt</h3>
<p>In Ihre Jira-Site, im Rahmen eines Merge: Kopien von Kommentaren (mit Kopfzeile aus Quell-Schlüssel, Autorname und Datum), Kopien von Anhängen, Verknüpfungen, ein Hinweis-Kommentar am Ziel und bei Service-Anfragen ein Hinweis für den Kunden sowie hinzugefügte Teilnehmer; eine &quot;Duplicate&quot;-Verknüpfung; ein Statusübergang, der das Quellticket schließt. Rückgängig entfernt die Kopien und öffnet das Quellticket wieder. Diese Inhalte gehören zu Ihrer Jira-Site und folgen dort Ihren Aufbewahrungsregeln.</p>
<h3>5. Was die App speichert</h3>
<p>Im Forge-Speicher (Key-Value-Store) Ihrer Installation, ein Eintrag je Merge (&quot;Auftrag&quot;):</p>
<ul>
<li>Auftrags-ID, Schlüssel von Quell- und Zielticket, Account-ID des Agenten, Sprache (en/de), Optionen, Zeitstempel, Status, Rückgängig-Frist;</li>
<li>je Schritt: Art, ID des Quell-Kommentars/-Anhangs/-Links, ID der angelegten Kopie, Link-Typ und -Richtung und Schlüssel des anderen Tickets, bei hinzugefügten Teilnehmern deren Account-IDs, Statusname vor und nach dem Schließen, Versuchszähler und ein kurzer Fehlertext (HTTP-Status und Meldung), falls ein Schritt scheiterte.
<strong>Nicht gespeichert:</strong> Kommentartexte, Ticket-Titel, Anhangsdateien oder -namen, Namen oder E-Mail-Adressen von Kunden.
Anhangsdateien laufen beim Kopieren durch den Arbeitsspeicher der laufenden Funktion und werden nicht aufbewahrt.
Warteschlangen-Ereignisse (Forge-Queue) enthalten bis zur Verarbeitung Auftrags-ID, Ticket-Schlüssel, Account-ID des Agenten und Sprache.
Forge-Plattform-Logs: Die App protokolliert nur Schritt-IDs und Fehlertext fehlgeschlagener Schritte (keine Ticket-Inhalte). Die Aufbewahrung der Forge-Plattform-Logs legt Atlassian fest [nicht geprüft].</li>
</ul>
<h3>6. Wie lange</h3>
<p>Merge-Einträge werden <strong>30 Tage</strong> nach dem Merge aufbewahrt (die Rückgängig-Frist). Ein täglicher Job entfernt abgelaufene Einträge. Er läuft einmal am Tag, die Löschung kann daher bis etwa einen Tag nach Ablauf der 30 Tage erfolgen. Kopien in Ihren Tickets bleiben, bis Sie oder die App (Rückgängig) sie löschen. Bei der Deinstallation entfernt Forge die gespeicherten Daten der App [Verhalten von Atlassian, hier nicht geprüft].</p>
<h3>7. Wer die Daten bekommt</h3>
<ul>
<li>Kein Dritter, keine Analyse, kein Tracking, keine Werbung, kein KI-Modell. Keine Daten verlassen die Forge-Plattform von Atlassian.</li>
<li>Atlassian betreibt die App (Forge) und die Jira-Site. Dafür gelten die Bedingungen und die Datenschutzerklärung von Atlassian.</li>
<li>Lizenz und Abrechnung: Der Atlassian Marketplace gibt dem Betreiber Lizenzangaben (Kunden-Site, Kontakt, Nutzerzahl, Lizenzstatus). Der Betreiber nutzt sie nur zur Lizenzverwaltung und für den Support. [Prüfen, welche Felder Atlassian tatsächlich liefert.]</li>
<li>Support: Wenn Sie an die Support-Adresse schreiben, verarbeiten wir Ihre E-Mail und was Sie mitsenden. Bitte senden Sie keine Kundendaten und keine Passwörter.</li>
</ul>
<h3>8. Wo</h3>
<p>Forge-Speicher und -Funktionen laufen in den Regionen von Atlassian. Für den Speicher gelten die Datenresidenz-Optionen Ihres Atlassian-Produkts [für diese App nicht geprüft].</p>
<h3>9. Angeforderte Rechte und wofür</h3>
<p><code>read:jira-work</code> (Tickets, Kommentare, Anhänge, Links lesen); <code>write:jira-work</code> (Kopien, Links, Übergänge anlegen; Rückgängig löscht, was die App angelegt hat); <code>read:servicedesk-request</code> und <code>write:servicedesk-request</code> (Anfrage-Teilnehmer lesen und hinzufügen); <code>storage:app</code> (Merge-Einträge speichern). Rückgängig und Hintergrundschritte laufen unter dem Konto der App; die App löscht nur Objekte, die sie selbst angelegt hat (gespeicherte IDs). <em>Ob das in Service-Projekten mit eingeschränkten Rechten funktioniert, ist nicht getestet.</em></p>
<h3>10. Rechtsgrundlage (EU/EWR)</h3>
<p>Als Auftragsverarbeiter nach Ihrer Weisung (die Aktionen, die Ihre Agenten starten); die Rechtsgrundlage für den Verantwortlichen (Sie) bestimmen Sie. Für Support-E-Mails und Lizenzverwaltung: berechtigtes Interesse an der Beantwortung von Anfragen und der Lizenzverwaltung (Art. 6 Abs. 1 lit. f DSGVO) und gegebenenfalls Vertragserfüllung (Art. 6 Abs. 1 lit. b). [Jurist prüft; bei Bedarf Auftragsverarbeitungsvertrag ergänzen.]</p>
<h3>11. Ihre Rechte</h3>
<p>Sie können Auskunft, Berichtigung, Löschung und Einschränkung Ihrer Daten verlangen und der Verarbeitung widersprechen. Da die Merge-Einträge nur IDs und Schlüssel in Ihrem eigenen Forge-Speicher enthalten, erfolgt die Löschung nach 30 Tagen oder bei Deinstallation von selbst. Kontakt: privacy@helmdeck.de. Sie können sich außerdem bei Ihrer Datenschutzbehörde beschweren.</p>
<h3>12. Änderungen</h3>
<p>Wir aktualisieren diese Seite, wenn der Code den Umgang mit Daten ändert. Version und Datum stehen oben.</p>
`);

const TICKET_MERGE_TERMS = page("ticket-merge", "Ticket Merge", "Terms / AGB, Ticket Merge", `
<h1>Terms of Use (EULA) / Nutzungsbedingungen (AGB), Ticket Merge (working name / Arbeitsname)</h1>
<p>Stand / Version: 2026-10-10 · <strong>Gerüst, nicht anwaltlich geprüft</strong> / <strong>Skeleton, not reviewed by a lawyer.</strong> Platzhalter in <code>[eckigen Klammern]</code>. Vor Veröffentlichung von einem Juristen prüfen lassen. Alternative: die Standardbedingungen des Atlassian Marketplace als EULA verwenden (Entscheidung Owner).</p>
<hr>
<h2>English</h2>
<h3>1. Parties and scope</h3>
<p>These terms apply between Project Kaiser (Tien Duy Vo), {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Germany (&quot;we&quot;) and the organisation that installs Ticket Merge on its Atlassian Cloud site (&quot;you&quot;). They cover the app and its documentation. Atlassian's own terms for the Marketplace, Forge and your Atlassian products apply in addition.</p>
<h3>2. What the app does</h3>
<p>The app merges one Jira ticket into another: it copies comments, attachments and links, links the tickets as duplicates, closes the duplicate and can undo this within 30 days. It does not delete tickets. Details: documentation page.</p>
<h3>3. Licence</h3>
<p>We grant you a non-exclusive, non-transferable right to use the app on your Atlassian Cloud site for the licence period shown in the Atlassian Marketplace. You may not copy, reverse engineer or resell the app, except where mandatory law allows.</p>
<h3>4. Price and payment</h3>
<p>Use is free for sites with up to 10 users. For more users the price shown in the Atlassian Marketplace applies (per user and month) [currently 0.50 USD, to be shown in the listing]. Payment, invoicing, taxes and refunds are handled by Atlassian under the Marketplace terms. We may change prices; changes apply from the next billing period as handled by the Marketplace. A 30-day trial is offered by Atlassian.
If the licence is not active, the merge function is blocked. Preview and undo remain available.</p>
<h3>5. Your duties</h3>
<ul>
<li>You decide who may use the app and are responsible for what your agents merge. Check the preview before you merge.</li>
<li>Make sure you have the right to process the data in your tickets and to copy it between tickets.</li>
<li>Do not use the app unlawfully.</li>
</ul>
<h3>6. Important limits (please read)</h3>
<ul>
<li><strong>Emails already sent cannot be taken back.</strong> If a customer already received an email caused by a copied comment, a note or a status change, undo restores tickets, not inboxes.</li>
<li>Undo is available for 30 days and removes only what the app created. Changes that people made since (for example a new status) are not overwritten; the app reports them.</li>
<li>Copied comments are new comments created by the app account; the author and date appear in a header line, not as the original author. Large attachments (over 10 MB) are not copied.</li>
<li>Features for Jira Service Management (internal comments, customers as participants, customer note) have <strong>not been verified on a Jira Service Management site</strong> at the time of this version. Test first with a copy or a test project.</li>
<li>Atlassian may extend its own merge function or change its APIs; we do not guarantee that every Atlassian change keeps every function.</li>
</ul>
<h3>7. Data protection</h3>
<p>See the privacy policy. We process your data as described there, as processor on your behalf.</p>
<h3>8. Support</h3>
<p>Support by email at support@helmdeck.de on business days, in German or English, with a response target of two business days, Monday to Friday (a target, not a guaranteed response time). For sites in the free tier (up to 10 users) support is the same.</p>
<h3>9. Warranty and liability</h3>
<p>The app is provided &quot;as is&quot; as far as the law allows. We are liable without limit for intent, gross negligence, injury to life, body and health and under mandatory product liability law. For slight negligence we are liable only for breach of essential contract duties and only for typical, foreseeable damage, limited to [AMOUNT, e.g. the fees paid in the last 12 months]. Free use (up to 10 users): liability only for intent and gross negligence. [Lawyer to confirm for the operator's country.]
You are responsible for backups of your Jira data. Before the first productive use, test the app on a non-productive site.</p>
<h3>10. Term and termination</h3>
<p>The licence runs as long as the Marketplace subscription (or the free tier) is active. You can uninstall at any time; the stored merge records are removed (see privacy policy). We may end the offer for good reason and will give [30 days] notice where possible.</p>
<h3>11. Changes</h3>
<p>We may change these terms for good reason. Material changes apply from the next licence period or after notice in the listing and on our website.</p>
<h3>12. Law and courts</h3>
<p>[Governing law and place of jurisdiction, to be set by the operator and lawyer.] Mandatory consumer rights remain unaffected (the app is meant for businesses).</p>
<h3>13. Contact</h3>
<p>Project Kaiser (Tien Duy Vo), {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Germany, support@helmdeck.de</p>
<hr>
<h2>Deutsch</h2>
<h3>1. Parteien und Geltungsbereich</h3>
<p>Diese Bedingungen gelten zwischen Project Kaiser (Anschrift: {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Deutschland) (&quot;wir&quot;) und der Organisation, die Ticket-Merge auf ihrer Atlassian-Cloud-Site installiert (&quot;Sie&quot;). Sie umfassen die App und ihre Dokumentation. Zusätzlich gelten die Bedingungen von Atlassian für den Marketplace, Forge und Ihre Atlassian-Produkte.</p>
<h3>2. Was die App tut</h3>
<p>Die App führt ein Jira-Ticket in ein anderes zusammen: Sie kopiert Kommentare, Anhänge und Links, verknüpft die Tickets als Duplikat, schließt das Duplikat und kann das 30 Tage lang rückgängig machen. Sie löscht keine Tickets. Einzelheiten: Seite Dokumentation.</p>
<h3>3. Lizenz</h3>
<p>Wir räumen Ihnen ein einfaches, nicht übertragbares Recht ein, die App auf Ihrer Atlassian-Cloud-Site für den im Atlassian Marketplace angezeigten Lizenzzeitraum zu nutzen. Sie dürfen die App nicht kopieren, zurückentwickeln oder weiterverkaufen, soweit zwingendes Recht nichts anderes erlaubt.</p>
<h3>4. Preis und Zahlung</h3>
<p>Die Nutzung ist für Sites mit bis zu 10 Nutzern kostenlos. Für mehr Nutzer gilt der im Atlassian Marketplace angezeigte Preis (pro Nutzer und Monat) [derzeit 0,50 USD, im Listing anzugeben]. Zahlung, Rechnung, Steuern und Erstattungen wickelt Atlassian nach den Marketplace-Bedingungen ab. Wir können Preise ändern; Änderungen gelten ab der nächsten Abrechnungsperiode, wie vom Marketplace abgewickelt. Eine 30-tägige Testphase bietet Atlassian an.
Ist die Lizenz nicht aktiv, ist die Merge-Funktion gesperrt. Vorschau und Rückgängig bleiben nutzbar.</p>
<h3>5. Ihre Pflichten</h3>
<ul>
<li>Sie bestimmen, wer die App nutzen darf, und verantworten, was Ihre Agenten zusammenführen. Prüfen Sie die Vorschau vor dem Merge.</li>
<li>Stellen Sie sicher, dass Sie die Daten in Ihren Tickets verarbeiten und zwischen Tickets kopieren dürfen.</li>
<li>Nutzen Sie die App nicht rechtswidrig.</li>
</ul>
<h3>6. Wichtige Grenzen (bitte lesen)</h3>
<ul>
<li><strong>Bereits gesendete E-Mails lassen sich nicht zurückholen.</strong> Hat ein Kunde schon eine E-Mail erhalten, die durch einen kopierten Kommentar, einen Hinweis oder einen Statuswechsel ausgelöst wurde, stellt Rückgängig Tickets wieder her, nicht den Posteingang.</li>
<li>Rückgängig ist 30 Tage lang möglich und entfernt nur, was die App angelegt hat. Änderungen, die Menschen seither gemacht haben (zum Beispiel ein neuer Status), werden nicht überschrieben; die App meldet sie.</li>
<li>Kopierte Kommentare sind neue Kommentare des App-Kontos; Autor und Datum stehen in einer Kopfzeile, nicht als ursprünglicher Autor. Große Anhänge (über 10 MB) werden nicht kopiert.</li>
<li>Funktionen für Jira Service Management (interne Kommentare, Kunden als Teilnehmer, Kunden-Hinweis) sind zum Stand dieser Version <strong>auf einer Jira-Service-Management-Site nicht überprüft</strong>. Testen Sie zuerst mit einer Kopie oder einem Testprojekt.</li>
<li>Atlassian kann die eigene Merge-Funktion erweitern oder Schnittstellen ändern; wir garantieren nicht, dass jede Änderung bei Atlassian jede Funktion erhält.</li>
</ul>
<h3>7. Datenschutz</h3>
<p>Siehe Datenschutzerklärung. Wir verarbeiten Ihre Daten wie dort beschrieben, als Auftragsverarbeiter in Ihrem Auftrag.</p>
<h3>8. Support</h3>
<p>Support per E-Mail an support@helmdeck.de an Werktagen, auf Deutsch oder Englisch, Ziel: Antwort innerhalb von zwei Werktagen (Montag bis Freitag), keine zugesicherte Reaktionszeit. Für Sites in der kostenlosen Stufe (bis 10 Nutzer) gilt gleicher Support.</p>
<h3>9. Gewährleistung und Haftung</h3>
<p>Die App wird, soweit gesetzlich zulässig, &quot;wie sie ist&quot; bereitgestellt. Wir haften unbeschränkt bei Vorsatz, grober Fahrlässigkeit, Verletzung von Leben, Körper und Gesundheit und nach zwingendem Produkthaftungsrecht. Bei leichter Fahrlässigkeit haften wir nur bei Verletzung wesentlicher Vertragspflichten und nur für den typischen, vorhersehbaren Schaden, begrenzt auf [BETRAG, z. B. die in den letzten 12 Monaten gezahlten Entgelte]. Kostenlose Nutzung (bis 10 Nutzer): Haftung nur bei Vorsatz und grober Fahrlässigkeit. [Jurist prüft für das Land des Betreibers.]
Sie sind für Sicherungen Ihrer Jira-Daten verantwortlich. Testen Sie die App vor dem ersten produktiven Einsatz auf einer nicht produktiven Site.</p>
<h3>10. Laufzeit und Beendigung</h3>
<p>Die Lizenz läuft, solange das Marketplace-Abonnement (oder die kostenlose Stufe) aktiv ist. Sie können jederzeit deinstallieren; die gespeicherten Merge-Einträge werden entfernt (siehe Datenschutzerklärung). Wir können das Angebot aus wichtigem Grund beenden und kündigen nach Möglichkeit [30 Tage] vorher an.</p>
<h3>11. Änderungen</h3>
<p>Wir können diese Bedingungen aus wichtigem Grund ändern. Wesentliche Änderungen gelten ab der nächsten Lizenzperiode oder nach Hinweis im Listing und auf unserer Website.</p>
<h3>12. Recht und Gerichtsstand</h3>
<p>[Anwendbares Recht und Gerichtsstand, vom Betreiber mit Jurist festzulegen.] Zwingende Verbraucherrechte bleiben unberührt (die App richtet sich an Unternehmen).</p>
<h3>13. Kontakt</h3>
<p>Project Kaiser, {{ADDR_STREET}}, {{ADDR_ZIP}} Frankfurt am Main, Deutschland, support@helmdeck.de</p>
`);

// ---------------------------------------------------------------- price comparison
// Source: public Atlassian Marketplace API, checked 18 October 2026. USD per
// month at 10 / 50 / 100 / 500 users. The lowest value per column is computed,
// never typed, so a bold cell can not claim more than the data shows.
const PRICE_DATE_EN = "18 October 2026";
const PRICE_DATE_DE = "18. Oktober 2026";
const TIERS = [10, 50, 100, 500];
const money = (v) => v.toFixed(2).replace(/\.00$/, "");

function compareTable(own, others, free) {
  const rows = [own, ...others];
  const best = TIERS.map((_, i) => Math.min(...rows.map((r) => r.p[i])));
  const tr = (r) => `<tr><td>${r.n}${r === own ? " (this app / diese App)" : ""}</td>` +
    r.p.map((v, i) => `<td>${v === best[i] ? `<strong>${money(v)}</strong>` : money(v)}</td>`).join("") + "</tr>";
  return `<table>
<tr><th>App</th>${TIERS.map((t) => `<th>${t} users / Nutzer</th>`).join("")}</tr>
${rows.map(tr).join("\n")}
</table>
<p class=muted>USD per month / USD pro Monat. Bold = lowest price in that column among the apps listed, ties included. / Fett = niedrigster Preis der Spalte unter den gelisteten Apps, Gleichstände eingeschlossen.</p>` +
    (free ? `<p>Free apps, not in the table / Kostenlose Apps, nicht in der Tabelle: ${free}.</p>` : "");
}

const RP_OTHERS = [
  { n: "Comala", p: [0, 47, 94, 259.5] },
  { n: "QC Read &amp; Understood", p: [1, 16.5, 33, 97.5] },
  { n: "Clearlane Read &amp; Understood", p: [0, 15, 30, 87.5] },
  { n: "Read &amp; Understood Acknowledgement", p: [3, 15, 30, 107] },
  { n: "Read Receipts", p: [0, 28, 56, 196.5] },
  { n: "Ackdesk", p: [0, 27.5, 55, 210] },
  { n: "Read &amp; Confirm", p: [0, 33.5, 67, 238.5] },
];
const LD_OTHERS = [
  { n: "Narva", p: [0, 27.5, 55, 165] },
  { n: "codecentric", p: [0, 17.5, 35, 136] },
  { n: "ALDEVA", p: [0, 15.5, 31, 143.5] },
  { n: "Label Pro", p: [0, 15, 30, 85] },
  { n: "Label Organizer", p: [0, 19, 38, 85] },
  { n: "Labele", p: [0, 14, 28, 107.5] },
];

const RP_COMPARE = page("readproof", "ReadProof", "Price comparison, ReadProof", `<h1>Price comparison / Preisvergleich</h1>
<p><strong>EN:</strong> Monthly list prices of ReadProof and seven read-and-confirm apps for Confluence Cloud. Source: public Atlassian Marketplace API, checked ${PRICE_DATE_EN}. Prices change; check the listing before you buy.</p>
<p><strong>DE:</strong> Monatliche Listenpreise von ReadProof und sieben Lesebestätigungs-Apps für Confluence Cloud. Quelle: öffentliche Atlassian-Marketplace-API, Stand ${PRICE_DATE_DE}. Preise ändern sich; prüfe die Listung vor dem Kauf.</p>
${compareTable({ n: "ReadProof", p: [0, 28, 28, 100] }, RP_OTHERS)}
<h2>What the numbers say / Was die Zahlen sagen</h2>
<p>EN: ReadProof is free up to 10 users, like most of the others. The ReadProof price is the Atlassian tier price (rate times the top of the tier: USD 0.28 up to 100 users, USD 0.10 for 251 to 1000 users). At 100 users ReadProof is the cheapest of the apps listed (28 against 30 for Clearlane and Read &amp; Understood Acknowledgement). At 50 users Clearlane and Read &amp; Understood Acknowledgement (15) and QC (16.5) are cheaper, because our tier is not full yet. At 500 users Clearlane (87.5) and QC (97.5) are cheaper; ReadProof is cheaper than the other five. Compare features and price together.</p>
<p>DE: ReadProof ist bis 10 Nutzer gratis, wie die meisten anderen. Der ReadProof-Preis ist der Atlassian-Stufenpreis (Satz mal Obergrenze der Stufe: 0,28 USD bis 100 Nutzer, 0,10 USD für 251 bis 1000 Nutzer). Bei 100 Nutzern ist ReadProof die günstigste der gelisteten Apps (28 gegen 30 bei Clearlane und Read &amp; Understood Acknowledgement). Bei 50 Nutzern sind Clearlane und Read &amp; Understood Acknowledgement (15) sowie QC (16,5) günstiger, weil unsere Stufe noch nicht voll ist. Bei 500 Nutzern sind Clearlane (87,5) und QC (97,5) günstiger; ReadProof ist günstiger als die anderen fünf. Vergleiche Funktionen und Preis zusammen.</p>
<p><a href="/readproof/">Back to ReadProof / Zurück zu ReadProof</a></p>`);

const LD_COMPARE = page("label-doktor", "Label Doctor", "Price comparison, Label Doctor", `<h1>Price comparison / Preisvergleich</h1>
<p><strong>EN:</strong> Monthly list prices of Label Doctor and six label apps for Jira Cloud. Source: public Atlassian Marketplace API, checked ${PRICE_DATE_EN}. Prices change; check the listing before you buy.</p>
<p><strong>DE:</strong> Monatliche Listenpreise von Label Doctor und sechs Label-Apps für Jira Cloud. Quelle: öffentliche Atlassian-Marketplace-API, Stand ${PRICE_DATE_DE}. Preise ändern sich; prüfe die Listung vor dem Kauf.</p>
${compareTable({ n: "Label Doctor", p: [0, 12.5, 25, 108] }, LD_OTHERS, "Label It, Smart Label Manager, Label Ledger")}
<h2>What the numbers say / Was die Zahlen sagen</h2>
<p>EN: Among the paid apps listed, Label Doctor has the lowest price at 50 and 100 users. At 500 users Label Pro and Label Organizer (85) and Labele (107.50) are cheaper than Label Doctor (108). Three apps are free, so Label Doctor is not the cheapest option overall; compare what each one does.</p>
<p>DE: Unter den gelisteten Bezahl-Apps hat Label Doctor bei 50 und 100 Nutzern den niedrigsten Preis. Bei 500 Nutzern sind Label Pro und Label Organizer (85) und Labele (107,50) günstiger als Label Doctor (108). Drei Apps sind kostenlos, Label Doctor ist also insgesamt nicht die günstigste Wahl; vergleiche, was jede App leistet.</p>
<p><a href="/label-doktor/">Back to Label Doctor / Zurück zu Label Doctor</a></p>`);

export const APP_PAGES = {
  "/readproof/compare": RP_COMPARE,
  "/label-doktor/compare": LD_COMPARE,
  "/readproof": LESENACHWEIS_INDEX,
  "/readproof/": LESENACHWEIS_INDEX,
  "/readproof/docs": LESENACHWEIS_DOCS,
  "/readproof/support": LESENACHWEIS_SUPPORT,
  "/readproof/privacy": LESENACHWEIS_PRIVACY,
  "/readproof/terms": LESENACHWEIS_TERMS,
  "/readproof/security": LESENACHWEIS_SECURITY,
  "/seiten-review": SEITEN_REVIEW_INDEX,
  "/seiten-review/": SEITEN_REVIEW_INDEX,
  "/seiten-review/docs": SEITEN_REVIEW_DOCS,
  "/seiten-review/support": SEITEN_REVIEW_SUPPORT,
  "/seiten-review/privacy": SEITEN_REVIEW_PRIVACY,
  "/seiten-review/terms": SEITEN_REVIEW_TERMS,
  "/ticket-merge": TICKET_MERGE_INDEX,
  "/ticket-merge/": TICKET_MERGE_INDEX,
  "/ticket-merge/docs": TICKET_MERGE_DOCS,
  "/ticket-merge/support": TICKET_MERGE_SUPPORT,
  "/ticket-merge/privacy": TICKET_MERGE_PRIVACY,
  "/ticket-merge/terms": TICKET_MERGE_TERMS,
};
