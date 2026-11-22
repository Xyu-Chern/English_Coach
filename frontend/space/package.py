"""Create an allowlisted Space build context from the reviewed corpus (run in WSL)."""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    "podcast_sources",
    "podcast_transcripts",
    "podcast_feed_reviews",
    "corpus_builds",
    "corpus_chunks",
    "corpus_embedding_builds",
    "corpus_embeddings",
)


def package():
    local = ROOT / "frontend/.local"
    local.mkdir(exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="hf-build-", dir=local))

    def copy(source, name):
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dst)

    for name in ("Dockerfile", "seed.sh", "start.sh", "README.md"):
        copy(ROOT / "frontend/space" / name, name)
    for name in (
        "frontend/server.py",
        "frontend/staged.py",
        "frontend/quick.py",
        "frontend/requirements.txt",
        "translation_agent_demo/requirements.txt",
        "translation_agent_demo/requirements-local.txt",
    ):
        copy(ROOT / name, name)
    for p in (ROOT / "frontend/web").iterdir():
        if p.suffix in (".html", ".css", ".js", ".webmanifest", ".png", ".json"):
            copy(p, p.relative_to(ROOT))
    demo = ROOT / "translation_agent_demo"
    for directory in ("", "agents", "providers", "corpus", "storage", "tools"):
        for p in (demo / directory).glob("**/*.py" if directory else "*.py"):
            copy(p, p.relative_to(ROOT))
    db = ["sudo", "-u", "postgres"]
    count = subprocess.check_output(
        [
            *db,
            "psql",
            "-XAt",
            "-d",
            "english_coach",
            "-c",
            "SELECT count(*) FROM podcast_sources WHERE rights_status <> 'approved'",
        ],
        text=True,
    ).strip()
    if count != "0":
        raise SystemExit("Review source redistribution before packaging this database.")
    cmd = [
        *db,
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--no-security-labels",
    ]
    for table in TABLES:
        cmd.extend(["--table", "public." + table])
    with (target / "corpus.dump").open("wb") as dump:
        subprocess.run([*cmd, "english_coach"], stdout=dump, check=True)
    definition = subprocess.check_output(
        [
            *db,
            "psql",
            "-XAt",
            "-d",
            "english_coach",
            "-c",
            "SELECT pg_get_functiondef('public.transcript_url_matches_review_scope(text,text)'::regprocedure)",
        ],
        text=True,
    )
    (target / "review_scope.sql").write_text(
        definition.rstrip() + ";\n", encoding="utf8"
    )
    return target


if __name__ == "__main__":
    print(package())
