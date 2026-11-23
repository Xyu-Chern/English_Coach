"""Persist the bounded Podcast Index worker's schedule and selected episode queue.

Claims must use the idle autocommit connection returned by connect_database().
Their short transactions finish before the caller performs any network work.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .postgres import CorpusStorageError

MAX_CACHED_EPISODES = 200


@dataclass(frozen=True)
class SyncFeed:
    feed_id: int
    last_run_at: datetime | None
    next_run_at: datetime
    cooldown_until: datetime | None
    last_refresh_at: datetime | None
    next_refresh_at: datetime
    initial_scan_done: bool
    backfill_complete: bool


@dataclass(frozen=True)
class SyncItem:
    feed_id: int
    episode_id: int
    episode_data: dict[str, Any] = field(repr=False)
    attempts: int


def _identity(value: int) -> None:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError("Feed and episode IDs must be positive bigint integers.")


def _seconds(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("Scheduling intervals must be positive integer seconds.")


def _feed_ids(values: tuple[int, ...]) -> list[int]:
    if not isinstance(values, tuple):
        raise ValueError("feed_ids must be an explicit tuple of feed IDs.")
    for value in values:
        _identity(value)
    return list(dict.fromkeys(values))  # Preserve configured order without duplicates.


def _require_idle_connection(conn: psycopg.Connection) -> None:
    if not conn.autocommit or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise CorpusStorageError("Scheduling claims require an idle autocommit connection.")


def ensure_feeds(conn: psycopg.Connection, feed_ids: tuple[int, ...]) -> None:
    """Register configured feeds without bypassing an existing provider cooldown.

    New feeds inherit the longest recorded cooldown. Existing feeds retain their
    schedules, including longer backoff or retry delays.
    """
    ids = _feed_ids(feed_ids)
    if not ids:
        return
    try:
        with conn.transaction(), conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO public.podcast_sync_feeds (feed_id, cooldown_until, next_run_at)
                SELECT %s, max(cooldown_until), GREATEST(now(), max(cooldown_until))
                FROM public.podcast_sync_feeds
                ON CONFLICT (feed_id) DO NOTHING
                """,
                [(feed_id,) for feed_id in ids],
            )
    except psycopg.Error:
        raise CorpusStorageError("Could not register the configured podcast feeds.") from None


def claim_next_feed(
    conn: psycopg.Connection, feed_ids: tuple[int, ...], *, interval_seconds: int = 180,
) -> SyncFeed | None:
    """Claim one due configured feed and commit its next-run time before HTTP."""
    ids = _feed_ids(feed_ids)
    _seconds(interval_seconds)
    if not ids:
        return None
    _require_idle_connection(conn)
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                WITH selected AS (
                    SELECT feed_id FROM public.podcast_sync_feeds
                    WHERE feed_id = ANY(%s::bigint[]) AND next_run_at <= now()
                    ORDER BY last_run_at ASC NULLS FIRST,
                             array_position(%s::bigint[], feed_id)
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE public.podcast_sync_feeds f
                SET last_run_at = now(), next_run_at = now() + %s * interval '1 second'
                FROM selected WHERE f.feed_id = selected.feed_id
                RETURNING f.feed_id, f.last_run_at, f.next_run_at, f.cooldown_until, f.last_refresh_at,
                          f.next_refresh_at, f.initial_scan_done, f.backfill_complete
                """,
                (ids, ids, interval_seconds),
            ).fetchone()
        return SyncFeed(**row) if row is not None else None
    except psycopg.Error:
        raise CorpusStorageError("Could not claim a scheduled podcast feed.") from None


def count_stored_episodes(conn: psycopg.Connection, feed_id: int) -> int:
    """Count distinct episode sources with an actual stored transcript body."""
    _identity(feed_id)
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                SELECT count(*) AS count FROM public.podcast_sources s
                WHERE s.feed_id = %s AND EXISTS (
                    SELECT 1 FROM public.podcast_transcripts d WHERE d.source_key = s.source_key
                )
                """,
                (feed_id,),
            ).fetchone()
        return row["count"]
    except psycopg.Error:
        raise CorpusStorageError("Could not count stored podcast episodes.") from None


