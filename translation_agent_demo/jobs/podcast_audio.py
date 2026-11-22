"""Podcast audio positions; prints counts only, never keys, URLs or transcript text, and downloads no audio.

    python -m translation_agent_demo.jobs.podcast_audio backfill [--feed-ids 1,2] [--interval 0.5] [--dry-run]
        podcast_episode_audio from Podcast Index: one archive page per feed (/episodes/byfeedid, max 1000), then
        /episodes/byid for the rest. Requests are spaced by --interval; failures are skipped, 401/403 stops.
    python -m translation_agent_demo.jobs.podcast_audio anchors [--dry-run] [--processing-version V]
        transcript_time_anchors (migration 013) = exactly the anchors of every ready build of one processing
        version (the searchable one by default). Local and idempotent: unchanged documents are not written.
"""

import argparse
import json
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import UUID

from psycopg import Connection, Error as PsycopgError

from ..corpus.chunking import ChunkingSettings
from ..providers.podcast_index import PodcastIndexClient, PodcastIndexCredentials, PodcastIndexError
from ..storage.episode_audio import (
    SOURCE_INLINE_MARKER, SOURCE_SEGMENT_END, SOURCE_SEGMENT_START, SOURCES, audio_coverage, audio_from_episode,
    document_anchors, episodes_missing_audio, replace_document_anchors, save_episode_audio,
)
from ..storage.postgres import CorpusStorageError, PostgresSettings, connect_database

MAX_REQUESTS = 3000
MAX_RETRY_WAIT_SECONDS = 60
FEED_PAGE_MIN_MISSING = 3  # fewer missing episodes are cheaper as single lookups
BATCH = 50  # builds read at once


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


@dataclass
class AnchorRunResult:
    status: str = "ok"
    processing_version: str = ""
    dry_run: bool = False
    builds_scanned: int = 0
    documents_with_anchors: int = 0
    anchors: int = 0
    inline_markers: int = 0
    segment_starts: int = 0
    segment_end_estimates: int = 0
    documents_written: int = 0
    documents_cleared: int = 0
    documents_unchanged: int = 0


def backfill_audio(conn: Connection, client: PodcastIndexClient, *, feed_ids: tuple[int, ...] | None = None,
                   interval: float = 0.5, max_requests: int = MAX_REQUESTS, dry_run: bool = False,
                   sleep: Callable[[float], None] = time.sleep) -> AudioBackfillResult:
    if not 0 <= interval <= 10 or type(max_requests) is not int or not 1 <= max_requests <= MAX_REQUESTS:
        raise ValueError("interval must be 0-10 seconds and max_requests 1-3000.")
    result, errors = AudioBackfillResult(), Counter()
    missing = episodes_missing_audio(conn, feed_ids=feed_ids)
    result.missing_before, requests = len(missing), 0

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

    def more() -> bool:
        return requests < max_requests and result.status == "ok"

    if dry_run:
        result.status = "dry_run"
    else:
        wanted = {episode for _, episode in missing}
        for feed, count in sorted(Counter(feed for feed, _ in missing).items()):
            if count < FEED_PAGE_MIN_MISSING or not more():
                continue
            payload = request(lambda: client.historical_episodes_by_feed_id(feed))
            result.feed_requests += 1
            records = [] if payload is None else [audio for audio in map(audio_from_episode, payload["items"]) if audio]
            for offset in range(0, len(records), 1000):
                result.saved += save_episode_audio(conn, records[offset:offset + 1000])
            wanted -= {audio.episode_id for audio in records}
        for episode_id in sorted(wanted):
            if not more():
                break
            payload = request(lambda: client.episode_by_id(episode_id))
            result.episode_requests += 1
            if payload is None:
                continue
            if (audio := audio_from_episode(payload["episode"])) is None:
                result.skipped_no_enclosure += 1
            else:
                result.saved += save_episode_audio(conn, [audio])
        if result.status == "ok" and requests >= max_requests:
            result.status = "request_budget_reached"
    result.errors = dict(errors)
    result.with_audio, result.total_episodes = audio_coverage(conn)
    return result


