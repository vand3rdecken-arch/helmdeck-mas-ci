import type { Dict } from "../index";

/** First run on the desktop shell: one screen, one button. Claude Code is the
 *  installer; the screen ends on the pairing QR. See ui/onboard.tsx.
 *
 *  The sign-in screen (ui/login_screen.tsx) lives here too: it is the same
 *  arrival chrome - the first thing a new workspace sees - and it was hardcoded
 *  German end to end until this dict reached it. */
export const onboard: Dict = {
  "onboard.title": { de: "HelmDeck einrichten", en: "Set up HelmDeck" },
  "onboard.sub": {
    de: "Ein Klick: HelmDeck prüft Claude Code, richtet die Laufzeit ein, startet deine Instanz und zeigt den Kopplungs-Code.",
    en: "One click: HelmDeck checks Claude Code, sets up the runtime, starts your instance and shows the pairing code.",
  },
  "onboard.subClaude": {
    de: "HelmDeck arbeitet mit deinem Claude Code. Ist es installiert und angemeldet, erledigt es die Einrichtung selbst.",
    en: "HelmDeck works through your Claude Code. Once it is installed and signed in, it does the setup itself.",
  },
  "onboard.subScan": {
    de: "Fertig. Scanne den Code mit dem Handy — HelmDeck öffnet sich und koppelt automatisch.",
    en: "Done. Scan the code with your phone — HelmDeck opens and pairs automatically.",
  },
  "onboard.start": { de: "Mit Claude einrichten", en: "Set up with Claude" },
  "onboard.working": { de: "Richte ein…", en: "Setting up…" },
  "onboard.openBoard": { de: "Zum Board", en: "Open the board" },
  "onboard.skip": { de: "Später einrichten", en: "Set up later" },
  "onboard.pairFailed": {
    de: "Kopplung fehlgeschlagen — ist eine Relay-URL in den Einstellungen hinterlegt?",
    en: "Pairing failed — is a relay URL configured in Settings?",
  },
  // Both cover the same failure class: the desktop's local setup control plane
  // (surfaces/desktop/setup.js, 127.0.0.1 loopback) did not answer - startFailed
  // for the button click itself, connErr when the background poll starts
  // missing too. Without these the button used to fail into silence: fetch()
  // throws, setup.ts's call() swallows it, and nothing on screen ever changed.
  "onboard.startFailed": {
    de: "Konnte die Einrichtung nicht starten — HelmDeck neu starten und erneut versuchen.",
    en: "Could not start setup — restart HelmDeck and try again.",
  },
  "onboard.connErr": {
    de: "Keine Verbindung zum Einrichtungs-Dienst — HelmDeck neu starten.",
    en: "Lost connection to the setup service — restart HelmDeck.",
  },
  // No "sign in first" string here on purpose: pairing needing an account is a
  // STEP, not a message. onboard.tsx hands that step to ui/login_screen.tsx
  // (its "setup" mode below), which says it properly instead.

  // ---- engine picker (setup.js ENGINES; see that file's own docstring for
  // why each tier can only promise what it promises) -----------------------
  "onboard.enginesTitle": { de: "Agent-Engines", en: "Agent engines" },
  "onboard.engineRequired": { de: "erforderlich", en: "required" },
  "onboard.engineTier.full": { de: "richtet alles ein", en: "sets up everything" },
  "onboard.engineTier.npm-install": { de: "wird automatisch installiert", en: "installed automatically" },
  "onboard.engineTier.agent-install": { de: "Claude installiert es für dich", en: "Claude installs it for you" },
  "onboard.engineTier.detect-only": { de: "nur Status, keine Installation", en: "status only, no install" },

  // ---- repo type, the last onboarding step (ui/repo_type_picker.tsx) ------
  // Provisioning installs an instance; it does not say what the user works on.
  // This step is what turns a running HelmDeck into one that knows how THIS
  // repo runs - which stations, which gate command, which deploy hook.
  "onboard.repoTitle": { de: "Woran arbeitest du?", en: "What do you work on?" },
  "onboard.repoSub": {
    de: "Ein Ordner und eine Frage: Was für ein Repo ist das? Den Rest belegt die Vorlage vor.",
    en: "One folder and one question: what kind of repo is this? The template presets the rest.",
  },
  "onboard.repoIntro": {
    de: "Wähle den Ordner, in dem gearbeitet wird, und dann seinen Typ. Der Typ entscheidet, ob jede Karte einen eigenen Worktree bekommt, was das Gate prüft und ob es einen Deploy gibt. Änderbar bleibt alles später.",
    en: "Pick the folder the work happens in, then its type. The type decides whether each card gets its own worktree, what the gate checks, and whether there is a deploy. All of it stays changeable later.",
  },
  "onboard.repoNext": { de: "Weiter", en: "Continue" },
  "onboard.repoLater": { de: "Später einrichten", en: "Set this up later" },

  // ---- sign in / register (ui/login_screen.tsx) ---------------------------
  // The error the daemon returns on a failed attempt is NOT here - routes_auth
  // speaks through daemon/i18n.py, so it arrives already in the right language.
  "login.signIn": { de: "Anmelden", en: "Sign in" },
  "login.createAccount": { de: "Konto erstellen", en: "Create account" },
  "login.setupTitle": { de: "Owner-Konto anlegen", en: "Create the owner account" },
  "login.setupHint": {
    de: "Erster Start - dieses Konto verwaltet alles, inklusive weiterer Benutzer.",
    en: "First run - this account manages everything, including any further users.",
  },
  "login.setupSubmit": { de: "Anlegen & anmelden", en: "Create & sign in" },
  "login.user": { de: "Benutzername", en: "Username" },
  "login.password": { de: "Passwort", en: "Password" },
  "login.passwordNew": { de: "Passwort (mind. 8 Zeichen)", en: "Password (at least 8 characters)" },
  "login.invite": { de: "Einladungscode", en: "Invitation code" },
  "login.failed": { de: "Anmeldung fehlgeschlagen", en: "Sign-in failed" },

  // ---- first-run fork: server vs. client (login_screen.tsx mode "choose") ----
  "login.chooseTitle": { de: "Wie willst du HelmDeck nutzen?", en: "How do you want to use HelmDeck?" },
  "login.chooseHint": {
    de: "HelmDeck braucht EINEN Server: den Rechner, auf dem die Agenten laufen und die Daten liegen. Alle anderen Geräte (Handy, weitere PCs) sind nur Fenster darauf.",
    en: "HelmDeck needs ONE server: the machine where the agents run and the data lives. Every other device (phone, more PCs) is just a window onto it.",
  },
  "login.chooseServerTitle": { de: "Dieser PC ist der Server", en: "This PC is the server" },
  "login.chooseServerBody": {
    de: "Mein erster HelmDeck-Rechner. Du legst jetzt das Owner-Konto an. Handy und andere Geräte koppelst du später an diesen PC.",
    en: "My first HelmDeck machine. You create the owner account now. You pair your phone and other devices to this PC later.",
  },
  "login.chooseClientTitle": { de: "Mit bestehendem Server verbinden", en: "Connect to an existing server" },
  "login.chooseClientBody": {
    de: "HelmDeck läuft schon auf einem anderen Rechner. Dieser PC zeigt dann nur dessen Oberfläche, mit deinem vorhandenen Konto.",
    en: "HelmDeck already runs on another machine. This PC then only shows its interface, using your existing account.",
  },
  "login.connectTitle": { de: "Mit bestehendem Server verbinden", en: "Connect to an existing server" },
  "login.connectSteps": {
    de: "1. Am Server-Rechner: Einstellungen → Team & Geräte → Telefon koppeln.\n2. Pairing-Code oder Link kopieren.\n3. Hier einfügen. Eine Einladung von jemand anderem funktioniert genauso.",
    en: "1. On the server machine: Settings → Team & devices → Pair phone.\n2. Copy the pairing code or link.\n3. Paste it here. An invitation from someone else works the same way.",
  },
  "login.connectBtn": { de: "Verbinden", en: "Connect" },
  "login.back": { de: "Zurück", en: "Back" },
};
