# HelmDeck Launchplan 20.09. bis 30.09.2026

**Ziel:** der erste fremde Download. Arbeitsziel des Owners: 10 fremde Installs bis 30.09.
**Stand der Recherche:** 2026-09-19, alle Preise und Regeln an diesem Tag geprüft.
**Umrechnung:** 1 USD = 0,8726 EUR (EZB-Referenz 2026-09-18, frankfurter.dev).

---

## 0. Kurzfassung

Das Ziel scheitert derzeit nicht an Reichweite, sondern am Trichter. 50 Besucher,
25 Video-Starts, 0 Klicks auf einen Download-Knopf. Die Hälfte aller Besucher
startet das Video, also überzeugt die Botschaft. Danach klickt niemand. Ein
zusätzlicher Kanal multipliziert diese Null.

Zweitens: die Grundannahme "jedes Konto ist neu" stimmt nur zur Hälfte. Das
Reddit-Konto ist über ein Jahr alt und hat 253 Karma. Reddit ist damit der
einzige Kanal, der heute schon offen ist, und der Kanal mit dem klar besten
Verhältnis aus Aufwand und erwarteten Besuchern.

Drittens: es gibt bereits eine zweite, unabhängige und kostenlose Messung für
"fremder Download", die noch niemand benutzt. Die GitHub-Release-Assets zählen
jeden Abruf öffentlich mit.

---

## 1. Was heute wirklich belegt ist

### 1.1 Die harten Zahlen

| Beleg | Quelle | Wert |
|---|---|---|
| Besucher seit 17.09. | eigene D1-Messung (`ops/tools/site_stats.py`) | ca. 50 |
| Video-Starts | dieselbe Messung, Event `video_play` | ca. 25 |
| Klicks auf Download | dieselbe Messung, Event `cta_click` | 0 |
| Downloads Windows-Installer (aktuelles Release v0.2.18) | GitHub Release API, `download_count` | 0 |
| Downloads macOS arm64 dmg (aktuelles Release) | GitHub Release API | 1 |
| Downloads Vorgängerrelease v0.2.17 (exe / dmg) | GitHub Release API | 3 / 2 |
| HN-Konto `helmdeck` | `hacker-news.firebaseio.com/v0/user/helmdeck` | Karma 1, ein einziger Beitrag |
| HN-Beitrag 49766069 | `hacker-news.firebaseio.com/v0/item/49766069` | `"dead": true`, Score 1 |
| Abstand Kontoerstellung bis Beitrag | dieselben zwei Abrufe | **11 Minuten** |
| r/SideProject-Post 1wkmztq | old.reddit.com, eingeloggt geprüft | 1 Punkt, 3 Kommentare, lebt |
| r/ClaudeAI-Post 1wj3lsw | old.reddit.com, eingeloggt geprüft | 0 Punkte, **4 echte Kommentare**, lebt |
| Reddit-Konto `imaxalpha` | Profilseite | 253 Karma, Trophäe "One-Year Club" |
| dev.to-Konto | Profilseite des Artikels | beigetreten 19.09.2026, Artikel sofort live |

Die drei Zahlen aus der Kanalarbeit (Besucher, Video, Downloads) konnte ich in
dieser Karte nicht selbst nachziehen: `site_stats.py` bricht hier mit
Cloudflare-Fehler 7403 ab, weil die Karte keinen Zugriff auf die
Cloudflare-Sitzung des Owners hat. Die GitHub-Zahlen dagegen sind öffentlich und
stammen aus einem eigenen Abruf von heute. Sie bestätigen die Null unabhängig.

### 1.2 Fünf Korrekturen an der Annahme

**Korrektur 1: das Reddit-Konto ist nicht neu.** `imaxalpha` hat 253 Karma und
die Trophäe "One-Year Club". Für r/SideProject, r/devtools und r/ClaudeCode ist
das ausreichend. Es gibt hier nichts aufzuwärmen, nur besser zu posten.

**Korrektur 2: der r/ClaudeAI-Post steckt nicht im Spamfilter.** Er ist
öffentlich erreichbar und hat vier echte Antworten von echten Nutzern
(u/this_for_loona unter anderem). Er hat nur 0 Punkte. Das ist kein Sperrproblem,
das ist ein Flop. Der Unterschied ist wichtig: gegen eine Sperre hilft ein
anderes Konto, gegen einen Flop nur ein anderer Beitrag.

**Korrektur 3: Hacker News hat keine Show-HN-Sperre für neue Konten.** Weder die
Show-HN-Richtlinie noch die Sammlung der undokumentierten HN-Regeln kennt eine
Karma- oder Altersschwelle fürs Einreichen. Was tatsächlich passiert ist: ein
Konto, das 11 Minuten alt war, hat einen Link auf die eigene Domain eingereicht.
Genau darauf reagiert die Missbrauchserkennung. Karma-Schwellen existieren bei
HN nur fürs Flaggen (31), fürs Downvoten (501) und für Kosmetik (251). Neue
Konten laufen zwei Wochen lang mit grünem Namen und landen in `/noobstories`.

**Korrektur 4: Product Hunt hat eine Wartezeit von einer Woche, und sie ist
offiziell umgehbar.** Aus dem PH-Hilfecenter, wörtlich: "you will need to wait
one week before you can post a product. However, if you're ready to post earlier
than a week, you can subscribe to our newsletter for immediate access." Das
Konto muss außerdem ein persönliches Konto sein, mit Vor- und Nachname,
Profilbild und Bio. Firmenkonten dürfen nicht posten.

**Korrektur 5: der 23.09.2026 ist ein Mittwoch, nicht ein Dienstag.** Beide Tage
sind für PH gleich gut. Der Launchtag beginnt um 00:01 Uhr Pazifik, also
09:01 Uhr deutscher Zeit. Der Eintrag muss zu dieser Minute stehen, nicht später.

