"""Resume one selected feed per cron tick using PostgreSQL progress records.

The initial pass inspects at most 200 episodes to acquire up to 100 transcripts.
Later refreshes revisit a bounded recent window, including delayed captions.
No feed discovery, index traversal, or same-URL body-change polling happens here.
"""

import json
import os
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from psycopg import Connection, Error as PsycopgError

from ..config import _read_env_file
from ..providers.podcast_index import PodcastIndexClient, PodcastIndexCredentials, PodcastIndexError
from ..providers.changelog_transcripts import (
    CHANGELOG_SHOWS, ChangelogTranscriptCatalogError, published_episode_numbers,
)
from ..providers.podcast_transcripts import (
    PodcastTranscriptError,
    _select_transcript,
    fetch_episode_transcript,
    select_corpus_transcript,
)
from ..storage.corpus import has_transcript, save_transcript
from ..storage.episode_audio import audio_from_episode, save_episode_audio
from ..storage.podcast_sync import (
    cache_episodes,
    claim_next_feed,
    claim_next_item,
    count_stored_episodes,
    defer_all_feeds,
    ensure_feeds,
    finish_backfill,
    finish_item,
    remaining_items,
    schedule_feed,
)
from ..storage.postgres import CorpusStorageError, PostgresSettings, connect_database
from ..storage.source_reviews import approved_feed_ids, transcript_url_is_approved

MAX_FEEDS = 30
INITIAL_TRANSCRIPT_TARGET = 100  # Unique episodes, not transcript body versions.
EPISODES_PER_REFRESH = 200  # A fixed window; never paginate to fill a shortfall.
MAX_DOWNLOADS = 10  # Failed downloads also consume this per-run budget.
TICK_SECONDS = 180
REFRESH_SECONDS = 90 * 60  # One rotation of 30 feeds at the three-minute tick.
AUTH_COOLDOWN_SECONDS = 6 * 60 * 60
RETRY_SECONDS = 900
RECENT_OVERLAP_DAYS = 7
RUN_BUDGET_SECONDS = 150  # Stop starting requests; an in-flight request may take longer.
SYNC_LOCK_ID = 1162036035


class SyncConfigurationError(Exception):
    """Invalid job settings; messages contain setting names, never their values."""


@dataclass(frozen=True)
class SyncSettings:
    enabled: bool
    feed_ids: tuple[int, ...]

    @classmethod
    def from_environment(cls) -> "SyncSettings":
        try:
            values = _read_env_file(Path(__file__).resolve().parents[1] / ".env")
        except (OSError, UnicodeError):
            raise SyncConfigurationError("Could not read the sync environment file.") from None
        values.update(os.environ)
        enabled = values.get("PODCAST_SYNC_ENABLED", "false").strip().lower()
        if enabled not in {"true", "false"}:
            raise SyncConfigurationError("PODCAST_SYNC_ENABLED must be true or false.")
        if enabled == "false":
            return cls(False, ())
        raw_ids = ",".join(value.strip() for value in values.get("PODCAST_SYNC_FEED_IDS", "").split(","))
        if not raw_ids or len(raw_ids) > MAX_FEEDS * 20:
            raise SyncConfigurationError(
                f"Set PODCAST_SYNC_FEED_IDS to 1–{MAX_FEEDS} comma-separated feed IDs."
            )
        try:
            feed_ids = tuple(int(value) for value in raw_ids.split(","))
        except ValueError:
            raise SyncConfigurationError("PODCAST_SYNC_FEED_IDS must contain positive integers.") from None
        _validate_feed_ids(feed_ids)
        return cls(True, feed_ids)


@dataclass
class SyncResult:
    status: Literal["ok", "idle", "failed", "partial_failure", "already_running", "disabled"] = "ok"
    feed_id: int | None = None
    eligible_feeds: int = 0
    skipped_unapproved_feeds: int = 0
    idle_reason: Literal["unapproved_feeds", "not_due", "approval_withdrawn"] | None = None
    api_calls: int = 0
    catalog_calls: int = 0
    catalog_failures: int = 0
    episodes_seen: int = 0
    skipped_unusable_metadata: int = 0
    skipped_existing: int = 0
    download_attempts: int = 0
    downloaded: int = 0
    inserted: int = 0
    unchanged: int = 0
    download_failures: int = 0
    api_failures: int = 0
    pending: int = 0
    stored_episodes: int = 0
    backfill_complete: bool = False
    download_limit_reached: bool = False


def _validate_feed_ids(feed_ids: tuple[int, ...]) -> None:
    if (
        not isinstance(feed_ids, tuple)
        or not 1 <= len(feed_ids) <= MAX_FEEDS
        or any(type(value) is not int or not 0 < value <= 2**63 - 1 for value in feed_ids)
        or len(set(feed_ids)) != len(feed_ids)
    ):
        raise SyncConfigurationError(f"Provide 1–{MAX_FEEDS} distinct positive integer feed IDs.")


