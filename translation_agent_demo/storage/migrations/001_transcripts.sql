-- Initial tables in english_coach's default public schema.
-- Docker runs this only for an empty PostgreSQL data directory.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE public.podcast_sources (
    source_key text PRIMARY KEY,
    feed_id bigint NOT NULL CHECK (feed_id > 0),
    episode_id bigint NOT NULL CHECK (episode_id > 0),
    title text NOT NULL,
    episode_url text,
    language text CHECK (language IS NULL OR length(language) BETWEEN 1 AND 64),
    license_evidence jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(license_evidence) = 'object'),
    rights_status text NOT NULL DEFAULT 'unverified'
        CHECK (rights_status IN ('unverified', 'approved', 'revoked')),
    review_note text,
    review_url text,
    reviewed_at timestamptz,
    last_download_url text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (feed_id, episode_id),
    CHECK (source_key = 'podcast_index:' || feed_id::text || ':' || episode_id::text),
    CHECK (rights_status <> 'approved' OR
        (reviewed_at IS NOT NULL AND review_note IS NOT NULL AND length(trim(review_note)) > 0))
);

CREATE TABLE public.podcast_transcripts (
    document_id uuid PRIMARY KEY,
    source_key text NOT NULL REFERENCES public.podcast_sources(source_key),
    download_url text NOT NULL CHECK (length(download_url) BETWEEN 1 AND 2048),
    declared_type text,
    content_type text,
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    raw_text text NOT NULL CHECK (octet_length(raw_text) BETWEEN 1 AND 2097152),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_key, content_sha256)
);

COMMIT;