### 1.3 Der eigentliche Engpass

Die Seite hat funktionierende Download-Knöpfe für Windows, macOS, App Store,
Play Store und APK. Das Klick-Event ist verdrahtet (`data-cta` auf jedem Knopf,
`cta_click` in PostHog und in der eigenen Messung). Es feuert nur nie.

Drei Hypothesen, jede in einem Tag prüfbar:

1. **Kein Linux-Build.** Ein Werkzeug, das einen lokalen Daemon neben Claude Code
   betreibt, wird zu einem großen Teil von Leuten gesucht, die auf Linux
   entwickeln. Für die gibt es auf helmdeck.de nichts zu klicken. Prüfbar über
   die Geräteklasse in der eigenen Messung.
2. **Windows-Warnung.** Der Installer ist unsigniert, die Seite kündigt das
   selbst an ("unsigned warning expected"). Wer das liest, klickt nicht.
   macOS ist signiert und notarisiert, dort fällt das weg.
3. **Die Einstiegshürde steht vor dem Download, nicht dahinter.** Wer
   HelmDeck testen will, braucht ein laufendes Claude Code, einen Daemon auf dem
   PC und ein gekoppeltes Telefon. Wenn die Seite das nicht in drei Zeilen
   beantwortet, ist der Download keine kleine Entscheidung mehr.

Die Sektionsmessung (`section_seen`) beantwortet Hypothese 3 direkt: wenn
Besucher die Downloads-Sektion nie sehen, ist es ein Layoutproblem, wenn sie sie
sehen und nicht klicken, ist es ein Angebotsproblem. Diese Abfrage ist die
billigste Erkenntnis im ganzen Plan und kostet 0 Euro.

---

## 2. Kanaltabelle

Spalte "Besucher" ist die erwartete Zahl **fremder** Besucher im Fenster
20.09. bis 30.09., unter der Annahme, dass die Beiträge so gut sind wie der
r/SideProject-Post, also ordentlich, aber nicht viral. Die Spannen sind breit,
weil das ehrlich ist: ein einziger Beitrag, der auf r/ClaudeCode zieht, wiegt
alle anderen Kanäle zusammen auf.

| Kanal | Sperre für neue Konten | Aufwärmzeit (Tage) | Besucher | Kosten | Entscheidung |
|---|---|---|---|---|---|
| **r/ClaudeCode** | keine. Regel 5 verlangt aber "was du gebaut hast, wie Claude Code benutzt wurde, was du gelernt hast". Reine Projektvorstellung gehört in den wöchentlichen Showcase-Thread | 0 (Konto ist warm) | 80 bis 500 | 0 | **jetzt**, Hauptkanal |
| **r/devtools** | keine. Nur zwei Regeln, Eigenprojekte ausdrücklich erlaubt "if you include some information about how you built it or why it matters" | 0 | 20 bis 70 | 0 | **jetzt** |
| **r/SideProject** | keine Regeln hinterlegt, zwei Moderatoren, niedrigste Hürde von allen. Formatwunsch aus der Sidebar: `[Projektname] - [Kurzbeschreibung]` | 0 | 30 bis 90 | 0 | **jetzt**, zweiter Beitrag mit anderem Aufhänger |
| **r/ChatGPTCoding** | Regel 5 "No pure self-promotion / low-value project posts", Regel 3 verlangt passendes Flair. Der stumme Schluck war vermutlich genau das, kein Kontoproblem | 0 | 0 bis 150 | 0 | **jetzt**, aber nur als Erfahrungsbericht mit Flair, nie als Launch |
| **r/ClaudeAI** | keine, Konto postet dort bereits erfolgreich | 0 | 30 bis 120 | 0 | **jetzt**, Thema muss Claude sein, nicht HelmDeck |
| **r/LocalLLaMA** | Regel 2: Beiträge müssen Llama oder lokale LLMs betreffen. HelmDeck fährt Claude, also am Thema vorbei | n/a | 0 | 0 | **nie** in diesem Fenster |
| **Hacker News, normale Einreichung** | keine formale Sperre. Konto `helmdeck` ist verbrannt (Karma 1, ein toter Beitrag). Zwei Wochen grüner Name | 7 bis 14 | 0 bis 40 | 0 | **später** (nach dem 30.09.) |
| **Hacker News, Show HN** | siehe oben, plus: Show HN verlangt etwas, das man ohne Anmeldung ausprobieren kann. HelmDeck verlangt Installation plus Claude-Abo | 14 | 0 | 0 | **später**, und dann mit dem persönlichen Konto, nicht mit `helmdeck` |
| **Hacker News, Kommentare** | keine | 0 | 5 bis 30 | 0 | **jetzt**. In fremden Threads zu Agenten-Harnesses antworten, ohne Link. Baut gleichzeitig das Karma für später auf |
| **Indie Hackers** | ja, belegt: "You can't create posts yet". Link-Beiträge brauchen ca. 20 Punkte, die nur aus Kommentaren und Upvotes kommen | 5 bis 10 | 0 bis 20 | 0 | **später** |
| **Product Hunt** | eine Woche Wartezeit für neue Konten, offiziell aufhebbar durch Abo des PH-Newsletters. Konto muss persönlich sein (Name, Bild, Bio) | 0 bis 7 | 150 bis 600 | 0 | **jetzt**, Mi 23.09., 09:01 Uhr |
| **dev.to** | keine, heute empirisch bestätigt: neues Konto, Artikel sofort live | 0 | 20 bis 120 | 0 | **jetzt**, zwei weitere Artikel |
| **Hashnode** | keine formale Sperre, aber ein KI-Spamfilter prüft jeden neuen Beitrag und löscht automatisch. Vertrauenssignal ist eine eigene Domain | 0 bis 2 | 10 bis 50 | 0 | **jetzt**, als Zweitveröffentlichung mit Canonical-Link |
| **Lobsters** | ja, hart: nur auf Einladung. Zusätzlich dürfen neue Nutzer 70 Tage lang keine Links von bisher unbekannten Domains einreichen | 70+ | 0 | 0 | **nie** in diesem Fenster |
| **tildes.net** | auf Einladung | unbestimmt | 0 | 0 | **nie** |
| **Slashdot** | keine, Einreichung über die Firehose ist offen | 0 | 0 bis 10 | 0 | **nie**, Publikum passt nicht |
| **X** | keine Sperre, aber praktisch null Follower. Eigene Beiträge erreichen niemanden | 0 | 5 bis 25 | 0 | **jetzt**, aber ausschließlich als Antwort in fremden Threads zu Claude Code, nicht als eigener Beitrag |
| **LinkedIn** | keine, vorhandenes persönliches Netzwerk ist der einzige echte Verteiler den es heute gibt | 0 | 15 bis 60 | 0 | **jetzt**. Link in den ersten Kommentar, nicht in den Beitrag, LinkedIn drosselt ausgehende Links |
| **YouTube Shorts** | keine, aber neuer Kanal ohne Historie | 0 | 0 bis 80 | 0 | **jetzt**, das vorhandene Hero-Video in drei 30-Sekunden-Schnitte zerlegen, Kosten nur Zeit |
| **Discord: r/ClaudeCode-Server** (`discord.gg/4QbtMRErUc`) | keine, in der Sidebar des Subs verlinkt, gleiche Zielgruppe | 1 (erst lesen, dann schreiben) | 10 bis 60 | 0 | **jetzt** |
| **Discord: Anthropic Developers** | keine, Kanäle zu Claude Code sind aktiv, Publikum ist genau die Zielgruppe | 1 bis 2 | 10 bis 50 | 0 | **jetzt**, im passenden Showcase-Kanal, nach Lesen der Serverregeln |
| **Discord: Cursor** | keine, großes Publikum, aber Konkurrenzprodukt-Server | 2 | 0 bis 20 | 0 | **später** |
| **Slack: Build Club, Maven-Alumni** | Aufnahme nötig, teils kostenpflichtige Kurse als Zugang | 7+ | 0 bis 15 | 0 bis hoch | **nie** in diesem Fenster |

