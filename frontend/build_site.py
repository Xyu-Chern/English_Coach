"""Assemble the static web app and the installable Android download in dist/."""

from pathlib import Path
from shutil import copy2
import base64
import json

ROOT = Path(__file__).resolve().parent


def main():
    apk = ROOT / "android/build/PhraseRoom.apk"
    if not apk.is_file():
        raise SystemExit("Build frontend/android/build.sh before assembling the site.")
    target = ROOT / "dist"
    (target / "downloads").mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "web").iterdir():
        if source.is_file():
            copy2(source, target / source.name)
    copy2(apk, target / "downloads" / apk.name)
    types = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json",
        ".webmanifest": "application/manifest+json",
        ".png": "image/png",
        ".apk": "application/vnd.android.package-archive",
    }
    assets = {}
    for source in [*sorted((ROOT / "web").iterdir()), apk]:
        if source.is_file():
            path = "/downloads/" + source.name if source == apk else "/" + source.name
            assets[path] = [
                types[source.suffix],
                base64.b64encode(source.read_bytes()).decode("ascii"),
            ]
    server = target / "server"
    server.mkdir(exist_ok=True)
    (server / "index.js").write_text(
        "const ASSETS="
        + json.dumps(assets)
        + ";\n"
        + (ROOT / "relay/worker.js").read_text(encoding="utf8"),
        encoding="utf8",
    )
    print(target)


if __name__ == "__main__":
    main()
