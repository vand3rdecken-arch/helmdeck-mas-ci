import type { Dict } from "../core";

// The hidden diagnostics panel (ui/diag_panel.tsx). Only the CHROME is
// translated - the log lines themselves are technical (method, path, status)
// and stay verbatim, the same rule the audit trail follows (see i18n/index.ts).
export const diag: Dict = {
  "diag.title": { de: "Diagnose", en: "Diagnostics" },
  "diag.copy": { de: "Kopieren", en: "Copy" },
  "diag.copied": { de: "Kopiert", en: "Copied" },
  "diag.clear": { de: "Leeren", en: "Clear" },
  "diag.empty": {
    de: "Noch nichts aufgezeichnet - nur Fehler und Setup-Aufrufe landen hier.",
    en: "Nothing recorded yet - only failures and setup calls land here.",
  },
  "diag.hint": {
    de: "Lokal, ungesendet. \"Kopieren\" legt alles in die Zwischenablage - Tokens und Nonces sind ersetzt.",
    en: "Local, never sent. \"Copy\" puts it all on the clipboard - tokens and nonces are masked.",
  },
};
