-- Publisher audio enclosure per Podcast Index episode; metadata only, never audio bytes.
-- Safe to apply to an existing DB. Rows are refreshed by the audio backfill and sync jobs.
BEGIN;

CREATE TABLE IF NOT EXISTS public.podcast_episode_audio (
    episode_id bigint PRIMARY KEY CHECK (episode_id > 0),
    feed_id bigint CHECK (feed_id IS NULL OR feed_id > 0),
    enclosure_url text NOT NULL
        CHECK (length(enclosure_url) BETWEEN 1 AND 2048 AND enclosure_url ~ '^https?://'),
    duration_s integer CHECK (duration_s IS NULL OR duration_s > 0),
    fetched_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS podcast_episode_audio_feed_idx
    ON public.podcast_episode_audio (feed_id);

COMMIT;
