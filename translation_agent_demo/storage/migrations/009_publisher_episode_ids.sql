-- Publisher episode numbers and Podcast Index episode IDs are separate namespaces.
BEGIN;
ALTER TABLE public.podcast_sources
    DROP CONSTRAINT podcast_sources_check,
    DROP CONSTRAINT podcast_sources_feed_id_episode_id_key,
    ADD CHECK (source_key IN ('podcast_index:' || feed_id || ':' || episode_id,
                              'changelog:' || feed_id || ':' || episode_id));
COMMIT;
