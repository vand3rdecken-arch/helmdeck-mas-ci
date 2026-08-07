# -*- coding: utf-8 -*-
"""The daemon's half of "one language, sharply".

The app translates its screens (app/src/i18n); this translates the prose the
daemon SPEAKS to the owner - board-chat messages, push notifications, unblock
proposals. Both read the same policy key (settings.policy.lang), so the whole
product switches together instead of the app being German and the chat English.

NOT translated on purpose, and this is the line:
  - the append-only AUDIT trail: events.emit payloads, ActionLog technical
    lines, gate output, git/merge messages. That is a record, not owner prose;
    it must read identically in every workspace and stay greppable.
  - anything quoted FROM the tools (gate stderr, git conflict text).
The card feed shows some of those audit lines verbatim - that is intended: they
are evidence, and evidence is not localised.

Usage:  from i18n import t;  t("say.accepted", kind="merged")
Keys carry both languages; a missing translation falls back to the other one so
a half-added key degrades to the wrong language, never to a blank message.
"""

LANGS = ("de", "en")

MESSAGES = {
    # -- lane outcomes the harness reports in chat (sessions._say_card) --------
    "say.bouncedToWorking": {
        "de": "zurueck auf 'In Arbeit' geschoben - der Agent macht weiter.",
        "en": "moved back to 'Working' - the agent picks it up again.",
    },
    "say.conflictMarkers": {
        "de": "bleibt auf Review - im Worktree stehen noch offene Konfliktmarkierungen. {detail}",
        "en": "stays on Review - there are still open conflict markers in the worktree. {detail}",
    },
    "say.gateRunning": {
        "de": "Gate laeuft - ich pruefe den Stand (compile, Typen, Tests, sauberer Baum). Das dauert ein paar Sekunden.",
        "en": "Gate running - checking the change (compile, types, tests, clean tree). This takes a few seconds.",
    },
    "say.gateGreen": {
        "de": "Gate gruen - alle Checks bestanden.",
        "en": "Gate green - all checks passed.",
    },
    "say.gateRed": {
        "de": "Gate ist rot - bleibt auf Review. Grund:\n{detail}",
        "en": "Gate is red - stays on Review. Reason:\n{detail}",
    },
    "say.mergeBlockedDirty": {
        "de": "Merge blockiert: der Haupt-Checkout hat uncommittete FREMDE Aenderungen (nicht diese Karte). Ich parke sie sicher auf einem wip-Branch (nichts geht verloren) und versuche den Merge erneut.",
        "en": "Merge blocked: the main checkout has uncommitted OTHER changes (not this card). Parking them safely on a wip branch (nothing lost) and retrying the merge.",
    },
    "say.mergeUnblocked": {
        "de": "board-Agent: {detail}",
        "en": "board-Agent: {detail}",
    },
    "say.reviewChecked": {
        "de": "auf Review geprueft. {verdict}",
        "en": "checked on Review. {verdict}",
    },
    "verdict.mergeable": {
        "de": "Gate gruen, sauber mergebar - zieh sie auf Done zum Landen.",
        "en": "Gate green, merges cleanly - drag it to Done to land it.",
    },
    "verdict.alreadyMerged": {
        "de": "Gate gruen, ist aber schon in main - Done schliesst sie nur noch.",
        "en": "Gate green, but it is already in main - Done just closes it.",
    },
    "verdict.conflict": {
        "de": "Gate gruen, ABER sie kollidiert mit main - das muss vor Done aufgeloest werden.",
        "en": "Gate green, BUT it collides with main - that has to be resolved before Done.",
    },
    "verdict.other": {"de": "Geprueft: {detail}", "en": "Checked: {detail}"},
    "say.cannotLand": {
        "de": "konnte nicht landen ({kind}) - bleibt auf Review. {detail}",
        "en": "could not land ({kind}) - stays on Review. {detail}",
    },
    "say.landed.merged": {
        "de": "abgenommen und nach main gemergt",
        "en": "accepted and merged into main",
    },
    "say.landed.redundant": {
        "de": "abgenommen - war schon in main, jetzt geschlossen",
        "en": "accepted - was already in main, now closed",
    },
    "say.landed.plain": {"de": "abgenommen", "en": "accepted"},
    "say.deployOk": {"de": " · Deploy ok.", "en": " · deploy ok."},
    "say.deployFailed": {
        "de": " · ACHTUNG: Deploy-Hook fehlgeschlagen.",
        "en": " · WARNING: deploy hook failed.",
    },
    "say.machineReview": {
        "de": "auf dem Rechner erledigt - schau dir das Ergebnis an und nimm die Karte ab "
              "(kein Branch, kein Merge).",
        "en": "done on the machine - check the result and accept the card "
              "(no branch, no merge).",
    },
    "say.machineAccepted": {
        "de": "abgenommen und geschlossen (Maschinen-Aufgabe).",
        "en": "accepted and closed (machine task).",
    },

    # -- push notifications (notify.card_event) -------------------------------
    "push.needsYou": {"de": "Karte fertig - dein Urteil", "en": "Card finished - your call"},
    "push.bounced": {"de": "Karte gescheitert", "en": "Card failed"},
    "push.done": {"de": "Karte akzeptiert", "en": "Card accepted"},
    "push.pmDone": {"de": "PM: fertig", "en": "PM: finished"},
    "push.pmStuck": {"de": "PM: haengt", "en": "PM: stuck"},
    "push.pmDoneBody": {"de": "'{task}' - braucht deine Abnahme.",
                        "en": "'{task}' - needs your acceptance."},
    "push.pmStuckBody": {"de": "'{task}' - {proposal}", "en": "'{task}' - {proposal}"},
    # the per-card autopilot escalating on its own (processes._auto_resolve)
    "push.autopilotStuck": {"de": "Autopilot: haengt", "en": "Autopilot: stuck"},
    "push.autopilotStuckBody": {
        "de": "'{task}' haengt trotz Fix-Versuchen. {proposal}",
        "en": "'{task}' is still stuck despite fix attempts. {proposal}",
    },

    # -- the PM speaking in chat (pm._say) ------------------------------------
    "pm.planned": {
        "de": "Kurzes Update: ich hab {n} neue Aufgabe(n) fuer dein Ziel eingeplant.",
        "en": "Quick update: I planned {n} new task(s) for your goal.",
    },
    "pm.delivered": {
        "de": "Fertig: '{task}' ist geliefert und wartet auf deine Abnahme (oder Bounce). "
              "Sag mir Bescheid oder tipp die Karte an.",
        "en": "Done: '{task}' is delivered and waiting for you to accept (or bounce) it. "
              "Tell me, or tap the card.",
    },
    "pm.stillStuck": {
        "de": "Achtung: '{task}' haengt weiter - meine Fix-Versuche haben nicht gereicht. {proposal}",
        "en": "Heads up: '{task}' is still stuck - my fix attempts were not enough. {proposal}",
    },
    "pm.onIt": {
        "de": "'{task}' ist gebounct ({kind}) - ich kuemmere mich: Fix delegiert, "
              "danach reiche ich die Karte selbst neu ein.",
        "en": "'{task}' bounced ({kind}) - I am on it: fix delegated, then I resubmit "
              "the card myself.",
    },
    "pm.freeAgain": {"de": "Geschafft: '{task}' ist wieder frei{note}",
                     "en": "Sorted: '{task}' is unblocked again{note}"},
    "pm.launchCheck": {
        "de": "Koordinations-Check fuers Play-Store-Deploy (highest prio: in den Store) - das "
              "brauche nur ich VON DIR, den Rest treibe ich selbst als Karten: "
              "1) Google-Play-Console-Account angelegt? 2) Upload-Keystore / Play App Signing "
              "bereit? 3) Datenschutz-URL + Data-Safety-Angaben? Sag mir kurz, was schon steht - "
              "fuer den Rest lege ich Karten an und arbeite sie ab.",
        "en": "Coordination check for the Play Store deploy (highest priority: get into the "
              "store) - this is all I need FROM YOU, I drive the rest myself as cards: "
              "1) Google Play Console account created? 2) Upload keystore / Play App Signing "
              "ready? 3) Privacy URL + data-safety answers? Tell me briefly what already "
              "exists - for the rest I file cards and work through them.",
    },

    # -- unblock proposals attached to every escalation (pm._unblock_proposal) -
    "unblock.dispatch": {
        "de": "Vorschlag: Repo/Setup pruefen ({err}) und die Karte dann wieder auf "
              "'In Arbeit' ziehen - meine automatischen Neustarts haben es nicht behoben.",
        "en": "Suggestion: check the repo/setup ({err}) and then drag the card back to "
              "'Working' - my automatic restarts did not fix it.",
    },
    "unblock.dirty": {
        "de": "Vorschlag: sag im Chat 'resolve_blocker {branch}' - das parkt die uncommitteten "
              "Aenderungen im Haupt-Checkout auf einen wip-Branch (nichts geht verloren).",
        "en": "Suggestion: say 'resolve_blocker {branch}' in the chat - that parks the "
              "uncommitted changes in the main checkout on a wip branch (nothing is lost).",
    },
    "unblock.conflict": {
        "de": "Vorschlag: sag im Chat 'resolve_conflict {branch}' fuer einen weiteren Versuch - "
              "oder entscheide, ob der Branch anders aufgesetzt werden soll ({detail}).",
        "en": "Suggestion: say 'resolve_conflict {branch}' in the chat for another attempt - "
              "or decide whether the branch should be set up differently ({detail}).",
    },
    "unblock.gate": {
        "de": "Vorschlag: entscheide die Ursache '{reason}' - steuere den Worker mit deiner "
              "Entscheidung oder zieh die Karte zurueck ins Backlog.",
        "en": "Suggestion: decide on the cause '{reason}' - steer the worker with your "
              "decision, or pull the card back into the backlog.",
    },
    "unblock.reasonFallback": {"de": "Review rot", "en": "review red"},
    "unblock.dispatchErr": {"de": "Dispatch-Fehler", "en": "dispatch error"},
}


def lang():
    """The workspace language, from policy. Defaults to de and never raises -
    a settings read must not be able to break a message."""
    try:
        import events
        v = ((events.settings().get("policy") or {}).get("lang") or "de").lower()
        return v if v in LANGS else "de"
    except Exception:
        return "de"


def t(key, **vars):
    """Translate + interpolate. An unknown key returns the key itself: visible
    and greppable in the chat, never a blank message."""
    entry = MESSAGES.get(key)
    if not entry:
        return key
    cur = lang()
    s = entry.get(cur) or entry.get("de") or entry.get("en") or key
    if not vars:
        return s
    try:
        return s.format(**vars)
    except (KeyError, IndexError, ValueError):
        return s
