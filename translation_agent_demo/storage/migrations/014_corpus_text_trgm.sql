-- A trigram index on chunk text for the literal-first search (key phrase ILIKE) and the whole-word
-- count (~*): both can use it instead of reading every chunk. No table or column changes; without it
-- the same queries still work, only slower. pg_trgm is a trusted extension (PostgreSQL 13+).
BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS corpus_chunks_text_trgm
    ON public.corpus_chunks USING gin (text gin_trgm_ops);

COMMIT;
