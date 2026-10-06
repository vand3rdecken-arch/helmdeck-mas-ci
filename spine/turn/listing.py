# -*- coding: utf-8 -*-
"""A list handed to an agent must say what it is: FOUND, not ALL.

A closed list ("hier sind die 3 Plaene") reads as the whole world; the agent
reasons correctly over it and still concludes "that is all there is". The
silent cut is the same lie from the other side (a [:5] nobody mentions). Both
are the closed-world mistake. Best practice (Anthropic, "Writing tools for
agents": truncate with sensible defaults AND tell the agent how to get more;
the silent-truncation literature: bounded page + total + completeness flag):

  * the header names the criteria and what was CHECKED,
  * a cut says how many are omitted,
  * an empty result says "nothing by these criteria" - never "nothing",
  * a way to fetch more is named.

Same shape copilot_memory.digest already uses ("... und N aeltere, die HIER
NICHT STEHEN - find <begriff> sucht ueber alle"). ONE owner for it here."""


def found(lines, what, criteria="", checked="", more="", cap=12, complete=False):
    """Render `lines` as an open-world block. `what` = 'Plaene', `criteria` = the
    filter in words, `checked` = the denominator ('16 Prozesse, 54 Karten'),
    `more` = how to see beyond (a command), `cap` = how many lines to show,
    `complete` = the list IS exhaustive over `checked` (a plain listing, not a
    heuristic search) - then it says so instead of the open-world caveat."""
    lines = list(lines)
    shown = lines[:cap]
    head = "AUTOMATISCH GEFUNDEN - %s" % what
    meta = []
    if criteria:
        meta.append("Kriterium: " + criteria)
    if checked:
        meta.append("geprueft: " + checked)
    meta.append("vollstaendig, nichts gefiltert" if complete
                else "kann mehr geben, als diese Suche kennt")
    head += " (" + "; ".join(meta) + ")"
    if not lines:
        body = "  nichts nach diesen Kriterien - das heisst nicht, dass es nichts gibt"
    else:
        body = "\n".join("  - " + x for x in shown)
        if len(lines) > len(shown):
            body += "\n  ... und %d weitere nicht gezeigt" % (len(lines) - len(shown))
    tail = ("\n  mehr: " + more) if more else ""
    return head + ":\n" + body + tail