**Summe organisch, Mittelwert der Spannen: rund 420 fremde Besucher.**
Untergrenze rund 180, Obergrenze rund 1.900.

### Was den Unterschied zwischen 180 und 1.900 macht

Nicht der Kanal, sondern die Form des Beitrags. Der r/ClaudeAI-Post, der 0 Punkte
bekam, hat vier echte Antworten bekommen. Menschen haben ihn gelesen und
geantwortet, nur niemand fand ihn wichtig genug zum Hochstimmen. Beide
Reddit-Regelwerke, die es wirklich zu beachten gibt (r/ClaudeCode Regel 5,
r/devtools Regel 2), verlangen dasselbe: **wie gebaut, was gelernt.** Der
Jev-Benchmark-Artikel ist genau das und hat als einziger Beitrag echte Antworten
erzeugt. Das ist die Form, die hier funktioniert, und der Plan setzt darauf.

---

## 3. Bezahlte Optionen, Preise von heute

### 3.1 Anzeigen

| Option | Preis | Reichweite | Buchbar in | Neues Konto ein Hindernis? | Urteil für ein kostenloses Entwicklerwerkzeug |
|---|---|---|---|---|---|
| **Reddit Ads** | Mindestens 5 USD pro Tag, 25 USD Laufzeitbudget. CPC typisch 0,75 bis 2,00 USD, Median 1,25 bis 1,85 USD. CPM 3,50 bis 15 USD | exakte Sub-Auswahl möglich: r/ClaudeAI, r/ChatGPTCoding, r/ClaudeCode | Selbstbedienung, gleicher Tag | nein, Werbekonto ist getrennt vom Forumkonto | **ja, beste bezahlte Option.** Einziger Kanal, der die Zielgruppe direkt adressiert, ohne Moderation und ohne Karma. 90 EUR kaufen 55 bis 80 Klicks, mehr als alles Organische bisher zusammen |
| **X Ads** | keine harte Untergrenze, Selbstbedienung ab ca. 20 USD pro Tag. CPC 0,50 bis 2,00 USD | breit, Entwickler-Targeting schwach | gleicher Tag | nein | **nein.** Kampagnen unter 500 USD pro Monat verlassen die Lernphase kaum. Bei 200 EUR Gesamtbudget verbrannt |
| **Google Search Ads** | kein Mindestbudget. Durchschnitt aller Branchen 5,42 USD CPC, Technik 3,80 USD. Long-Tail deutlich billiger | winzige Suchvolumina bei Problembegriffen wie "claude code phone notification" | gleicher Tag | nein | **bedingt ja, 40 bis 50 EUR.** Nicht wegen der Menge, wegen der Absicht: wer das sucht, hat das Problem heute. Nur exakte Übereinstimmung, Markenbegriffe (helmdeck) für 2 bis 3 EUR mitnehmen |
| **daily.dev Ads** | 8 bis 20 USD CPM, 0,50 bis 2,50 USD CPC, 1,2 Mio Entwickler | nativ im Entwickler-Feed | Selbstbedienung | nein | **später.** Preislich möglich, aber Streuverlust: das Publikum sind Entwickler allgemein, nicht Claude-Code-Nutzer |
| **LinkedIn Ads** | 5 bis 12 USD CPC, B2B-Software eher 8 bis 12 USD | präzises Berufs-Targeting | gleicher Tag | nein | **nein.** Bei diesem Budget kauft man 15 Klicks |
| **Product Hunt Promoted** | Preis nur auf Anfrage über die Sponsorenseite | Startseite plus Newsletter | Vertrieb, Tage bis Wochen | nicht relevant | **nein**, und formal ausgeschlossen: Promoted Products sind laut PH-Hilfecenter für brandneue Launches nicht verfügbar |

