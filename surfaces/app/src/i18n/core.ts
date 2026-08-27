// The translation ENGINE, with zero app imports.
//
// Split out of ./index.ts on purpose: the transport layer (data/client.ts,
// data/config.ts) has to translate its own error messages, and index.ts imports
// `api` from data/client for the /me query. Importing index.ts from client.ts
// would close that loop; importing core.ts cannot, because core imports nothing
// but the dictionaries. Everything React-flavoured stays in ./index.ts.
import { board } from "./dict/board";
import { card } from "./dict/card";
import { chrome } from "./dict/chrome";
import { composer } from "./dict/composer";
import { demo } from "./dict/demo";
import { net } from "./dict/net";
import { onboard } from "./dict/onboard";
import { screens } from "./dict/screens";
import { settings } from "./dict/settings";
import { sign } from "./dict/sign";

export type Lang = "de" | "en";
export const LANGS: { id: Lang; label: string }[] = [
  { id: "de", label: "Deutsch" }, { id: "en", label: "English" },
];

/** A dict entry is the pair; missing `en` falls back to `de` and vice versa so
 *  a half-added key degrades to the other language, never to a blank label. */
export type Entry = { de: string; en: string };
export type Dict = Record<string, Entry>;

export const DICT: Dict = {
  ...chrome, ...board, ...card, ...composer, ...demo, ...net, ...onboard, ...screens, ...settings,
  ...sign,
};

/** The device's language, used ONLY as the fallback when the workspace hasn't
 *  pinned one (demo mode and the unpaired first run both arrive here with no
 *  settings.policy.lang). Before this, that fallback was a hard "de", so every
 *  English-locale visitor — i.e. almost every closed-test tester — saw a German
 *  board. Hermes ships Intl on Android and iOS, so reading the locale needs no
 *  native module. Defaults to "en" for the international audience if detection
 *  ever throws (older Hermes without Intl). */
export function deviceLang(): Lang {
  try {
    const loc = Intl.DateTimeFormat().resolvedOptions().locale || "";
    return loc.toLowerCase().startsWith("de") ? "de" : "en";
  } catch {
    return "en";
  }
}

// Module-level current language. Components use useT() (which re-renders on
// change); plain helpers outside React - laneVerdict, sorters, transport errors
// - import t() directly and read this. Seeded from the device so pre-mount
// helpers match the UI; useLang() overrides it once /me resolves a real policy.
let current: Lang = deviceLang();

export function setLang(l: Lang) { current = l; }
export function getLang(): Lang { return current; }

export function render(entry: Entry | undefined, key: string, lang: Lang,
                       vars?: Record<string, string | number>): string {
  if (!entry) return key;                       // visible, greppable, never blank
  const s = (lang === "en" ? entry.en || entry.de : entry.de || entry.en) || key;
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

/** Translate outside React (helpers, formatters, transport errors). Inside a
 *  component prefer useT() so a language switch re-renders it. */
export function t(key: string, vars?: Record<string, string | number>): string {
  return render(DICT[key], key, current, vars);
}

/** Every key the app knows - used by ops/tools/i18n_lint.py to verify both
 *  languages are complete before the gate goes green. */
export function allKeys(): string[] { return Object.keys(DICT); }
export function dict(): Dict { return DICT; }
