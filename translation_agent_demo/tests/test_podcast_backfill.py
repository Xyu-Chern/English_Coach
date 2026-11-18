"""Archive target/identity checks without model calls or a mutable live test DB."""

import unittest
from unittest.mock import Mock, patch

from translation_agent_demo.jobs.podcast_backfill import MAX_TARGET, backfill_corpus, select_candidates
from translation_agent_demo.providers.changelog_transcripts import transcript_reference
from translation_agent_demo.providers.podcast_index import PodcastIndexClient, PodcastIndexCredentials


def episode(feed, number, *, episode_id=None):
    return {"id": episode_id or number, "feedId": feed, "datePublished": number,
            "transcripts": [{"url": f"https://example.org/{feed}/{number}.md"}]}


class BackfillTests(unittest.TestCase):
    def test_existing_bodies_count_toward_total_and_shows_balance(self):
        candidates = {feed: [episode(feed, i) for i in range(500)] for feed in (1, 2, 3)}
        existing = {episode(1, i)["transcripts"][0]["url"]: 1 for i in range(56)}
        selected = select_candidates(candidates, existing, target=1000)
        self.assertEqual(sum(map(len, selected.values())), 944)
        self.assertEqual(sorted([len(selected[1]) + 56, len(selected[2]), len(selected[3])]), [333, 333, 334])
        urls = [e["transcripts"][0]["url"] for rows in selected.values() for e in rows]
        self.assertEqual(len(set(urls)), len(urls))
        self.assertFalse(set(urls).intersection(existing))

    def test_same_published_url_with_different_api_ids_is_not_two_sources(self):
        first = episode(1, 4)
        duplicate = episode(1, 4, episode_id=99)
        result = select_candidates({1: [first, duplicate, episode(1, 5)]}, {}, target=5)
        self.assertEqual([e["id"] for e in result[1]], [4, 5])

    def test_archive_capacity_shortfall_stops_without_manufacturing_ids(self):
        result = select_candidates({1: [episode(1, 1)], 2: []}, {}, target=1000)
        self.assertEqual(sum(map(len, result.values())), 1)

    def test_target_concurrency_and_unknown_feed_reject_before_connection(self):
        for kwargs in ({"target": MAX_TARGET + 1}, {"target": True}, {"concurrency": 5}, {"max_downloads": MAX_TARGET + 1}):
            with self.assertRaises(ValueError):
                backfill_corpus(None, None, (542376,), **kwargs)
        with self.assertRaises(ValueError):
            backfill_corpus(None, None, (99,))

    def test_completed_target_resume_does_not_call_provider_or_download(self):
        conn = Mock(autocommit=True)
        conn.execute.return_value.fetchone.side_effect = [(True,), (None,)]
        existing = {"https://example.org/one.md": 542376}
        with patch("translation_agent_demo.jobs.podcast_backfill.approved_feed_ids", return_value=(542376,)), \
             patch("translation_agent_demo.jobs.podcast_backfill.ensure_feeds"), \
             patch("translation_agent_demo.jobs.podcast_backfill._stored", return_value=existing), \
             patch("translation_agent_demo.jobs.podcast_backfill.published_episode_numbers") as catalog, \
             patch("translation_agent_demo.jobs.podcast_backfill.fetch_episode_transcript") as download:
            client = Mock()
            result = backfill_corpus(conn, client, (542376,), target=1)
        self.assertEqual(result.total_stored, 1)
        client.historical_episodes_by_feed_id.assert_not_called()
        catalog.assert_not_called()
        download.assert_not_called()

    def test_show_mapping_requires_catalog_and_correct_publisher_url(self):
        item = {"feedId": 218840, "link": "https://changelog.com/gotime/1"}
        self.assertEqual(transcript_reference(item, published_numbers=frozenset({1})),
                         ("https://raw.githubusercontent.com/thechangelog/transcripts/master/gotime/go-time-1.md", "text/markdown"))
        for wrong in (dict(item, link="https://changelog.com/podcast/1"), dict(item, link="https://evil.test/gotime/1")):
            with self.assertRaises(ValueError):
                transcript_reference(wrong, published_numbers=frozenset({1}))
        with self.assertRaises(ValueError):
            transcript_reference(item, published_numbers=frozenset())

    def test_archive_is_opt_in_and_keeps_ordinary_refresh_limit(self):
        client = PodcastIndexClient(PodcastIndexCredentials("public-key", "test-secret"))
        with patch.object(client, "_get", return_value={}) as get:
            client.historical_episodes_by_feed_id(542376, limit=1000)
            get.assert_called_once_with("/episodes/byfeedid", {"id": 542376, "max": 1000}, "items", max_response_bytes=8 * 1024 * 1024)
        with self.assertRaises(ValueError):
            client.episodes_by_feed_id(542376, limit=201)
        with self.assertRaises(ValueError):
            client.historical_episodes_by_feed_id(542376, limit=1001)


if __name__ == "__main__":
    unittest.main()
