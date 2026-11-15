-- Public transcript-source evidence reviewed on 2026-11-15. No transcript bodies or keys.
-- This record covers the dedicated Markdown repository used by the Changelog adapter.
BEGIN;
INSERT INTO public.podcast_feed_reviews
    (feed_id, status, license_id, review_url, review_note, license_evidence, reviewed_at, transcript_url_prefix)
VALUES (
    542376, 'approved', 'CC-BY-SA-4.0',
    'https://github.com/thechangelog/transcripts#license--copyright',
    'The Changelog adapter selects this feed''s transcripts only from the publisher''s '
    'dedicated podcast/ Markdown transcript repository. Its README and LICENSE cover '
    'the repository content under CC BY-SA 4.0. Preserve attribution, the license link '
    'and modification notices; share adapted distributed material under the same license. '
    'This review does not cover the website/audio or unrelated third-party materials.',
    '{"scope":"podcast/ Markdown transcript repository",'
      '"repository":"https://github.com/thechangelog/transcripts",'
      '"reviewed_commit":"44a0e16c5919d332e05de481919fbfca90a2c90b",'
      '"license_url":"https://creativecommons.org/licenses/by-sa/4.0/",'
      '"license_snapshot":"https://github.com/thechangelog/transcripts/blob/44a0e16c5919d332e05de481919fbfca90a2c90b/LICENSE",'
      '"attribution":"Changelog Media LLC",'
      '"example_episode":"https://changelog.com/podcast/600",'
      '"example_transcript":"https://github.com/thechangelog/transcripts/blob/44a0e16c5919d332e05de481919fbfca90a2c90b/podcast/the-changelog-600.md"}'::jsonb,
    '2026-11-15T09:33:58Z',
    'https://raw.githubusercontent.com/thechangelog/transcripts/master/podcast/'
)
ON CONFLICT (feed_id) DO NOTHING; -- Never undo an existing operator decision.
COMMIT;
