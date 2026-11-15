-- Explicit scheduling state for selected feeds; safe to apply to an existing DB.
BEGIN;

CREATE TABLE IF NOT EXISTS public.podcast_sync_feeds (
    feed_id bigint PRIMARY KEY CHECK (feed_id > 0),
    last_run_at timestamptz,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    cooldown_until timestamptz,
    last_refresh_at timestamptz,
    next_refresh_at timestamptz NOT NULL DEFAULT now(),
    initial_scan_done boolean NOT NULL DEFAULT false,
    backfill_complete boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS public.podcast_sync_items (
    feed_id bigint NOT NULL REFERENCES public.podcast_sync_feeds(feed_id),
    episode_id bigint NOT NULL CHECK (episode_id > 0),
    transcript_url text NOT NULL CHECK (length(transcript_url) BETWEEN 1 AND 2048),
    episode_data jsonb NOT NULL CHECK (jsonb_typeof(episode_data) = 'object'),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'stored', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (feed_id, episode_id),
    CHECK ((episode_data -> 'feedId') IS NOT DISTINCT FROM to_jsonb(feed_id)),
    CHECK ((episode_data -> 'id') IS NOT DISTINCT FROM to_jsonb(episode_id)),
    CHECK ((episode_data #>> '{transcripts,0,url}') IS NOT DISTINCT FROM transcript_url)
);

CREATE INDEX IF NOT EXISTS podcast_sync_items_pending_idx
    ON public.podcast_sync_items (feed_id, next_attempt_at)
    WHERE status = 'pending' AND attempts < 3;

COMMIT;
