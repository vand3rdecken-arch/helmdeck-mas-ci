# HelmDeck relay (thin - the APK rule)

The cloud's ONLY jobs, all tiny and stateless beyond the newest values:

- `/pair` - rendezvous: daemon and APK exchange a pairing code once (like Herald's cast code).
- `/frame` - newest live frame (POST from daemon, GET from glasses viewer). One JPEG held in a
  Durable Object, overwritten each push. Nothing archived - the archive is the PHONE.
- `/tracks` - tiny rows: run id, title, status, step count, last flag. For the glasses feed.

No recordings, no timelines, no playbooks, no auth store here. If a feature seems to need
more cloud than this, it belongs in the APK.

Not deployed yet - deploying is a separate explicit ask (it creates a new public endpoint).
The glasses/phone work over LAN against the daemon until then; the relay only matters
away-from-home.
