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

Android 1.3 uses the Vercel origin in the app. The backend bundle is generated from the repository root using `python -m frontend.vercel.package` in WSL. Set `RESPONSES_API_KEY` as a Vercel production secret before deploying the generated directory.

The live Vercel app serves the chat UI, Android download and coach at the same HTTPS origin. A deployment includes 185 reviewed passages, their vectors and the MiniLM encoder. Vercel computes the query vector and calls the Responses gateway. Anyone can ask a question directly. The computer can be off. Publish a new snapshot when transcripts or rights change.

## Staged answers, mode and request log

`POST /api/search` takes `{question, context}`. By default it returns one JSON reply, as before: `{"expressions": [...], "note": ...}`. Installed APKs keep working. A client that sends `Accept: application/x-ndjson` gets one JSON object per line instead:

| Line | When | Fields |
|---|---|---|
| `first` | The first stage verified 1–3 examples | `expressions`: verified examples only, which never change. `pending`: `false` means nothing follows. `note` |
| `final` | After the continuation. It is the only line when nothing was verified first or the request was declined | `expressions`: after a `first`, the `first` items and then only examples verified later; without a `first`, the whole answer. `added`: indexes of examples verified later. `note` |
| `error` | In place of `final` | `code`: `timeout`, `coach_unavailable` or a coach code such as `model_unavailable` |

Refusals (401, 403, 422 `invalid_input`, 429 `coach_busy`) are plain HTTP errors and come before any line. The JSON reply is the whole last answer, as old clients expect, so it can include unverified candidates that the stream leaves out after a `first`. If the continuation fails after the first stage verified examples, the reply still returns them.

- **Mode:** `COACH_SYSTEM` is `agent` (the locked agent, the default) or `baseline`. `COACH_CONTINUATION` is `on` (the default) or `off`. `off` runs the first stage only, a setting that was not evaluated. The server reads both when it starts, and any other value stops the start. Locally, set them before the start, for example `COACH_SYSTEM=baseline python -m frontend.server --port 8790`. On Vercel, change them under Settings → Environment Variables, then redeploy.
- **Limits:** The work stops 280 s after the request starts, because Vercel's `maxDuration` is 300 s. A stream then ends with an `error` line whose code is `timeout`. The local server takes `--deadline` or `COACH_DEADLINE_SECONDS` (1–3600 s) for a slow provider or the relay. One request runs per process. The slot returns when the stream ends or the work ends, whichever comes first. If the client leaves, the work stops at its next model call or search.
- **Request log:** Each request that passes the access checks prints one JSON line to stdout. On Vercel, search the runtime logs for `coach_request`. Nothing else about a request is stored. Vercel keeps runtime logs for 1 hour on Hobby and 1 day on Pro.

| Field | Meaning |
|---|---|
| `event`, `ts`, `request_id` | `coach_request`, the start time (UTC) and a random id |
| `mode`, `continuation_setting`, `transport` | `agent` or `baseline`; `on` or `off`; `ndjson` or `json` |
| `status`, `error_code` | One of `ok`, `declined`, `invalid_input`, `busy`, `error`, `timeout`, `disconnected`; the error code |
| `verified_first`, `added_final`, `verified_final` | Examples the first stage verified; examples verified after a `first` (0 without one); verified examples the learner ends with |
| `continuation`, `invariant_ok` | `skipped` (all verified), `ran`, `off` or `none` (declined or failed in the first stage); whether the final answer kept the `first` items |
| `first_ms`, `total_ms` | Milliseconds to the `first` line (`ndjson` only; `null` without one and on `json`, whose client sees nothing before the end) and to the end. Time to the first answer is `first_ms`, or `total_ms` when it is `null` |
| `llm_calls`, `searches`, `input_tokens`, `output_tokens`, `cached_input_tokens` | Model calls and searches attempted; tokens the provider reported |
| `disconnected`, `question_head` | Whether the client left early; the first 40 characters of the question, without the context or the answer |

## Learner app: staged answers

