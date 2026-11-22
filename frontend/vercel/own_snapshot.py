"""Our own Vercel package, built beside package.py (whose default build is unchanged) from the local corpus.

The corpus is the approved Changelog-family chunks of the active local corpus build (DATABASE_URL in
translation_agent_demo/.env), in the files coach.PublishedCorpus reads:
- corpus/passages.json: CorpusSearchHit records with attribution, license and audio fields (stored cue timing, else
  interpolated between the transcript's time markers, else character position x episode duration)
- corpus/vectors.npy: the chunk texts embedded with the deploy's own MiniLM encoder, float16 at 384 dimensions
  (coach.py treats the missing columns as the encoder's zero padding to 1536)
- corpus/alignments.json: the saved speech-recognition alignments (GET /api/audio/alignment)
- corpus/manifest.json: what was selected and why
Only sources with rights_status approved, an approved feed review covering the transcript URL and the review's license
are exported. Over the size budget, whole episodes are kept: the most cited in --run's answers first, then the newest.

    python -m frontend.vercel.own_snapshot align --run DIR [--run DIR] [--model base.en]   re-runnable: skips saved
    python -m frontend.vercel.own_snapshot package --run DIR --admin-data FILE [--out DIR] [--max-mb 500]
"""

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import UUID

import numpy as np

from frontend import admin_data
from frontend.vercel import package
from translation_agent_demo.agents.contracts import CorpusSearchHit, SearchSpan
from translation_agent_demo.providers.local_embeddings import DIRECTORY, MODEL
from translation_agent_demo.storage.episode_audio import MAX_LOAD, anchors_for_builds, estimate_clip
from translation_agent_demo.storage.retrieval import _display_url

ROOT = package.ROOT
DEFAULT_OUT = ROOT / "frontend/.local/vercel-phrase-room-own"
CACHE = ROOT / "frontend/.local/own-snapshot-cache"  # embeddings and the measured dependencies, reused by reruns
ENTRY = "frontend/vercel/own_index.py"  # becomes api/search.py
FAMILY_PREFIX = "https://raw.githubusercontent.com/thechangelog/transcripts/"  # the reviewed Changelog feeds
STORED_DIMENSIONS, DIMENSIONS = 384, 1536  # MiniLM's width; the profile's (zero padded, as the encoder returns)
# Vercel's limit for a Python function, uncompressed with its dependencies (250 MB for other runtimes); a margin is
# kept for the runtime's own files.
MAX_MB, MARGIN_MB = 500, 20
DEPS_PLATFORM, DEPS_PYTHON = "x86_64-manylinux_2_28", "3.12"
# Left out of the function: local tools and the Responses provider's SDK (15 MB). anthropic stays: this
# deployment uses Claude (LLM_PROVIDER=responses would need openai back).
LOCAL_ONLY = ("-r", "huggingface-hub==", "faster-whisper==", "openai==")
ENCODER_FILES = ("tokenizer.json", "onnx/model.onnx")
BATCH = 32  # LocalEmbeddings' largest batch


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- reading the local corpus -------------------------------------------------------------------------------------

def database():
    from translation_agent_demo.storage.postgres import PostgresSettings
    return replace(PostgresSettings.from_environment(), statement_timeout_ms=600_000)


def connect():
    from translation_agent_demo.storage.postgres import connect_database
    return connect_database(database())


ACTIVE_VERSION_SQL = """
    SELECT b.processing_version FROM public.corpus_builds AS b JOIN public.corpus_embedding_builds USING (build_id)
    WHERE b.status = 'ready' GROUP BY 1 ORDER BY max(b.created_at) DESC LIMIT 1"""
