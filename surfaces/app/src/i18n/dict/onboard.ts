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
  // Pairing needs an authenticated account: the desktop shell no longer hands
  // the UI a free owner token, so this is the normal state right after
  // provisioning, not an error.
  "onboard.pairNeedsLogin": {
    de: "Melde dich zuerst an — danach kannst du dein Telefon koppeln.",
    en: "Sign in first — then you can pair your phone.",
  },

  // ---- engine picker (setup.js ENGINES; see that file's own docstring for
  // why each tier can only promise what it promises) -----------------------
  "onboard.enginesTitle": { de: "Agent-Engines", en: "Agent engines" },
  "onboard.engineRequired": { de: "erforderlich", en: "required" },
  "onboard.engineTier.full": { de: "richtet alles ein", en: "sets up everything" },
  "onboard.engineTier.npm-install": { de: "wird automatisch installiert", en: "installed automatically" },
  "onboard.engineTier.agent-install": { de: "Claude installiert es für dich", en: "Claude installs it for you" },
  "onboard.engineTier.detect-only": { de: "nur Status, keine Installation", en: "status only, no install" },

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
};
