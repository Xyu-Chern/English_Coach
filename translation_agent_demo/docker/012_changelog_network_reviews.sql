-- Explicit transcript repository reviews; never infer website/audio reuse rights.
-- The publisher README at the pinned commit assigns CC BY-SA 4.0 to the repository,
-- and Changelog Media LLC copyright to everything except bigtent/ (Grafana Labs).
BEGIN;
INSERT INTO public.podcast_feed_reviews
    (feed_id, status, license_id, review_url, review_note, license_evidence, reviewed_at, transcript_url_prefix)
SELECT feed_id, 'approved', 'CC-BY-SA-4.0',
    'https://github.com/thechangelog/transcripts/blob/44a0e16c5919d332e05de481919fbfca90a2c90b/README.md#license--copyright',
    'This review covers only ' || directory || '/ Markdown transcripts in the publisher transcript repository. '
    'Repository README and LICENSE explicitly provide CC BY-SA 4.0; everything except bigtent/ is '
    'copyright Changelog Media LLC. Preserve attribution, license link and modification notices; '
    'distributed adaptations use the same license. Website, audio and unrelated third-party materials are excluded.',
    jsonb_build_object(
        'scope', directory || '/ Markdown transcript repository',
        'repository', 'https://github.com/thechangelog/transcripts',
        'reviewed_commit', '44a0e16c5919d332e05de481919fbfca90a2c90b',
        'license_url', 'https://creativecommons.org/licenses/by-sa/4.0/',
        'license_snapshot', 'https://github.com/thechangelog/transcripts/blob/44a0e16c5919d332e05de481919fbfca90a2c90b/LICENSE',
        'attribution', 'Changelog Media LLC',
        'feed_identity_url', 'https://changelog.com/' || directory || '/feed',
        'example_episode', 'https://changelog.com/' || directory || '/1',
        'example_transcript', 'https://github.com/thechangelog/transcripts/blob/44a0e16c5919d332e05de481919fbfca90a2c90b/' || directory || '/' || filename_prefix || '-1.md'
    ),
    CURRENT_TIMESTAMP,
    'https://raw.githubusercontent.com/thechangelog/transcripts/master/' || directory || '/'
FROM (VALUES (218840::bigint, 'gotime', 'go-time'), (403674::bigint, 'jsparty', 'js-party'))
    AS sources(feed_id, directory, filename_prefix)
ON CONFLICT (feed_id) DO NOTHING; -- Preserve prior operator decisions.
COMMIT;