# The latest complete build of each approved source, as storage/retrieval.py's _LATEST_COMPLETE picks it.
CHUNKS_SQL = """
    WITH latest AS (
        SELECT DISTINCT ON (s.source_key) b.build_id, b.document_id, s.source_key
        FROM public.corpus_builds AS b JOIN public.corpus_embedding_builds AS done USING (build_id)
        JOIN public.podcast_transcripts AS d USING (document_id) JOIN public.podcast_sources AS s USING (source_key)
        JOIN public.podcast_feed_reviews AS r ON r.feed_id = s.feed_id
        WHERE b.status = 'ready' AND b.processing_version = %(version)s AND s.source_key LIKE 'podcast_index:%%'
          AND s.rights_status = 'approved' AND r.status = 'approved' AND r.transcript_url_prefix LIKE %(family)s
          AND public.transcript_url_matches_review_scope(d.download_url, r.transcript_url_prefix)
        ORDER BY s.source_key, d.last_observed_at DESC, d.document_id DESC)
    SELECT c.chunk_id, c.build_id, l.document_id, s.source_key, s.feed_id, s.episode_id, s.title AS episode_title,
           s.episode_url, d.download_url AS transcript_url, s.language, c.text, c.start_ms, c.end_ms, c.spans,
           s.review_url AS rights_review_url, s.license_evidence #>> '{feed_review,license_id}' AS license_id,
           s.license_evidence #>> '{feed_review,evidence,license_url}' AS license_url,
           s.license_evidence #>> '{feed_review,evidence,attribution}' AS attribution,
           r.license_id AS review_license_id, s.rights_status, r.status AS review_status,
           (i.episode_data ->> 'datePublished')::bigint AS published
    FROM latest AS l JOIN public.corpus_chunks AS c USING (build_id)
    JOIN public.podcast_transcripts AS d ON d.document_id = l.document_id
    JOIN public.podcast_sources AS s ON s.source_key = l.source_key
    JOIN public.podcast_feed_reviews AS r ON r.feed_id = s.feed_id
    LEFT JOIN public.podcast_sync_items AS i ON i.feed_id = s.feed_id AND i.episode_id = s.episode_id
    ORDER BY c.chunk_id"""
CUES_SQL = """
    SELECT b.build_id, array_agg(length(q.value ->> 'text') ORDER BY q.n), array_agg(q.value ->> 'speaker' ORDER BY q.n)
    FROM public.corpus_builds AS b CROSS JOIN LATERAL jsonb_array_elements(b.cues) WITH ORDINALITY AS q(value, n)
    WHERE b.build_id = ANY(%s::uuid[]) GROUP BY b.build_id"""
AUDIO_SQL = """SELECT episode_id, feed_id, enclosure_url, duration_s FROM public.podcast_episode_audio
               WHERE episode_id = ANY(%s::bigint[])"""
ALIGNMENTS_SQL = """
    SELECT chunk_id, audio_url, window_start_ms, words, cues, method, model FROM public.chunk_audio_alignment
    WHERE chunk_id = ANY(%s::uuid[])"""


def load_corpus(conn) -> dict:
    """Everything the export needs from the database, as plain values (tests pass the same dict)."""
    from psycopg.rows import dict_row

    version = conn.execute(ACTIVE_VERSION_SQL).fetchone()
    if version is None:
        raise SystemExit("No ready corpus build with completed embeddings in the local database.")
    with conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(CHUNKS_SQL, {"version": version[0], "family": FAMILY_PREFIX + "%"}).fetchall()
    builds = sorted({row["build_id"] for row in rows})
    cues = {build: (lengths, speakers) for build, lengths, speakers in conn.execute(CUES_SQL, (builds,))}
    episodes = sorted({row["episode_id"] for row in rows})
    audio = {r[0]: {"feed_id": r[1], "enclosure_url": r[2], "duration_s": r[3]}
             for r in conn.execute(AUDIO_SQL, (episodes,))}
    anchors = {}
    for start in range(0, len(builds), MAX_LOAD):  # anchors_for_builds reads at most MAX_LOAD builds at once
        anchors.update(anchors_for_builds(conn, builds[start:start + MAX_LOAD]))
    exists = conn.execute("SELECT to_regclass('public.chunk_audio_alignment') IS NOT NULL").fetchone()[0]
    alignments = {}
    if exists:
        for row in conn.execute(ALIGNMENTS_SQL, ([row["chunk_id"] for row in rows],)):
            alignments[row[0]] = dict(zip(("audio_url", "window_start_ms", "words", "cues", "method", "model"),
                                          row[1:]))
    return {"processing_version": version[0], "rows": rows, "cues": cues, "audio": audio, "anchors": anchors,
            "alignments": alignments}


# --- passages -----------------------------------------------------------------------------------------------------

def approved(row) -> bool:
    """The rights checks again, on the row: approved source and review, the review's license, an attribution."""
    return (row["rights_status"] == "approved" and row["review_status"] == "approved"
            and row["license_id"] is not None and row["license_id"] == row["review_license_id"]
            and bool(row["attribution"]))


