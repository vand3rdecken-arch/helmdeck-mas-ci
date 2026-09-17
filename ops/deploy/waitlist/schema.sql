-- Cookieless reach measurement (helmdeck.de), D1 database helmdeck-site-stats.
-- One flexible table: every event type (view, section_seen, scroll,
-- video_play/progress, cta_click, form_start/error/submit, leave,
-- server_view) writes into the same columns, nulling what does not apply.
-- No cookies, no IP address, no user-agent string ever land here - see
-- /datenschutz section 3a and ops/deploy/waitlist/src/index.js (isBot(),
-- handleEvent(), insertEvent()). Read via ops/tools/site_stats.py.
--
-- Apply:  cd ops/deploy/waitlist && npx wrangler d1 execute helmdeck-site-stats --remote --file=schema.sql

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,          -- unix seconds
  vid TEXT NOT NULL,            -- random id, one per page load, dies with the tab
  type TEXT NOT NULL,           -- view | server_view | section_seen | scroll | video_play | video_progress | cta_click | form_start | form_error | form_submit | leave
  path TEXT,
  lang TEXT,
  device TEXT,                  -- mobile | desktop
  ref_host TEXT,                -- referrer hostname only, never the full URL
  utm_source TEXT,
  utm_medium TEXT,
  utm_campaign TEXT,
  country TEXT,                 -- request.cf.country (Cloudflare edge geo, no IP stored)
  section TEXT,                 -- section_seen: which section; leave: last section seen
  seconds INTEGER,              -- section_seen: seconds since view; leave: time on page
  pct INTEGER,                  -- scroll/video_progress: percent; leave: max scroll depth
  label TEXT,                   -- cta_click: button; form_start/submit: product; form_error: kind
  already INTEGER,              -- form_submit: 1 if the address was already on the list
  bot INTEGER NOT NULL DEFAULT 0,  -- User-Agent looked bot-like (checked, never stored)
  test INTEGER NOT NULL DEFAULT 0  -- ?hd_test=1 on the visit, excluded from reports by default
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_vid ON events(vid);
