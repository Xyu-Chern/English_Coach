-- A repository review covers its URL directory, not every transcript in a feed.
BEGIN;

ALTER TABLE public.podcast_feed_reviews
    ADD COLUMN IF NOT EXISTS transcript_url_prefix text
        CHECK (transcript_url_prefix IS NULL OR length(transcript_url_prefix) BETWEEN 1 AND 2048);

CREATE OR REPLACE FUNCTION public.transcript_url_matches_review_scope(
    transcript_url text, review_prefix text
) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $scope$
    SELECT CASE WHEN review_prefix IS NULL THEN transcript_url IS NOT NULL
    ELSE COALESCE(
        starts_with(transcript_url, review_prefix)
        -- Canonical HTTPS paths only: no escapes, queries, fragments or dot traversal.
        AND transcript_url ~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9/_.~!$&''()*+,;=:@-]*$'
        AND transcript_url !~ '(^|/)[.]{1,2}(/|$)',
        false
    ) END;
$scope$;

UPDATE public.podcast_feed_reviews
SET transcript_url_prefix = 'https://raw.githubusercontent.com/thechangelog/transcripts/master/podcast/'
WHERE feed_id = 542376 AND transcript_url_prefix IS NULL;

-- Correct prior scope metadata and withdraw only over-broad source approvals.
-- Neither this correction nor replaying the migration can approve a source.
UPDATE public.podcast_sources AS s
SET rights_status = CASE
        WHEN s.rights_status = 'approved' AND (
            r.status <> 'approved'
            OR NOT public.transcript_url_matches_review_scope(s.last_download_url, r.transcript_url_prefix)
        ) THEN 'unverified' ELSE s.rights_status END,
    license_evidence = s.license_evidence || jsonb_build_object('feed_review', jsonb_build_object(
        'feed_id', r.feed_id, 'scope', 'url_prefix', 'transcript_url_prefix', r.transcript_url_prefix,
        'status', r.status, 'license_id', r.license_id, 'review_url', r.review_url,
        'reviewed_at', r.reviewed_at, 'evidence', r.license_evidence
    )),
    updated_at = now()
FROM public.podcast_feed_reviews AS r
WHERE s.feed_id = r.feed_id AND r.feed_id = 542376 AND s.rights_status <> 'revoked';

COMMIT;