def position(row, lengths) -> tuple[int, int, int]:
    """(char_start, char_end, char_total) of the chunk in its build's document, as AUDIO_POSITION_SQL counts."""
    spans = row["spans"]
    first, last = spans[0], spans[-1]
    return (sum(lengths[:first["cue_index"]]) + first["start_char"],
            sum(lengths[:last["cue_index"]]) + last["end_char"], sum(lengths))


def build_hit(row, corpus) -> tuple[dict, str]:
    """One passage record (CorpusSearchHit, similarity 0) and where its audio position comes from."""
    lengths, speakers = corpus["cues"][row["build_id"]]
    audio = corpus["audio"].get(row["episode_id"])
    url = _display_url(audio["enclosure_url"]) if audio and audio["feed_id"] in (None, row["feed_id"]) else None
    anchors = corpus["anchors"].get(row["build_id"])
    char_start, char_end, char_total = position(row, lengths)
    clip = estimate_clip(url, start_ms=row["start_ms"], end_ms=row["end_ms"], char_start=char_start,
                         char_end=char_end, char_total=char_total, duration_s=audio and audio["duration_s"],
                         anchors=anchors)
    saved = corpus["alignments"].get(row["chunk_id"])
    if url is None:
        source = "none"
    elif saved is not None and saved["audio_url"] == url:
        source = saved["method"]  # asr (or stored): exact, served by /api/audio/alignment
    elif row["start_ms"] is not None:
        source = "cue_timing"
    elif anchors and clip.audio_start_ms is not None:
        source = "anchors"
    else:
        source = "duration" if clip.audio_start_ms is not None else "url_only"
    hit = CorpusSearchHit(
        chunk_id=row["chunk_id"], document_id=row["document_id"], build_id=row["build_id"],
        source_key=row["source_key"], feed_id=row["feed_id"], episode_id=row["episode_id"],
        episode_title=row["episode_title"], episode_url=_display_url(row["episode_url"]),
        transcript_url=_display_url(row["transcript_url"]), language=row["language"], text=row["text"],
        similarity=0.0, start_ms=row["start_ms"], end_ms=row["end_ms"],
        speakers=tuple(dict.fromkeys(s for s in (speakers[span["cue_index"]] for span in row["spans"]) if s)),
        spans=tuple(SearchSpan(**span) for span in row["spans"]), rights_status="approved",
        rights_review_url=_display_url(row["rights_review_url"]), license_id=row["license_id"],
        license_url=_display_url(row["license_url"]), attribution=row["attribution"], **clip.as_fields())
    return hit.model_dump(mode="json"), source


def alignment_rows(corpus, hits) -> dict:
    """Saved alignments of exported chunks whose audio is still the passage's own, by chunk id."""
    urls = {hit["chunk_id"]: hit["audio_url"] for hit in hits}
    rows = {str(chunk): row for chunk, row in corpus["alignments"].items()}
    return {chunk: row for chunk, row in rows.items() if urls.get(chunk) and urls[chunk] == row["audio_url"]}


# --- citations and the size budget --------------------------------------------------------------------------------

def cited_chunks(runs) -> Counter:
    """chunk_id -> how often the answers of the runs' systems (<run>/<system>/attempts.jsonl) cite it."""
    counts = Counter()
    for run in runs:
        for path in sorted(Path(run).glob("*/attempts.jsonl")):
            for line in filter(str.strip, path.read_text(encoding="utf-8").splitlines()):
                result = json.loads(line).get("result") or {}
                for item in result.get("expressions") or ():
                    chunk = (item.get("citation") or {}).get("chunk_id")
                    if chunk:
                        counts[str(UUID(chunk))] += 1
    return counts


def by_citation(counts: Counter) -> list[str]:
    return sorted(counts, key=lambda chunk: (-counts[chunk], chunk))


def episode_order(hits, published, cited: Counter) -> list[int]:
    """Episodes by citations of their chunks (most first), then publication date and episode id (newest first)."""
    citations = Counter()
    for hit in hits:
        citations[hit["episode_id"]] += cited.get(hit["chunk_id"], 0)
    return sorted({hit["episode_id"] for hit in hits},
                  key=lambda e: (-citations[e], -(published.get(e) or 0), -e))


def hit_bytes(hit) -> int:
    return len(compact(hit).encode("utf-8")) + 1 + STORED_DIMENSIONS * 2  # the record, its comma, its vector