def _episode_snapshot(
    episode: dict[str, Any], *, published_changelog_episodes: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Keep only the selected transcript and fields needed to save its provenance."""
    url, declared_type = select_corpus_transcript(episode, published_changelog_episodes=published_changelog_episodes)
    if not 1 <= len(url) <= 2048:
        raise ValueError("Invalid selected transcript URL length.")
    for key in ("id", "feedId"):
        if type(episode.get(key)) is not int or not 0 < episode[key] <= 2**63 - 1:
            raise ValueError("Invalid episode identity.")
    title, link, language = episode.get("title"), episode.get("link"), episode.get("feedLanguage")
    if not isinstance(title, str) or (link is not None and not isinstance(link, str)):
        raise ValueError("Invalid episode title or link.")
    if language is not None:
        if not isinstance(language, str) or len(language.strip()) > 64:
            raise ValueError("Invalid episode language.")
        language = language.strip() or None
    for value in (url, declared_type, title, link, language):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("Episode metadata cannot contain null characters.")
    published = episode.get("datePublished")
    snapshot = {
        "id": episode["id"], "feedId": episode["feedId"], "title": title,
        "link": link, "feedLanguage": language,
        "datePublished": published if type(published) is int and 0 <= published <= 2**63 - 1 else 0,
        "transcripts": [{"url": url, "type": declared_type}],
    }
    if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > 16384:
        raise ValueError("Selected episode metadata exceeds 16 KiB.")
    return snapshot


def _save_audio(conn: Connection, episodes: list[dict[str, Any]]) -> None:
    """Keep enclosure URLs from the page already fetched; never blocks transcript sync."""
    try:
        save_episode_audio(conn, [audio for audio in map(audio_from_episode, episodes) if audio])
    except (CorpusStorageError, ValueError):
        pass  # E.g. migration 010 not yet applied; the audio backfill CLI can fill later.


def sync_feeds(conn: Connection, client: PodcastIndexClient, feed_ids: tuple[int, ...]) -> SyncResult:
    """Resume one due feed from the explicitly reviewed configured subscriptions.

    At most one Podcast Index request and ten publisher downloads occur. Changelog
    additionally reads one public repository directory at metadata refresh time.
    Metadata is cached across ticks. Claims and attempts are committed before HTTP;
    a session lock prevents overlap without holding a transaction during HTTP.
    Every next HTTP request checks feed approval again; an already in-flight
    request cannot be cancelled. Storage separately rechecks before inheritance.
    """
    _validate_feed_ids(feed_ids)
    if not conn.autocommit:
        raise SyncConfigurationError("Podcast sync requires an autocommit database connection.")
    locked = conn.execute("SELECT pg_try_advisory_lock(%s)", (SYNC_LOCK_ID,)).fetchone()[0]
    if not locked:
        return SyncResult(status="already_running")

    result = SyncResult()
    started_at = time.monotonic()
    try:
        eligible = approved_feed_ids(conn, feed_ids)
        result.eligible_feeds = len(eligible)
        result.skipped_unapproved_feeds = len(feed_ids) - len(eligible)
        if not eligible:
            result.status = "idle"
            result.idle_reason = "unapproved_feeds"
            return result
        ensure_feeds(conn, eligible)
        state = claim_next_feed(conn, eligible, interval_seconds=TICK_SECONDS)
        if state is None:
            result.status = "idle"
            result.idle_reason = "not_due"
            return result
        feed_id = state.feed_id
        result.feed_id = feed_id
        result.stored_episodes = count_stored_episodes(conn, feed_id)
        result.backfill_complete = state.backfill_complete
        if not state.backfill_complete and result.stored_episodes >= INITIAL_TRANSCRIPT_TARGET:
            finish_backfill(conn, feed_id, refresh_seconds=REFRESH_SECONDS)
            result.backfill_complete = True
            return result

        now = datetime.now(timezone.utc)
        if not state.initial_scan_done or (state.backfill_complete and state.next_refresh_at <= now):
            if not approved_feed_ids(conn, (feed_id,)):
                result.status = "idle"
                result.idle_reason = "approval_withdrawn"
                return result
            # Revisit seven days so captions attached after episode publication can appear.
            # This is a bounded window, not a guarantee of finding every historical change.
            since = None
            if state.backfill_complete and state.last_refresh_at is not None:
                since = max(0, int((state.last_refresh_at - timedelta(days=RECENT_OVERLAP_DAYS)).timestamp()))
            result.api_calls = 1
            try:
                payload = client.episodes_by_feed_id(feed_id, limit=EPISODES_PER_REFRESH, since=since)
            except PodcastIndexError as exc:
                result.api_failures = 1
                result.status = "failed"
                delay = AUTH_COOLDOWN_SECONDS if exc.status_code in {401, 403} else RETRY_SECONDS
                defer_all_feeds(conn, seconds=max(delay, exc.retry_after_seconds or 0))
                return result  # Persist provider-wide cooldown across cron/container restarts.
            published = None
            if feed_id in CHANGELOG_SHOWS:
                result.catalog_calls = 1
                try:
                    published = published_episode_numbers(feed_id)
                except ChangelogTranscriptCatalogError:
                    result.status, result.catalog_failures = "failed", 1
                    schedule_feed(conn, feed_id, now + timedelta(seconds=RETRY_SECONDS))
                    return result
            snapshots = []
            for episode in payload["items"]:
                result.episodes_seen += 1
                try:
                    snapshots.append(_episode_snapshot(episode, published_changelog_episodes=published))
                except (PodcastTranscriptError, ValueError, UnicodeError):
                    result.skipped_unusable_metadata += 1
            cache_episodes(conn, feed_id, snapshots, refresh_seconds=REFRESH_SECONDS)
            _save_audio(conn, payload["items"])
            now = datetime.now(timezone.utc)
            state = replace(state, initial_scan_done=True, last_refresh_at=now,
                            next_refresh_at=now + timedelta(seconds=REFRESH_SECONDS))

        while result.download_attempts < MAX_DOWNLOADS:
            if time.monotonic() - started_at >= RUN_BUDGET_SECONDS:
                break
            if not state.backfill_complete and result.stored_episodes >= INITIAL_TRANSCRIPT_TARGET:
                break
            if not approved_feed_ids(conn, (feed_id,)):
                result.status = "idle"
                result.idle_reason = "approval_withdrawn"
                return result
            item = claim_next_item(conn, feed_id, retry_seconds=RETRY_SECONDS)
            if item is None:
                break
            episode = item.episode_data
            url, _ = _select_transcript(episode, 0)
            if not transcript_url_is_approved(conn, feed_id, url):
                result.skipped_unusable_metadata += 1
                finish_item(conn, feed_id, item.episode_id, success=False, retry_seconds=86400)
                continue  # Old cached references cannot widen the reviewed source scope.
            if has_transcript(conn, feed_id, item.episode_id, url):
                finish_item(conn, feed_id, item.episode_id, success=True)
                result.skipped_existing += 1
                continue

            result.download_attempts += 1
            try:
                transcript = fetch_episode_transcript(episode, transcript_index=0)
                # Commit the body and its completed item together; retrying cannot duplicate it.
                with conn.transaction():
                    saved = save_transcript(conn, transcript, language=episode.get("feedLanguage"))
                    finish_item(conn, feed_id, item.episode_id, success=True)
            except (PodcastTranscriptError, ValueError) as exc:
                result.download_failures += 1
                result.status = "partial_failure"
                delay = max(RETRY_SECONDS * 2 ** (item.attempts - 1),
                            getattr(exc, "retry_after_seconds", None) or 0)
                finish_item(conn, feed_id, item.episode_id, success=False, retry_seconds=delay)
                if getattr(exc, "status_code", None) in {429, 503}:
                    defer_all_feeds(conn, seconds=delay)
                    result.pending, _ = remaining_items(conn, feed_id)
                    return result
                continue
            result.downloaded += 1
            result.inserted += int(saved.created)
            result.unchanged += int(not saved.created)
            result.stored_episodes = count_stored_episodes(conn, feed_id)

        result.pending, next_attempt_at = remaining_items(conn, feed_id)
        result.download_limit_reached = result.download_attempts >= MAX_DOWNLOADS and result.pending > 0
        if not state.backfill_complete and (
            result.stored_episodes >= INITIAL_TRANSCRIPT_TARGET or result.pending == 0
        ):
            # A shortfall does not trigger wider traversal. Refresh recent episodes every 90 minutes.
            finish_backfill(conn, feed_id, refresh_seconds=REFRESH_SECONDS)
            result.backfill_complete = True
            result.pending = 0
        else:
            due_times = [next_attempt_at] if next_attempt_at is not None else []
            if state.backfill_complete:
                due_times.append(state.next_refresh_at)
            # Align ready work to cron's next boundary. Adding 180 seconds after a
            # download finishes would skip the next tick and silently double the gap.
            next_tick = datetime.fromtimestamp(
                (int(datetime.now(timezone.utc).timestamp()) // TICK_SECONDS + 1) * TICK_SECONDS,
                tz=timezone.utc,
            )
            schedule_feed(conn, feed_id, max(next_tick, min(due_times)))
        return result
    finally:
        if not conn.closed:
            conn.execute("SELECT pg_advisory_unlock(%s)", (SYNC_LOCK_ID,))


def run_once() -> SyncResult:
    """Run one cron invocation; PostgreSQL retains the next feed and pending work."""
    settings = SyncSettings.from_environment()
    if not settings.enabled:
        return SyncResult(status="disabled")
    client = PodcastIndexClient(PodcastIndexCredentials.from_environment())
    with connect_database(PostgresSettings.from_environment()) as conn:
        return sync_feeds(conn, client, settings.feed_ids)


def _main() -> int:
    try:
        result = run_once()
    except (SyncConfigurationError, PodcastIndexError, ValueError):
        print(json.dumps({"status": "failed", "error": "Invalid podcast sync settings or input metadata."}))
        return 1
    except (CorpusStorageError, PsycopgError):
        print(json.dumps({"status": "failed", "error": "Podcast sync database operation failed."}))
        return 1
    print(json.dumps(asdict(result)))  # Feed identity and counts; never keys, URLs or body text.
    return int(result.status in {"failed", "partial_failure"})


if __name__ == "__main__":
    raise SystemExit(_main())
