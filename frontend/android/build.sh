#!/usr/bin/env bash
# Build the study client with JDK 17 and Android SDK Platform/Build Tools 35.
set -euo pipefail
cd "$(dirname "$0")"
sdk=${ANDROID_HOME:?Set ANDROID_HOME to your Android SDK}
tools="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-35/android.jar"
out="$PWD/build"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/classes" "$out"
assets=../web
if [[ -n "${COACH_SPACE_ORIGIN:-}" ]]; then
  [[ "$COACH_SPACE_ORIGIN" =~ ^https://[a-z0-9-]+((\.static)?\.hf\.space|\.vercel\.app)$ ]] || { echo "Invalid Space origin" >&2; exit 1; }
  cp -R ../web "$tmp/web"
  sed -i "s|^const onlineSite = .*;.*$|const onlineSite = \"$COACH_SPACE_ORIGIN\";|" "$tmp/web/app.js"
  grep -Fq "const onlineSite = \"$COACH_SPACE_ORIGIN\";" "$tmp/web/app.js"
  if [[ "${COACH_STATIC_ONLY:-0}" == 1 ]]; then
    sed -i 's|<head>|<head><meta name="coach-static" content="1">|' "$tmp/web/index.html"
  fi
  assets="$tmp/web"
fi
"$tools/aapt" package -f -M AndroidManifest.xml -S res -A "$assets" -I "$platform" -F "$tmp/app.apk"
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$platform" -d "$tmp/classes" src/app/phraseroom/coach/MainActivity.java
jar cf "$tmp/classes.jar" -C "$tmp/classes" .
"$tools/d8" --min-api 24 --lib "$platform" --output "$tmp" "$tmp/classes.jar"
(cd "$tmp" && "$tools/aapt" add app.apk classes.dex >/dev/null)
"$tools/zipalign" -f 4 "$tmp/app.apk" "$tmp/aligned.apk"
sign_dir="${XDG_DATA_HOME:-$HOME/.local/share}/phrase-room"
mkdir -p "$sign_dir"
if [[ ! -f "$sign_dir/debug.jks" ]]; then
  keytool -genkeypair -keystore "$sign_dir/debug.jks" -alias coach-debug -storepass android -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=English Coach Debug" >/dev/null
fi
"$tools/apksigner" sign --ks "$sign_dir/debug.jks" --ks-pass pass:android --out "$out/EnglishCoach.apk" "$tmp/aligned.apk"
"$tools/apksigner" verify "$out/EnglishCoach.apk"
echo "$out/EnglishCoach.apk"
