"""Build a Vercel project containing only publishable assets and approved passages.

public/ holds the web app, the APK and the admin page (/admin/, noindex) with its data.json, built by
frontend.admin_data from --admin-run (else the committed frontend/admin/data.json, else none). api/search.py
is frontend/vercel/index.py; vercel.json rewrites /admin/requests.json, /admin/mode and /api/audio/alignment
(answered from corpus/alignments.json, never by speech recognition) to it. --skip-apk / --skip-search-data
build a preview and need --out.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import UUID

import numpy as np
from evaluation.snapshot_store import _hit
from frontend import admin_data
from translation_agent_demo.providers.local_embeddings import DIRECTORY
from translation_agent_demo.storage.episode_audio import NO_AUDIO, estimate_clip
from translation_agent_demo.storage.retrieval import _display_url

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "frontend/.local/vercel-phrase-room"
ADMIN = ROOT / "frontend/admin"
DATA_FILES = (admin_data.DATA_FILE, admin_data.TRACES_FILE)
FUNCTION_DIRS = ("corpus", "encoder", "translation_agent_demo", "frontend", "evaluation")
ADMIN_PATHS = ("/admin", "/admin/(.*)")  # what vercel.json marks X-Robots-Tag: noindex
LIVE_ADMIN_PATHS = ("/admin/requests.json", "/admin/mode")  # answered by the function (frontend/server.py)
FUNCTION_PATHS = (*LIVE_ADMIN_PATHS, "/api/audio/alignment")  # rewritten to the function, which sees the path
LOCAL_ONLY_REQUIREMENTS = ("-r", "anthropic==", "huggingface-hub==", "faster-whisper==")  # no ASR on Vercel
# The Python files the function needs beyond translation_agent_demo/ (copied whole) and its entry point
FUNCTION_FILES = (
    "frontend/server.py",
    "frontend/audio_align.py",
    "frontend/staged.py",
    "frontend/request_log.py",
    "frontend/sql/request_log.sql",
    "frontend/admin_data.py",
    "frontend/vercel/coach.py",
    "evaluation/__init__.py",
    "evaluation/snapshot_search.py",
    "evaluation/report.py",
    "evaluation/viewer.py",
)


def psql(sql):
    return subprocess.check_output(
        ["sudo", "-u", "postgres", "psql", "-XAt", "-d", "english_coach", "-c", sql],
        text=True,
    )


def episode_audio():
    """Enclosure rows (migration 010) by episode_id; empty when this database has no audio table yet."""
    if psql("SELECT to_regclass('public.podcast_episode_audio') IS NOT NULL").strip() != "t":
        return {}
    output = psql("""SELECT json_build_object('episode_id',episode_id,'feed_id',feed_id,
                'enclosure_url',enclosure_url,'duration_s',duration_s) FROM public.podcast_episode_audio""")
    return {r["episode_id"]: r for r in map(json.loads, output.splitlines())}


def audio_fields(chunk, document, audio):
    """A passage's citation audio fields: stored cue timing, else character position x episode duration
    (estimate_clip, audio_estimated=True); no known audio gives null/false."""
    row = audio.get(chunk["episode_id"])
    url = _display_url(row["enclosure_url"]) if row and row["feed_id"] in (None, chunk["feed_id"]) else None
    if url is None:
        return NO_AUDIO.as_fields()
    lengths = [len(cue["text"]) for cue in document["cues"]]
    spans = chunk["spans"]
    char_start = sum(lengths[:spans[0]["cue_index"]]) + spans[0]["start_char"] if spans else None
    char_end = sum(lengths[:spans[-1]["cue_index"]]) + spans[-1]["end_char"] if spans else None
    return estimate_clip(url, start_ms=chunk.get("start_ms"), end_ms=chunk.get("end_ms"), char_start=char_start,
                         char_end=char_end, char_total=sum(lengths), duration_s=row["duration_s"]).as_fields()


def export_corpus(directory):
    sql = """SELECT json_build_object('chunk',c.record,'document',d.record,'vector',c.embedding::text,
                'profile',m.manifest->'profile',
                'approved',coalesce(s.rights_status='approved' AND r.status='approved'
                    AND d.license_id=r.license_id AND public.transcript_url_matches_review_scope(
                        d.transcript_url,r.transcript_url_prefix),false))
            FROM evaluation_zh_local_v1.chunks c JOIN evaluation_zh_local_v1.documents d USING(document_id)
            CROSS JOIN evaluation_zh_local_v1.metadata m LEFT JOIN public.podcast_sources s USING(source_key)
            LEFT JOIN public.podcast_feed_reviews r ON r.feed_id=s.feed_id ORDER BY c.chunk_id"""
    rows = [json.loads(line) for line in psql(sql).splitlines()]
    if not rows or not all(r["approved"] for r in rows):
        raise ValueError("Snapshot failed source review")
    audio = episode_audio()
    directory.mkdir(exist_ok=True)
    (directory / "passages.json").write_text(
        json.dumps(
            dict(
                profile=rows[0]["profile"],
                hits=[
                    _hit(r["chunk"], r["document"], 0).model_dump(mode="json")
                    | audio_fields(r["chunk"], r["document"], audio)
                    for r in rows
                ],
            ),
            ensure_ascii=False,
        ),
        encoding="utf8",
    )
    np.save(
        directory / "vectors.npy",
        np.asarray([json.loads(r["vector"]) for r in rows], dtype=np.float32),
        allow_pickle=False,
    )


def export_alignments(directory, snapshot="evaluation_zh_local_v1.chunks"):
    """corpus/alignments.json: the saved alignments (migration 011) of the snapshot's chunks, precomputed with
    python -m frontend.audio_align <chunk_id>...; none gives an empty file."""
    alignments = {}
    if psql("SELECT to_regclass('public.chunk_audio_alignment') IS NOT NULL").strip() == "t":
        output = psql(f"""SELECT json_build_object('chunk_id',chunk_id,'audio_url',audio_url,
                    'window_start_ms',window_start_ms,'words',words,'cues',cues,'method',method,'model',model)
                FROM public.chunk_audio_alignment WHERE chunk_id IN (SELECT chunk_id FROM {snapshot})""")
        for row in map(json.loads, output.splitlines()):
            alignments[str(UUID(row.pop("chunk_id")))] = row
    (directory / "alignments.json").write_text(json.dumps({"alignments": alignments}, ensure_ascii=False),
                                               encoding="utf8")
    return len(alignments)


def stage_admin(public, *, run=None, results=None, tasks=None, systems=None, coach_system=None):
    """Copy the admin page to public/admin with its data (an older package's data removed first); returns one
    line on what was shipped."""
    page = public / "admin"
    page.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        (page / name).unlink(missing_ok=True)
    if ADMIN.is_dir():
        shutil.copytree(ADMIN, page, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*DATA_FILES, "*.tmp", ".DS_Store"))
    if not (page / "index.html").is_file():
        raise SystemExit(f"No admin page: {ADMIN / 'index.html'} is missing.")
    if run:
        argv = ["--results", str(results), "--run", run, "--tasks", str(tasks), "--out", str(page)]
        argv += ["--systems", systems] if systems else []
        argv += ["--coach-system", coach_system] if coach_system else []
        if admin_data.main(argv) != 0:
            raise SystemExit(f"Could not build the admin data from run {run!r}.")
        return f"admin data: run {run!r}"
    committed = ADMIN / admin_data.DATA_FILE
    if not committed.is_file():
        return ("admin data: none. /admin/ will say there is no data. Pass --admin-run <run> "
                "(or set COACH_ADMIN_RUN) to build it from an evaluation run.")
    data = json.loads(committed.read_text(encoding="utf-8"))
    if (data.get("meta") or {}).get("schema_version") != admin_data.SCHEMA_VERSION:
        raise SystemExit(f"{committed} is not admin data schema {admin_data.SCHEMA_VERSION}; rebuild it.")
    for name in DATA_FILES:
        if (ADMIN / name).is_file():
            shutil.copyfile(ADMIN / name, page / name)
    traces = data["meta"]["files"].get("traces")
    if traces and not (page / traces).is_file():
        raise SystemExit(f"{committed} names {traces}, which is not in {ADMIN}.")
    shown = committed.relative_to(ROOT) if committed.is_relative_to(ROOT) else committed
    line = f"admin data: {shown} (run {data['meta']['run']['id']!r})"
    try:
        deployed, origin = admin_data.resolve_mode(coach_system)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if data["mode"]["current"] != deployed:
        line += (f"; it was built for mode {data['mode']['current']!r} but this package's mode is {deployed!r} "
                 f"({origin}). Rebuild it with --admin-run to show the deployed mode.")
    return line


def vercel_config():
    return {
        "framework": None,
        "functions": {
            "api/search.py": {
                "maxDuration": 300,
                "includeFiles": "{" + ",".join(FUNCTION_DIRS) + "}/**",
            }
        },
        "redirects": [{"source": "/admin", "destination": "/admin/", "permanent": False}],
        "rewrites": [{"source": source, "destination": "/api/search"} for source in FUNCTION_PATHS],
        "headers": [{"source": source, "headers": [{"key": "X-Robots-Tag", "value": "noindex"}]}
                    for source in ADMIN_PATHS],
    }


def size(path):
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def size_report(target):
    """Bytes of the static files and the function's own files (without the installed requirements)."""
    target = Path(target)
    return {
        "public": size(target / "public"),
        "public/admin": size(target / "public/admin"),
        "function": size(target / "api") + sum(size(target / d) for d in FUNCTION_DIRS),
        "function/corpus": size(target / "corpus"),
        "function/encoder": size(target / "encoder"),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m frontend.vercel.package", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"the Vercel project folder (default {DEFAULT_OUT.relative_to(ROOT)})")
    parser.add_argument("--admin-run", default=os.environ.get("COACH_ADMIN_RUN") or None,
                        help="the evaluation run whose record /admin shows (default $COACH_ADMIN_RUN)")
    parser.add_argument("--admin-results", type=Path,
                        default=Path(os.environ.get("COACH_ADMIN_RESULTS") or ROOT / "evaluation/results"),
                        help="the results root holding the run (default $COACH_ADMIN_RESULTS, else evaluation/results)")
    parser.add_argument("--admin-tasks", type=Path, default=ROOT / "evaluation/data/tasks.jsonl", help="the task file")
    parser.add_argument("--admin-systems", help="comma-separated systems of the run (default: the run's manifest)")
    parser.add_argument("--coach-system", choices=admin_data.MODES,
                        help="the deployment's COACH_SYSTEM, shown on /admin (default $COACH_SYSTEM, else agent)")
    parser.add_argument("--skip-apk", action="store_true", help="leave out the Android build (preview only)")
    parser.add_argument("--skip-search-data", action="store_true",
                        help="leave out the corpus and the encoder (preview only: questions fail)")
    args = parser.parse_args(argv)
    args.out = args.out.resolve()
    if (args.skip_apk or args.skip_search_data) and args.out == DEFAULT_OUT.resolve():
        parser.error("--skip-apk and --skip-search-data make a preview; pass --out to a folder other than "
                     f"{DEFAULT_OUT.relative_to(ROOT)}")
    return args


def main(argv=None):
    args = parse_args(argv)
    target = args.out
    target.mkdir(parents=True, exist_ok=True)

    def copy(source, dest):
        dst = target / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dst)

    demo = ROOT / "translation_agent_demo"
    for d in ("", "agents", "corpus", "storage", "tools", "providers"):
        for p in (demo / d).glob("**/*.py" if d else "*.py"):
            copy(p, p.relative_to(ROOT))
    for name in FUNCTION_FILES:
        copy(ROOT / name, name)
    copy(ROOT / "frontend/vercel/index.py", "api/search.py")
    for p in (ROOT / "frontend/web").iterdir():
        if p.is_file():
            copy(p, "public/" + p.name)
    admin_line = stage_admin(target / "public", run=args.admin_run, results=args.admin_results,
                             tasks=args.admin_tasks, systems=args.admin_systems, coach_system=args.coach_system)
    if args.skip_search_data:
        print("warning: no corpus or encoder; this preview cannot answer questions.", file=sys.stderr)
    else:
        for name in ("tokenizer.json", "onnx/model.onnx"):
            if not (DIRECTORY / name).is_file():
                raise SystemExit(f"Encoder file missing: {DIRECTORY / name}. Download it with "
                                 "python -m translation_agent_demo.providers.local_embeddings.")
            copy(DIRECTORY / name, "encoder/" + name)
    if args.skip_apk:
        print("warning: no Android build; /downloads/PhraseRoom.apk is missing from this preview.", file=sys.stderr)
    else:
        subprocess.run(
            ["bash", "frontend/android/build.sh"],
            cwd=ROOT,
            env=dict(os.environ, ANDROID_HOME=os.getenv("ANDROID_HOME", "/opt/coach-sdk")),
            check=True,
        )
        copy(
            ROOT / "frontend/android/build/PhraseRoom.apk",
            "public/downloads/PhraseRoom.apk",
        )
    (target / ".vercelignore").write_text(".env*\n**/__pycache__/\n**/*.pyc\n")
    if not args.skip_search_data:
        export_corpus(target / "corpus")
        print(f"audio alignments: {export_alignments(target / 'corpus')} saved for the snapshot's chunks")
    requirements = []
    for p in (
        demo / "requirements.txt",
        demo / "requirements-local.txt",
        ROOT / "frontend/requirements.txt",
    ):
        requirements += [
            line
            for line in p.read_text().splitlines()
            if line and not line.startswith(LOCAL_ONLY_REQUIREMENTS)
        ]
    (target / "requirements.txt").write_text("\n".join(requirements) + "\n")
    (target / ".python-version").write_text("3.12\n")
    (target / "vercel.json").write_text(json.dumps(vercel_config()))
    print(admin_line)
    for name, value in size_report(target).items():
        print(f"  {name}: {value / 1e6:.1f} MB")
    print(target)


if __name__ == "__main__":
    main()
