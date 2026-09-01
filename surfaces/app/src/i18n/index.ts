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
import { cachedProfile } from "@/data/profile";
import type { Me } from "@/data/types";

import { DICT, deviceLang, getLang, render, setLang, type Lang } from "./core";

export {
  allKeys, dict, getLang, LANGS, setLang, t, type Dict, type Entry, type Lang,
} from "./core";

/** The language THIS ACCOUNT reads in.
 *
 *  Read from /me, NOT from the dashboard payload: that one strips `settings`
 *  for operators and 403s clients, so the language would only ever resolve for
 *  the owner and everyone else would silently sit in German - the very split
 *  this replaced. /me is the one endpoint every authenticated role can call.
 *
 *  Since accounts-boards-prd phase 1 the answer is per-ACCOUNT: `me.profile`
 *  is the account's own choice resolved over the workspace default, so signing
 *  in on a second device renders the same language without carrying anything
 *  on the device. The resolution order below is the app's hydration order:
 *
 *    profile (the account, authoritative)
 *      -> ui.lang (an older daemon that predates `profile`; it resolves the
 *         same value, so this is a version fallback, not a second opinion)
 *      -> the device cache (offline, or the frame before /me answers - stops
 *         a cold start from flashing the workspace default)
 *      -> the OS locale (demo / unpaired: nobody has said anything yet, and
 *         defaulting everyone to German is worse than following the device). */
export function useLang(): Lang {
  const { data } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const me = data as Me | undefined;
  const raw = me?.profile?.lang ?? me?.ui?.lang ?? cachedProfile()?.lang;
  const lang: Lang = raw === "en" ? "en" : raw === "de" ? "de" : deviceLang();
  if (lang !== getLang()) setLang(lang);   // keep the non-React t() in sync
  return lang;
}

/** Component-facing translator: re-renders when the workspace language changes. */
export function useT(): (key: string, vars?: Record<string, string | number>) => string {
  const lang = useLang();
  return (key, vars) => render(DICT[key], key, lang, vars);
}
