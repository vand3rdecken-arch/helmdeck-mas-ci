// ONE language, sharply. HelmDeck used to mix German prose with English chrome
// ("Board / Needs you / urgent" next to "Karte hängt – ansehen"); the language
// is now POLICY DATA (settings.policy.lang, daemon/events.py DEFAULTS), read by
// the app here and by the daemon in daemon/i18n.py, so both voices switch
// together.
//
// NOT translated on purpose: the append-only AUDIT trail (event log, gate
// output, git messages, flight-recorder technical lines). That is a technical
// record, not owner prose - it must read identically in every workspace and be
// greppable. ops/tools/i18n_lint.py enforces the split and fails the gate if a
// user-facing literal is added without a key.
//
// The engine itself lives in ./core (no app imports) so the transport layer can
// translate without importing this file, which pulls in data/client.
import { useQuery } from "@tanstack/react-query";

import { api } from "@/data/client";

import { DICT, deviceLang, getLang, render, setLang, type Lang } from "./core";

export {
  allKeys, dict, getLang, LANGS, setLang, t, type Dict, type Entry, type Lang,
} from "./core";

/** The language the workspace is set to.
 *
 *  Read from /me, NOT from the dashboard payload: that one strips `settings`
 *  for operators and 403s clients, so the language would only ever resolve for
 *  the owner and everyone else would silently sit in German - the very split
 *  this replaced. /me is the one endpoint every authenticated role can call. */
export function useLang(): Lang {
  const { data } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const raw = (data as { ui?: { lang?: string } } | undefined)?.ui?.lang;
  // A pinned workspace language wins; otherwise (demo / unpaired, where `raw` is
  // undefined) follow the device instead of defaulting everyone to German.
  const lang: Lang = raw === "en" ? "en" : raw === "de" ? "de" : deviceLang();
  if (lang !== getLang()) setLang(lang);   // keep the non-React t() in sync
  return lang;
}

/** Component-facing translator: re-renders when the workspace language changes. */
export function useT(): (key: string, vars?: Record<string, string | number>) => string {
  const lang = useLang();
  return (key, vars) => render(DICT[key], key, lang, vars);
}
