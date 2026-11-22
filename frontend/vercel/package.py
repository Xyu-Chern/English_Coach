"""Build a Vercel project containing only publishable assets and approved passages.

    python -m frontend.vercel.package [--out DIR] [--admin-run RUN] [--admin-results DIR] [--admin-tasks FILE]
        [--admin-systems a,b] [--coach-system baseline|agent] [--skip-apk] [--skip-search-data]

public/        static files: the web app at /, the APK at /downloads/, the admin page (frontend/admin) at
               /admin/ with its data.json (+ data-traces.json when split). Open, like the app (D4).
api/search.py  the function (frontend/vercel/index.py) with the Python files, corpus/ and encoder/ it reads.
vercel.json    the function's limits and files, /admin -> /admin/ (the page reads data.json relatively), and
               X-Robots-Tag: noindex on /admin and everything under it.

The admin data is an evaluation run's record (D5), built by frontend.admin_data from --admin-run (or
COACH_ADMIN_RUN) under --admin-results (or COACH_ADMIN_RESULTS, default evaluation/results), in the
deployment's mode: --coach-system, else COACH_SYSTEM, else agent. Without a run, a frontend/admin/data.json
is shipped when there is one; otherwise the page ships without data and says so.

--skip-apk and --skip-search-data leave out the Android build and the corpus and encoder, for a preview
that cannot offer the APK or answer questions; they need --out, so the deploy folder never holds one.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
from evaluation.snapshot_store import _hit
from frontend import admin_data
from translation_agent_demo.providers.local_embeddings import DIRECTORY

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "frontend/.local/vercel-phrase-room"
ADMIN = ROOT / "frontend/admin"
DATA_FILES = (admin_data.DATA_FILE, admin_data.TRACES_FILE)
FUNCTION_DIRS = ("corpus", "encoder", "translation_agent_demo", "frontend", "evaluation")
ADMIN_PATHS = ("/admin", "/admin/(.*)")  # what vercel.json marks X-Robots-Tag: noindex


def export_corpus(directory):
    sql = """SELECT json_build_object('chunk',c.record,'document',d.record,'vector',c.embedding::text,
                'profile',m.manifest->'profile',
                'approved',coalesce(s.rights_status='approved' AND r.status='approved'
                    AND d.license_id=r.license_id AND public.transcript_url_matches_review_scope(
                        d.transcript_url,r.transcript_url_prefix),false))
            FROM evaluation_zh_local_v1.chunks c JOIN evaluation_zh_local_v1.documents d USING(document_id)
            CROSS JOIN evaluation_zh_local_v1.metadata m LEFT JOIN public.podcast_sources s USING(source_key)
            LEFT JOIN public.podcast_feed_reviews r ON r.feed_id=s.feed_id ORDER BY c.chunk_id"""
    output = subprocess.check_output(
        ["sudo", "-u", "postgres", "psql", "-XAt", "-d", "english_coach", "-c", sql],
        text=True,
    )
    rows = [json.loads(line) for line in output.splitlines()]
    if not rows or not all(r["approved"] for r in rows):
        raise ValueError("Snapshot failed source review")
    directory.mkdir(exist_ok=True)
    (directory / "passages.json").write_text(
        json.dumps(
            dict(
                profile=rows[0]["profile"],
                hits=[
                    _hit(r["chunk"], r["document"], 0).model_dump(mode="json")
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


def stage_admin(public, *, run=None, results=None, tasks=None, systems=None, coach_system=None):
    """Copy the admin page to public/admin and put its data beside it; returns one line on what was shipped.

    An older package's data files are removed first, so a page never shows another run by mistake."""
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
        # The admin page fetches data.json relative to itself: /admin must become /admin/.
        "redirects": [{"source": "/admin", "destination": "/admin/", "permanent": False}],
        # /admin is open to anyone with the address (D4) but kept out of search engines, its data included.
        "headers": [{"source": source, "headers": [{"key": "X-Robots-Tag", "value": "noindex"}]}
                    for source in ADMIN_PATHS],
    }


def size(path):
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def size_report(target):
    """Bytes of the static files and of the function's own files (Vercel adds the installed requirements)."""
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
    for name in (
        "frontend/server.py",
        "frontend/staged.py",
        "frontend/vercel/coach.py",
        "evaluation/snapshot_search.py",
    ):
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
    requirements = []
    for p in (
        demo / "requirements.txt",
        demo / "requirements-local.txt",
        ROOT / "frontend/requirements.txt",
    ):
        requirements += [
            line
            for line in p.read_text().splitlines()
            if line and not line.startswith(("-r", "anthropic==", "huggingface-hub=="))
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