### 3.2 Newsletter

| Newsletter | Preis | Reichweite | Buchbar in | Neues Konto ein Hindernis? | Urteil |
|---|---|---|---|---|---|
| **TLDR** | drei Plätze pro Ausgabe: 15.000 / 10.000 / 5.000 USD | sehr groß, technisch | Vertrieb, Wochen Vorlauf | nein | **nein**, Faktor 25 über Budget |
| **Hacker Newsletter** | Hauptsponsor 850 bis 1.000 USD pro Ausgabe, Kleinanzeige ca. 150 USD (Drittquellen, auf der eigenen Seite heute nicht veröffentlicht, Seiten `/sponsor` und `/advertise` liefern 404). Bestätigt auf der Startseite: **60.000+ Abonnenten** | exakt das HN-Publikum, ganz ohne HN-Karma | per Mail, typisch 1 bis 3 Wochen Vorlauf | nein | **die interessanteste Option des ganzen Berichts, aber zu spät.** 150 USD = 131 EUR für eine Kleinanzeige an 60.000 HN-Leser ist der einzige bezahlbare Weg an diese Zielgruppe. Vorlauf passt nicht ins Fenster. **Preis heute per Mail erfragen, für Oktober buchen** |
| **Console.dev** | kein öffentlicher Preis, Kontakt hello@console.dev. Belegte Publikumsdaten: "68% of our readers have signed-up to a tool featured by Console", "77% have been coding for 5+ years" | Entwicklerwerkzeuge, hohe Kaufabsicht | Mail, Vorlauf unbekannt | nein | **anfragen, nicht buchen.** 68 Prozent Anmeldequote ist der beste Wert im Feld. Console nimmt Werkzeuge auch redaktionell auf, das ist kostenlos und der eigentliche Hebel |
| **Bytes** | kein öffentlicher Preis, sponsor@fireship.dev | JavaScript-Publikum | Mail | nein | **nein**, falsches Publikum |
| **Pointer** | CPM 15 bis 40 USD laut Sammelliste, kein eigener Preisaushang | Engineering-Leadership | Mail | nein | **später** |
| **Refind** | kein öffentlicher Preis heute auffindbar | breit | Mail | nein | **nein**, nicht bewertbar ohne Preis |

### 3.3 Podcasts

| Podcast | Preis | Reichweite | Urteil |
|---|---|---|---|
| **The Changelog** | 3.000 USD pro Woche (2 Folgen), Minimum 4 Wochen | 40.000 bis 80.000 Entwickler pro Woche | **nein**, 12.000 USD Einstiegsticket |
| **Changelog News** | 1.500 USD pro Woche, kein Minimum | 20.000 bis 30.000 Hörer, 22.000 Newsletter-Abos, 51,35 % Öffnungsrate | **nein** für jetzt, günstigste ernsthafte Option im Segment |
| **Practical AI** | 1.200 USD pro Folge, Minimum 4 Wochen | 35.000 bis 45.000 Hörer | **nein** |
| **Fallthrough** | 200 USD pro Folge, Minimum 4 Wochen | 1.000 bis 2.000 Hörer, Go-Publikum | **nein**, Publikum passt nicht, und 4 Folgen Minimum = 800 USD |

Allgemeine Marke für später: Entwickler-Podcasts liegen bei 25 bis 50 USD CPM
für Mid-Roll, technikspezifische bei 45 bis 65 USD.

### 3.4 Launch-Verzeichnisse

| Dienst | Preis | Reichweite | Buchbar in | Neues Konto | Urteil |
|---|---|---|---|---|---|
| **Peerlist Launchpad** | **kostenlos**, ein Launch pro Woche möglich | Entwicklerpublikum, kleine aber echte Besucherzahl | sofort | nein | **jetzt buchen.** Bestes Verhältnis im Feld, weil Null |
| **Fazier** | Basic **kostenlos** (Prüfung binnen 30 Tagen, Rückverweis auf Fazier nötig), Lite 29 USD, Premium 49 USD, Super 139 USD (heute auf fazier.com/submit geprüft) | DR 83, Backlink, wenig menschlicher Verkehr | sofort bei bezahlt, 30 Tage bei gratis | nein | **Lite 29 USD nur, wenn der Eintrag am Launchtag stehen soll.** Sonst Basic kostenlos |
| **Uneed** | freie Warteschlange **seit 17.08.2026 für neue Produkte geschlossen**. Fast-Track 14,99 USD (Termin ca. 2 Wochen später), Skip the Line 29,99 USD (Termin frei wählbar), Boosted 59 USD (plus X-Erwähnung) | mittel | sofort | nein | **Skip the Line 29,99 USD**, wenn der Termin auf den PH-Tag gelegt werden soll. Sonst auslassen |
| **BetaList** | keine kostenlosen Einreichungen mehr, ab ca. 39 USD, Preis wird erst am Ende des Formulars gezeigt | gut für Vorab-Registrierungen | Tage bis Wochen | nein | **nein.** Kriterium "recently launched or still unreleased" passt zwar, aber BetaList treibt Newsletter-Anmeldungen, nicht Installationen |
| **MicroLaunch** | ab 39 USD, DR 63, Dofollow | klein | sofort | nein | **nein**, Preis pro echtem Besucher zu hoch |
| **Launching Next** | kostenlose Stufe vorhanden, bezahlt ab 99 USD | klein | Tage | nein | **kostenlose Stufe jetzt**, bezahlt nein |
| **Startup Fame** | Preis heute nicht aus einer Primärquelle belegbar | unbekannt | unbekannt | nein | **nein**, nicht bewertbar |
| **Product Hunt selbst** | kostenlos | 150 bis 600 Besucher für einen Launch ohne Publikum | sofort, nach Freischaltung | ja, eine Woche, per Newsletter-Abo aufhebbar | **jetzt** |