The web and Android client asks for NDJSON (`Accept: application/x-ndjson, application/json;q=0.9`). When a server answers with JSON instead (an older deployment, or the relay's `202` jobs), the client uses the previous one-reply flow. Installed APKs keep the JSON flow; rebuild the APK to ship this client. The service worker cache is `phrase-room-shell-v8`.

| What arrives | What the learner sees |
|---|---|
| Nothing yet | The waiting line with elapsed seconds. After 30 s it says that finding examples takes a little longer |
| `first` with `pending: false` | The verified examples as the answer. No notice |
| `first` with `pending: true` | Only the verified examples, an empty "searching" slot under them, and a notice above the chat: **Looking for more podcast examples** · keep this screen open and you will be told when it ends |
| Then `final` | The chat answer does not change. Examples at the `added` indexes go to the **Podcast** tab, which gets a badge. The slot and the notice point there. If nothing was added, both say so |
| Then `error` or a broken stream | The first examples stay. The notice and the slot offer **Look again**, without the error colour |
| `final` only | The whole answer at once, as before. Items without a verified example keep the "quote not confirmed yet" line |
| `error` only, or an HTTP refusal | The existing error line with **Retry** |

- **Records:** the device history keeps each answer's first items, the added items and a stage (`pending`, `done`, `stopped` or `incomplete`). The history page shows both groups, and cards from either can be saved. A follow-up question's context still uses the first item.
- **Leaving the page:** nothing is kept on the server (D5). On the next start, a record that is still `pending` becomes `incomplete`. A notice then offers **View first results** and **Look again**, which sends the same question with the context it sent before.
- **One search at a time:** the server answers one request per process, so a new coach question waits until the background search ends. The question box says so. Library searches are not held.
- **Accessibility and layout:** one polite live region speaks only when an answer arrives: the first examples and the end of the search. The notice sits outside the redrawn page, and a redraw keeps the cursor in the question box. The tabs are visible on the chat page too, so the **Podcast** tab's badge can be seen and tapped at once; the notice and the slot under the answer also link to it. With large text or a short screen, the question box no longer sticks to the bottom.
- **Checks:** server tests cover the stream; the screen states were checked in a headless browser with tools kept outside the repository. `ask()` (the 300 s abort, the running limit, the JSON and relay fallbacks) has no automated test.

## Project Owner Judgment Questions

1. While a background search runs, a new coach question waits, because the server answers one request per process and would refuse it as busy. Keep this default, or let the question go and accept an occasional busy reply?

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

Android 1.3 直接访问 Vercel，打开即可提问。更新后端时，从仓库根目录在 WSL 运行 `python -m frontend.vercel.package`。部署生成的目录前，在 Vercel 的生产环境配置 `RESPONSES_API_KEY`。

Vercel 独立网址同时提供聊天首页、Android 安装包和教练接口。云端随部署携带 185 个字幕片段、对应向量与 MiniLM 编码器，在云端计算问题向量并调用 Responses 接口。手机打开即可提问，电脑可以关机。字幕或使用许可发生变化时需重新发布快照。

## 分阶段回答、模式与请求日志

`POST /api/search` 接收 `{question, context}`。默认仍返回一个 JSON 回复：`{"expressions": [...], "note": ...}`，已安装的 APK 可以照常使用。客户端发送 `Accept: application/x-ndjson` 时，改为每行返回一个 JSON 对象：

| 行 | 何时 | 字段 |
|---|---|---|
| `first` | 第一阶段核对了 1–3 个例句 | `expressions`：只有核对通过的例句，之后不会改变。`pending`：`false` 表示后面没有内容。`note` |
| `final` | 后续阶段结束后。第一阶段一个都没核对或请求被拒绝时，只有这一行 | `expressions`：完整答案，以 `first` 的条目开头。`added`：后来核对通过的例句序号。`note` |
| `error` | 代替 `final` | `code`：`timeout`、`coach_unavailable` 或 `model_unavailable` 等教练错误码 |

拒绝（401、403、422 `invalid_input`、429 `coach_busy`）是普通 HTTP 错误，在任何行之前返回。JSON 回复就是流最终会显示的答案。第一阶段已核对例句后，即使后续阶段失败，回复仍会返回这些例句。

- **模式：** `COACH_SYSTEM` 为 `agent`（加锁的 agent，默认）或 `baseline`。`COACH_CONTINUATION` 为 `on`（默认）或 `off`。`off` 只运行第一阶段，这一设置没有经过评估。服务启动时读取这两个值，其他值会让启动失败。在本地，启动前设置即可，例如 `COACH_SYSTEM=baseline python -m frontend.server --port 8790`。在 Vercel 上，到 Settings → Environment Variables 修改，然后重新部署。
- **限制：** 请求开始 280 秒后停止工作，因为 Vercel 的 `maxDuration` 是 300 秒。此时流以 `code` 为 `timeout` 的 `error` 行结束。每个进程同时只处理一个请求。流结束或工作结束时（以先到者为准）归还名额。客户端离开后，工作会在下一次模型调用或检索前停止。
- **请求日志：** 每个通过访问检查的请求都向 stdout 打印一行 JSON。在 Vercel 上，可在运行日志中搜索 `coach_request`。请求的其他内容都不保存。Vercel 运行日志在 Hobby 计划保留 1 小时，在 Pro 计划保留 1 天。

| 字段 | 含义 |
|---|---|
| `event`、`ts`、`request_id` | `coach_request`、开始时间（UTC）和随机 ID |
| `mode`、`continuation_setting`、`transport` | `agent` 或 `baseline`；`on` 或 `off`；`ndjson` 或 `json` |
| `status`、`error_code` | `ok`、`declined`、`invalid_input`、`busy`、`error`、`timeout`、`disconnected` 之一；错误码 |
| `verified_first`、`added_final`、`verified_final` | 第一阶段核对的例句数；`first` 之后新增的例句数（没有 `first` 时为 0）；学习者最终拿到的已核对例句数 |
| `continuation`、`invariant_ok` | `skipped`（全部已核对）、`ran`、`off` 或 `none`（被拒绝或第一阶段失败）；最终答案是否保留了 `first` 的条目 |
| `first_ms`、`total_ms` | 到 `first` 事件的毫秒数（没有时为 `null`）和到结束的毫秒数。首次看到答案的时间是 `first_ms`，为 `null` 时是 `total_ms` |
| `llm_calls`、`searches`、`input_tokens`、`output_tokens`、`cached_input_tokens` | 尝试的模型调用和检索次数；服务商报告的 token 数 |
| `disconnected`、`question_head` | 客户端是否提前离开；问题的前 40 个字符，不含场景和答案 |

## 学习端：分阶段显示

网页和 Android 客户端请求 NDJSON（`Accept: application/x-ndjson, application/json;q=0.9`）。如果服务端仍返回 JSON（旧部署，或中继的 `202` 任务），客户端沿用原来的一次性回复流程。已安装的 APK 继续使用 JSON 流程；要发布这一客户端，需要重新构建 APK。Service worker 缓存为 `phrase-room-shell-v8`。

| 收到的内容 | 学习者看到的内容 |
|---|---|
| 还没有内容 | 等待提示和已等待的秒数。30 秒后提示查找例句需要多一点时间 |
| `first`，`pending: false` | 核对通过的例句作为回答。没有提示条 |
| `first`，`pending: true` | 只显示核对通过的例句，下方有一个“正在查找”的空位，聊天上方显示提示条：**正在查找更多播客例句** · 保持此页面打开，找到后会告诉你 |
| 随后收到 `final` | 聊天里的回答不变。`added` 序号对应的例句放进 **播客** 页，该标签显示徽标。空位和提示条都指向那里。如果没有新增，两处都会说明 |
| 随后收到 `error` 或流中断 | 先前的例句保留。提示条和空位提供 **重新查找**，不使用错误颜色 |
| 只有 `final` | 和以前一样一次显示完整回答。没有核对到例句的条目仍显示“暂时没有核对到播客原句” |
| 只有 `error`，或 HTTP 拒绝 | 原有的错误提示和 **重试** |

- **记录：** 设备上的历史为每个回答保存先前条目、新增条目和阶段（`pending`、`done`、`stopped` 或 `incomplete`）。历史页显示两组内容，两组卡片都可以收藏。后续提问的场景仍使用第一条例句。
- **离开页面：** 服务端不保存任何内容（D5）。下次打开时，仍为 `pending` 的记录变为 `incomplete`，提示条提供 **查看先前结果** 和 **重新查找**。重新查找会用同一问题和当时发送的场景再次提问。
- **一次一个查找：** 服务端每个进程同时只处理一个请求，所以后台查找结束前，新的教练提问需要等待，输入框下方会说明。表达库搜索不受影响。
- **无障碍与布局：** 只有一个礼貌型实时区域，只在回答到达时播报：先到的例句和查找结束。提示条位于会重绘的页面之外，重绘时输入框保留光标。聊天页也显示标签栏，**播客** 页的徽标一眼可见，可以直接点开；提示条和回答下方的空位也链接到那里。字号很大或屏幕很矮时，输入框不再固定在底部。
- **检查：** 服务端测试覆盖流式传输；各个画面状态在无头浏览器中检查过，所用工具不在仓库里。`ask()`（300 秒中止、同时查找上限、JSON 和中继回退）没有自动化测试。

## 项目负责人判断题

1. 后台查找进行时，新的教练提问会等待，因为服务端每个进程只处理一个请求，否则会以忙碌拒绝。保留这一默认做法，还是允许发送并接受偶尔的忙碌回复？

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

Android 1.3는 Vercel에 직접 연결한다. WSL 저장소 루트에서 `python -m frontend.vercel.package`로 배포 파일을 만들고 Vercel 프로덕션에 `RESPONSES_API_KEY`를 설정한 뒤 배포한다.

Vercel의 같은 HTTPS 주소에서 대화 화면, Android 설치 파일과 코치 API를 제공한다. 배포본은 검토된 자막 185개, 벡터, MiniLM 인코더를 포함한다. 서버가 질문 벡터를 계산하고 Responses API를 호출한다. 휴대폰에서 바로 질문할 수 있으며 컴퓨터는 꺼도 된다. 자막이나 이용 허가가 바뀌면 스냅샷을 다시 배포한다.

## 단계별 응답, 모드, 요청 로그

`POST /api/search`는 `{question, context}`를 받는다. 기본 응답은 지금처럼 JSON 하나다: `{"expressions": [...], "note": ...}`. 설치된 APK도 그대로 동작한다. 클라이언트가 `Accept: application/x-ndjson`을 보내면 줄마다 JSON 객체 하나를 받는다.

| 줄 | 언제 | 필드 |
|---|---|---|
| `first` | 첫 단계에서 예문 1~3개가 검증됨 | `expressions`: 검증된 예문만 담으며, 이후 바뀌지 않는다. `pending`: `false`면 뒤에 오는 것이 없다. `note` |
| `final` | 후속 단계가 끝난 뒤. 첫 단계에서 하나도 검증되지 않았거나 요청이 거절되면 이 줄만 온다 | `expressions`: 전체 답이며 `first` 항목으로 시작한다. `added`: 나중에 검증된 예문의 번호. `note` |
| `error` | `final` 대신 | `code`: `timeout`, `coach_unavailable`, 또는 `model_unavailable` 같은 코치 오류 코드 |

거절(401, 403, 422 `invalid_input`, 429 `coach_busy`)은 일반 HTTP 오류이며 어떤 줄보다 먼저 온다. JSON 응답은 스트림이 마지막에 보여 줄 답과 같다. 첫 단계에서 예문이 검증된 뒤 후속 단계가 실패해도 응답은 그 예문을 돌려준다.

- **모드:** `COACH_SYSTEM`은 `agent`(잠금 agent, 기본값) 또는 `baseline`이다. `COACH_CONTINUATION`은 `on`(기본값) 또는 `off`다. `off`는 첫 단계만 실행하며, 평가되지 않은 설정이다. 서버는 시작할 때 두 값을 읽고, 다른 값이면 시작하지 않는다. 로컬에서는 시작하기 전에 정한다. 예: `COACH_SYSTEM=baseline python -m frontend.server --port 8790`. Vercel에서는 Settings → Environment Variables에서 바꾼 뒤 다시 배포한다.
- **제한:** 작업은 요청 시작 280초 뒤에 멈춘다. Vercel의 `maxDuration`이 300초이기 때문이다. 이때 스트림은 `code`가 `timeout`인 `error` 줄로 끝난다. 프로세스당 한 번에 요청 하나만 처리한다. 자리는 스트림이 끝나거나 작업이 끝날 때 중 먼저 오는 때에 반환된다. 클라이언트가 떠나면 작업은 다음 모델 호출이나 검색 전에 멈춘다.
- **요청 로그:** 접근 검사를 통과한 요청마다 stdout에 JSON 한 줄을 출력한다. Vercel에서는 런타임 로그에서 `coach_request`로 검색한다. 그 밖의 요청 내용은 저장하지 않는다. Vercel 런타임 로그는 Hobby에서 1시간, Pro에서 1일 동안 보관된다.

| 필드 | 뜻 |
|---|---|
| `event`, `ts`, `request_id` | `coach_request`, 시작 시각(UTC), 임의 id |
| `mode`, `continuation_setting`, `transport` | `agent` 또는 `baseline`; `on` 또는 `off`; `ndjson` 또는 `json` |
| `status`, `error_code` | `ok`, `declined`, `invalid_input`, `busy`, `error`, `timeout`, `disconnected` 중 하나; 오류 코드 |
| `verified_first`, `added_final`, `verified_final` | 첫 단계에서 검증된 예문 수; `first` 뒤에 추가된 예문 수(`first`가 없으면 0); 학습자가 최종으로 받는 검증된 예문 수 |
| `continuation`, `invariant_ok` | `skipped`(모두 검증), `ran`, `off`, `none`(거절 또는 첫 단계 실패); 최종 답이 `first` 항목을 유지했는지 |
| `first_ms`, `total_ms` | `first` 이벤트까지의 밀리초(없으면 `null`)와 끝까지의 밀리초. 첫 답을 보는 시간은 `first_ms`이고, `null`이면 `total_ms`다 |
| `llm_calls`, `searches`, `input_tokens`, `output_tokens`, `cached_input_tokens` | 시도한 모델 호출과 검색 수; 제공자가 보고한 토큰 수 |
| `disconnected`, `question_head` | 클라이언트가 일찍 떠났는지; 질문의 앞 40자(맥락과 답은 넣지 않음) |

## 학습자 앱: 단계별 표시

웹과 Android 클라이언트는 NDJSON을 요청한다(`Accept: application/x-ndjson, application/json;q=0.9`). 서버가 JSON으로 답하면(이전 배포, 또는 릴레이의 `202` 작업) 클라이언트는 예전의 한 번 응답 흐름을 쓴다. 설치된 APK는 JSON 흐름을 그대로 쓴다. 이 클라이언트를 배포하려면 APK를 다시 빌드한다. 서비스 워커 캐시는 `phrase-room-shell-v8`이다.

| 도착한 것 | 학습자가 보는 것 |
|---|---|
| 아직 없음 | 기다림 문구와 경과 초. 30초가 지나면 예문을 찾느라 조금 더 걸린다고 알린다 |
| `first`, `pending: false` | 검증된 예문을 답으로 보여 준다. 공지는 없다 |
| `first`, `pending: true` | 검증된 예문만 보여 주고, 그 아래에 '찾는 중' 빈 자리를 두며, 채팅 위에 공지를 띄운다: **팟캐스트 예문을 더 찾는 중** · 이 화면을 열어 두면 끝날 때 알려드릴게요 |
| 이어서 `final` | 채팅의 답은 바뀌지 않는다. `added` 번호의 예문은 **팟캐스트** 탭으로 가고, 탭에 배지가 붙는다. 빈 자리와 공지가 그곳을 가리킨다. 추가된 것이 없으면 두 곳 모두 그렇게 알린다 |
| 이어서 `error` 또는 스트림 끊김 | 처음 예문은 그대로 둔다. 공지와 빈 자리에 **다시 찾기**를 두고, 오류 색은 쓰지 않는다 |
| `final`만 | 예전처럼 전체 답을 한 번에 보여 준다. 검증된 예문이 없는 항목에는 '원문 미확인' 문구가 그대로 붙는다 |
| `error`만, 또는 HTTP 거절 | 기존 오류 문구와 **재시도** |

- **기록:** 기기 기록은 답마다 처음 항목, 추가 항목, 단계(`pending`, `done`, `stopped`, `incomplete`)를 보관한다. 기록 화면은 두 묶음을 모두 보여 주고, 어느 쪽 카드든 저장할 수 있다. 후속 질문의 맥락은 지금처럼 첫 항목을 쓴다.
- **화면을 떠났을 때:** 서버에는 아무것도 남지 않는다(D5). 다음에 앱을 열 때 아직 `pending`인 기록은 `incomplete`가 된다. 공지에서 **처음 결과 보기**와 **다시 찾기**를 고를 수 있고, 다시 찾기는 같은 질문을 그때 보낸 맥락과 함께 다시 보낸다.
- **한 번에 한 검색:** 서버는 프로세스당 요청 하나만 처리한다. 그래서 백그라운드 검색이 끝날 때까지 새 코치 질문은 기다리며, 입력창 아래에 그 이유를 보여 준다. 표현 모음 검색은 막지 않는다.
- **접근성과 배치:** polite 라이브 영역 하나가 답이 도착할 때만 읽어 준다(처음 예문, 검색 끝). 공지는 다시 그려지는 화면 밖에 있고, 다시 그릴 때 입력창의 커서를 유지한다. 채팅 화면에도 탭을 보여 주므로 **팟캐스트** 탭의 배지를 바로 보고 누를 수 있다. 공지와 답 아래 빈 자리도 그 탭으로 연결된다. 글자가 아주 크거나 화면이 낮으면 입력창을 아래에 고정하지 않는다.
- **확인:** 서버 테스트가 스트리밍을 다룬다. 화면 상태는 저장소 밖 도구로 헤드리스 브라우저에서 확인했다. `ask()`(300초 중단, 동시 검색 제한, JSON·릴레이 대체 흐름)에는 자동 테스트가 없다.

## 프로젝트 책임자 판단 질문

1. 백그라운드 검색 중에는 새 코치 질문이 기다린다. 서버가 프로세스당 요청 하나만 처리해서, 보내면 busy로 거절되기 때문이다. 이 기본값을 유지할까요, 아니면 질문을 보내게 하고 가끔 나오는 busy 응답을 감수할까요?
