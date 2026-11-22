"""Fill podcast_episode_audio for stored transcripts from Podcast Index metadata.

Phase 1 reads one archive page per feed (/episodes/byfeedid, max 1000) and
saves every enclosure it returns. Phase 2 asks /episodes/byid for episodes still
missing. Requests are spaced by --interval seconds; failures are skipped, and
401/403 stops the run. Only metadata is fetched; audio files are never downloaded.

    python -m translation_agent_demo.jobs.podcast_audio_backfill [--feed-ids 1,2] [--dry-run]
"""

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from psycopg import Connection

from ..providers.podcast_index import PodcastIndexClient, PodcastIndexCredentials, PodcastIndexError
from ..storage.episode_audio import (
    audio_coverage, audio_from_episode, episodes_missing_audio, save_episode_audio,
)
from ..storage.postgres import PostgresSettings, connect_database

MAX_REQUESTS = 3000
MAX_RETRY_WAIT_SECONDS = 60
FEED_PAGE_MIN_MISSING = 3  # Fewer missing episodes are cheaper as single lookups.


@dataclass
class AudioBackfillResult:
    status: str = "ok"
    missing_before: int = 0
    feed_requests: int = 0
    episode_requests: int = 0
    saved: int = 0
    failed: int = 0
    skipped_no_enclosure: int = 0
    with_audio: int = 0
    total_episodes: int = 0
    errors: dict[str, int] = field(default_factory=dict)


def backfill_audio(
    conn: Connection, client: PodcastIndexClient, *, feed_ids: tuple[int, ...] | None = None,
    interval: float = 0.5, max_requests: int = MAX_REQUESTS, dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> AudioBackfillResult:
    if not 0 <= interval <= 10 or type(max_requests) is not int or not 1 <= max_requests <= MAX_REQUESTS:
        raise ValueError("interval must be 0-10 seconds and max_requests 1-3000.")
    result = AudioBackfillResult()
    errors: Counter[str] = Counter()
    missing = episodes_missing_audio(conn, feed_ids=feed_ids)
    result.missing_before = len(missing)
    requests = 0

    def request(call):
        nonlocal requests
        if requests:
            sleep(interval)
        requests += 1
        try:
            return call()
        except PodcastIndexError as error:
            result.failed += 1
            errors[str(error.status_code or "network")] += 1
            if error.status_code in {401, 403}:
                result.status = "auth_failed"
            elif error.status_code == 429:
                sleep(min(error.retry_after_seconds or interval * 10, MAX_RETRY_WAIT_SECONDS))
            return None

    if dry_run:
        result.status = "dry_run"
    else:
        wanted = {episode for _, episode in missing}
        per_feed = Counter(feed for feed, _ in missing)
        for feed, count in sorted(per_feed.items()):
            if count < FEED_PAGE_MIN_MISSING or requests >= max_requests or result.status != "ok":
                continue
            payload = request(lambda: client.historical_episodes_by_feed_id(feed))
            result.feed_requests += 1
            if payload is None:
                continue
            records = [audio for audio in map(audio_from_episode, payload["items"]) if audio]
            for offset in range(0, len(records), 1000):
                result.saved += save_episode_audio(conn, records[offset:offset + 1000])
            wanted -= {audio.episode_id for audio in records}
        for episode_id in sorted(wanted):
            if requests >= max_requests or result.status != "ok":
                break
            payload = request(lambda: client.episode_by_id(episode_id))
            result.episode_requests += 1
            if payload is None:
                continue
            audio = audio_from_episode(payload["episode"])
            if audio is None:
                result.skipped_no_enclosure += 1
                continue
            result.saved += save_episode_audio(conn, [audio])
        if result.status == "ok" and requests >= max_requests:
            result.status = "request_budget_reached"
    result.errors = dict(errors)
    result.with_audio, result.total_episodes = audio_coverage(conn)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feed-ids", help="Optional comma-separated Podcast Index feed IDs")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between API requests")
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    parser.add_argument("--dry-run", action="store_true", help="Only count episodes missing audio")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    feed_ids = tuple(int(value) for value in args.feed_ids.split(",")) if args.feed_ids else None
    client = PodcastIndexClient(PodcastIndexCredentials.from_environment(args.env_file))
    with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
        result = backfill_audio(conn, client, feed_ids=feed_ids, interval=args.interval,
                                max_requests=args.max_requests, dry_run=args.dry_run)
    print(json.dumps(asdict(result), sort_keys=True))  # Counts only; never keys or URLs.
    return 0 if result.status in {"ok", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
