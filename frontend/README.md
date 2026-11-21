# Phrase Room

The web client and the Android app share the files in `web/`. Search eight offline situations in Chinese, Korean or English, read the original podcast quote and its license, and keep bookmarks and recent questions on the current device. Online coaching uses the existing ExpressionCoach and the local PostgreSQL transcript index.

## Run and install

From the repository root, configure the existing transcript database, local embedding weights and model in the demo environment. For the Responses provider set `LLM_PROVIDER=responses`, `RESPONSES_BASE_URL`, `RESPONSES_API_KEY`, `LLM_MODEL` and `EMBEDDING_PROVIDER=local` on the server. Start with:

```sh
uv run --python 3.11 --with-requirements frontend/requirements.txt python -m frontend.server
```

Open `http://127.0.0.1:8787`. Select **问教练** for a model answer. Library searches work offline after the web app has cached its assets. Private HTTPS hosting also supports adding the web app to the iPhone home screen through Safari.

Build the Android package with Linux or WSL, JDK 17 and Android SDK Platform/Build Tools 35. The script signs a development APK with the local debug key. Use Settings in the web client to download the built APK.

```sh
ANDROID_HOME=/path/to/android-sdk bash frontend/android/build.sh
adb install -r frontend/android/build/PhraseRoom.apk
```

Android 1.2 uses the Vercel origin in the app. In Settings enter your personal connection code. The backend bundle is generated from the repository root using `python -m frontend.vercel.package` in WSL. Set `RESPONSES_API_KEY` and `COACH_PAIR_CODE` as Vercel production secrets before deploying the generated directory.

The live Vercel app serves the chat UI, Android download and coach at the same HTTPS origin. A deployment includes 185 reviewed passages, their vectors and the MiniLM encoder. Vercel computes the query vector and calls the Responses gateway. Questions require the device's personal connection code. The computer can be off. Publish a new snapshot when transcripts or rights change.

## Project Owner Judgment Questions

No decision is needed for this delivery.

# 中文

网页和 Android App 共用 `web/`。可以用中文、韩文或英文查找八个离线场景，查看播客原句、节目和许可。收藏与提问记录只保存在当前设备。在线教练使用项目已有的 ExpressionCoach 和本地 PostgreSQL 字幕库。

## 启动与安装

从仓库根目录启动。先按项目原有方式准备字幕库和本地向量模型。在服务端配置 `LLM_PROVIDER=responses`、`RESPONSES_BASE_URL`、`RESPONSES_API_KEY`、`LLM_MODEL` 和 `EMBEDDING_PROVIDER=local`。

```sh
uv run --python 3.11 --with-requirements frontend/requirements.txt python -m frontend.server
```

打开 `http://127.0.0.1:8787`，选「问教练」即可提交场景。网页缓存完成后可离线查表达。iPhone 可在 Safari 打开 HTTPS 网页，从分享菜单添加到主屏幕。

Android 构建需要 Linux 或 WSL、JDK 17 和 Android SDK Platform/Build Tools 35。脚本用本地开发签名生成 APK，可从网页「连接设置」下载。

```sh
ANDROID_HOME=/path/to/android-sdk bash frontend/android/build.sh
adb install -r frontend/android/build/PhraseRoom.apk
```

Android 1.2 直接访问 Vercel，在连接设置填写个人连接码。更新后端时，从仓库根目录在 WSL 运行 `python -m frontend.vercel.package`。部署生成的目录前，在 Vercel 的生产环境配置 `RESPONSES_API_KEY` 和 `COACH_PAIR_CODE`。

Vercel 独立网址同时提供聊天首页、Android 安装包和教练接口。云端随部署携带 185 个字幕片段、对应向量与 MiniLM 编码器，在云端计算问题向量并调用 Responses 接口。手机首次提问需要个人连接码，电脑可以关机。字幕或使用许可发生变化时需重新发布快照。

## 项目负责人判断题

本次交付无需额外决定。

# 한국어

웹과 Android 앱은 `web/`의 화면을 공유한다. 중국어, 한국어 또는 영어로 여덟 가지 오프라인 상황을 검색하고 팟캐스트 원문, 출처, 라이선스를 확인할 수 있다. 북마크와 질문 기록은 현재 기기에 저장된다. 온라인 코치는 기존 ExpressionCoach와 로컬 PostgreSQL 자막 색인을 사용한다.

## 실행 및 설치

저장소 루트에서 기존 자막 데이터베이스와 로컬 임베딩 모델을 준비한다. 서버에 `LLM_PROVIDER=responses`, `RESPONSES_BASE_URL`, `RESPONSES_API_KEY`, `LLM_MODEL`, `EMBEDDING_PROVIDER=local`을 설정한다.

```sh
uv run --python 3.11 --with-requirements frontend/requirements.txt python -m frontend.server
```

`http://127.0.0.1:8787`에서 ‘코치에게 질문’을 선택한다. 웹 앱이 캐시되면 오프라인 표현 검색도 가능하다. iPhone에서는 Safari로 HTTPS 사이트를 열고 공유 메뉴에서 홈 화면에 추가할 수 있다.

Android 빌드에는 Linux 또는 WSL, JDK 17, Android SDK Platform/Build Tools 35가 필요하다. 스크립트는 로컬 개발 키로 APK에 서명한다. 빌드한 APK는 웹 앱 연결 설정에서 내려받을 수 있다.

```sh
ANDROID_HOME=/path/to/android-sdk bash frontend/android/build.sh
adb install -r frontend/android/build/PhraseRoom.apk
```

Android 1.2는 Vercel에 직접 연결한다. 연결 설정에서 개인 코드를 입력한다. WSL 저장소 루트에서 `python -m frontend.vercel.package`로 배포 파일을 만들고 Vercel 프로덕션에 `RESPONSES_API_KEY`와 `COACH_PAIR_CODE`를 설정한 뒤 배포한다.

Vercel의 같은 HTTPS 주소에서 대화 화면, Android 설치 파일과 코치 API를 제공한다. 배포본은 검토된 자막 185개, 벡터, MiniLM 인코더를 포함한다. 서버가 질문 벡터를 계산하고 Responses API를 호출한다. 휴대폰에서 개인 연결 코드를 한 번 입력하면 컴퓨터가 꺼져 있어도 사용할 수 있다. 자막이나 이용 허가가 바뀌면 스냅샷을 다시 배포한다.

## 프로젝트 책임자 판단 질문

이번 제공 범위에서 추가로 결정할 사항은 없다.
