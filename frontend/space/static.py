"""Publish the working phrase library on a free static Space."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from huggingface_hub import HfApi
from huggingface_hub.utils import RepositoryNotFoundError
from frontend.space.package import ROOT


def main():
    api = HfApi()
    repo = api.whoami()["name"] + "/phrase-room"
    try:
        info = api.space_info(repo)
        if (
            info.private
            or info.sdk != "static"
            or "Phrase Room" not in (info.card_data.to_dict().get("title") or "")
        ):
            raise SystemExit("Existing Space has different content or visibility.")
    except RepositoryNotFoundError:
        api.create_repo(repo, repo_type="space", space_sdk="static", private=False)
        info = api.space_info(repo)
    origin = info.host
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for p in (ROOT / "frontend/web").iterdir():
            if p.is_file():
                shutil.copy2(p, stage / p.name)
        index = stage / "index.html"
        index.write_text(
            index.read_text().replace(
                "<head>", '<head><meta name="coach-static" content="1">'
            )
        )
        # The cache identity changes when switching between the static and server variants.
        sw = stage / "sw.js"
        sw.write_text(sw.read_text().replace("shell-v5", "static-v5"))
        (stage / "README.md").write_text(
            """---
title: Phrase Room
emoji: 🎧
colorFrom: green
colorTo: gray
sdk: static
app_file: index.html
---
# Phrase Room

Search eight bilingual phrase cards with attributed podcast quotes. The cloud coach is pending.
## Project Owner Judgment Questions

None.
# 中文

可查询八张中韩双语表达卡并查看播客原句，云端教练待上线。
## 项目负责人判断题

无。
# 한국어

중국어·한국어 표현 카드 여덟 장과 팟캐스트 인용을 검색할 수 있습니다. 클라우드 코치는 준비 중입니다.
## 프로젝트 책임자 판단 질문

없음.
""",
            encoding="utf8",
        )
        env = dict(
            os.environ,
            ANDROID_HOME=os.getenv("ANDROID_HOME", "/opt/coach-sdk"),
            COACH_SPACE_ORIGIN=origin,
            COACH_STATIC_ONLY="1",
        )
        subprocess.run(
            ["bash", "frontend/android/build.sh"], cwd=ROOT, env=env, check=True
        )
        (stage / "downloads").mkdir()
        shutil.copy2(
            ROOT / "frontend/android/build/PhraseRoom.apk",
            stage / "downloads/PhraseRoom.apk",
        )
        api.upload_folder(
            folder_path=stage,
            repo_id=repo,
            repo_type="space",
            commit_message="Publish mobile phrase library and chat homepage",
        )
    print(origin)


if __name__ == "__main__":
    main()
