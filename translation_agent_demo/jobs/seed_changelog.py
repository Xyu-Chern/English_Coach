"""Load six public publisher transcripts for a small local corpus, without API keys."""

from ..providers.changelog_transcripts import CHANGELOG_SHOWS, published_episode_numbers, transcript_reference
from ..providers.podcast_transcripts import fetch_episode_transcript
from ..storage.corpus import save_transcript
from ..storage.postgres import PostgresSettings, connect_database
from ..storage.source_reviews import transcript_url_is_approved


def main():
    selections = [(218840, "Go Time", (100, 101)), (403674, "JS Party", (210, 211)),
                  (542376, "The Changelog", (600, 601))]
    with connect_database(PostgresSettings.from_environment()) as conn:
        for feed_id, show, numbers in selections:
            directory, _ = CHANGELOG_SHOWS[feed_id]
            published = published_episode_numbers(feed_id)
            for number in numbers:
                episode = {"id": number, "feedId": feed_id, "title": f"{show} #{number}",
                           "link": f"https://changelog.com/{directory}/{number}"}
                url, mime = transcript_reference(episode, published_numbers=published)
                if not transcript_url_is_approved(conn, feed_id, url):
                    raise ValueError(f"Missing transcript source review for {show}.")
                episode["transcripts"] = [{"url": url, "type": mime}]
                result = save_transcript(conn, fetch_episode_transcript(episode),
                                         language="en", id_namespace="changelog")
                print(episode["title"], "inserted" if result.created else "already stored", flush=True)


if __name__ == "__main__":
    main()