**Ehrliches Urteil zur ganzen Kategorie:** Verzeichnisse liefern Backlinks, nicht
Installationen. Wer 150 USD über fünf Verzeichnisse verteilt, kauft SEO für das
nächste Quartal und ungefähr 30 Besucher für dieses. Der Plan nimmt deshalb nur
die kostenlosen mit plus höchstens einen bezahlten Eintrag, der auf den PH-Tag
gelegt wird.

---

## 4. Kalender 20.09. bis 30.09.

"Agent" heißt: als HelmDeck-Karte ausführbar. "Owner" heißt: braucht ein Konto,
ein Urteil oder eine Unterschrift und kann nicht delegiert werden.

### So, 20.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| Messung | `site_stats.py --days 14` ausführen und drei Fragen beantworten: erreichen Besucher die Downloads-Sektion, welche Geräteklasse dominiert, wo brechen sie ab | Owner (Cloudflare-Sitzung nötig, Agent scheitert an Fehler 7403) | nichts |
| Seite | Ergebnis umsetzen: Download-Block über den Falz, ein einziger Knopf für das erkannte Betriebssystem, darunter in drei Zeilen was man braucht (Claude Code, ein PC der läuft, ein Telefon) | Agent | Messung von oben |
| Seite | Windows-Warnung entschärfen: statt "unsigned warning expected" eine Zeile mit den zwei Klicks, die es braucht, plus SHA256 sichtbar | Agent | nichts |
| Seite | Linux-Frage beantworten. Entweder ein Build, oder eine ehrliche Zeile "Linux kommt, hier eintragen" mit Mail-Feld. Nicht schweigen | Owner entscheidet, Agent baut | nichts |
| Product Hunt | Konto persönlich machen: Vor- und Nachname, Profilbild, Bio. **PH-Newsletter abonnieren**, das hebt die Wochensperre auf | Owner | nichts |
| Product Hunt | Eintrag vorbereiten: Name, Tagline, Beschreibung, vier Bilder, Video, Themen, Preis-Tag "Free". Noch nicht veröffentlichen | Agent, Owner gibt frei | nichts |

### Mo, 21.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| r/ClaudeCode | Beitrag nach Regel 5: was gebaut, wie Claude Code dabei benutzt wurde, was gelernt. Aufhänger: die Harness baut sich selbst, inklusive der Stelle wo es schiefging | Owner postet, Agent entwirft | Vorher zwei Tage lang in fremden Threads antworten, ohne Link |
| Discord r/ClaudeCode | Server betreten, Regeln lesen, zwei fremden Leuten helfen. **Nichts eigenes posten** | Owner | nichts |
| dev.to | Zweiter Artikel, Fortsetzung des Jev-Artikels: was ein Harness tun muss, wenn das billige Modell nicht plant | Agent | nichts |
| Hashnode | Jev-Artikel als Zweitveröffentlichung mit Canonical auf dev.to | Agent | nichts |
| Peerlist | Launchpad-Eintrag, kostenlos | Owner (Konto) | nichts |
| Launching Next | kostenlose Einreichung | Agent | nichts |
| Fazier | Basic-Einreichung, kostenlos | Agent | Rückverweis auf Fazier muss auf helmdeck.de stehen |

### Di, 22.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| Hacker News | **Neues persönliches Konto** anlegen, nicht `helmdeck` weiterverwenden. Ab heute täglich zwei bis drei sachliche Kommentare in Agenten-Threads. Kein Link, keine Erwähnung | Owner | nichts. Das ist selbst das Aufwärmen, Zielmarke 20+ Karma bis Anfang Oktober |
| r/devtools | Beitrag nach Regel 2: warum ein Gate zwischen Agent und Merge existiert und wie es gebaut ist | Owner postet, Agent entwirft | Konto ist warm |
| Reddit Ads | Werbekonto anlegen, Zahlungsmittel hinterlegen, Kampagne bauen aber pausiert lassen. Ziel: Traffic, CPC-Gebot, Platzierung in r/ClaudeAI, r/ChatGPTCoding, r/ClaudeCode | Owner | Landeseite muss bis hierhin gefixt sein, sonst kauft man Klicks auf eine Null |
| Product Hunt | Eintrag final prüfen, erste Kommentar-Antwort vorschreiben | Owner | Freischaltung muss stehen |
| YouTube Shorts | Hero-Video in drei Schnitte à 30 Sekunden, je eine Frage: was nervt, was passiert stattdessen, wie sieht es auf dem Telefon aus | Agent | nichts |

### Mi, 23.09. (Product-Hunt-Tag)

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| Product Hunt | **09:01 Uhr deutscher Zeit** veröffentlichen. Erster Maker-Kommentar in derselben Minute | Owner | Konto freigeschaltet seit 20.09. |
| Product Hunt | Den ganzen Tag jede Frage binnen einer Stunde beantworten. Das ist der eigentliche Ranking-Faktor | Owner | nichts |
| X, LinkedIn | Launch-Hinweis. LinkedIn: Link in den ersten Kommentar. X: unter eigene frühere Beiträge hängen, nicht neu | Owner | nichts |
| Uneed (optional, 29,99 USD) | Skip the Line auf den 23.09. legen, falls der bezahlte Posten im Budget bleibt | Owner | nichts |
| Reddit Ads | Kampagne starten, 10 EUR pro Tag | Owner | Landeseite gefixt |

