-- Derived parsing/chunking results are versioned separately from acquired text.
BEGIN;

CREATE TABLE IF NOT EXISTS public.corpus_builds (
    build_id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES public.podcast_transcripts(document_id),
    processing_version text NOT NULL
        CHECK (length(processing_version) BETWEEN 1 AND 128 AND length(btrim(processing_version)) > 0),
    status text NOT NULL CHECK (status IN ('ready', 'unsupported', 'failed')),
    error_code text CHECK (error_code IN ('unsupported_format', 'invalid_format', 'empty_transcript')),
    parser_format text CHECK (parser_format IN ('html', 'srt')),
    cues jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(cues) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, processing_version),
    CHECK (
        (status = 'ready' AND error_code IS NULL AND parser_format IS NOT NULL
            AND jsonb_array_length(cues) > 0)
        OR (status = 'unsupported' AND error_code IS NOT NULL AND error_code = 'unsupported_format'
            AND parser_format IS NULL AND cues = '[]'::jsonb)
        OR (status = 'failed' AND error_code IS NOT NULL
            AND error_code IN ('invalid_format', 'empty_transcript')
            AND parser_format IS NULL AND cues = '[]'::jsonb)
    )
);

CREATE TABLE IF NOT EXISTS public.corpus_chunks (
    chunk_id uuid PRIMARY KEY,
    build_id uuid NOT NULL REFERENCES public.corpus_builds(build_id) ON DELETE CASCADE,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    text text NOT NULL CHECK (text ~ '[^[:space:]]'),
    token_count integer NOT NULL CHECK (token_count > 0),
    spans jsonb NOT NULL
        CHECK (jsonb_typeof(spans) = 'array' AND jsonb_array_length(spans) > 0),
    start_ms bigint CHECK (start_ms >= 0),
    end_ms bigint CHECK (end_ms >= 0),
    CHECK (start_ms IS NULL OR end_ms IS NULL OR end_ms >= start_ms),
    UNIQUE (build_id, chunk_index)
);

COMMIT;
