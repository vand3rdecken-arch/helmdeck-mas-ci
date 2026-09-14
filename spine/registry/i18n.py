# -*- coding: utf-8 -*-
"""The daemon's half of "one language, sharply".

The app translates its screens (surfaces/app/src/i18n); this translates the prose the
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
    "say.baseDrifted": {
        "de": "bleibt auf Review - die Basis hat sich weiterbewegt und kollidiert mit dieser Karte. {detail}",
        "en": "stays on Review - the base moved on and collides with this card. {detail}",
    },
    # -- readable action labels for the card transcript (claude_sessions) -----
    "tool.read": {"de": "Lesen", "en": "Read"},
    "tool.edit": {"de": "Bearbeiten", "en": "Edit"},
    "tool.write": {"de": "Schreiben", "en": "Write"},
    "tool.run": {"de": "Befehl", "en": "Command"},
    "tool.search": {"de": "Suchen", "en": "Search"},
    "tool.web": {"de": "Web", "en": "Web"},
    "tool.agent": {"de": "Subagent", "en": "Subagent"},
    "tool.ask": {"de": "Frage an dich", "en": "Question for you"},
    "tool.plan": {"de": "Plan aktualisiert", "en": "Plan updated"},
    "tool.pc": {"de": "PC · {tool}", "en": "PC · {tool}"},

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
    "say.shipHenry": {
        "de": " · Ship-Entscheidung liegt bei Henry.",
        "en": " · ship decision is with Henry.",
    },
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
    # say.machineAccepted DELETED 2026-09-14 (owner correction 18:40,
    # "doppelt gemoppelt"): dispatch._accept_machine's Done transition no
    # longer echoes a second board-chat line on top of the needs_you result
    # card_mirror.mirror already printed - see the comment at that call site.

    # -- push notifications (notify.card_event) -------------------------------
    "push.henry": {"de": "Henry", "en": "Henry"},
    "push.needsYou": {"de": "Karte fertig - dein Urteil", "en": "Card finished - your call"},
    "push.bounced": {"de": "Karte gescheitert", "en": "Card failed"},
    "push.done": {"de": "Karte akzeptiert", "en": "Card accepted"},
    "push.question": {"de": "Worker fragt dich", "en": "Worker is asking you"},
    "push.pmDone": {"de": "PM: fertig", "en": "PM: finished"},
    "push.pmStuck": {"de": "PM: haengt", "en": "PM: stuck"},
    "push.pmDoneBody": {"de": "'{task}' - braucht deine Abnahme.",
                        "en": "'{task}' - needs your acceptance."},
    "push.pmStuckBody": {"de": "'{task}' - {proposal}", "en": "'{task}' - {proposal}"},
    "push.pmBurn": {"de": "Worker haengt in einer Schleife", "en": "Worker stuck in a loop"},
    "push.pmBurnBody": {"de": "'{task}': {n}x {tool} wiederholt - eingreifen?",
                        "en": "'{task}': {n}x {tool} repeated - step in?"},
    # PM escalations through the presence-aware pipe (pm._escalate -> notify.escalate)
    "push.pmAlert": {"de": "PM: Achtung", "en": "PM: heads-up"},
    "push.pmCost": {"de": "PM: Karte ueber Budget", "en": "PM: card over budget"},
    "push.pmQuota": {"de": "PM: Wochenkontingent laeuft voraus",
                     "en": "PM: weekly quota ahead of pace"},
    # push.pmCtx and push.pmTriangle were DELETED, not orphaned (owner decree
    # 2026-08-30): the context watchdog and the triangle tilt no longer reach
    # the owner at all - they go to Henry (pm_comm._to_henry), who has no push
    # title because he is not a notification. A push title left lying around
    # for a channel that no longer exists is an invitation to re-wire it.
    # the per-card autopilot escalating on its own (processes._auto_resolve)
    "push.autopilotStuck": {"de": "Autopilot: haengt", "en": "Autopilot: stuck"},
    "push.autopilotStuckBody": {
        "de": "'{task}' haengt trotz Fix-Versuchen. {proposal}",
        "en": "'{task}' is still stuck despite fix attempts. {proposal}",
    },

    # -- the PM speaking in chat (pm._say) ------------------------------------
    #
    # THE TWO-SENTENCE LAW (owner decree 2026-08-30: "Zu viel info.. bzw ich
    # weiss nicht was ich dazu machen soll"). Every string that survives here is
    # one the owner has a MOVE for, cut down to the sentence that names that
    # move. pm_comm._short enforces the cap regardless of what is written here;
    # these are written short so the clip never has to fire and take the
    # actionable half with it. Notices with NO owner move - the quota
    # projection, the plan gate, the triangle tilt, the context watchdog, "ich
    # kuemmere mich", "wieder frei" - left the chat entirely and now go to the
    # dashboard feed or to Henry (pm_comm._to_henry). Do not re-add one here
    # without a move in it.
    "pm.planned": {
        "de": "Kurzes Update: ich hab {n} neue Aufgabe(n) fuer dein Ziel eingeplant.",
        "en": "Quick update: I planned {n} new task(s) for your goal.",
    },
    "pm.delivered": {
        "de": "Fertig: '{task}' wartet auf deine Abnahme.",
        "en": "Done: '{task}' is waiting for you to accept it.",
    },
    # a card parked on an unanswered question is NOT delivered - saying so sent
    # the owner to accept work that was never finished
    "pm.asking": {
        "de": "'{task}' fragt dich: {question}",
        "en": "'{task}' is asking you: {question}",
    },
    "pm.stillStuck": {
        "de": "'{task}' haengt weiter - {proposal}",
        "en": "'{task}' is still stuck - {proposal}",
    },
    "pm.burnStuck": {
        "de": "Der Worker von '{task}' dreht sich im Kreis ({n}x {tool}) - meine "
              "{corr} Korrektur(en) haben nicht gereicht.",
        "en": "The worker on '{task}' is going in circles ({n}x {tool}) - my "
              "{corr} correction(s) were not enough.",
    },
    "pm.launchCheck": {
        "de": "Fuers Play-Store-Deploy brauche ich nur von dir: Console-Account, "
              "Upload-Keystore und Datenschutz-URL. Was steht schon?",
        "en": "For the Play Store deploy I only need this from you: console account, "
              "upload keystore and privacy URL. What already exists?",
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
        from spine.storage import events
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