### Do, 24.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| r/SideProject | Zweiter Beitrag, Format aus der Sidebar `HelmDeck - <Kurzbeschreibung>`. Anderer Aufhänger als am 19.09.: was nach 5 Tagen Launch tatsächlich passiert ist, inklusive der Null | Owner | Konto ist warm |
| Messung | Erste Zwischenbilanz: GitHub `download_count` gegen Vortag, `cta_click`-Rate, Reddit-Ads-CPC | Agent (GitHub), Owner (D1) | nichts |
| Google Ads | Kampagne mit 12 bis 15 exakten Problembegriffen plus Markenbegriff, 5 EUR pro Tag | Owner | nichts |
| Hacker News | weiter kommentieren | Owner | läuft |

### Fr, 25.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| Discord Anthropic Developers | Nach vier Tagen Mitlesen im passenden Showcase-Kanal vorstellen, als Erfahrungsbericht | Owner | vier Tage Mitlesen |
| dev.to | Dritter Artikel: die Messung selbst. 50 Besucher, 25 Video-Starts, 0 Downloads, und was daraus wurde. Das ist der Beitrag mit der höchsten Chance auf Reichweite, weil er ungewöhnlich ehrlich ist | Agent | echte Zahlen vom 24.09. |
| Hacker Newsletter | Preis für eine Kleinanzeige per Mail erfragen, Termin für Oktober | Owner | nichts |
| Console.dev | Werkzeug redaktionell einreichen (kostenlos) und gleichzeitig Preis erfragen | Owner | nichts |

### Sa, 26.09. und So, 27.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| alle | Antworten. Jeder Kommentar unter jedem Beitrag, binnen Stunden. Keine neuen Beiträge am Wochenende | Owner | nichts |
| YouTube Shorts | Drei Schnitte veröffentlichen, einer pro Tag ab Sa | Agent | nichts |
| Messung | GitHub-Downloadzähler protokollieren, täglich, in `campaign-links.csv` als eigene Zeile | Agent | nichts |

### Mo, 28.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| r/ChatGPTCoding | Erfahrungsbericht mit korrektem Flair, kein Launch. Aufhänger: was drei Tage bezahlter Reddit-Klicks über die eigene Landeseite verraten haben | Owner | Regel 5 des Subs, der Beitrag darf keine Produktvorstellung sein |
| r/ClaudeAI | Beitrag über Claude, nicht über HelmDeck. Zum Beispiel: Kostenverlauf einer selbstlaufenden Harness über eine Woche | Owner | Konto postet dort bereits |
| Reddit Ads | Nach 5 Tagen: schlechteste Anzeigengruppe abschalten, Budget umlegen | Owner | nichts |

### Di, 29.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| Indie Hackers | Punktestand prüfen. Bei 20+ Punkten den Launch-Beitrag setzen, sonst weiter kommentieren | Owner | seit 20.09. täglich zwei Kommentare, sonst kein Postrecht |
| LinkedIn | Zweiter Beitrag: die Zahlen der Woche, offen | Owner | nichts |
| Messung | Zwischenstand gegen das Ziel: wie viele fremde Downloads sind gezählt | Agent | nichts |

### Mi, 30.09.

| Kanal | Aufgabe | Wer | Vorher aufwärmen |
|---|---|---|---|
| Messung | Endbilanz. GitHub-Zähler, App Store Connect, Play Console, D1-Trichter, Ausgaben gegen Klicks pro Kanal | Owner (Konsolen), Agent (Rest) | nichts |
| Plan | Entscheidung für Oktober: Hacker Newsletter buchen ja oder nein, HN-Konto reif ja oder nein, Reddit Ads skalieren ja oder nein | Owner | Endbilanz |

---

## 5. Prognose

### 5.1 Besucher

| Quelle | erwartet (Mitte) | Spanne |
|---|---|---|
| Reddit organisch, 6 Beiträge | 200 | 80 bis 900 |
| Product Hunt | 300 | 150 bis 600 |
| dev.to und Hashnode, 3 Artikel | 70 | 30 bis 170 |
| Discord, 2 Server | 35 | 10 bis 110 |
| X und LinkedIn | 45 | 20 bis 85 |
| YouTube Shorts | 25 | 0 bis 80 |
| Verzeichnisse (kostenlos) | 20 | 5 bis 50 |
| Reddit Ads, 90 EUR | 65 | 45 bis 110 |
| Google Ads, 45 EUR | 20 | 10 bis 35 |
| **Summe** | **780** | **350 bis 2.140** |

Die Mitte ist bewusst nicht die Mitte der Spannen, sondern näher an der
Untergrenze. Grund: der einzige echte Datenpunkt, den es gibt, ist ein
r/SideProject-Beitrag mit 1 Punkt und ein r/ClaudeAI-Beitrag mit 0 Punkten. Bis
ein Beitrag das Gegenteil zeigt, ist der vorsichtige Wert der richtige.

### 5.2 Downloads

Die Umrechnung von Besuchern in Downloads ist die eigentliche Unbekannte, weil
der gemessene Wert heute exakt **0 von 50** ist. Drei Szenarien:

