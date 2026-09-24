# -*- coding: utf-8 -*-
"""A throwaway SANDBOX daemon that carries the marketing/store demo content of
the phone screenshots (Aurora Studio, Nordwind, reminder mails ...) in one
language, so helmdeck.de can show localized screenshots (EN default, DE toggle).

Same shape as boards_verify_daemon.py: the real request handler over a temp
store (asserted below), never the live daemon/db. With a relay url it also
starts the relay client and prints the pairing deep link for the emulator
(memory recipe: the release APK blocks cleartext, so the public relay is the
only path). Without one it is just a direct daemon for Playwright.

  py -3.12 ops/tools/demo_phone_daemon.py [port] [en|de] [--relay https://relay.helmdeck.de]
"""
import base64, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-phonedemo-")
import daemon.paths
daemon.paths.DAEMON_ROOT = SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import boards, db, events    # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET), ("users", auth.USERS)):
    assert path.startswith(SANDBOX), "REFUSING TO RUN: %s points at %s" % (label, path)

args = [a for a in sys.argv[1:]]
RELAY = ""
if "--relay" in args:
    i = args.index("--relay")
    RELAY = args[i + 1]
    del args[i:i + 2]
PORT = int(args[0]) if args else 8177
LANG = args[1] if len(args) > 1 else "en"
PW = "hunter2hunter2"

db.init()
# plan=api so cost chips read "AI $0.63" like the German shots, not a flat-plan token count
db.workspace_config_replace({"policy": {"lang": LANG}, "appearance": {"backdrop": "mesh"},
                             "pm": {"plan": "api", "goal": {
                                 "en": "Relaunch the Aurora Studio website and ship the invoice CSV export this month",
                                 "de": "Aurora-Studio-Website relaunchen und den Rechnungs-CSV-Export diesen Monat ausliefern"}[LANG]}})
auth.create_user("owner", PW, "owner")
boards.ensure_default()

# a card whose stored status is `running` needs a live turn or it presents as
# needs_you (lifecycle.present) - faked at its real address, as glance_shoot does
from spine.agent import drivers                 # noqa: E402
_LIVE = {"csv"}
drivers.turn_active = lambda tid: tid in _LIVE

T = {
    "en": dict(
        onb=("Set up onboarding mail series for new customers",
             "Welcome series (3 mails) in portal style: greeting, setup, tips. Sender hello@aurora.studio, sent via the existing mail relay."),
        faq="Pricing page: add FAQ and comparison table",
        csv="CSV export of invoices in the customer portal",
        rem="Reminder mails: set send time",
        remq="Question: Should existing customers also get the reminder mail or only new customers since 07/01? After that I switch on the cron job.",
        remask="Should existing customers also get the reminder mail, or only new customers since 07/01?",
        remhead="Audience", opt1="All customers", opt2="New customers only",
        lp="Landing page relaunch: Hero, ...",
        lpn=["REQUEST filed: Landing page relaunch (branch landingpage-relaunch)",
             "Gate: 4/4 checks passed - ready for approval",
             "REVIEW: card is waiting for approval",
             "Turn 4: hero section rebuilt - product screenshot, headline, sub and CTA above the fold",
             "Reference slider with 5 customer logos added, lazy loading for all images",
             "Lighthouse: performance 96, a11y 100, SEO 100 - screenshot stored in the history"],
        internal="internal", goal=None,
        done=["Contact form with spam protection", "Newsletter signup in the footer", "Redesign the 404 page"],
    ),
    "de": dict(
        onb=("Onboarding-Mailstrecke für Neukunden aufsetzen",
             "Willkommensserie (3 Mails) im Portal-Stil: Begrüßung, Einrichtung, Tipps. Absender hello@aurora.studio, Versand über den bestehenden Mail-Relay."),
        faq="Preisseite: FAQ und Vergleichstabelle ergänzen",
        csv="CSV-Export der Rechnungen im Kundenportal",
        rem="Reminder-Mails: Versandzeitpunkt festlegen",
        remq="Rückfrage: Sollen Bestandskunden die Reminder-Mail auch erhalten oder nur Neukunden seit dem 01.07.? Danach schalte ich den Cron ein.",
        remask="Sollen Bestandskunden die Reminder-Mail auch erhalten oder nur Neukunden seit dem 01.07.?",
        remhead="Zielgruppe", opt1="Alle Kunden", opt2="Nur Neukunden",
        lp="Landingpage-Relaunch: Hero, ...",
        lpn=["REQUEST filed: Landingpage-Relaunch (branch landingpage-relaunch)",
             "Gate: 4/4 Prüfungen bestanden - bereit zur Abnahme",
             "REVIEW: Karte wartet auf Freigabe",
             "Turn 4: Hero-Sektion umgebaut - Produkt-Screenshot, Headline, Sub und CTA ueber dem Fold",
             "Referenz-Slider mit 5 Kundenlogos eingebaut, Lazy-Loading fuer alle Bilder",
             "Lighthouse: Performance 96, A11y 100, SEO 100 - Screenshot im Verlauf abgelegt"],
        internal="intern", goal=None,
        done=["Kontaktformular mit Spam-Schutz", "Newsletter-Anmeldung im Footer", "404-Seite neu gestalten"],
    ),
}[LANG]

