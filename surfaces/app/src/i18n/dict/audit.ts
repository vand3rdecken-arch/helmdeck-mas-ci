import type { Dict } from "../index";

// The audit-trail review screen (src/app/audit.tsx, ops/docs/backlog/
// rbac-gxp card 5). Read-only surface over GET /audit.
export const audit: Dict = {
  "audit.title": { de: "Audit-Log", en: "Audit log" },
  "audit.sub": {
    de: "Jede sicherheitsrelevante Aktion, unveränderlich protokolliert - wer, was, wann.",
    en: "Every security-relevant action, logged immutably - who, what, when.",
  },
  "audit.kindPh": { de: "Art (z.B. gxp,signature)", en: "Kind (e.g. gxp,signature)" },
  "audit.actorPh": { de: "Akteur", en: "Actor" },
  "audit.qPh": { de: "Freitext", en: "Free text" },
  "audit.search": { de: "Suchen", en: "Search" },
  "audit.count": { de: "{returned} von {total} Treffern", en: "{returned} of {total} matches" },
  "audit.empty": { de: "Keine Einträge für diese Filter.", en: "No entries for these filters." },
};
