import type { Dict } from "../index";

// GxP-mode activation (ui/gxp_activate.tsx). See ops/docs/gxp-mode-design.md
// §2.7 and ops/docs/backlog/rbac-gxp card 6.
export const gxp: Dict = {
  "gxp.title": { de: "GxP-Modus aktivieren", en: "Activate GxP mode" },
  "gxp.explain": {
    de: "Im GxP-Modus kommt keine Karte nach main, solange kein Mensch mit Passwort unterschrieben hat. Das Ausschalten bleibt bewusst außerhalb der App - direkter Zugriff auf diesen Rechner, danach ein Neustart des Daemons.",
    en: "In GxP mode, no card lands on main until a human has signed with their password. Deactivation deliberately stays outside the app - direct access to this machine, then a daemon restart.",
  },
  "gxp.currentState": { de: "AKTUELLER STATUS", en: "CURRENT STATE" },
  "gxp.inactive": { de: "Aus.", en: "Off." },
  "gxp.activeWorkspace": { de: "An - ganzer Workspace, aktiviert von {who}.", en: "On - whole workspace, activated by {who}." },
  "gxp.activeRepos": { de: "An - {n} Repo(s), aktiviert von {who}.", en: "On - {n} repo(s), activated by {who}." },

  "gxp.scope": { de: "GELTUNGSBEREICH", en: "SCOPE" },
  "gxp.scopeHint": { de: "Wähle bekannte Repos aus oder lege neue an. Nichts ausgewählt = der ganze Workspace.", en: "Pick known repos or create new ones. Nothing selected = the whole workspace." },
  "gxp.knownRepos": { de: "Bekannte Repos", en: "Known repos" },
  "gxp.createNew": { de: "Neues Repo anlegen", en: "Create a new repo" },
  "gxp.createNewHint": {
    de: "Pfad, der noch kein Repo ist - wird beim Aktivieren angelegt und mit git init versehen (Startcommit, damit ein Audit-Trail existiert).",
    en: "A path that isn't a repo yet - created and git-init'd on activation (with a seed commit, so an audit trail exists).",
  },
  "gxp.createNewNote": { de: "Wird beim Aktivieren erstellt und initialisiert.", en: "Will be created and initialized on activation." },
  "gxp.reposPh": { de: "C:/pfad/zum/repo", en: "C:/path/to/repo" },
  "gxp.scopeRepos": { de: "{n} Repo(s) werden hinzugefügt", en: "{n} repo(s) will be added" },
  "gxp.scopeWorkspace": { de: "Der ganze Workspace wird reguliert", en: "The whole workspace will be regulated" },
  "gxp.scopeGrowsOnly": {
    de: "Bereits regulierte Repos bleiben es - dieses Feld fügt nur hinzu.",
    en: "Already-regulated repos stay regulated - this field only adds.",
  },

  "gxp.fourEyes": { de: "VIER-AUGEN", en: "FOUR-EYES" },
  "gxp.fourEyesLabel": {
    de: "Freigabe erfordert eine andere Person als den Auftraggeber der Karte",
    en: "Approval requires a different person than the card's own dispatcher",
  },

  "gxp.legal": {
    de: "Mit dem Aktivieren bestätigst du diese Einstellung als Owner. Zeitstempel in UTC, protokolliert im Audit-Log.",
    en: "Activating confirms this setting as owner. Timestamp in UTC, recorded in the audit log.",
  },
  "gxp.activate": { de: "Aktivieren", en: "Activate" },
  "gxp.activating": { de: "Aktiviere…", en: "Activating…" },

  "gxp.activatedWorkspace": { de: "GxP-Modus aktiv für den ganzen Workspace (von {who}).", en: "GxP mode active for the whole workspace (by {who})." },
  "gxp.activatedRepos": { de: "GxP-Modus aktiv für {n} Repo(s) (von {who}).", en: "GxP mode active for {n} repo(s) (by {who})." },

  "gxp.openDialog": { de: "GxP-Modus", en: "GxP mode" },
  "gxp.openDialogSub": { de: "Signaturpflicht für regulierte Repos einschalten", en: "Turn on mandatory sign-off for regulated repos" },
};
