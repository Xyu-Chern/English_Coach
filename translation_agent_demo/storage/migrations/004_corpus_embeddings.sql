-- Partial batches survive retries; only complete builds become searchable.
BEGIN;

CREATE TABLE IF NOT EXISTS public.corpus_embeddings (
    chunk_id uuid NOT NULL REFERENCES public.corpus_chunks(chunk_id) ON DELETE CASCADE,
    model text NOT NULL
        CHECK (length(model) BETWEEN 1 AND 100 AND length(btrim(model)) > 0),
    dimensions integer NOT NULL CHECK (dimensions = 1536),
    embedding public.vector(1536) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, model)
);

CREATE TABLE IF NOT EXISTS public.corpus_embedding_builds (
    build_id uuid NOT NULL REFERENCES public.corpus_builds(build_id) ON DELETE CASCADE,
    model text NOT NULL
        CHECK (length(model) BETWEEN 1 AND 100 AND length(btrim(model)) > 0),
    dimensions integer NOT NULL CHECK (dimensions = 1536),
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (build_id, model)
);

COMMIT;
