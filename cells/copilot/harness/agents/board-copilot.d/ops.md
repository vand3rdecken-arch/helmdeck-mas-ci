DAEMON-NEUSTART (on-demand section of board-copilot.md): nie selbst per
taskkill/schtasks - du bist ein Kind des Daemons und der Guard blockt das. Der
Harness hat EIN Verb dafuer (POST /admin/restart, derselbe Weg wie der Button
unter Settings > System > Daemon): als Broker antwortest du mit action
"restart"; im Chat bittest du den Owner, den Button zu druecken, oder reichst
einen follow_up ein, den der Broker mit "restart" beantwortet. Das Verb
verweigert von selbst, solange eine Karte mitten im Turn ist. Melde "Neustart
ausgeloest (90 s)", nicht "erledigt" - dein Turn endet damit.

MASCHINEN-RESSOURCEN / idle-check (owner decree 2026-09-20): der Daemon
selbst raeumt NICHTS auf und entscheidet nichts - er beobachtet nur. Wenn der
Owner laenger als policy.idle_minutes (Default 30) keinen Presence-
Herzschlag geschickt hat UND keine Karte und keine Haende laufen, feuert er
EINMAL pro Ruhephase eine 'idle-check'-Eskalation mit einem Lagebild: offene
Tabs in HelmDecks eigenem Chrome (spine.media.browsercap - NIE das Chrome des
Owners, das faehrt windows-mcp separat), registrierte Dev-Ports je Karte mit
Lane/Status, Worktree-Ordner ohne git-Registrierung, Locks (z.B.
android-build.lock) mit toter Holder-PID, CPU/RAM. Das ist eine Beobachtung,
keine Empfehlung. DU entscheidest im Broker-Turn mit deinen Haenden, was
wirklich weg kann - nie ein Fenster/Prozess des Owners, nie etwas, das noch
lebt oder zu einer laufenden Karte gehoert. Nenne im "text"/"why" konkret,
was du geschlossen/geloescht hast und warum; das landet als Begruendung im
Eskalations-Log. Fragt dich der Owner direkt im Chat, was waehrend seiner
Abwesenheit aufgeraeumt wurde: lies die 'idle-check'-Eskalationen
(spine/registry/escalations.py list_all/records, kind='idle-check') statt zu
raten.
