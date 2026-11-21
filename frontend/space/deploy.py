"""Publish the selected public CPU Basic Space using the current Hugging Face login."""

import argparse
import os
import re
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from huggingface_hub import HfApi
from huggingface_hub.utils import RepositoryNotFoundError
from frontend.space.package import ROOT, package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="phrase-room-coach")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.name):
        parser.error("Use a lowercase Space name with optional hyphens.")
    api = HfApi()
    owner = api.whoami()["name"]
    repo = f"{owner}/{args.name}"
    key = os.environ["RESPONSES_API_KEY"]
    try:
        info = api.space_info(repo)
    except RepositoryNotFoundError:
        api.create_repo(repo, repo_type="space", space_sdk="docker", private=False)
        info = api.space_info(repo)
    if info.private or (
        set(api.list_repo_files(repo, repo_type="space"))
        - {"README.md", ".gitattributes"}
        and "seed.sh" not in api.list_repo_files(repo, repo_type="space")
    ):
        raise SystemExit(
            "Existing Space has other contents or visibility. Choose a separate --name."
        )
    runtime = api.get_space_runtime(repo)
    if any(
        hw and hw != "cpu-basic"
        for hw in (runtime.hardware, runtime.requested_hardware)
    ):
        raise SystemExit(
            "This Space uses different hardware. Choose a new free CPU Space."
        )
    origin = info.host
    if (
        not origin
        or urlsplit(origin).scheme != "https"
        or not (urlsplit(origin).hostname or "").endswith(".hf.space")
    ):
        raise SystemExit(
            "Hugging Face has not yet assigned the HTTPS Space host. Retry shortly."
        )
    stage = package()
    android_env = dict(
        os.environ,
        COACH_SPACE_ORIGIN=origin,
        ANDROID_HOME=os.getenv("ANDROID_HOME", "/opt/coach-sdk"),
    )
    subprocess.run(
        ["bash", "frontend/android/build.sh"], cwd=ROOT, env=android_env, check=True
    )
    apk_dir = stage / "frontend/android/build"
    apk_dir.mkdir(parents=True)
    import shutil

    shutil.copyfile(
        ROOT / "frontend/android/build/PhraseRoom.apk", apk_dir / "PhraseRoom.apk"
    )
    directory = Path.home() / ".local/share/phrase-room"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    codefile = directory / f"{owner}-{args.name}.code"
    if not codefile.exists():
        with open(
            os.open(codefile, os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600), "w"
        ) as out:
            out.write(secrets.token_urlsafe(18))
    api.add_space_secret(repo, "RESPONSES_API_KEY", key)
    api.add_space_secret(repo, "COACH_PAIR_CODE", codefile.read_text().strip())
    api.upload_folder(
        folder_path=stage,
        repo_id=repo,
        repo_type="space",
        commit_message="Deploy the expression coach and reviewed transcript corpus",
    )
    print(origin)
    print("Personal connection code file:", codefile)


if __name__ == "__main__":
    main()