def select(hits, published, cited: Counter, budget: int | None, extra=None) -> tuple[list[dict], list[int], int]:
    """The passages of the longest prefix of episode_order that fits in budget bytes (None: all); returns the
    passages (by chunk_id), the kept episodes in order and their bytes (records, vectors and extra[chunk_id])."""
    sizes, extra = Counter(), extra or {}
    for hit in hits:
        sizes[hit["episode_id"]] += hit_bytes(hit) + extra.get(hit["chunk_id"], 0)
    kept, used = [], 0
    for episode in episode_order(hits, published, cited):
        if budget is not None and used + sizes[episode] > budget:
            break
        kept.append(episode)
        used += sizes[episode]
    chosen = set(kept)
    return sorted((h for h in hits if h["episode_id"] in chosen), key=lambda h: h["chunk_id"]), kept, used


def size(path) -> int:
    return package.size(path)


def requirements_text() -> str:
    lines = []
    for path in (ROOT / "translation_agent_demo/requirements.txt", ROOT / "translation_agent_demo/requirements-local.txt",
                 ROOT / "frontend/requirements.txt"):
        lines += [line for line in path.read_text().splitlines() if line and not line.startswith(LOCAL_ONLY)]
    return "\n".join(dict.fromkeys(lines)) + "\n"


def dependency_bytes(requirements: str) -> int:
    """The installed size of the requirements on Vercel's platform: measured once per requirements with uv in a
    temporary folder; the number is kept in CACHE."""
    record = CACHE / f"deps-{hashlib.sha256(requirements.encode()).hexdigest()[:12]}.bytes"
    if not record.is_file():
        with tempfile.TemporaryDirectory() as temporary:
            listed = Path(temporary) / "requirements.txt"
            listed.write_text(requirements)
            try:
                subprocess.run(["uv", "pip", "install", "--quiet", "--target", str(Path(temporary) / "site"),
                                "--python-platform", DEPS_PLATFORM, "--python-version", DEPS_PYTHON, "-r", str(listed)],
                               check=True)
            except (OSError, subprocess.CalledProcessError):
                raise SystemExit("Could not measure the dependencies with uv; pass --deps-mb.") from None
            measured = size(Path(temporary) / "site")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(str(measured))
    return int(record.read_text())


# --- vectors ------------------------------------------------------------------------------------------------------

def text_key(text: str) -> str:
    return hashlib.sha256((MODEL + "\0" + text).encode("utf-8")).hexdigest()


def encode(texts, encoder=None) -> np.ndarray:
    """The texts through LocalEmbeddings (the deploy's query encoder): its 384 MiniLM columns as float16."""
    if encoder is None:
        from translation_agent_demo.providers.local_embeddings import local_client
        encoder = local_client()
    parts = []
    for start in range(0, len(texts), BATCH):
        result = encoder.embed_texts(tuple(texts[start:start + BATCH]))
        if result.model != MODEL or result.dimensions != DIMENSIONS:
            raise ValueError(f"The encoder is {result.model}/{result.dimensions}, not {MODEL}/{DIMENSIONS}.")
        vectors = np.asarray(result.vectors, dtype=np.float32)
        if np.any(vectors[:, STORED_DIMENSIONS:]):
            raise ValueError("The encoder's columns past 384 are not zero padding.")
        parts.append(vectors[:, :STORED_DIMENSIONS].astype(np.float16))
    return np.concatenate(parts) if parts else np.zeros((0, STORED_DIMENSIONS), np.float16)