NOW = "2026-09-22 12:00:00"
onb_t, onb_d = T["onb"]
CARDS = [
    dict(id="onb", task=onb_t, lane="backlog", status="queued", priority="medium",
         branch="onboarding-mails", client="Aurora Studio", value=240, last_reply=onb_d),
    dict(id="faq", task=T["faq"], lane="backlog", status="queued", priority="low",
         branch="pricing-faq", client=T["internal"], value=120),
    dict(id="csv", task=T["csv"], lane="working", status="running", priority="high",
         branch="invoice-csv-export", client="Nordwind GmbH", value=480, ai_cost=1.42),
    dict(id="rem", task=T["rem"], lane="working", status="needs_you", priority="medium",
         branch="reminder-mails", client="Aurora Studio", value=180, ai_cost=0.63,
         waiting_on="you", last_reply=T["remq"],
         question={"id": "q-rem", "kind": "choice", "questions": [
             {"question": T["remask"], "header": T["remhead"],
              "options": [{"label": T["opt1"], "description": ""},
                          {"label": T["opt2"], "description": ""}]}]}),
    dict(id="lp", task=T["lp"], lane="review", status="submitted", priority="medium",
         branch="landingpage-relaunch", client="Aurora Studio", value=0, ai_cost=1.1),
]
# accepted work: EUR 500 delivered, $6.94 AI spend in total (the German shot's totals)
done_cost = round(6.94 - 1.42 - 0.63 - 1.1, 2)
for i, name in enumerate(T["done"]):
    CARDS.append(dict(id="dn%d" % i, task=name, lane="done", status="accepted",
                      priority="medium", branch="done-%d" % i, client="Aurora Studio",
                      value=[200, 200, 100][i], ai_cost=[done_cost / 2, done_cost / 4, done_cost / 4][i]))
for i, c in enumerate(CARDS):
    c.setdefault("ai_cost", 0.0)
    c.update(created=NOW, rank=i, repo=ROOT, driver="claude", actor="owner", client=c["client"])
    db.track_put(c)
# human touches: 2 on the reminder card, 3 on the CSV one, 6 on the landing page
for tid, n in (("rem", 2), ("csv", 3), ("lp", 6)):
    for _ in range(n):
        events.emit("touch", tid, touch="answer")

from spine.ops.actionlog import ActionLog       # noqa: E402
rd = os.path.join(SANDBOX, "lp")
os.makedirs(rd, exist_ok=True)
log = ActionLog(rd)
for line in T["lpn"]:
    log.log("note", line)
db.track_put({**[c for c in CARDS if c["id"] == "lp"][0], "run_dir": rd})

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

if RELAY:
    from spine.comms import relay_client
    events.save_settings({"relay": {"url": RELAY}})
    pay = relay_client.pairing_payload()
    tok = auth.issue_token("owner", "demo phone", unused_days=auth.PAIR_UNUSED_TTL_DAYS)
    relay_client.start(PORT)
    c = base64.urlsafe_b64encode(json.dumps(
        {"u": pay["url"], "r": pay["room"], "k": pay["daemon_pub"], "t": tok}).encode()).decode().rstrip("=")
    print("pair    : helmdeck://pair?c=%s" % c)
print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d  (owner/%s) lang=%s" % (PORT, PW, LANG))
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.shutdown()
