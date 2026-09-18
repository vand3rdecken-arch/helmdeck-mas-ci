-- Adds the per-post identifier column to an existing events table without
-- losing any rows (D1 = SQLite: ALTER TABLE ADD COLUMN is safe, nulls old rows).
-- Apply once:
--   cd ops/deploy/waitlist && npx wrangler d1 execute helmdeck-site-stats --remote --file=migrations/0001_add_utm_content.sql
ALTER TABLE events ADD COLUMN utm_content TEXT;
