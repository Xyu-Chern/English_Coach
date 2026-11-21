"""Build a Vercel project containing only publishable assets and approved passages."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np
from evaluation.snapshot_store import _hit
from translation_agent_demo.providers.local_embeddings import DIRECTORY

ROOT = Path(__file__).resolve().parents[2]


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


def main():
    target = ROOT / "frontend/.local/vercel-phrase-room"
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
        "frontend/vercel/coach.py",
        "evaluation/snapshot_search.py",
    ):
        copy(ROOT / name, name)
    copy(ROOT / "frontend/vercel/index.py", "api/search.py")
    for p in (ROOT / "frontend/web").iterdir():
        if p.is_file():
            copy(p, "public/" + p.name)
    for name in ("tokenizer.json", "onnx/model.onnx"):
        copy(DIRECTORY / name, "encoder/" + name)
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
    (target / "vercel.json").write_text(
        json.dumps(
            {
                "framework": None,
                "functions": {
                    "api/search.py": {
                        "maxDuration": 300,
                        "includeFiles": "{corpus,encoder,translation_agent_demo,frontend,evaluation}/**",
                    }
                },
            }
        )
    )
    print(target)


if __name__ == "__main__":
    main()
