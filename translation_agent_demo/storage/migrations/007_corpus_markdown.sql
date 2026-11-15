-- Preserve existing builds while accepting explicitly declared Markdown transcripts.
BEGIN;

ALTER TABLE public.corpus_builds
    DROP CONSTRAINT IF EXISTS corpus_builds_parser_format_check;

ALTER TABLE public.corpus_builds
    ADD CONSTRAINT corpus_builds_parser_format_check
    CHECK (parser_format IN ('html', 'srt', 'markdown'));

COMMIT;