def extract_time_anchors(conn: Connection, *, processing_version: str, dry_run: bool = False) -> AnchorRunResult:
    """Scan all ready builds of `processing_version`; write only documents whose anchors changed."""
    result = AnchorRunResult(processing_version=processing_version, dry_run=dry_run)
    has_table = conn.execute("SELECT to_regclass('public.transcript_time_anchors') IS NOT NULL").fetchone()[0]
    if not has_table and not dry_run:
        raise CorpusStorageError("Apply migration 013_transcript_time_anchors.sql first.")
    build_ids = [row[0] for row in conn.execute(
        "SELECT build_id FROM public.corpus_builds WHERE processing_version = %s AND status = 'ready' "
        "ORDER BY document_id", (processing_version,)).fetchall()]
    for start in range(0, len(build_ids), BATCH):
        batch = conn.execute("""
            SELECT b.build_id, b.document_id,
                   coalesce((SELECT jsonb_agg(jsonb_build_array(q.value ->> 'text', q.value ->> 'speaker') ORDER BY q.n)
                             FROM jsonb_array_elements(b.cues) WITH ORDINALITY AS q(value, n)), '[]'::jsonb)
            FROM public.corpus_builds AS b WHERE b.build_id = ANY(%s::uuid[]) ORDER BY b.document_id""",
                             (build_ids[start:start + BATCH],)).fetchall()
        rows = conn.execute(
            "SELECT document_id, char_offset, time_ms, source, build_id FROM public.transcript_time_anchors "
            "WHERE document_id = ANY(%s::uuid[])", ([build[1] for build in batch],)).fetchall() if has_table else []
        stored: dict[UUID, set[tuple[int, int, str, UUID]]] = {}
        for document_id, char, ms, source, build in rows:
            stored.setdefault(document_id, set()).add((int(char), int(ms), source, build))
        for build_id, document_id, cues in batch:
            anchors = document_anchors([(text or "", speaker) for text, speaker in cues])
            sources = [anchor.source for anchor in anchors]
            result.builds_scanned += 1
            result.anchors += len(anchors)
            result.inline_markers += sources.count(SOURCE_INLINE_MARKER)
            result.segment_starts += sources.count(SOURCE_SEGMENT_START)
            result.segment_end_estimates += sources.count(SOURCE_SEGMENT_END)
            result.documents_with_anchors += bool(anchors)
            wanted = {(a.char_offset, a.time_ms, a.source, build_id) for a in anchors}
            if {row for row in stored.get(document_id, ()) if row[2] in SOURCES or row[3] != build_id} == wanted:
                result.documents_unchanged += 1
                continue
            result.documents_written += bool(anchors)
            result.documents_cleared += not anchors
            if not dry_run:
                replace_document_anchors(conn, document_id, build_id, anchors)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    commands = parser.add_subparsers(dest="command", required=True)
    backfill = commands.add_parser("backfill", parents=[common], help="fill podcast_episode_audio")
    backfill.add_argument("--feed-ids", help="Optional comma-separated Podcast Index feed IDs")
    backfill.add_argument("--interval", type=float, default=0.5, help="Seconds between API requests")
    backfill.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    backfill.add_argument("--dry-run", action="store_true", help="Only count episodes missing audio")
    anchors = commands.add_parser("anchors", parents=[common], help="store transcript time anchors")
    anchors.add_argument("--dry-run", action="store_true", help="Extract and count; do not write the DB")
    anchors.add_argument("--processing-version", default=ChunkingSettings().processing_version,
                         help="Corpus build version whose cue texts define the offsets (default: the searchable one)")
    args = parser.parse_args(argv)
    if args.command == "backfill":
        feed_ids = tuple(int(value) for value in args.feed_ids.split(",")) if args.feed_ids else None
        client = PodcastIndexClient(PodcastIndexCredentials.from_environment(args.env_file))
        with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
            result = backfill_audio(conn, client, feed_ids=feed_ids, interval=args.interval,
                                    max_requests=args.max_requests, dry_run=args.dry_run)
    else:
        try:
            with connect_database(PostgresSettings.from_environment(args.env_file)) as conn:
                result = extract_time_anchors(conn, processing_version=args.processing_version, dry_run=args.dry_run)
        except (CorpusStorageError, PsycopgError) as error:
            failure = str(error) if isinstance(error, CorpusStorageError) else "Time anchor database operation failed."
            print(json.dumps({"status": "failed", "error": failure}))
            return 1
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.status in {"ok", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