| Szenario | Annahme | Klicks auf Download | Tatsächliche Downloads | Funktionierende Installation |
|---|---|---|---|---|
| **Trichter bleibt wie er ist** | 0 bis 1 % | 0 bis 8 | 0 bis 5 | 0 bis 2 |
| **Trichter wird am 20.09. gefixt, Wert landet im unteren Normalbereich für Entwicklerwerkzeuge** | 3 % | 23 | 14 bis 18 | 6 bis 10 |
| **Trichter gefixt und Linux-Antwort steht** | 5 % | 39 | 25 bis 30 | 12 bis 18 |

Der Schwund zwischen Klick und tatsächlichem Download kommt aus der
Windows-Warnung (unsignierter Installer) und aus Abbrüchen beim 86-MB-Download.
Der Schwund zwischen Download und funktionierender Installation kommt aus der
Einstiegshürde: Claude Code muss vorhanden sein, ein Daemon muss laufen, ein
Telefon muss gekoppelt werden.

### 5.3 Ist das Ziel von 10 fremden Installs bis 30.09. erreichbar?

**Ja, aber nur unter zwei Bedingungen, und die Antwort hängt an der Definition.**

Wenn "Install" heißt: **ein Fremder hat eine Binärdatei geladen** (messbar über
GitHub `download_count` plus App Store und Play Console), dann ist 10 im
mittleren Szenario erreicht und im guten Szenario deutlich übertroffen. Das ist
realistisch.

Wenn "Install" heißt: **ein Fremder hat HelmDeck laufen, mit gekoppeltem
Telefon**, dann liegt die Erwartung bei 6 bis 10 im mittleren Szenario, also
genau auf der Kippe, und im heutigen Zustand bei 0 bis 2.

Die zwei Bedingungen:

1. **Der Trichter wird vor dem bezahlten Verkehr repariert, nicht danach.** Jeder
   Euro, der vor dem 22.09. in Anzeigen fließt, kauft Klicks auf eine Seite mit
   0 % Konversion. Deshalb steht in diesem Plan der Landeseiten-Tag am 20.09. und
   die erste Anzeige am 23.09.
2. **Product Hunt muss am 23.09. stehen.** Es ist der einzige Kanal im Fenster,
   der an einem Tag dreistelligen Verkehr liefert, ohne Karma, ohne Aufwärmen
   und ohne Geld. Fällt er aus, fällt die Mitte der Prognose von 780 auf etwa
   480 und das Ziel wird unwahrscheinlich.

**Was die Prognose zusätzlich gefährdet:** das Produkt verlangt ein bezahltes
Claude-Abo, einen dauerhaft laufenden PC und eine Gerätekopplung. Das ist kein
Werkzeug, das man aus Neugier um 23 Uhr installiert. Wer die 10 Installationen
will, sollte zusätzlich damit rechnen, drei bis fünf davon persönlich durch die
Einrichtung zu begleiten, in Reddit-Antworten oder im Discord. Das ist bei den
ersten Nutzern normal und zählt.

---

## 6. Budget

### 6.1 Variante unter 200 Euro, wirkungsvollste Aufteilung

| Posten | Betrag | Warum |
|---|---|---|
| **Reddit Ads**, 10 EUR pro Tag vom 23.09. bis 30.09. | 80 EUR | Einziger bezahlter Kanal, der exakt die Zielgruppe erreicht, ohne Karma und ohne Moderation. Bei CPC 1,25 bis 1,85 USD ergibt das 50 bis 75 Klicks. Wichtiger als die Klicks: es ist der einzige Weg, die Konversionsrate der Landeseite in einer Woche statistisch zu messen statt zu raten |
| **Google Search Ads**, exakte Übereinstimmung, 5 EUR pro Tag vom 24.09. bis 30.09. | 35 EUR | Kleine Menge, höchste Absicht. Enthält den Markenbegriff "helmdeck" für wenige Cent, damit PH- und Reddit-Leser, die später suchen, nicht verloren gehen |
| **Uneed Skip the Line** 29,99 USD | 26 EUR | Terminierbar auf den 23.09., verdoppelt die Sichtbarkeit des PH-Tags an einem zweiten Ort |
| **Fazier Lite** 29 USD | 25 EUR | Nur falls der Eintrag am Launchtag stehen soll, sonst streichen und Basic kostenlos nehmen |
| Reserve | 34 EUR | Für die beste Anzeigengruppe am 28.09. nachlegen, wenn eine klar funktioniert |
| **Summe** | **200 EUR** | |

**Wenn nur eine Zeile bleibt: die 80 EUR Reddit Ads.** Sie sind die einzige
Ausgabe im ganzen Plan, die eine Frage beantwortet statt nur Verkehr zu kaufen.

**Ausdrücklich nicht im Budget:** alle Newsletter (der billigste relevante,
Hacker Newsletter Kleinanzeige, liegt bei 131 EUR und hätte zwei Wochen
Vorlauf), alle Podcasts (Einstieg ab 800 USD), X Ads (verbrennt unter 500 USD
pro Monat), BetaList und MicroLaunch (ab 34 EUR für Backlinks statt
Installationen).

### 6.2 Variante mit 0 Euro

Streiche aus dem Kalender: Reddit Ads, Google Ads, Uneed, Fazier Lite. Alles
andere bleibt unverändert. Ersetze die bezahlten Posten durch:

| statt | nimm | Kosten |
|---|---|---|
| Uneed Skip the Line | Peerlist Launchpad (kostenlos, wöchentlich wiederholbar) plus Launching Next kostenlose Stufe | 0 |
| Fazier Lite | Fazier Basic, kostenlos, 30 Tage Prüfzeit, Rückverweis auf fazier.com nötig | 0 |
| Reddit Ads | Ein siebter organischer Reddit-Beitrag plus täglich fünf echte Antworten in fremden Threads zu Claude Code. Zeitaufwand ca. 40 Minuten pro Tag | 0 |
| Google Ads | Die dev.to-Artikel auf die Problembegriffe hin betiteln, die sonst die Anzeigen gekauft hätten. dev.to rankiert bei Google schnell | 0 |