def save_vectors(path: Path, known: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = sorted(known)
    temporary = path.with_name(path.stem + ".tmp.npz")
    np.savez(temporary, keys=np.asarray(names), vectors=np.stack([known[k] for k in names]))
    temporary.replace(path)


def embed(texts, encoder=None, cache: Path | None = None, log=print, workers: int = 1) -> np.ndarray:
    """MiniLM vectors of texts (float16, 384 columns), cached by text; workers > 1 encodes in that many processes
    (each its own LocalEmbeddings) unless an encoder is given."""
    path = cache / f"vectors-{hashlib.sha256(MODEL.encode()).hexdigest()[:12]}.npz" if cache else None
    known = {}
    if path is not None and path.is_file():
        with np.load(path, allow_pickle=False) as saved:
            known = dict(zip(saved["keys"].tolist(), saved["vectors"]))
    keys = [text_key(t) for t in texts]
    missing = list(dict.fromkeys(k for k in keys if k not in known))
    if missing:
        text_of, started = dict(zip(keys, texts)), time.monotonic()
        slices = [missing[i:i + BATCH * 25] for i in range(0, len(missing), BATCH * 25)]
        if encoder is not None or workers <= 1:
            results = (encode([text_of[k] for k in part], encoder) for part in slices)
        else:
            from concurrent.futures import ProcessPoolExecutor
            pool = ProcessPoolExecutor(max_workers=workers)
            results = pool.map(encode, [[text_of[k] for k in part] for part in slices])
        for n, (part, vectors) in enumerate(zip(slices, results), 1):
            known.update(zip(part, vectors))
            log(f"embedded {min(n * BATCH * 25, len(missing))}/{len(missing)} ({time.monotonic() - started:.0f} s)")
            if path is not None and (n % 8 == 0 or n == len(slices)):  # an interrupted run keeps most of its work
                save_vectors(path, known)
        if encoder is None and workers > 1:
            pool.shutdown()
    if not keys:
        return np.zeros((0, STORED_DIMENSIONS), np.float16)
    return np.stack([known[k] for k in keys]).astype(np.float16)


# --- export -------------------------------------------------------------------------------------------------------

def write_corpus(directory: Path, profile: dict, hits, vectors, alignments, manifest) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("passages.json", "vectors.npy", "alignments.json", "manifest.json"):
        (directory / name).unlink(missing_ok=True)
    (directory / "passages.json").write_text(compact({"profile": profile, "hits": list(hits)}), encoding="utf8")
    np.save(directory / "vectors.npy", np.asarray(vectors, dtype=np.float16), allow_pickle=False)
    (directory / "alignments.json").write_text(compact({"alignments": alignments}), encoding="utf8")
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf8")


def export(directory: Path, corpus: dict, *, cited: Counter, budget: int | None, encoder=None,
           cache: Path | None = CACHE, log=print, workers: int = 1) -> dict:
    """Write corpus/ from load_corpus's values; returns the manifest."""
    rows = [row for row in corpus["rows"] if approved(row)]
    refused = len(corpus["rows"]) - len(rows)
    built = [build_hit(row, corpus) for row in rows]
    hits = [hit for hit, _ in built]
    sources = {hit["chunk_id"]: source for hit, source in built}
    published = {row["episode_id"]: row["published"] for row in rows}
    alignments = alignment_rows(corpus, hits)
    align_bytes = {chunk: len(compact({chunk: row}).encode()) for chunk, row in alignments.items()}
    chosen, episodes, used = select(hits, published, cited, budget, align_bytes)
    if not chosen:
        raise SystemExit("No passage fits in the size budget.")
    ids = {hit["chunk_id"] for hit in chosen}
    alignments = {chunk: row for chunk, row in alignments.items() if chunk in ids}
    vectors = embed([hit["text"] for hit in chosen], encoder, cache, log, workers)
    profile = {"model": MODEL, "dimensions": DIMENSIONS, "processing_version": corpus["processing_version"]}
    in_corpus = {str(UUID(c)) for c in cited} & ids
    manifest = {
        "profile": profile, "stored_dimensions": STORED_DIMENSIONS, "vector_dtype": "float16",
        "approved_chunks": len(hits), "refused_rows": refused, "exported_chunks": len(chosen),
        "approved_episodes": len(published), "exported_episodes": len(episodes), "complete": len(chosen) == len(hits),
        "selection": "all approved chunks" if len(chosen) == len(hits) else
                     "whole episodes, most cited in the runs first, then newest",
        "budget_bytes": budget, "selected_bytes": used,
        "cited_chunks": len(cited), "cited_chunks_exported": len(in_corpus),
        "positions": dict(Counter(sources[c] for c in ids).most_common()),
        "alignments": len(alignments),
        "licenses": dict(Counter(f'{h["license_id"]} | {h["attribution"]}' for h in chosen).most_common()),
        "feeds": dict(Counter(str(h["feed_id"]) for h in chosen).most_common()),
    }
    write_corpus(directory, profile, chosen, vectors, alignments, manifest)
    return manifest


# --- alignment precompute -----------------------------------------------------------------------------------------

def align(chunk_ids, *, model=None, limit=None, log=print) -> Counter:
    """Align and save (chunk_audio_alignment) the chunks without a saved alignment, in order; one chunk's failure
    never stops the rest. Returns status counts."""
    from frontend import audio_align
    from translation_agent_demo.storage.postgres import connect_database

    settings = database()
    ids = [UUID(str(c)) for c in dict.fromkeys(chunk_ids)]
    with connect_database(settings) as conn:
        conn.execute(audio_align.MIGRATION.read_text(encoding="utf-8"), prepare=False)
        saved = {row[0] for row in conn.execute(
            "SELECT chunk_id FROM public.chunk_audio_alignment WHERE chunk_id = ANY(%s::uuid[])", (ids,))}
    todo = [c for c in ids if c not in saved][:limit]
    log(json.dumps({"event": "start", "asked": len(ids), "saved_before": len(saved), "todo": len(todo)}))
    transcriber = audio_align.WhisperTranscriber(model, threads=6, workers=1)
    counts = Counter(saved=len(saved))
    for n, chunk_id in enumerate(todo, 1):
        started, line = time.monotonic(), {"n": n, "of": len(todo), "chunk_id": str(chunk_id)}
        try:
            with connect_database(settings) as conn:
                source = audio_align.load_source(conn, chunk_id)
            alignment = (audio_align.align_source(source, audio_align.decode_window, transcriber)
                         if source is not None else None)
            if alignment is not None:
                with connect_database(settings) as conn:
                    audio_align.save_alignment(conn, alignment)
                line.update(status="ready", method=alignment.method, coverage=alignment.coverage)
            else:
                line.update(status="failed", error="no_source" if source is None else "not_found")
        except Exception as exc:  # network, decoding or recognition trouble: the next run tries again
            line.update(status="failed", error=type(exc).__name__)
        counts[line["status"]] += 1
        log(json.dumps({**line, "ms": round((time.monotonic() - started) * 1000)}))
    log(json.dumps({"event": "done", **counts}))
    return counts


# --- package ------------------------------------------------------------------------------------------------------

def stage_admin(public: Path, data_file: Path | None, args) -> str:
    """public/admin: the admin page with a prebuilt data.json (validated), else package.stage_admin's choice."""
    if data_file is None:
        return package.stage_admin(public, run=args.admin_run, results=args.admin_results, tasks=args.admin_tasks)
    package.stage_admin(public)  # the page itself (and any committed data, replaced below)
    page = public / "admin"
    for name in package.DATA_FILES:
        (page / name).unlink(missing_ok=True)
    data = json.loads(data_file.read_text(encoding="utf-8"))
    if (data.get("meta") or {}).get("schema_version") != admin_data.SCHEMA_VERSION:
        raise SystemExit(f"{data_file} is not admin data schema {admin_data.SCHEMA_VERSION}.")
    shutil.copyfile(data_file, page / admin_data.DATA_FILE)
    traces = (data["meta"].get("files") or {}).get("traces")
    if traces:
        shutil.copyfile(data_file.parent / traces, page / traces)
    return f"admin data: {data_file} (run {data['meta']['run']['id']!r})"


def copy_code(target: Path) -> None:
    def copy(source, dest):
        dst = target / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dst)

    demo = ROOT / "translation_agent_demo"
    for d in ("", "agents", "corpus", "storage", "tools", "providers"):
        for p in (demo / d).glob("**/*.py" if d else "*.py"):
            copy(p, p.relative_to(ROOT))
    for name in package.FUNCTION_FILES:
        copy(ROOT / name, name)
    copy(ROOT / ENTRY, "api/search.py")
    for p in (ROOT / "frontend/web").iterdir():
        if p.is_file():
            copy(p, "public/" + p.name)


