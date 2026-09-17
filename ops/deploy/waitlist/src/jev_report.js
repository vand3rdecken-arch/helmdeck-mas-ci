export const JEV_REPORT_HTML = `<!doctype html><html lang=de><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta name=robots content="noindex,nofollow">
<title>Jev vs. HelmDeck Hands – Formular-Benchmark</title>
<style>
body{font:15px/1.5 -apple-system,system-ui,Segoe UI,Roboto,sans-serif;margin:0;padding:20px;background:#0f1115;color:#e7e9ee;max-width:760px;margin:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.sub{color:#9aa3b2;font-size:13px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:6px}
th,td{padding:8px 6px;border-bottom:1px solid #262b35;text-align:left;vertical-align:top}
th{color:#9aa3b2;font-weight:600;font-size:12px;text-transform:uppercase}
td:first-child{color:#9aa3b2;width:30%}
.good{color:#5fd38d}.bad{color:#ff7a7a}.mid{color:#f2c46d}
.box{background:#171a21;border-radius:12px;padding:14px 16px;margin:14px 0}
.note{color:#9aa3b2;font-size:12px}
</style>
<h1>Jev vs. HelmDeck Hands</h1>
<div class=sub>Formular-Ausfüllen im Browser · Benchmark 17.09.2026 · 3 echte Websites, je 2–3 Durchläufe pro Methode · nichts abgeschickt</div>

<div class=box><b>Kurz:</b> Jev ist <span class=good>20–100x billiger</span> und <span class=good>zuverlässiger</span>, aber <span class=mid>nicht pauschal 10x schneller</span>.</div>

<h2>CHECK24 Kfz-Versicherung <span class=note>(13 Schritte)</span></h2>
<table>
<tr><th></th><th>Heute (Claude)</th><th>Jev</th></tr>
<tr><td>Zeit</td><td>40s <span class=note>(erstes Mal 134s)</span></td><td class=good>19s</td></tr>
<tr><td>Kosten</td><td>4–35 ct <span class=note>(geschätzt)</span></td><td class=good>0,13 ct</td></tr>
<tr><td>Geschafft</td><td class=mid>5 von 13</td><td class=bad>0 von 13</td></tr>
<tr><td>Blockiert durch</td><td>Autovervollständigung Modell</td><td>Cookie-Banner</td></tr>
</table>

<h2>Palantir-Bewerbung <span class=note>(11 Felder)</span></h2>
<table>
<tr><th></th><th>Heute (Claude)</th><th>Jev</th></tr>
<tr><td>Zeit</td><td class=good>30s <span class=note>(erstes Mal ~235s)</span></td><td>36s</td></tr>
<tr><td>Kosten</td><td>4–30 ct <span class=note>(geschätzt)</span></td><td class=good>0,64 ct</td></tr>
<tr><td>Geschafft</td><td class=mid>7 von 11</td><td class=mid>7 von 11</td></tr>
<tr><td>Blockiert durch</td><td>Dropdown geht technisch nicht</td><td>unsichere Dropdown-Wahl</td></tr>
</table>

<h2>Arbeitsagentur Jobbörse <span class=note>(Suche, 5 Filter)</span></h2>
<table>
<tr><th></th><th>Heute (Claude)</th><th>Jev</th></tr>
<tr><td>Zeit</td><td>65–119s</td><td class=good>18s</td></tr>
<tr><td>Kosten</td><td>3–25 ct <span class=note>(geschätzt)</span></td><td class=good>0,3–0,4 ct</td></tr>
<tr><td>Geschafft</td><td class=bad>0 von 5, meldet trotzdem „ok"</td><td class=mid>3 von 5, einmal 5 von 5</td></tr>
<tr><td>Blockiert durch</td><td>Eingaben kommen nie an</td><td>Umkreis-Dropdown</td></tr>
</table>

<h2>Gesamtbild</h2>
<table>
<tr><th>Kriterium</th><th>Ergebnis</th></tr>
<tr><td>Kosten</td><td class=good>Jev 20–100x billiger</td></tr>
<tr><td>Tempo</td><td class=mid>kein 10x: mal 6x schneller, mal etwas langsamer</td></tr>
<tr><td>Zuverlässigkeit</td><td class=good>Jev besser: kann Dropdowns, scheitert mit Grund statt still</td></tr>
<tr><td>Braucht noch Claude</td><td>unklare Auswahlfelder, Cookie-Banner</td></tr>
</table>

<h2>Empfehlung</h2>
<div class=box>Nicht die Browser-Werkzeuge komplett ersetzen. Stattdessen ein neues Werkzeug <b>browser_do(Ziel, Werte)</b> auf Jev-Basis für das stumpfe Ausfüllen, und Claude springt nur bei den Feldern ein, die Jev selbst als unsicher meldet.</div>

<p class=note>Kosten „Heute" sind aus gemessenen Aufrufzahlen × Sonnet-5-Preis geschätzt; Jev-Kosten sind aus den echten Token-Zahlen gerechnet.</p>
</html>`;
