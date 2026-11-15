-- Preserve immutable acquisition times while tracking repeated body observations.
BEGIN;

ALTER TABLE public.podcast_transcripts
    ADD COLUMN IF NOT EXISTS last_observed_at timestamptz;

UPDATE public.podcast_transcripts
SET last_observed_at = fetched_at
WHERE last_observed_at IS NULL;

ALTER TABLE public.podcast_transcripts
    ALTER COLUMN last_observed_at SET DEFAULT clock_timestamp(),
    ALTER COLUMN last_observed_at SET NOT NULL;

COMMIT;