def size_report(target: Path, deps: int) -> dict:
    report = package.size_report(target)
    report["dependencies (measured)"] = deps
    report["function total"] = report["function"] + deps
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m frontend.vercel.own_snapshot", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    aligning = commands.add_parser("align", help="speech-recognition alignments of the runs' cited chunks")
    aligning.add_argument("--run", action="append", type=Path, default=[], help="an evaluation run folder")
    aligning.add_argument("--ids-file", type=Path, help="one chunk id per line, in order")
    aligning.add_argument("--model", help="faster-whisper model (default COACH_ALIGN_MODEL, else base.en)")
    aligning.add_argument("--limit", type=int, help="align at most this many in this run")
    packing = commands.add_parser("package", help="build the Vercel project folder")
    packing.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default {DEFAULT_OUT.relative_to(ROOT)}")
    packing.add_argument("--run", action="append", type=Path, default=[],
                         help="evaluation run folders whose citations rank the episodes kept over the budget")
    packing.add_argument("--admin-data", type=Path, help="a prebuilt admin data.json for /admin")
    packing.add_argument("--admin-run", help="else: build /admin's data from this run (package.py's option)")
    packing.add_argument("--admin-results", type=Path, default=ROOT / "evaluation/results")
    packing.add_argument("--admin-tasks", type=Path, default=ROOT / "evaluation/data/tasks.jsonl")
    packing.add_argument("--max-mb", type=float, default=MAX_MB, help=f"function size limit in MB (default {MAX_MB})")
    packing.add_argument("--margin-mb", type=float, default=MARGIN_MB, help=f"kept free (default {MARGIN_MB})")
    packing.add_argument("--deps-mb", type=float, help="installed dependency size (default: measured with uv)")
    packing.add_argument("--encoder-dir", type=Path, default=DIRECTORY, help="the MiniLM files (tokenizer, onnx)")
    packing.add_argument("--workers", type=int, default=2, help="embedding processes (default 2)")
    packing.add_argument("--corpus-from", type=Path,
                         help="reuse an exported corpus folder instead of reading the database (no size selection)")
    args = parser.parse_args(argv)
    if args.command == "align" and not (args.run or args.ids_file):
        parser.error("give --run or --ids-file")
    return args


