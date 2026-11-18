"""Explicit, resumable archive acquisition with a fixed total corpus target.

This CLI supplements the small cron refresh. It never approves new sources,
embeds text, follows pagination, or fabricates Podcast Index episode identities.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from psycopg import Connection

from .podcast_sync import SYNC_LOCK_ID, RETRY_SECONDS, _episode_snapshot
from ..providers.changelog_transcripts import CHANGELOG_SHOWS, published_episode_numbers
from ..providers.podcast_index import PodcastIndexClient, PodcastIndexCredentials, PodcastIndexError
from ..providers.podcast_transcripts import PodcastTranscriptError, fetch_episode_transcript
from ..storage.corpus import save_transcript
from ..storage.podcast_sync import (
    cache_episodes, claim_next_item, defer_all_feeds, ensure_feeds, finish_item,
)
from ..storage.postgres import PostgresSettings, connect_database
from ..storage.source_reviews import approved_feed_ids, transcript_url_is_approved

MAX_TARGET = 2000  # Raised from 1000 to widen the approved-show corpus; still bounded.


@dataclass
class BackfillResult:
    status: str = "ok"
    target: int = 0
    existing: int = 0
    candidates: int = 0
    queued: int = 0
    attempted: int = 0
    downloaded: int = 0
    failed: int = 0
    total_stored: int = 0
    per_feed: dict[int, int] = field(default_factory=dict)
    metadata_counts: dict[int, dict[str, int]] = field(default_factory=dict)


def _stored(conn: Connection, feed_ids: tuple[int, ...]) -> dict[str, int]:
    """Count attributable source URLs, not transcript revisions or chunk rows."""
    rows = conn.execute(
        """SELECT DISTINCT s.last_download_url, s.feed_id
           FROM public.podcast_sources s
           JOIN public.podcast_feed_reviews r USING (feed_id)
           WHERE s.feed_id = ANY(%s::bigint[]) AND s.rights_status = 'approved'
             AND r.status = 'approved'
             AND public.transcript_url_matches_review_scope(s.last_download_url, r.transcript_url_prefix)
             AND EXISTS (SELECT 1 FROM public.podcast_transcripts t WHERE t.source_key=s.source_key)""",
        (list(feed_ids),),
    ).fetchall()
    return {url: feed_id for url, feed_id in rows}


def select_candidates(
    candidates: dict[int, list[dict]], existing: dict[str, int], *, target: int,
) -> dict[int, list[dict]]:
    """Balance shows while deduplicating canonical transcript URLs across IDs."""
    chosen = {feed: [] for feed in candidates}
    counts = {feed: sum(value == feed for value in existing.values()) for feed in candidates}
    seen = set(existing)
    positions = dict.fromkeys(candidates, 0)
    while len(seen) < target:
        available = [feed for feed in candidates if positions[feed] < len(candidates[feed])]
        if not available:
            break
        feed = min(available, key=lambda item: (counts[item], item))
        episode = candidates[feed][positions[feed]]
        positions[feed] += 1
        url = episode["transcripts"][0]["url"]
        if url in seen:
            continue
        chosen[feed].append(episode)
        seen.add(url)
        counts[feed] += 1
    return chosen


def backfill_corpus(
    conn: Connection, client: PodcastIndexClient, feed_ids: tuple[int, ...],
    *, target: int = 1000, concurrency: int = 4, max_downloads: int = 1000,
) -> BackfillResult:
    """One archive page and catalog per show; <=MAX_TARGET attempts, <=4 simultaneous GETs.

    Queue claims commit before HTTP. The existing durable retry budget is three
    attempts with cooldowns. A restart reuses saved bodies and pending queue state.
    The shared sync lock prevents the cron collector exceeding the total target
    during this run. A paused process does not leave a long database transaction.
    """
    if (not isinstance(feed_ids, tuple) or not 1 <= len(feed_ids) <= 4
            or len(set(feed_ids)) != len(feed_ids)
            or any(type(feed) is not int or feed not in CHANGELOG_SHOWS for feed in feed_ids)):
        raise ValueError("Select 1–4 distinct explicitly mapped Changelog feed IDs.")
    for value, maximum in ((target, MAX_TARGET), (max_downloads, MAX_TARGET), (concurrency, 4)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError("Invalid bounded target, download budget, or concurrency.")
    if not conn.autocommit:
        raise ValueError("Backfill requires an autocommit connection.")
    if not conn.execute("SELECT pg_try_advisory_lock(%s)", (SYNC_LOCK_ID,)).fetchone()[0]:
        return BackfillResult(status="already_running", target=target)
    result = BackfillResult(target=target)
    try:
        if approved_feed_ids(conn, feed_ids) != feed_ids:
            raise ValueError("Every selected feed needs an explicit transcript-directory review.")
        ensure_feeds(conn, feed_ids)
        cooldown = conn.execute(
            "SELECT max(cooldown_until) FROM public.podcast_sync_feeds WHERE feed_id=ANY(%s::bigint[])",
            (list(feed_ids),),
        ).fetchone()[0]
        if cooldown is not None and cooldown > datetime.now(timezone.utc):
            result.status = "cooldown"
            return result
        existing = _stored(conn, feed_ids)
        result.existing = len(existing)
        candidates = {}
        if len(existing) < target:
            for feed in feed_ids:
                if feed not in approved_feed_ids(conn, (feed,)):
                    result.status = "approval_withdrawn"
                    return result
                published = published_episode_numbers(feed)
                try:
                    payload = client.historical_episodes_by_feed_id(feed)
                except PodcastIndexError as error:
                    defer_all_feeds(conn, seconds=max(21600 if error.status_code in {401, 403} else RETRY_SECONDS,
                                                     error.retry_after_seconds or 0))
                    raise
                snapshots = []
                for episode in payload["items"]:
                    try:
                        snapshots.append(_episode_snapshot(episode, published_changelog_episodes=published))
                    except (PodcastTranscriptError, ValueError, UnicodeError):
                        continue
                snapshots.sort(key=lambda item: (-item["datePublished"], item["id"]))
                candidates[feed] = snapshots
                result.metadata_counts[feed] = {"catalog": len(published), "api": len(payload["items"]),
                                               "matched": len(snapshots)}
            result.candidates = len({e["transcripts"][0]["url"] for values in candidates.values() for e in values})
            selected = select_candidates(candidates, existing, target=target)
            for feed, episodes in selected.items():
                for offset in range(0, len(episodes), 200):
                    cache_episodes(conn, feed, episodes[offset:offset + 200])
                result.queued += len(episodes)
        stopped = False
        claims = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            while len(existing) < target and result.attempted < max_downloads and claims < MAX_TARGET:
                batch = []
                for _ in range(min(concurrency, target - len(existing), max_downloads - result.attempted)):
                    item = None
                    for feed in sorted(feed_ids, key=lambda value: sum(v == value for v in existing.values())):
                        if feed not in approved_feed_ids(conn, (feed,)):
                            result.status, stopped = "approval_withdrawn", True
                            break
                        item = claim_next_item(conn, feed, retry_seconds=RETRY_SECONDS)
                        if item is not None:
                            break
                    if stopped or item is None:
                        break
                    claims += 1
                    episode = item.episode_data
                    url = episode["transcripts"][0]["url"]
                    if url in existing:
                        finish_item(conn, item.feed_id, item.episode_id, success=True)
                        continue
                    if not transcript_url_is_approved(conn, item.feed_id, url):
                        finish_item(conn, item.feed_id, item.episode_id, success=False, retry_seconds=86400)
                        continue
                    result.attempted += 1
                    batch.append((item, pool.submit(fetch_episode_transcript, episode)))
                for item, future in batch:
                    try:
                        transcript = future.result()
                        with conn.transaction():
                            save_transcript(conn, transcript, language=item.episode_data.get("feedLanguage"))
                            finish_item(conn, item.feed_id, item.episode_id, success=True)
                        # Re-read approval on storage; a concurrent revocation cannot count as eligible.
                        existing = _stored(conn, feed_ids)
                        result.downloaded += 1
                    except (PodcastTranscriptError, ValueError) as error:
                        result.failed += 1
                        delay = max(RETRY_SECONDS * 2 ** (item.attempts - 1),
                                    getattr(error, "retry_after_seconds", None) or 0)
                        finish_item(conn, item.feed_id, item.episode_id, success=False, retry_seconds=delay)
                        if getattr(error, "status_code", None) in {429, 503}:
                            defer_all_feeds(conn, seconds=delay)
                            stopped = True
                if stopped or not batch:
                    break
        existing = _stored(conn, feed_ids)
        result.total_stored = len(existing)
        result.per_feed = {feed: sum(value == feed for value in existing.values()) for feed in feed_ids}
        if result.total_stored < target and result.status == "ok":
            result.status = "partial" if result.failed or result.attempted >= max_downloads else "exhausted_or_waiting"
        return result
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SYNC_LOCK_ID,))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-ids", required=True, help="Explicit reviewed Podcast Index feed IDs")
    parser.add_argument("--target", type=int, default=1000, help=f"Total approved unique transcripts, at most {MAX_TARGET}")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-downloads", type=int, default=1000)
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    client = PodcastIndexClient(PodcastIndexCredentials.from_environment(args.env_file))
    with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
        result = backfill_corpus(conn, client, tuple(int(value) for value in args.feed_ids.split(",")),
                                 target=args.target, concurrency=args.concurrency, max_downloads=args.max_downloads)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.total_stored >= args.target else 1


if __name__ == "__main__":
    raise SystemExit(main())