def _episode_snapshot(feed_id: int, episode: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(episode, dict) or episode.get("feedId") != feed_id:
        raise ValueError("Episode metadata must belong to the selected feed.")
    _identity(episode.get("id"))
    _identity(episode.get("feedId"))
    if not isinstance(episode.get("title"), str):
        raise ValueError("Episode title must be a string.")
    entries = episode.get("transcripts")
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        raise ValueError("Cached episodes need a selected transcript at index 0.")
    url = entries[0].get("url")
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        raise ValueError("The selected transcript URL must contain 1 to 2048 characters.")
    transcript_type = entries[0].get("type")
    for value in (episode.get("link"), episode.get("feedLanguage"), transcript_type):
        if value is not None and not isinstance(value, str):
            raise ValueError("Optional episode metadata must be strings or null.")
    language = episode.get("feedLanguage")
    if language is not None:
        language = language.strip() or None
        if language is not None and len(language) > 64:
            raise ValueError("Episode language must contain at most 64 characters.")
    published = episode.get("datePublished")
    if published is not None and (type(published) is not int or not 0 <= published < 2**63):
        raise ValueError("datePublished must be a nonnegative bigint or null.")
    snapshot = {
        "id": episode["id"], "feedId": feed_id, "title": episode["title"],
        "link": episode.get("link"), "feedLanguage": language,
        "datePublished": published, "transcripts": [{"url": url, "type": transcript_type}],
    }
    # Preserve only the fields the downloader uses; never cache the full API response.
    for value in (snapshot["title"], snapshot["link"], snapshot["feedLanguage"], url, transcript_type):
        if value is not None and "\x00" in value:
            raise ValueError("Episode metadata cannot contain null characters.")
    try:
        serialized = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    except UnicodeError:
        raise ValueError("Episode metadata must be valid UTF-8.") from None
    if len(serialized) > 16384:
        raise ValueError("Selected episode metadata exceeds 16 KiB.")
    return snapshot


def cache_episodes(
    conn: psycopg.Connection, feed_id: int, episodes: list[dict[str, Any]],
    *, refresh_seconds: int = 90 * 60,
) -> None:
    """Persist up to 200 selected references and the completed metadata refresh.

    An unchanged URL retains its status/retry count until its failed-attempt
    cooldown expires. A later bounded metadata refresh may then retry it, so
    delayed transcripts are not abandoned permanently. A changed URL gets a
    fresh attempt budget. The caller supplies selected transcript references.
    Existing source display metadata is refreshed without changing rights or bodies.
    """
    _identity(feed_id)
    _seconds(refresh_seconds)
    if not isinstance(episodes, list) or len(episodes) > MAX_CACHED_EPISODES:
        raise ValueError("episodes must be a list of at most 200 selected episodes.")
    snapshots = [_episode_snapshot(feed_id, episode) for episode in episodes]
    try:
        with conn.transaction(), conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO public.podcast_sync_items
                    (feed_id, episode_id, transcript_url, episode_data)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (feed_id, episode_id) DO UPDATE SET
                    transcript_url = EXCLUDED.transcript_url,
                    episode_data = EXCLUDED.episode_data,
                    status = CASE WHEN podcast_sync_items.transcript_url <> EXCLUDED.transcript_url
                        OR (podcast_sync_items.status = 'failed' AND podcast_sync_items.next_attempt_at <= now())
                        THEN 'pending' ELSE podcast_sync_items.status END,
                    attempts = CASE WHEN podcast_sync_items.transcript_url <> EXCLUDED.transcript_url
                        OR (podcast_sync_items.status = 'failed' AND podcast_sync_items.next_attempt_at <= now())
                        THEN 0 ELSE podcast_sync_items.attempts END,
                    next_attempt_at = CASE WHEN podcast_sync_items.transcript_url <> EXCLUDED.transcript_url
                        OR (podcast_sync_items.status = 'failed' AND podcast_sync_items.next_attempt_at <= now())
                        THEN now() ELSE podcast_sync_items.next_attempt_at END
                """,
                [(feed_id, item["id"], item["transcripts"][0]["url"], Jsonb(item)) for item in snapshots],
            )
            cursor.executemany(
                """
                UPDATE public.podcast_sources
                SET title = %s, episode_url = COALESCE(%s, episode_url),
                    language = COALESCE(%s, language), updated_at = now()
                WHERE feed_id = %s AND episode_id = %s
                """,
                [(item["title"], item["link"], item["feedLanguage"], feed_id, item["id"])
                 for item in snapshots],
            )
            cursor.execute(
                """
                UPDATE public.podcast_sync_feeds
                SET initial_scan_done = true, last_refresh_at = now(),
                    next_refresh_at = now() + %s * interval '1 second'
                WHERE feed_id = %s
                """,
                (refresh_seconds, feed_id),
            )
            if cursor.rowcount != 1:
                raise CorpusStorageError("The podcast feed was not registered before caching.")
    except (psycopg.Error, UnicodeError):
        raise CorpusStorageError("Could not cache the selected podcast episodes.") from None


def claim_next_item(
    conn: psycopg.Connection, feed_id: int, *, retry_seconds: int = 900,
) -> SyncItem | None:
    """Persist an attempt and its retry delay before returning one selected item."""
    _identity(feed_id)
    _seconds(retry_seconds)
    _require_idle_connection(conn)
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cursor:
            # A process can stop after recording its third attempt but before finish_item.
            cursor.execute(
                "UPDATE public.podcast_sync_items SET status = 'failed', "
                "next_attempt_at = GREATEST(next_attempt_at, now() + interval '1 day') "
                "WHERE feed_id = %s AND status = 'pending' AND attempts >= 3",
                (feed_id,),
            )
            row = cursor.execute(
                """
                WITH selected AS (
                    SELECT feed_id, episode_id FROM public.podcast_sync_items
                    WHERE feed_id = %s AND status = 'pending' AND attempts < 3
                      AND next_attempt_at <= now()
                    ORDER BY COALESCE((episode_data ->> 'datePublished')::bigint, 0) DESC,
                             episode_id DESC
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE public.podcast_sync_items item
                SET attempts = item.attempts + 1,
                    next_attempt_at = now() + %s * interval '1 second'
                FROM selected
                WHERE item.feed_id = selected.feed_id AND item.episode_id = selected.episode_id
                RETURNING item.feed_id, item.episode_id, item.episode_data, item.attempts
                """,
                (feed_id, retry_seconds),
            ).fetchone()
        return SyncItem(**row) if row is not None else None
    except psycopg.Error:
        raise CorpusStorageError("Could not claim a cached podcast episode.") from None


def finish_item(
    conn: psycopg.Connection, feed_id: int, episode_id: int,
    *, success: bool, retry_seconds: int = 900,
) -> None:
    """After three failures, wait at least a day and require fresh bounded metadata."""
    _identity(feed_id)
    _identity(episode_id)
    _seconds(retry_seconds)
    if type(success) is not bool:
        raise ValueError("success must be a boolean.")
    try:
        conn.execute(
            """
            UPDATE public.podcast_sync_items
            SET status = CASE WHEN %s THEN 'stored' WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END,
                next_attempt_at = now() + CASE WHEN NOT %s AND attempts >= 3
                    THEN GREATEST(%s, 86400) ELSE %s END * interval '1 second'
            WHERE feed_id = %s AND episode_id = %s
            """,
            (success, success, retry_seconds, retry_seconds, feed_id, episode_id),
        )
    except psycopg.Error:
        raise CorpusStorageError("Could not finish the podcast episode attempt.") from None


def remaining_items(conn: psycopg.Connection, feed_id: int) -> tuple[int, datetime | None]:
    """Return pending work, including retries whose delay has not expired yet."""
    _identity(feed_id)
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                SELECT count(*) AS count, min(next_attempt_at) AS next_attempt_at
                FROM public.podcast_sync_items
                WHERE feed_id = %s AND status = 'pending' AND attempts < 3
                """,
                (feed_id,),
            ).fetchone()
        return row["count"], row["next_attempt_at"]
    except psycopg.Error:
        raise CorpusStorageError("Could not inspect the remaining podcast work.") from None


def finish_backfill(
    conn: psycopg.Connection, feed_id: int, *, refresh_seconds: int = 90 * 60,
) -> None:
    """Finish the bounded backlog, retaining stored/failed entries for deduplication."""
    _identity(feed_id)
    _seconds(refresh_seconds)
    try:
        with conn.transaction():
            conn.execute(
                "UPDATE public.podcast_sync_items SET status = 'failed' "
                "WHERE feed_id = %s AND status = 'pending' AND attempts >= 3",
                (feed_id,),
            )
            conn.execute(
                "DELETE FROM public.podcast_sync_items WHERE feed_id = %s AND status = 'pending'",
                (feed_id,),
            )
            conn.execute(
                """
                UPDATE public.podcast_sync_feeds
                SET backfill_complete = true,
                    next_refresh_at = now() + %s * interval '1 second',
                    next_run_at = now() + %s * interval '1 second'
                WHERE feed_id = %s
                """,
                (refresh_seconds, refresh_seconds, feed_id),
            )
    except psycopg.Error:
        raise CorpusStorageError("Could not finish the bounded podcast backfill.") from None


def schedule_feed(conn: psycopg.Connection, feed_id: int, next_run_at: datetime) -> None:
    _identity(feed_id)
    if not isinstance(next_run_at, datetime) or next_run_at.tzinfo is None or next_run_at.utcoffset() is None:
        raise ValueError("next_run_at must be a timezone-aware datetime.")
    try:
        conn.execute(
            "UPDATE public.podcast_sync_feeds SET next_run_at = %s WHERE feed_id = %s",
            (next_run_at, feed_id),
        )
    except psycopg.Error:
        raise CorpusStorageError("Could not reschedule the podcast feed.") from None


def defer_all_feeds(conn: psycopg.Connection, *, seconds: int) -> None:
    """Record provider-wide backoff so both existing and newly added feeds wait.

    Neither the recorded cooldown nor any existing longer schedule is shortened.
    """
    _seconds(seconds)
    try:
        conn.execute(
            "UPDATE public.podcast_sync_feeds "
            "SET cooldown_until = GREATEST(cooldown_until, now() + %s * interval '1 second'), "
            "next_run_at = GREATEST(next_run_at, cooldown_until, now() + %s * interval '1 second')",
            (seconds, seconds),
        )
    except psycopg.Error:
        raise CorpusStorageError("Could not persist the Podcast Index cooldown.") from None
