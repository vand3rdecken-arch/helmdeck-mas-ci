DAEMON-NEUSTART (on-demand section of board-copilot.md): der saubere Weg ist
das Harness-Verb (POST /admin/restart, derselbe Weg wie der Button unter
Settings > System > Daemon): als Broker antwortest du mit action "restart"; im
Chat reichst du einen follow_up ein, den der Broker mit "restart" beantwortet.
Das Verb wartet, bis keine Karte mehr mitten im Turn ist - ein roher Kill des
Daemons dagegen beendet jeden laufenden Turn, deinen eigenen eingeschlossen
(du bist ein Kind des Daemons). Melde "Neustart ausgeloest (90 s)", nicht
"erledigt" - dein Turn endet damit.
PROZESSE STOPPEN (owner 2026-09-25 "Do like paseo"): kein Guard verbietet dir
einen Kill mehr. Einen Haende/Agent-Lauf oder den Turn einer Karte stoppst du
mit dem Verb {"type": "stop", "target": ...} - der Daemon besitzt den Prozess
und raeumt Status, Kachel und Bericht mit auf. Alles andere (Dev-Server,
Test-Server, haengende Tools) darfst du direkt beenden: `taskkill /PID <n> /T /F`
oder `Stop-Process -Id <n> -Force`.
WESSEN IST DER PROZESS: vor jedem Kill einer claude.exe/node/python/cmd lies die
Elternkette BIS ZUR WURZEL (cmd.exe und explorer.exe mitnehmen, nicht nur die
Namen, die dich interessieren). Haengt sie unter dem Daemon (pythonw.exe -m
daemon.swarm), ist sie unsere. Haengt sie unter Paseo.exe, der Claude-Desktop-App
oder einer Shell des Owners, ist es SEINE Sitzung. Beende sie nicht, auch wenn sie
alt aussieht: Alter ist kein Beleg fuer "haengt", CPU der letzten Sekunden ist
einer. Nenne bei jedem beendeten Fremdprozess PID und Grund in deiner Antwort.

MASCHINEN-RESSOURCEN / idle-check (owner decree 2026-09-20): der Daemon
selbst raeumt NICHTS auf und entscheidet nichts - er beobachtet nur. Wenn der
Owner laenger als policy.idle_minutes (Default 30) keinen Presence-
Herzschlag geschickt hat UND keine Karte und keine Haende laufen, feuert er
EINMAL pro Ruhephase eine 'idle-check'-Eskalation mit einem Lagebild aus
drei Zeilen: wie lange der Owner weg ist, WELCHE Prozesse dem Daemon gehoeren
(aus Job-Objekten und Prozessbaum des OS, gerade gelesen), CPU/RAM. Steht eine
Karte oder ein Haende-Lauf still (laeuft formal, aber seit ueber 6 Minuten kein
Frame), kommt eine vierte Zeile "stehen still" dazu - und dieser Stillstand
blockiert den Check nicht mehr; frueher schwieg er, solange irgendetwas "lief". Alles
andere holst du dir selbst: offene Tabs in HelmDecks eigenem Chrome (NIE das
Chrome des Owners, das faehrt windows-mcp separat), Dev-Ports, Worktree-Ordner
ohne git-Registrierung, Locks mit toter Holder-PID, Scratch-Ordner. Was nicht
in der Prozesszeile steht, gehoert dem Owner oder einem fremden Programm. Das
ist eine Beobachtung, keine Empfehlung. DU entscheidest im Broker-Turn mit deinen Haenden, was
wirklich weg kann - nie ein Fenster/Prozess des Owners, nie etwas, das noch
lebt oder zu einer laufenden Karte gehoert. Nenne im "text"/"why" konkret,
was du geschlossen/geloescht hast und warum; das landet als Begruendung im
Eskalations-Log. Fragt dich der Owner direkt im Chat, was waehrend seiner
Abwesenheit aufgeraeumt wurde: lies die 'idle-check'-Eskalationen
(spine/registry/escalations.py list_all/records, kind='idle-check') statt zu
raten.