**Erwarteter Unterschied:** rund 85 Besucher weniger, also Mitte 695 statt 780.
Das sind ungefähr 2 bis 3 Downloads weniger im mittleren Szenario.

**Ehrliche Einordnung:** die 200 Euro entscheiden nicht, ob das Ziel erreicht
wird. Das entscheidet der Landeseiten-Tag am 20.09. Wenn die Wahl zwischen
"200 Euro ausgeben" und "einen Tag an der Downloads-Sektion arbeiten" steht,
gewinnt der Tag an der Sektion, und zwar deutlich. Die Null-Euro-Variante ist
keine Notlösung, sondern die ordentliche Antwort, solange die Konversionsrate
der Seite unbekannt ist.

---

## 7. Wie "fremder Download" ab sofort gezählt wird

Die App sendet nichts, PostHog sieht deshalb keine Installationen. Das muss
nicht so bleiben, denn drei Zähler existieren bereits und kosten nichts:

| Zähler | Quelle | Wer kommt dran | Frische |
|---|---|---|---|
| **Desktop und APK** | `api.github.com/repos/Tienduyvo/helmdeck-release/releases`, Feld `download_count` je Asset | öffentlich, kein Token | Minuten |
| **iOS und Apple Watch** | App Store Connect, Verkaufsbericht | nur Owner | ein Tag Versatz |
| **Android über Play** | Play Console | nur Owner | ein bis zwei Tage Versatz |

Zwei Fallstricke, die die Zahl verfälschen:

1. **Der eigene Auto-Updater zählt mit.** Die Dateien `latest.yml` und
   `latest-mac.yml` werden vom Desktop-Updater abgerufen, nicht von Menschen.
   Im Release v0.2.17 stehen 8 Abrufe auf `latest.yml` gegen 3 auf der exe. Nur
   die exe-, dmg- und apk-Zähler sind ein Mensch.
2. **Eigene Tests zählen mit.** Vor dem 20.09. einmal den Stand aller Assets
   festhalten, danach nur noch Differenzen betrachten. Aktueller Stand
   (2026-09-19, Release v0.2.18): exe 0, arm64 dmg 1, x64 dmg 0, arm64 zip 0.

**Empfehlung:** den täglichen Abruf des GitHub-Zählers als Zeile in
`ops/docs/marketing/campaign-links.csv` mitschreiben. Dann steht am 30.09. eine
lückenlose Kurve statt einer Momentaufnahme.

---

## 8. Quellen

Alle am 2026-09-19 abgerufen.

**Primärquellen (eigene Abrufe):**
- Hacker News Item- und User-API: `hacker-news.firebaseio.com/v0/item/49766069.json`, `.../user/helmdeck.json`
- GitHub Releases API: `api.github.com/repos/Tienduyvo/helmdeck-release/releases`
- Reddit, eingeloggt über old.reddit.com: Regelseiten von r/ChatGPTCoding, r/ClaudeAI, r/ClaudeCode, r/LocalLLaMA, r/devtools, r/SideProject; Profil und Posteingang von u/imaxalpha; Beiträge 1wkmztq und 1wj3lsw
- EZB-Referenzkurs über frankfurter.dev
- helmdeck.de, Quelltext `ops/deploy/waitlist/src/index.js` in diesem Arbeitsbaum

**Regeln:**
- Show HN Richtlinie: https://news.ycombinator.com/showhn.html
- HN undokumentierte Normen: https://github.com/minimaxir/hacker-news-undocumented
- Product Hunt, Posting-Zugang: https://help.producthunt.com/en/articles/481909-how-can-i-get-access-to-post
- Product Hunt, Promoted Products: https://help.producthunt.com/en/articles/1444961-how-do-i-get-my-product-promoted
- Lobsters: https://lobste.rs/about
- BetaList Kriterien: https://betalist.com/criteria
- Hashnode Nutzungsbedingungen und Verhaltenskodex: https://hashnode.com/terms, https://hashnode.com/code-of-conduct
- Indie Hackers, Postrecht: https://www.indiehackers.com/post/any-requirements-for-posting-a108d65954

**Preise:**
- Fazier: https://fazier.com/submit
- Uneed: https://www.uneed.best/pricing
- Changelog Sponsoring: https://changelog.com/sponsor/pricing
- Console.dev: https://console.dev/advertise
- Bytes: https://bytes.dev/advertise
- Hacker Newsletter Abonnentenzahl: https://hackernewsletter.com/
- Reddit Ads Kosten: https://www.stackmatix.com/blog/reddit-ads-cost-pricing-guide-2026
- X Ads Kosten: https://www.stackmatix.com/blog/x-twitter-ads-cost
- Google Ads Kosten: https://www.webfx.com/blog/ppc/much-cost-advertise-google-adwords/
- daily.dev Ads: https://business.daily.dev/resources/developer-ads-pricing-options-best-channels/
- Entwickler-Newsletter Übersicht: https://github.com/jackbridger/developer-newsletters
- TLDR Sponsorenpreise: https://growthinreverse.com/tldr/
- Verzeichnisse mit Preisen: https://noonlaunch.com/blog/startup-launch-directories

**Nicht belegbar:** Startup Fame (kein öffentlicher Preis auffindbar), Refind
(kein öffentlicher Preis auffindbar), Console.dev und Bytes (Preis nur auf
Anfrage), Hacker Newsletter (eigene Preisseiten liefern heute 404, die genannten
850 bis 1.000 USD und 150 USD stammen aus Drittquellen und sind vor einer
Buchung per Mail zu bestätigen).