def build_package(args, *, log=print) -> dict:
    target = args.out.resolve()
    if target == package.DEFAULT_OUT.resolve():
        raise SystemExit(f"{target} is package.py's default build; choose another --out.")
    target.mkdir(parents=True, exist_ok=True)
    copy_code(target)
    admin_line = stage_admin(target / "public", args.admin_data, args)
    for name in ENCODER_FILES:
        if not (args.encoder_dir / name).is_file():
            raise SystemExit(f"Encoder file missing: {args.encoder_dir / name}. Download it with "
                             "python -m translation_agent_demo.providers.local_embeddings.")
        (target / "encoder" / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.encoder_dir / name, target / "encoder" / name)
    requirements = requirements_text()
    (target / "requirements.txt").write_text(requirements)
    (target / ".python-version").write_text(DEPS_PYTHON + "\n")
    (target / ".vercelignore").write_text(".env*\n**/__pycache__/\n**/*.pyc\n")
    (target / "vercel.json").write_text(json.dumps(package.vercel_config()))
    deps = round(args.deps_mb * 1e6) if args.deps_mb is not None else dependency_bytes(requirements)
    corpus_dir = target / "corpus"
    if args.corpus_from is not None:
        if args.corpus_from.resolve() != corpus_dir.resolve():
            shutil.copytree(args.corpus_from, corpus_dir, dirs_exist_ok=True)
        manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf8"))
    else:
        if corpus_dir.exists():
            shutil.rmtree(corpus_dir)
        fixed = size(target / "api") + sum(size(target / d) for d in package.FUNCTION_DIRS if d != "corpus")
        budget = round((args.max_mb - args.margin_mb) * 1e6) - deps - fixed - 50_000  # manifest and JSON frame
        with connect() as conn:
            corpus = load_corpus(conn)
        manifest = export(corpus_dir, corpus, cited=cited_chunks(args.run), budget=budget, log=log,
                          workers=args.workers)
    sizes = size_report(target, deps)
    if sizes["function total"] > args.max_mb * 1e6:
        raise SystemExit(f"The function is {sizes['function total'] / 1e6:.1f} MB, over {args.max_mb} MB.")
    log(admin_line)
    log(f"passages: {manifest['exported_chunks']} of {manifest['approved_chunks']} approved chunks, "
        f"{manifest['exported_episodes']} of {manifest['approved_episodes']} episodes; alignments: "
        f"{manifest['alignments']}; positions: {manifest['positions']}")
    for name, value in sizes.items():
        log(f"  {name}: {value / 1e6:.1f} MB")
    log(str(target))
    return {"manifest": manifest, "sizes": sizes, "admin": admin_line}


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "align":
        order = by_citation(cited_chunks(args.run))
        if args.ids_file:
            order += [line.strip() for line in args.ids_file.read_text().splitlines() if line.strip()]
        counts = align(order, model=args.model, limit=args.limit, log=lambda line: print(line, flush=True))
        return 1 if counts["failed"] else 0
    build_package(args, log=lambda line: print(line, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
