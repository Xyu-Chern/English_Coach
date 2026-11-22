-- Where each cited chunk plays in its episode's publisher audio (frontend/audio_align.py).
-- A cache: one row per chunk, rebuilt by aligning again. Times only (ms); never audio bytes.
--   words  the chunk's own words in order, [{"w": word, "s": start_ms, "e": end_ms}]
--   cues   the chunk's lines for display, [{"text", "start_ms", "end_ms"}]
--   method "asr" (speech recognition matched to the transcript) | "stored" (the transcript's own cue timing)
-- Safe to apply to an existing DB; the local server also runs it (CREATE ... IF NOT EXISTS) before first use.
BEGIN;

CREATE TABLE IF NOT EXISTS public.chunk_audio_alignment (
    chunk_id uuid PRIMARY KEY REFERENCES public.corpus_chunks(chunk_id) ON DELETE CASCADE,
    audio_url text NOT NULL CHECK (length(audio_url) BETWEEN 1 AND 2048 AND audio_url ~ '^https?://'),
    window_start_ms integer NOT NULL CHECK (window_start_ms >= 0),
    words jsonb NOT NULL CHECK (jsonb_typeof(words) = 'array' AND jsonb_array_length(words) > 0),
    cues jsonb NOT NULL CHECK (jsonb_typeof(cues) = 'array' AND jsonb_array_length(cues) > 0),
    method text NOT NULL CHECK (method IN ('asr', 'stored')),
    model text CHECK (model IS NULL OR length(model) BETWEEN 1 AND 128),
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
