-- Optional local seed: the already inspected Podcasting 2.0 episode.
-- Runs only during Docker's first database initialization; no API call is made.
-- Raw third-party text stays in ignored .local/transcripts, outside Git/images.
DO $seed$
DECLARE
    body text;
    body_hash text;
BEGIN
    IF (pg_stat_file('/bootstrap/PC20-278-Captions.srt', true)).size IS NULL THEN
        RAISE NOTICE 'Local transcript seed absent; schema initialization is complete.';
        RETURN;
    END IF;

    body := pg_read_file('/bootstrap/PC20-278-Captions.srt');
    body_hash := encode(sha256(convert_to(body, 'UTF8')), 'hex');
    IF body_hash <> '1141f4074ff2aefbb716278785fec39ae5278f65b707aac7fdf803bcdeda0d79' THEN
        RAISE EXCEPTION 'The local transcript seed does not match the inspected file.';
    END IF;

    INSERT INTO public.podcast_sources
        (source_key, feed_id, episode_id, title, episode_url, language,
         license_evidence, rights_status, last_download_url)
    VALUES
        ('podcast_index:920666:63179241903', 920666, 63179241903,
         'Episode 278: "1 Billion Tokens!"', 'https://www.podpage.com/podcasting-20/1billion-tokens/', 'en',
         '{"feed_license_at_inspection":"not_found","transcript_reuse":"unverified"}'::jsonb,
         'unverified', 'https://mp3s.nashownotes.com/PC20-278-Captions.srt')
    ON CONFLICT (source_key) DO NOTHING;

    INSERT INTO public.podcast_transcripts
        (document_id, source_key, download_url, declared_type, content_type,
         content_sha256, raw_text, fetched_at)
    VALUES
        ('b1e34612-7aca-50ac-8062-6d7cf4e33181'::uuid, 'podcast_index:920666:63179241903', 'https://mp3s.nashownotes.com/PC20-278-Captions.srt',
         'application/srt', 'application/octet-stream', body_hash, body,
         '2026-11-15T06:32:11.089873+00:00'::timestamptz)
    ON CONFLICT (source_key, content_sha256) DO NOTHING;
END;
$seed$;
