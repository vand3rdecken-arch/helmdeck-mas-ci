/** A card's `task` is the whole prompt (paths, candidate lists, ...), not a
 *  title. For tiles, rows and sheet headers show its lead: the first line, cut
 *  at the first sentence end past ~40 chars, hard-capped at `max`. The card
 *  detail still edits and shows the full text. */
export function cardTitle(task: string, max = 90): string {
  const one = (task ?? "").split("\n").find((l) => l.trim())?.replace(/\s+/g, " ").trim() ?? "";
  const m = one.match(/^.{40,}?[.:?!](?=\s)/);
  const lead = m && m[0].length <= max ? m[0].replace(/:$/, "") : one;
  return lead.length > max ? lead.slice(0, max - 1).trimEnd() + "…" : lead;
}
