import type { Dict } from "../index";

// GxP sign-off (ui/sign_off.tsx). See ops/docs/gxp-mode-design.md 3.
//
// Note what is NOT here: the signature RECORD itself is never translated. It is
// audit material and must read identically in every workspace and stay
// greppable (i18n/index.ts:1-11). Only the surface a person reads is bilingual.
export const sign: Dict = {
  "sign.title": { de: "Freigabe", en: "Sign-off" },
  "sign.cta": { de: "Freigeben", en: "Sign off" },
  "sign.ctaN": { de: "Freigeben ({n})", en: "Sign off ({n})" },

  // What the landing will actually do - today a single tap merges and deploys
  // with no dialog at all, so saying it out loud is new information.
  "sign.whatHappens": { de: "WAS PASSIERT", en: "WHAT HAPPENS" },
  "sign.willMerge": { de: "merge {branch} → {base}", en: "merge {branch} → {base}" },
  "sign.willDeploy": { de: "danach läuft der Deploy-Hook des Repos", en: "then the repo's deploy hook runs" },

  "sign.bench": { de: "PRÜFSTAND", en: "WHAT YOU ARE SIGNING" },
  "sign.commits": { de: "{n} Commit(s)", en: "{n} commit(s)" },
  "sign.range": { de: "{base} → {head}", en: "{base} → {head}" },
  "sign.files": { de: "Dateien ansehen", en: "Show files" },
  "sign.filesHide": { de: "Dateien ausblenden", en: "Hide files" },
  "sign.filesMore": { de: "… und {n} weitere", en: "… and {n} more" },
  "sign.dispatchedBy": { de: "beauftragt von {who}", en: "filed by {who}" },

  "sign.meaning": { de: "BEDEUTUNG", en: "MEANING" },
  // Select-then-confirm is the house doctrine (card_question.tsx:116-119) and
  // matters more here than anywhere else, so the hint is explicit.
  "sign.meaningHint": { de: "Auswählen sendet noch nicht.", en: "Selecting does not send yet." },
  "sign.approved": { de: "Freigegeben", en: "Approved" },
  "sign.approvedSub": { de: "landet und deployt", en: "lands and deploys" },
  "sign.reviewed": { de: "Geprüft", en: "Reviewed" },
  "sign.reviewedSub": { de: "bleibt für eine Zweitfreigabe liegen", en: "waits for a second approval" },
  "sign.rejected": { de: "Abgelehnt", en: "Rejected" },
  "sign.rejectedSub": { de: "zurück in Arbeit, mit deiner Begründung", en: "back to working, with your reason" },

  "sign.reason": { de: "BEGRÜNDUNG", en: "REASON" },
  "sign.reasonPh": { de: "Was hast du geprüft?", en: "What did you check?" },
  "sign.reasonRequired": { de: "Bei einer Ablehnung ist eine Begründung Pflicht.", en: "A rejection has to say why." },

  "sign.signature": { de: "UNTERSCHRIFT", en: "SIGNATURE" },
  "sign.signer": { de: "Unterzeichner", en: "Signer" },
  "sign.password": { de: "Passwort", en: "Password" },
  "sign.passwordPh": { de: "Passwort zur Bestätigung", en: "Password to confirm" },
  "sign.legal": {
    de: "Mit dem Signieren bestätigst du die gewählte Bedeutung. Zeitstempel in UTC, der Eintrag ist unveränderlich und an genau diesen Stand gebunden.",
    en: "Signing confirms the meaning you selected. Timestamp in UTC; the record is immutable and bound to exactly this state.",
  },
  "sign.submit": { de: "Signieren", en: "Sign" },
  "sign.submitting": { de: "Signiere…", en: "Signing…" },

  // Failure states. Never an Alert - Alert.alert is a no-op on react-native-web
  // (new.tsx:52-55), so everything here renders inline.
  "sign.errBadPassword": { de: "Passwort nicht akzeptiert.", en: "Password not accepted." },
  "sign.errDirty": { de: "Die Karte hat noch nicht committete Änderungen. Eine Unterschrift muss einen Commit benennen, den es gibt.", en: "The card has uncommitted changes. A signature has to name a commit that exists." },
  "sign.errDrift": { de: "Die Karte hat sich geändert, seit du sie geöffnet hast. Prüfstand neu laden und erneut ansehen.", en: "The card changed since you opened it. Reload and review again." },
  "sign.errFourEyes": { de: "Vier-Augen: Wer eine Karte beauftragt hat, darf sie nicht selbst freigeben.", en: "Four-eyes: whoever filed a card cannot also approve it." },
  "sign.reload": { de: "Neu laden", en: "Reload" },
  "sign.loading": { de: "Prüfstand wird geladen…", en: "Loading…" },

  "sign.doneApproved": { de: "Freigegeben von {who} · {at} UTC", en: "Approved by {who} · {at} UTC" },
  "sign.doneReviewed": { de: "Als geprüft vermerkt", en: "Marked as reviewed" },
  "sign.doneRejected": { de: "Abgelehnt — zurück in Arbeit", en: "Rejected — back to working" },

  // Batch
  "sign.batchTitle": { de: "Mehrere freigeben", en: "Sign off several" },
  "sign.batchHint": { de: "Ein Passwort, eine Unterschrift pro Karte.", en: "One password, one signature per card." },
  "sign.batchSelect": { de: "Auswählen", en: "Select" },
  "sign.batchCancel": { de: "Auswahl beenden", en: "Done selecting" },
  "sign.batchSome": { de: "{ok} von {n} freigegeben.", en: "{ok} of {n} signed off." },
  "sign.batchNone": { de: "Keine Karte konnte freigegeben werden.", en: "No card could be signed off." },

  // Board badges
  "sign.badgeNeeds": { de: "Freigabe nötig", en: "Needs sign-off" },
  "sign.badgeSigned": { de: "Freigegeben", en: "Signed off" },
};
