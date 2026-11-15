-- Explicit publisher-wide transcript reviews; no source is approved by this migration.
BEGIN;

CREATE TABLE IF NOT EXISTS public.podcast_feed_reviews (
    feed_id bigint PRIMARY KEY CHECK (feed_id > 0),
    status text NOT NULL CHECK (status IN ('approved', 'revoked')),
    license_id text NOT NULL
        CHECK (length(license_id) BETWEEN 1 AND 128 AND length(btrim(license_id)) > 0),
    review_url text NOT NULL CHECK (length(review_url) BETWEEN 1 AND 2048),
    review_note text NOT NULL
        CHECK (length(review_note) BETWEEN 1 AND 4096 AND length(btrim(review_note)) > 0),
    license_evidence jsonb NOT NULL CHECK (jsonb_typeof(license_evidence) = 'object'),
    reviewed_at timestamptz NOT NULL
);

COMMIT;
