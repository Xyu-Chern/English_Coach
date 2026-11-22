# Phrase Room

The web client and the Android app share the files in `web/`. Search eight offline situations in Chinese, Korean or English, read the original podcast quote and its license, and keep bookmarks and recent questions on the current device. Online coaching uses the existing ExpressionCoach and the local PostgreSQL transcript index.

## Run and install

From the repository root, configure the existing transcript database, local embedding weights and model in the demo environment. For Claude set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and `LLM_MODEL`; for the Responses provider set `LLM_PROVIDER=responses`, `RESPONSES_BASE_URL`, `RESPONSES_API_KEY` and `LLM_MODEL`; set `EMBEDDING_PROVIDER` too. `frontend/requirements.txt` includes `translation_agent_demo/requirements-local.txt` (MiniLM, faster-whisper). Start with:

```sh
uv run --python 3.11 --with-requirements frontend/requirements.txt python -m frontend.server
```

Open `http://127.0.0.1:8787`. Select **问教练** for a model answer. Library searches work offline after the web app has cached its assets. Private HTTPS hosting also supports adding the web app to the iPhone home screen through Safari. Locally there is no daily cap unless `COACH_DAILY_LIMIT` is set.

Build the Android package with Linux or WSL, JDK 17 and Android SDK Platform/Build Tools 35. The script signs a development APK with the local debug key. Use Settings in the web client to download the built APK.

```sh
ANDROID_HOME=/path/to/android-sdk bash frontend/android/build.sh
adb install -r frontend/android/build/PhraseRoom.apk
```

Android 1.3 uses the teammate's Vercel origin in the app. That backend bundle is generated from the repository root using `python -m frontend.vercel.package` in WSL. Set `RESPONSES_API_KEY` as a Vercel production secret before deploying the generated directory.

The teammate's live Vercel app serves the chat UI, Android download and coach at the same HTTPS origin. Its deployment includes 185 reviewed passages, their vectors and the MiniLM encoder; it computes the query vector and calls the Responses gateway. Anyone can ask a question directly, and the computer can be off. Publish a new snapshot when transcripts or rights change. Our own Vercel project is separate: see **Own Vercel deployment**.

## Staged answers, mode and request log

`POST /api/search` takes `{question, context}`. By default it returns one JSON reply, as before: `{"expressions": [...], "note": ...}`. Installed APKs keep working. A client that sends `Accept: application/x-ndjson` gets one JSON object per line instead:

| Line | When | Fields |
|---|---|---|
| `quick` | Optional, before any other line: the quick model call answered within 3 s of the request (target: 2 s). Not sent when it fails, is late or declines | `text`: one natural English expression. `note`: a short note in the learner's language. A generated suggestion with no source, not a verified example |
| `first` | The first stage verified 1–3 examples | `expressions`: verified examples only, which never change. `pending`: `false` means nothing follows. `note` |
| `final` | After the continuation. It is the only line when nothing was verified first or the request was declined | `expressions`: after a `first`, the `first` items and then only examples verified later; without a `first`, the whole answer. `added`: indexes of examples verified later. `note` |
| `error` | In place of `final` | `code`: `timeout`, `coach_unavailable` or a coach code such as `model_unavailable` |

Refusals are plain HTTP errors and come before any line: 401 or 403 `pairing_required`, 403 `origin_denied`, 422 `invalid_input`, 429 `coach_busy`, and with a daily cap 429 `daily_limit` or 503 `daily_limit_unavailable`. The JSON reply is the whole last answer, as old clients expect, so it can include unverified candidates that the stream leaves out after a `first`. If the continuation fails after the first stage verified examples, the reply still returns them. The JSON reply has no quick translation.

- **Quick translation and parallel searches:** the server starts the quick call next to the candidate call. `COACH_QUICK_MODEL` and `COACH_QUICK_PROVIDER` pick its model and provider; without them it uses `LLM_MODEL` and `LLM_PROVIDER`. It is not a slot: it does not count toward the three expressions and never changes the `first` items (D1). The local server and the Vercel function both send it. Searches run at the same time to shorten the wait for `first`; each trace step records `started_ms`. `COACH_SEARCH_WORKERS` (1–9, default 6) sets how many run at once; `1` runs them one after another, and any other value stops the start. Locally each search that runs at the same time gets its own database connection. Measured times are in `design.md` (Faster first answer).
- **Fast first stage (PR ⑦):** with `COACH_FIRST_STAGE=fast` (the app's default) the candidate call streams 3 candidates with short notes; each candidate is searched as soon as it is complete, then gets its own short selection call over at most 3 spans per passage cut to 300 characters around the key phrase (Claude Haiku 5.5 without thinking). 0.4 s after the first verified example, `first` is sent and empty slots go to the continuation. `first` came in 4.1 s at p50 (`full`: 14.6 s), quick in about 1 s, with fewer verified examples at once; the 1–2 s goal is not met (details in `design.md`, Fast first stage). Settings, read at the start (any other value stops it): `COACH_FIRST_STAGE` = `fast` or `full` (the evaluated first stage: 6 candidates, frozen prompts; the evaluation always runs it); for `fast`, `COACH_FIRST_CANDIDATES` (3–6, default 3), `COACH_FIRST_SPANS` (1–12, default 3) and `COACH_FIRST_SPAN_CHARS` (120–800, default 300). No setting turns the parallel path off; the rollback is `full`. Apply migration `014_corpus_text_trgm.sql` for the faster literal search. On Vercel, change settings under Settings → Environment Variables and redeploy.
- **Mode:** `COACH_SYSTEM` is `agent` (the locked agent, the default) or `baseline`. `COACH_CONTINUATION` is `on` (the default) or `off`. `off` runs the first stage only, a setting that was not evaluated. The server reads both when it starts, and any other value stops the start. Locally, set them before the start, for example `COACH_SYSTEM=baseline python -m frontend.server --port 8790`. With a database, a mode switched on `/admin` wins over `COACH_SYSTEM` without a redeploy (see **Live request log and mode switch**). Without one, change `COACH_SYSTEM` on Vercel under Settings → Environment Variables, then redeploy.
- **Limits:** the work stops 280 s after the request starts, because Vercel's `maxDuration` is 300 s. A stream then ends with an `error` line whose code is `timeout`. The local server takes `--deadline` or `COACH_DEADLINE_SECONDS` (1–3600 s) for a slow provider or the relay. One request runs per process. If the client leaves, the work stops at its next model call or search; the slot returns only when the work has stopped, and the log line and the row are still written.
- **Daily cap:** `COACH_DAILY_LIMIT` (unset by default: no cap) limits requests per day for all learners together, counted in the database table `coach_daily_usage`; `COACH_DAILY_TZ` (default `Asia/Seoul`) sets when the day starts. Each request that passes the access, input and busy checks counts once, before any model call. Over the cap: 429 `daily_limit`. With a cap but no database: 503 `daily_limit_unavailable` for every request. Replies carry `X-Coach-Daily-Limit` and `X-Coach-Daily-Remaining`. Our deployment uses 10 (`design.md`, Daily cap).
- **Request log:** each request that passes the access checks prints one JSON line to stdout. On Vercel, search the runtime logs for `coach_request`. Vercel keeps runtime logs for 1 hour on Hobby and 1 day on Pro. With a database, the request is also saved as one row with the whole question (see **Live request log and mode switch**).

| Field | Meaning |
|---|---|
| `event`, `ts`, `request_id` | `coach_request`, the start time (UTC) and a random id |
| `mode`, `mode_source`, `continuation_setting`, `transport` | `agent` or `baseline`; `db` or `env`; `on` or `off`; `ndjson` or `json` |
| `first_stage` | `full`, or `fast/<candidates>c/<spans>s/<characters>/p` (default `fast/3c/3s/300/p`; `/p` means parallel); stdout only, not a database column |
| `status`, `error_code` | One of `ok`, `declined`, `invalid_input`, `busy`, `daily_limit`, `error`, `timeout`, `disconnected`; the error code |
| `verified_first`, `added_final`, `verified_final` | Examples the first stage verified; examples verified after a `first` (0 without one); verified examples the learner ends with |
| `continuation`, `invariant_ok` | `skipped` (all verified), `ran`, `off` or `none` (declined or failed in the first stage); whether the final answer kept the `first` items |
| `quick_ms` | Milliseconds to the `quick` line; `null` when none was sent. A generated suggestion, so not the first answer |
| `first_ms`, `total_ms` | Milliseconds to the `first` line (`ndjson` only; `null` without one and on `json`, whose client sees nothing before the end) and to the end. Time to the first answer is `first_ms`, or `total_ms` when it is `null` |
| `llm_calls`, `searches`, `input_tokens`, `output_tokens`, `cached_input_tokens` | Model calls and searches attempted; tokens the provider reported |
| `disconnected`, `question_head` | Whether the client left early; the first 40 characters of the question, without the context or the answer |

## Learner app: staged answers

The web and Android client asks for NDJSON (`Accept: application/x-ndjson, application/json;q=0.9`). When a server answers with JSON instead (an older deployment, or the relay's `202` jobs), the client uses the previous one-reply flow. Installed APKs keep the JSON flow; rebuild the APK to ship this client. The service worker cache is `phrase-room-shell-v11`.

| What arrives | What the learner sees |
|---|---|
| Nothing yet | The waiting line with elapsed seconds. After 30 s it says that finding examples takes a little longer |
| `quick` | The quick translation and its note at once, marked as a generated suggestion that is not a podcast example. The waiting line stays until `first` or `final` |
| `first` with `pending: false` | The verified examples as the answer. No notice |
| `first` with `pending: true` | Only the verified examples, an empty "searching" slot under them, and a notice above the chat: **Looking for more podcast examples** · keep this screen open and you will be told when it ends |
| Then `final` | The chat answer does not change. Examples at the `added` indexes go to the **Podcast** tab, which gets a badge. The slot and the notice point there. If nothing was added, both say so |
| Then `error` or a broken stream | The first examples stay. The notice and the slot offer **Look again**, without the error colour |
| `final` only | The whole answer at once, as before. Items without a verified example keep the "quote not confirmed yet" line |
| `error` only, or an HTTP refusal | The existing error line with **Retry** |
| 429 `daily_limit` | A Chinese or Korean message that today's questions (with the daily number) are used up; try again tomorrow |

- **Records:** the device history keeps each answer's first items, the added items and a stage (`pending`, `done`, `stopped` or `incomplete`). The history page shows both groups, and cards from either can be saved. A follow-up question's context still uses the first item.
- **Leaving the page:** the server keeps no answer for the learner to fetch later (D5); a saved log row is for `/admin` only. On the next start, a record that is still `pending` becomes `incomplete`. A notice then offers **View first results** and **Look again**, which sends the same question with the context it sent before.
- **One search at a time:** the server answers one request per process, so a new coach question waits until the background search ends. The question box says so. Library searches are not held.
- **Daily count:** with a cap, the line under the question box shows today's remaining questions.
- **Accessibility and layout:** one polite live region speaks only when an answer arrives: the first examples and the end of the search. The notice sits outside the redrawn page, and a redraw keeps the cursor in the question box. The tabs are visible on the chat page too, so the **Podcast** tab's badge can be seen and tapped at once; the notice and the slot under the answer also link to it. With large text or a short screen, the question box no longer sticks to the bottom.
- **Checks:** server tests cover the stream; the screen states were checked in a headless browser with tools kept outside the repository. `ask()` (the 300 s abort, the running limit, the JSON and relay fallbacks) has no automated test.

## Podcast audio clips

A card with a verified podcast citation can play its passage from the publisher's audio file. The contract (fields, position order, `GET /api/audio/alignment`), the local coverage figures and the known gaps are in `design.md` (**Podcast audio clips**).

**Setup, once per database.** Migrations 010–014 are not in `initialize_schema` or `compose.yaml`, so apply them by hand; the local server creates 011 itself, and 012 is intentionally unused. Run from the repository root. Put `uv run --python 3.11 --with-requirements translation_agent_demo/requirements.txt` right before `python` for the jobs, and `--with-requirements frontend/requirements.txt` for `frontend.audio_align` (it needs faster-whisper). The demo settings hold the database URL and the free Podcast Index key.

```sh
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/010_episode_audio.sql
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/013_transcript_time_anchors.sql
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/014_corpus_text_trgm.sql   # faster literal search
python -m translation_agent_demo.jobs.podcast_audio backfill --dry-run    # count episodes without audio
python -m translation_agent_demo.jobs.podcast_audio backfill [--feed-ids 1,2] [--interval 0.5]
python -m translation_agent_demo.jobs.podcast_audio anchors [--dry-run]   # transcript time markers
python -m frontend.audio_align <chunk_id>... [--ids-file FILE]            # optional: align chunks ahead of time
```

| Setting | Meaning |
|---|---|
| `COACH_AUDIO_ALIGN` | `on` (the local default) or `off`. Speech recognition also needs faster-whisper and the database, so it never runs on Vercel |
| `COACH_ALIGN_MODEL` | The faster-whisper model, default `base.en` |

- **Backfill:** reads one archive page per feed, then looks up the remaining episodes one by one (`/episodes/byid`), `--interval` seconds apart and at most 3,000 requests. It stops on 401/403 and prints counts only. After that, `podcast_sync` keeps the enclosures of every page it fetches; without migration 010 it skips them and the sync goes on.
- **Anchors:** stores the publisher's time markers of every ready build of the searchable processing version. It is local and idempotent: unchanged documents are not written.
- **Positions:** a stored alignment (ASR or cue timing) first, then interpolation between the time markers, then the character position × the episode duration. Each citation carries `audio_url`, `audio_start_ms`, `audio_end_ms` and `audio_estimated`; `null` and `false` mean no audio. The local server answers `GET /api/audio/alignment` from the markers at once and aligns the chunk in the background (two workers); a stream queues its cited chunks before the learner presses play.
- **Player:** **听这一段 / 이 부분 듣기** opens one shared player under the card; **■ 关闭 / 닫기** closes it. It loops by default. The range is the quote, all lines or one tapped line. The speed is 0.75×, 1× or 1.25× and is remembered. Captions follow the spoken line. An estimated start shows **大致位置 / 대략 위치 · m:ss**. Without an alignment answer, it plays the citation's range or 20 s from its start. Changing tabs stops playback, and a file that cannot play shows a short notice. The single `<audio preload="none">` loads nothing until the learner taps, and the service worker does not cache audio.
- **Snapshots:** both packagers add the four fields to each passage in `passages.json` and the saved alignments of the bundled chunks to `corpus/alignments.json`, which the Vercel function serves without recognition. Align the chunks first to give them exact positions.
- **Licence:** the app plays the publisher's file from its original URL and never downloads, caches or redistributes it. The transcript licence does not cover the audio, which stays under the publisher's own terms.
- **Checks:** unit tests cover the positions, the time markers, the alignment answers, the search fields, the citation and the snapshots. Recognised and marker-timed clips played from the publishers' files in headless Chrome. 16 sampled URLs answered a Range request with 206.

## Admin page (/admin)

The admin page is open for viewing (D4): anyone with the address can see it, and the page says so. It ships in the same deployment as the app. Its evaluation data is one run's record, `data.json` built by `frontend/admin_data.py`. With a database, it also shows live requests and switches the mode (see **Live request log and mode switch**).

| Where | Page | Data |
|---|---|---|
| Local server | The admin page folder (`frontend/admin/`) at `/admin/` | `/admin/data.json`, plus `data-traces.json` when split, from the same folder |
| Local preview | `COACH_ADMIN_DIR=<page folder>` | `COACH_ADMIN_DATA=<folder with data.json>` |
| Vercel | `public/admin/`, static files | built into `public/admin/` by the packager |

The page is design B (Phrase Room brand) with design A's route map and design C's swimlane timeline (D7). It has four tabs:

| Tab | What it shows |
|---|---|
| **Mode comparison** | `baseline` and `agent` from the same run, side by side on the same measures, with the mode the data was built for |
| **Request log** | Every run request with status, examples, timings, tokens, follow-up and lock marks. No user column (D3) |
| **Metrics** | p50 · p95 · p99 of time and tokens. Final time compares only the tasks where both modes ran a follow-up |
| **Run graph** | One request as a route map of the components, a swimlane timeline and a step detail panel |

- **Languages:** a switch in the header shows the page in Korean, Chinese or English. `?lang=ko|zh|en` picks one for a link and is not saved; a choice in the header is saved in the browser. Korean is the default.
- **Rules for any design:** read `data.json` by relative URL, and show only a version message when `meta.schema_version` is not 1. The page writes text with `textContent` and DOM calls only, and keeps its Content-Security-Policy. Web fonts load from jsdelivr with SRI, and system fonts are used when they are blocked. Every `/admin` response is `noindex`.
- **Data builder safety:** `frontend/admin_data.py` keeps only allowlisted fields of each trace step and stops, writing nothing, when the output holds a secret-like value (API keys, tokens, PEM blocks, database URLs with a password) or a local home path.
- **Paths:** a page reads `data.json` relative to itself, so `/admin` redirects to `/admin/` (local server and `vercel.json`). A folder named by a variable must exist, and a data folder must hold `data.json`. Otherwise the server does not start.
- **Packaging:** `python -m frontend.vercel.package --admin-run <run> --admin-results <results root>` builds the data in the deployment's mode: `--coach-system`, else `COACH_SYSTEM`, else `agent`. `COACH_ADMIN_RUN` and `COACH_ADMIN_RESULTS` work too. Without a run, the packager ships `frontend/admin/data.json` if it exists, or no data, and prints which. It always removes an older package's data first. The packaging machine therefore needs the run folder or a committed `frontend/admin/data.json` (judgment question 2). Our own package takes a prebuilt file with `--admin-data`.
- **Size:** the admin files are static and add nothing to the function. The data of the submission run adds 2.9 MB to `public/` (0.26 MB gzip).
- **Preview package:** `--skip-apk` and `--skip-search-data` build without the Android SDK, the corpus or the encoder. They need an `--out` other than the deploy folder, and such a package cannot answer questions.
- **Known gaps:** the teammate's corpus export still uses `sudo -u postgres psql` (WSL). Its schema `evaluation_zh_local_v1` is not in the macOS Docker database, so build that package in WSL for now. Server tests check that the page is served and follows the rules above; the page's JavaScript has no automated test and was checked in a browser.

### Check with real data on local ports

Build the data once from a run, then start one server per design or mode on its own port. Run each line from the repository root, with `uv run --python 3.11 --with-requirements frontend/requirements.txt` placed right before `python`. For the re-evaluation, `<run>` is its folder under `evaluation/results`: `lock-20261122`.

```sh
python -m frontend.admin_data --results evaluation/results --run <run> --tasks evaluation/data/tasks.jsonl --out <data folder>
COACH_ADMIN_DATA=<data folder> python -m frontend.server --port 8788
COACH_ADMIN_DATA=<data folder> COACH_ADMIN_DIR=<design folder> python -m frontend.server --port 8789
COACH_SYSTEM=baseline COACH_ADMIN_DATA=<data folder> python -m frontend.server --port 8790
```

- Each port serves the learner app at `/` and the admin page at `/admin/`. Port 8788 shows `frontend/admin`, 8789 another design folder, and 8790 the learner app on the baseline.
- Opening `/admin/` asks the coach nothing, so it needs no model settings. The live requests and the mode switch use the database when one is set. A question in the learner app is a paid model call and needs the settings from **Run and install**.
- The evaluation data shows the mode it was built with: `--coach-system`, else `COACH_SYSTEM`, else `agent`.

## Live request log and mode switch

With a database, the server saves every coach request and reads the mode from it. Without one, both are off and the app works as before. Contracts are in `design.md` (Mode and request log, Admin API).

- **Database URL:** `COACH_LOG_DATABASE_URL`, else `DATABASE_URL`, else `POSTGRES_URL`. Locally the `.env` `DATABASE_URL` (Docker Postgres) is picked up with no extra step. At start the server creates `coach_request_log`, `coach_settings`, `coach_mode_changes` and `coach_daily_usage` if they are missing. `frontend/sql/request_log.sql` holds the same SQL.
- **Mode in effect:** the database's `coach_system` setting, else `COACH_SYSTEM`, else `agent`. It is cached for 10 s, and a database error falls back to `COACH_SYSTEM`. `GET /admin/mode` shows the mode, its source (`db` or `env`) and the switch history.
- **Admin token:** `COACH_ADMIN_TOKEN` requires the header `X-Admin-Token` on `POST /admin/mode`. On Vercel without it, the switch is off (403 `admin_token_required`, `"writable": false`); a local server without it stays open. Viewing stays open.
- **Public data:** questions are saved as written and `/admin` is open, so anyone with the address can read them. Rows are kept for the course period, then deleted by the owner (the D2/D4 exception in `design.md`).

| Saved column | Meaning |
|---|---|
| `id`, `created_at` | Row number and time saved |
| `mode`, `mode_source`, `transport` | `agent` or `baseline`; `db` or `env`; `ndjson` or `json` |
| `status`, `error_code` | As in the stdout line |
| `question` | The whole question, as written |
| `quick_ms`, `first_ms`, `total_ms` | Time to the `quick` line (`null` when none was sent); time to the `first` line (`null` without one); time to the end |
| `llm_calls`, `searches`, `input_tokens`, `output_tokens` | As in the stdout line |
| `verified_first`, `added_final`, `verified_final`, `continuation` | As in the stdout line |
| `result` | JSON with the answer's expressions and the trace, which `/admin` turns into the request log and run graph |

```sh
curl -s 'http://127.0.0.1:8787/admin/requests.json?limit=20'
curl -s http://127.0.0.1:8787/admin/mode
curl -s -X POST -H 'Content-Type: application/json' -H "X-Admin-Token: $COACH_ADMIN_TOKEN" \
  -d '{"mode": "baseline"}' http://127.0.0.1:8787/admin/mode
```

### Owner setup on Vercel (Neon, free)

The free Hobby plan cannot invite members, so the project owner does this once per Vercel project in the dashboard:

1. Open the project → **Storage** (or **Integrations** → **Browse Marketplace**) → **Neon** → create the database on the **Free** plan and connect it to this project, for Production and Preview.
2. Leave the variable prefix empty. Under **Settings → Environment Variables**, check the names Neon added. `DATABASE_URL` or `POSTGRES_URL` works as is. If needed (for example, the name is used for something else), add `COACH_LOG_DATABASE_URL` with the same connection string.
3. Add `COACH_ADMIN_TOKEN` (a long random value); without it the mode switch stays off on Vercel.
4. **Redeploy**. New variables reach only new deployments.
5. Check: `GET /admin/mode` shows `"writable": true`, and after one question `GET /admin/requests.json` lists it.

Locally nothing is needed: the Docker Postgres from `.env` is used.

## Own Vercel deployment

A new Vercel project, separate from the teammate's. It bundles all 36,397 approved Changelog chunks with MiniLM vectors, audio positions and precomputed ASR alignments, about 461 MB against Vercel's 500 MB Python limit. Contents and size are in `design.md` (Own Vercel deployment). The package was built and checked locally and is not deployed.

**Rebuild (we run it).** Put `uv run --python 3.11 --with-requirements frontend/requirements.txt` right before `python`. `<run>` is the D6 run folder (`…/evaluation/results/lock-20261122`).

```sh
python -m frontend.vercel.own_snapshot align --run <run>                              # exact ASR positions of cited chunks; skips saved ones
python -m frontend.vercel.own_snapshot package --run <run> --admin-data <data.json>   # into frontend/.local/vercel-phrase-room-own
```

The output holds the web app (`public/`, no APK), `/admin` with the D6 data, the function `api/search.py` (from `frontend/vercel/own_index.py`), the corpus, the encoder and `vercel.json` (`maxDuration` 300).

**Owner steps** (from the repository root; never send secret values to anyone):

1. `npx vercel login` (browser sign-in, owner only).
2. `npx vercel --cwd frontend/.local/vercel-phrase-room-own`. Answers: set up and deploy → `Y`; scope → your account; link to an existing project → `N` (not the teammate's); name → for example `phrase-room-own`; directory → `./`; modify settings → `N`.
3. Attach Neon to the new project as in **Owner setup on Vercel**. Keep the name `DATABASE_URL`. The function creates the request log, mode and daily count tables on its first start.
4. Add the production variables from the package folder: `npx vercel env add <NAME> production` for `ANTHROPIC_API_KEY` (owner pastes the key), `COACH_ADMIN_TOKEN` (for example the output of `openssl rand -hex 24`), `LLM_PROVIDER` (`anthropic`), `LLM_MODEL` (`claude-haiku-5-5`) and `COACH_DAILY_LIMIT` (`10`). Add `COACH_DAILY_LIMIT` only after Neon is attached: with a cap and no database every question is 503. `COACH_DAILY_TZ` defaults to Asia/Seoul. Without `LLM_PROVIDER`/`LLM_MODEL` the function also uses anthropic and claude-haiku-5-5.
5. `npx vercel --prod --cwd frontend/.local/vercel-phrase-room-own`. After a rebuild, repeat only this step.
6. Check `https://<domain>/`, `/admin/`, `/admin/data.json`, and `/api/audio/alignment?chunk_id=<chunk>&quote=<quote>` (an aligned chunk answers `"status":"ready","method":"asr"`). After one question, the request shows in the live log on `/admin/` and the reply's `X-Coach-Daily-Remaining` is 9.

**Risks:** if the upload is over the size limit, repackage with `--max-mb 400` (or less), which keeps whole episodes, the most cited first. The Hobby CLI upload limit is unclear (documented as 100 MB, while a 2026-06-17 changelog removed the CLI-only limit); this package uploads about 260 MB, and Pro may be needed. The web app's APK link is 404 here. The literal search scans the 36k chunks in Python (about 1.2 s per search). The package holds the files of build time, so repackage after the admin page work lands.

## Project Owner Judgment Questions

1. While a background search runs, a new coach question waits, because the server answers one request per process and would refuse it as busy. Keep this default, or let the question go and accept an occasional busy reply?
2. Should `frontend/admin/data.json` from the locked re-evaluation run be committed? It is about 3 MB and holds the evaluation questions verbatim. Committing it lets any machine package the same `/admin`. Otherwise it is built at packaging time from the git-ignored results folder, which exists on one machine only. Recommended: commit that one file.
3. **Owner action:** deploy our own Vercel project and attach Neon as in **Own Vercel deployment**. Until Neon is attached, a deployment keeps only the stdout line, and `/admin` cannot switch the mode. The admin token and how long questions are kept are settled (`design.md`, decision log).

# 中文

网页和 Android App 共用 `web/`。可以用中文、韩文或英文查找八个离线场景，查看播客原句、节目和许可。收藏与提问记录只保存在当前设备。在线教练使用项目已有的 ExpressionCoach 和本地 PostgreSQL 字幕库。

## 启动与安装

从仓库根目录启动。先按项目原有方式准备字幕库和本地向量模型，并在 Demo 设置中配置模型。使用 Claude 时设置 `LLM_PROVIDER=anthropic`、`ANTHROPIC_API_KEY` 和 `LLM_MODEL`；使用 Responses 服务时设置 `LLM_PROVIDER=responses`、`RESPONSES_BASE_URL`、`RESPONSES_API_KEY` 和 `LLM_MODEL`；同时设置 `EMBEDDING_PROVIDER`。`frontend/requirements.txt` 包含 `translation_agent_demo/requirements-local.txt`（MiniLM、faster-whisper）。

```sh
uv run --python 3.11 --with-requirements frontend/requirements.txt python -m frontend.server
```

打开 `http://127.0.0.1:8787`，选「问教练」即可提交场景。网页缓存完成后可离线查表达。iPhone 可在 Safari 打开 HTTPS 网页，从分享菜单添加到主屏幕。本地不设置 `COACH_DAILY_LIMIT` 时没有每日上限。

Android 构建需要 Linux 或 WSL、JDK 17 和 Android SDK Platform/Build Tools 35。脚本用本地开发签名生成 APK，可从网页「连接设置」下载。

```sh
ANDROID_HOME=/path/to/android-sdk bash frontend/android/build.sh
adb install -r frontend/android/build/PhraseRoom.apk
```

Android 1.3 直接访问队友的 Vercel，打开即可提问。更新这个后端时，从仓库根目录在 WSL 运行 `python -m frontend.vercel.package`。部署生成的目录前，在 Vercel 的生产环境配置 `RESPONSES_API_KEY`。

队友的线上 Vercel 应用在同一个 HTTPS 网址同时提供聊天首页、Android 安装包和教练接口。它的部署携带 185 个字幕片段、对应向量与 MiniLM 编码器，在云端计算问题向量并调用 Responses 网关。手机打开即可提问，电脑可以关机。字幕或使用许可发生变化时需重新发布快照。我们自己的 Vercel 项目是独立的，见 **自有 Vercel 部署**。

## 分阶段回答、模式与请求日志

`POST /api/search` 接收 `{question, context}`。默认仍返回一个 JSON 回复：`{"expressions": [...], "note": ...}`，已安装的 APK 可以照常使用。客户端发送 `Accept: application/x-ndjson` 时，改为每行返回一个 JSON 对象：

| 行 | 何时 | 字段 |
|---|---|---|
| `quick` | 可选，在所有其他行之前：快速模型调用在请求开始后 3 秒内返回（目标 2 秒）。失败、超时或拒绝回答时不发送 | `text`：一个自然的英语表达。`note`：用学习者语言写的简短说明。这是没有出处的生成建议，不是核对通过的例句 |
| `first` | 第一阶段核对了 1–3 个例句 | `expressions`：只有核对通过的例句，之后不会改变。`pending`：`false` 表示后面没有内容。`note` |
| `final` | 后续阶段结束后。第一阶段一个都没核对或请求被拒绝时，只有这一行 | `expressions`：有 `first` 时，先是 `first` 的条目，之后只有后来核对通过的例句；没有 `first` 时是完整答案。`added`：后来核对通过的例句序号。`note` |
| `error` | 代替 `final` | `code`：`timeout`、`coach_unavailable` 或 `model_unavailable` 等教练错误码 |

拒绝是普通 HTTP 错误，在任何行之前返回：401 或 403 `pairing_required`、403 `origin_denied`、422 `invalid_input`、429 `coach_busy`；设置每日上限时还有 429 `daily_limit` 或 503 `daily_limit_unavailable`。JSON 回复是旧客户端期待的完整最终答案，所以有 `first` 时，它可能包含流中省略的未核对候选。第一阶段已核对例句后，即使后续阶段失败，回复仍会返回这些例句。JSON 回复不含快速翻译。

- **快速翻译与并行检索：** 服务端在候选调用旁边同时发起快速调用。`COACH_QUICK_MODEL` 和 `COACH_QUICK_PROVIDER` 指定它的模型和服务商；未设置时使用 `LLM_MODEL` 和 `LLM_PROVIDER`。它不是位置（slot）：不计入三个表达，也不会改变 `first` 的条目（D1）。本地服务和 Vercel 函数都会发送它。检索同时进行，以缩短到 `first` 的等待；每个 trace 步骤都记录 `started_ms`。`COACH_SEARCH_WORKERS`（1–9，默认 6）决定同时进行几个检索；`1` 表示逐个进行，其他值会让启动失败。在本地，同时进行的每个检索各用一个数据库连接。实测时间见 `design.md`（更快看到第一个回答）。
- **快速第一阶段（PR ⑦）：** `COACH_FIRST_STAGE=fast`（应用默认）时，候选调用以流式返回 3 个带简短说明的候选；每个候选一完整就开始检索，再单独做一次简短选择调用，每段最多 3 个片段，围绕关键短语截成 300 个字符（Claude Haiku 5.5 不思考）。第一个例句核对通过 0.4 秒后发送 `first`，空位置交给后续阶段。`first` 的 p50 为 4.1 秒（`full` 为 14.6 秒），quick 约 1 秒，但一次核对通过的例句更少；未达到 1–2 秒的目标（细节见 `design.md` 的“快速第一阶段”）。设置在启动时读取（其他值会让启动失败）：`COACH_FIRST_STAGE` 为 `fast` 或 `full`（评估过的第一阶段：6 个候选、冻结的提示词；评估始终运行它）；`fast` 时还有 `COACH_FIRST_CANDIDATES`（3–6，默认 3）、`COACH_FIRST_SPANS`（1–12，默认 3）和 `COACH_FIRST_SPAN_CHARS`（120–800，默认 300）。没有关闭并行路径的设置，回退方式是 `full`。执行迁移 `014_corpus_text_trgm.sql` 可加快字面检索。在 Vercel 上到 Settings → Environment Variables 修改后重新部署。
- **模式：** `COACH_SYSTEM` 为 `agent`（加锁的 agent，默认）或 `baseline`。`COACH_CONTINUATION` 为 `on`（默认）或 `off`。`off` 只运行第一阶段，这一设置没有经过评估。服务启动时读取这两个值，其他值会让启动失败。在本地，启动前设置即可，例如 `COACH_SYSTEM=baseline python -m frontend.server --port 8790`。有数据库时，在 `/admin` 切换的模式优先于 `COACH_SYSTEM`，无需重新部署（见 **线上请求日志与模式切换**）。没有数据库时，到 Vercel 的 Settings → Environment Variables 修改 `COACH_SYSTEM`，然后重新部署。
- **限制：** 请求开始 280 秒后停止工作，因为 Vercel 的 `maxDuration` 是 300 秒。此时流以 `code` 为 `timeout` 的 `error` 行结束。本地服务可用 `--deadline` 或 `COACH_DEADLINE_SECONDS`（1–3600 秒）应对较慢的服务商或中继。每个进程同时只处理一个请求。客户端离开后，工作会在下一次模型调用或检索前停止；请求名额要等工作真正停止后才归还，日志行和数据库行照常写入。
- **每日上限：** `COACH_DAILY_LIMIT`（默认不设置，即没有上限）限制所有学习者合计每天的请求数，计数保存在数据库表 `coach_daily_usage` 中；`COACH_DAILY_TZ`（默认 `Asia/Seoul`）决定一天从何时开始。通过访问、输入和繁忙检查的每个请求在任何模型调用之前计一次。超过上限：429 `daily_limit`。设置了上限但没有数据库：每个请求都返回 503 `daily_limit_unavailable`。回复带有 `X-Coach-Daily-Limit` 和 `X-Coach-Daily-Remaining`。我们的部署用 10（`design.md` 的“每日上限”）。
- **请求日志：** 每个通过访问检查的请求都向 stdout 打印一行 JSON。在 Vercel 上，可在运行日志中搜索 `coach_request`。Vercel 运行日志在 Hobby 计划保留 1 小时，在 Pro 计划保留 1 天。有数据库时，请求还会连同完整问题保存为一行（见 **线上请求日志与模式切换**）。

| 字段 | 含义 |
|---|---|
| `event`、`ts`、`request_id` | `coach_request`、开始时间（UTC）和随机 ID |
| `mode`、`mode_source`、`continuation_setting`、`transport` | `agent` 或 `baseline`；`db` 或 `env`；`on` 或 `off`；`ndjson` 或 `json` |
| `first_stage` | `full`，或 `fast/<候选数>c/<片段数>s/<字符数>/p`（默认 `fast/3c/3s/300/p`；`/p` 表示并行）；只在 stdout 中，不是数据库列 |
| `status`、`error_code` | `ok`、`declined`、`invalid_input`、`busy`、`daily_limit`、`error`、`timeout`、`disconnected` 之一；错误码 |
| `verified_first`、`added_final`、`verified_final` | 第一阶段核对的例句数；`first` 之后新增的例句数（没有 `first` 时为 0）；学习者最终拿到的已核对例句数 |
| `continuation`、`invariant_ok` | `skipped`（全部已核对）、`ran`、`off` 或 `none`（被拒绝或第一阶段失败）；最终答案是否保留了 `first` 的条目 |
| `quick_ms` | 到 `quick` 行的毫秒数；没有发送时为 `null`。它是生成的建议，不算首次看到的答案 |
| `first_ms`、`total_ms` | 到 `first` 行的毫秒数（只有 `ndjson` 才有；没有 `first` 时以及 `json` 时为 `null`，因为 `json` 客户端在结束前什么也看不到）和到结束的毫秒数。首次看到答案的时间是 `first_ms`，为 `null` 时是 `total_ms` |
| `llm_calls`、`searches`、`input_tokens`、`output_tokens`、`cached_input_tokens` | 尝试的模型调用和检索次数；服务商报告的 token 数 |
| `disconnected`、`question_head` | 客户端是否提前离开；问题的前 40 个字符，不含场景和答案 |

## 学习端：分阶段显示

网页和 Android 客户端请求 NDJSON（`Accept: application/x-ndjson, application/json;q=0.9`）。如果服务端仍返回 JSON（旧部署，或中继的 `202` 任务），客户端沿用原来的一次性回复流程。已安装的 APK 继续使用 JSON 流程；要发布这一客户端，需要重新构建 APK。Service worker 缓存为 `phrase-room-shell-v11`。

| 收到的内容 | 学习者看到的内容 |
|---|---|
| 还没有内容 | 等待提示和已等待的秒数。30 秒后提示查找例句需要多一点时间 |
| `quick` | 立即显示快速翻译及其说明，并标明这是生成的建议，不是播客例句。等待提示保留到 `first` 或 `final` 到达 |
| `first`，`pending: false` | 核对通过的例句作为回答。没有提示条 |
| `first`，`pending: true` | 只显示核对通过的例句，下方有一个“正在查找”的空位，聊天上方显示提示条：**正在查找更多播客例句** · 保持此页面打开，找到后会告诉你 |
| 随后收到 `final` | 聊天里的回答不变。`added` 序号对应的例句放进 **播客** 页，该标签显示徽标。空位和提示条都指向那里。如果没有新增，两处都会说明 |
| 随后收到 `error` 或流中断 | 先前的例句保留。提示条和空位提供 **重新查找**，不使用错误颜色 |
| 只有 `final` | 和以前一样一次显示完整回答。没有核对到例句的条目仍显示“暂时没有核对到播客原句” |
| 只有 `error`，或 HTTP 拒绝 | 原有的错误提示和 **重试** |
| 429 `daily_limit` | 用中文或韩文提示今天的提问次数（附每日次数）已用完，请明天再试 |

- **记录：** 设备上的历史为每个回答保存先前条目、新增条目和阶段（`pending`、`done`、`stopped` 或 `incomplete`）。历史页显示两组内容，两组卡片都可以收藏。后续提问的场景仍使用第一条例句。
- **离开页面：** 服务端不保存供学习者之后取回的答案（D5）；保存的日志行只供 `/admin` 使用。下次打开时，仍为 `pending` 的记录变为 `incomplete`，提示条提供 **查看先前结果** 和 **重新查找**。重新查找会用同一问题和当时发送的场景再次提问。
- **一次一个查找：** 服务端每个进程同时只处理一个请求，所以后台查找结束前，新的教练提问需要等待，输入框下方会说明。表达库搜索不受影响。
- **每日次数：** 设置了上限时，输入框下方的一行显示今天还能提问几次。
- **无障碍与布局：** 只有一个礼貌型实时区域，只在回答到达时播报：先到的例句和查找结束。提示条位于会重绘的页面之外，重绘时输入框保留光标。聊天页也显示标签栏，**播客** 页的徽标一眼可见，可以直接点开；提示条和回答下方的空位也链接到那里。字号很大或屏幕很矮时，输入框不再固定在底部。
- **检查：** 服务端测试覆盖流式传输；各个画面状态在无头浏览器中检查过，所用工具不在仓库里。`ask()`（300 秒中止、同时查找上限、JSON 和中继回退）没有自动化测试。

## 播客音频片段

带有已核实播客出处的卡片，可以播放发布者音频文件中的对应段落。接口约定（字段、位置优先顺序、`GET /api/audio/alignment`）、本地覆盖数据和已知差距见 `design.md`（**播客音频片段**）。

**每个数据库设置一次。** 迁移 010–014 不在 `initialize_schema` 或 `compose.yaml` 中，需要手动应用；本地服务会自行创建 011，编号 012 有意空缺。在仓库根目录运行。运行任务时在 `python` 前加上 `uv run --python 3.11 --with-requirements translation_agent_demo/requirements.txt`；运行 `frontend.audio_align` 时改用 `--with-requirements frontend/requirements.txt`（它需要 faster-whisper）。数据库 URL 和免费的 Podcast Index 密钥在 Demo 设置中。

```sh
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/010_episode_audio.sql
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/013_transcript_time_anchors.sql
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/014_corpus_text_trgm.sql   # 加快字面检索
python -m translation_agent_demo.jobs.podcast_audio backfill --dry-run    # 统计缺少音频的节目
python -m translation_agent_demo.jobs.podcast_audio backfill [--feed-ids 1,2] [--interval 0.5]
python -m translation_agent_demo.jobs.podcast_audio anchors [--dry-run]   # 文字稿时间标记
python -m frontend.audio_align <chunk_id>... [--ids-file FILE]            # 可选：提前对齐片段
```

| 设置 | 含义 |
|---|---|
| `COACH_AUDIO_ALIGN` | `on`（本地默认）或 `off`。语音识别还需要 faster-whisper 和数据库，所以在 Vercel 上从不运行 |
| `COACH_ALIGN_MODEL` | faster-whisper 模型，默认 `base.en` |

- **回填：** 每个节目源先读一页存档，再逐集查询剩下的节目（`/episodes/byid`），请求间隔 `--interval` 秒，最多 3,000 次请求。遇到 401/403 时停止，只输出计数。之后 `podcast_sync` 会保存它取到的每一页里的 enclosure；没有迁移 010 时跳过保存，同步照常进行。
- **时间标记：** 保存可搜索处理版本中每个就绪构建的发布方时间标记。它在本地运行，可重复执行：没有变化的文稿不会写入。
- **位置：** 先用已保存的对齐（语音识别或字幕时间），其次在时间标记之间插值，最后用字符位置 × 节目时长。每个出处带有 `audio_url`、`audio_start_ms`、`audio_end_ms` 和 `audio_estimated`；`null` 和 `false` 表示没有音频。本地服务对 `GET /api/audio/alignment` 立即用时间标记回答，并在后台对齐该片段（两个 worker）；流式回答在学习者按下播放之前，会把引用的片段排入队列。
- **播放器：** **听这一段 / 이 부분 듣기** 在卡片下方打开一个共用播放器；**■ 关闭 / 닫기** 关闭它。默认循环播放。范围可以是引用句、全部字幕行或点选的一行。速度为 0.75×、1× 或 1.25×，会被记住。字幕跟随正在说的那一行。估算的起点显示 **大致位置 / 대략 위치 · m:ss**。没有对齐回答时，播放出处给出的范围，或从起点播放 20 秒。切换标签会停止播放，文件无法播放时显示简短提示。唯一的 `<audio preload="none">` 在学习者点按前不加载任何内容，service worker 也不缓存音频。
- **快照：** 两个打包脚本都会在 `passages.json` 的每个段落中加上这四个字段，并把随包片段已保存的对齐写入 `corpus/alignments.json`，Vercel 函数不做语音识别就能用它回答。先对齐片段，才能让它们有精确位置。
- **许可：** 应用从原始 URL 播放发布者的文件，从不下载、缓存或再分发。字幕许可不涵盖音频，音频仍受发布者自己的条款约束。
- **检查：** 单元测试覆盖位置、时间标记、对齐回答、搜索字段、出处和快照。在无头 Chrome 中，语音识别和时间标记计时的片段都能从发布者文件播放。抽查的 16 个 URL 对 Range 请求都返回 206。

## 管理页（/admin）

管理页查看不设保护（D4）：知道网址的人都能查看，页面上也会说明这一点。它和应用放在同一个部署里。评估数据是一次运行的记录，即 `frontend/admin_data.py` 生成的 `data.json`。有数据库时，页面还会显示线上请求并可切换模式（见 **线上请求日志与模式切换**）。

| 位置 | 页面 | 数据 |
|---|---|---|
| 本地服务 | 管理页文件夹（`frontend/admin/`），地址 `/admin/` | 同一文件夹的 `/admin/data.json`，拆分时还有 `data-traces.json` |
| 本地预览 | `COACH_ADMIN_DIR=<页面文件夹>` | `COACH_ADMIN_DATA=<含 data.json 的文件夹>` |
| Vercel | `public/admin/`，静态文件 | 打包脚本生成到 `public/admin/` |

页面采用设计稿 B（Phrase Room 品牌），并加入设计 A 的路线图和设计 C 的泳道时间轴（D7）。共有四个标签页：

| 标签页 | 显示内容 |
|---|---|
| **模式对比** | 同一次运行中的 `baseline` 和 `agent`，按相同指标并排比较，并标出数据生成时的模式 |
| **请求日志** | 运行中的每个请求：状态、例句、耗时、token、后续阶段和锁定标记。没有用户列（D3） |
| **指标** | 耗时和 token 的 p50 · p95 · p99。最终耗时只比较两种模式都运行了后续阶段的任务 |
| **执行图** | 单个请求的组件路线图、泳道时间轴和步骤详情面板 |

- **语言：** 页头的切换按钮可将页面显示为韩文、中文或英文。`?lang=ko|zh|en` 只对该链接生效，不会保存；在页头选择的语言会保存在浏览器中。默认是韩文。
- **所有设计稿的规则：** 按相对路径读取 `data.json`；`meta.schema_version` 不是 1 时，只显示版本不符的提示。页面只用 `textContent` 和 DOM 调用写入文字，并保留内容安全策略（CSP）。网页字体通过带 SRI 的 jsdelivr 加载，被拦截时使用系统字体。所有 `/admin` 响应都是 `noindex`。
- **数据生成的安全措施：** `frontend/admin_data.py` 对每个 trace 步骤只保留允许列表中的字段；输出中含有类似密钥的值（API 密钥、令牌、PEM 块、带密码的数据库 URL）或本机 home 路径时，停止生成，什么都不写入。
- **路径：** 页面按相对路径读取 `data.json`，所以 `/admin` 会重定向到 `/admin/`（本地服务和 `vercel.json` 都如此）。变量指定的文件夹必须存在，数据文件夹必须包含 `data.json`，否则服务不会启动。
- **打包：** `python -m frontend.vercel.package --admin-run <run> --admin-results <结果根目录>` 按部署模式生成数据：先用 `--coach-system`，其次 `COACH_SYSTEM`，否则为 `agent`。也可以使用 `COACH_ADMIN_RUN` 和 `COACH_ADMIN_RESULTS`。不指定运行时，若存在 `frontend/admin/data.json` 就打包它，否则不带数据，并打印说明。打包前总会先删除旧包里的数据。因此打包的机器需要有该运行文件夹，或已提交的 `frontend/admin/data.json`（判断题 2）。我们自己的包用 `--admin-data` 接收预先生成的文件。
- **大小：** 管理页文件是静态文件，函数大小不变。提交时那次运行的数据使 `public/` 增加 2.9 MB（gzip 后 0.26 MB）。
- **预览包：** `--skip-apk` 和 `--skip-search-data` 可在没有 Android SDK、语料或编码器时打包。必须用 `--out` 指定部署文件夹以外的位置，这种包不能回答问题。
- **已知差距：** 队友的语料导出仍使用 `sudo -u postgres psql`（WSL）。它读取的 `evaluation_zh_local_v1` schema 不在 macOS 的 Docker 数据库中，目前仍需在 WSL 中生成这个包。服务端测试检查页面能被提供并遵守上述规则；页面的 JavaScript 没有自动化测试，只在浏览器中检查过。

### 在本地端口用真实数据检查

先从一次运行生成一次数据，再为每个设计稿或模式在各自端口启动一个服务。每一行都在仓库根目录运行，并在 `python` 前面加上 `uv run --python 3.11 --with-requirements frontend/requirements.txt`。检查重新评估时，`<run>` 是它在 `evaluation/results` 下的文件夹：`lock-20261122`。

```sh
python -m frontend.admin_data --results evaluation/results --run <run> --tasks evaluation/data/tasks.jsonl --out <数据文件夹>
COACH_ADMIN_DATA=<数据文件夹> python -m frontend.server --port 8788
COACH_ADMIN_DATA=<数据文件夹> COACH_ADMIN_DIR=<设计稿文件夹> python -m frontend.server --port 8789
COACH_SYSTEM=baseline COACH_ADMIN_DATA=<数据文件夹> python -m frontend.server --port 8790
```

- 每个端口都在 `/` 提供学习端，在 `/admin/` 提供管理页。8788 显示 `frontend/admin`，8789 显示另一个设计稿文件夹，8790 是使用 baseline 的学习端。
- 打开 `/admin/` 不会向教练提问，所以不需要模型配置。设置了数据库时，线上请求和模式切换会使用它。在学习端提问会产生付费模型调用，并需要「启动与安装」中的配置。
- 评估数据显示生成时的模式：先用 `--coach-system`，其次 `COACH_SYSTEM`，否则为 `agent`。

## 线上请求日志与模式切换

有数据库时，服务端保存每个教练请求，并从数据库读取模式。没有数据库时，两者都关闭，应用照旧运行。契约见 `design.md`（模式与请求日志、管理页 API）。

- **数据库地址：** 依次使用 `COACH_LOG_DATABASE_URL`、`DATABASE_URL`、`POSTGRES_URL`。本地自动使用 `.env` 中的 `DATABASE_URL`（Docker Postgres），无需额外步骤。服务启动时，如果缺少 `coach_request_log`、`coach_settings`、`coach_mode_changes` 和 `coach_daily_usage`，就会创建它们。`frontend/sql/request_log.sql` 中是相同的 SQL。
- **生效的模式：** 依次取数据库中的 `coach_system` 设置、`COACH_SYSTEM`、`agent`。结果缓存 10 秒，数据库出错时退回 `COACH_SYSTEM`。`GET /admin/mode` 显示模式、来源（`db` 或 `env`）和切换历史。
- **管理令牌：** 设置 `COACH_ADMIN_TOKEN` 后，`POST /admin/mode` 需要 `X-Admin-Token` 请求头。在 Vercel 上没有它时，切换关闭（403 `admin_token_required`，`"writable": false`）；没有它的本地服务仍可切换。查看仍然公开。
- **公开数据：** 问题原样保存，`/admin` 不设保护，因此知道网址的人都能读到。这些行在课程期间保留，之后由项目负责人删除（`design.md` 中的 D2/D4 例外）。

| 保存的列 | 含义 |
|---|---|
| `id`、`created_at` | 行号和保存时间 |
| `mode`、`mode_source`、`transport` | `agent` 或 `baseline`；`db` 或 `env`；`ndjson` 或 `json` |
| `status`、`error_code` | 与 stdout 日志行相同 |
| `question` | 原样保存的完整问题 |
| `quick_ms`、`first_ms`、`total_ms` | 到 `quick` 行的时间（没有发送时为 `null`）；到 `first` 行的时间（没有时为 `null`）；到结束的时间 |
| `llm_calls`、`searches`、`input_tokens`、`output_tokens` | 与 stdout 日志行相同 |
| `verified_first`、`added_final`、`verified_final`、`continuation` | 与 stdout 日志行相同 |
| `result` | 包含答案表达和 trace 的 JSON，`/admin` 据此生成请求日志和执行图 |

```sh
curl -s 'http://127.0.0.1:8787/admin/requests.json?limit=20'
curl -s http://127.0.0.1:8787/admin/mode
curl -s -X POST -H 'Content-Type: application/json' -H "X-Admin-Token: $COACH_ADMIN_TOKEN" \
  -d '{"mode": "baseline"}' http://127.0.0.1:8787/admin/mode
```

### 项目负责人在 Vercel 上的设置（Neon 免费版）

免费的 Hobby 计划不能邀请成员，所以由项目负责人在 Vercel 控制台中为每个项目完成一次：

1. 打开项目 → **Storage**（或 **Integrations** → **Browse Marketplace**）→ **Neon** → 用 **Free** 计划创建数据库并连接到本项目，Production 和 Preview 都勾选。
2. 变量前缀留空。在 **Settings → Environment Variables** 中查看 Neon 添加的变量名。`DATABASE_URL` 或 `POSTGRES_URL` 可以直接使用。必要时（例如该名称已用于其他用途），用同一连接字符串添加 `COACH_LOG_DATABASE_URL`。
3. 添加 `COACH_ADMIN_TOKEN`（一个较长的随机值）；没有它时，Vercel 上的模式切换保持关闭。
4. **Redeploy**。新变量只对新的部署生效。
5. 检查：`GET /admin/mode` 显示 `"writable": true`；提问一次后，`GET /admin/requests.json` 中能看到这条请求。

本地无需任何操作：会使用 `.env` 中的 Docker Postgres。

## 自有 Vercel 部署

一个新的 Vercel 项目，与队友的项目分开。它携带全部 36,397 个已核准的 Changelog 片段、MiniLM 向量、音频位置和预先计算的语音识别对齐，大小约 461 MB，Vercel Python 上限为 500 MB。内容和大小见 `design.md`（自有 Vercel 部署）。这个包已在本地构建并检查，尚未部署。

**重新构建（由我们执行）。** 在 `python` 前加上 `uv run --python 3.11 --with-requirements frontend/requirements.txt`。`<run>` 是 D6 的运行文件夹（`…/evaluation/results/lock-20261122`）。

```sh
python -m frontend.vercel.own_snapshot align --run <run>                              # 被引用片段的精确语音识别位置；跳过已保存的
python -m frontend.vercel.own_snapshot package --run <run> --admin-data <data.json>   # 输出到 frontend/.local/vercel-phrase-room-own
```

输出包含网页应用（`public/`，不含 APK）、带 D6 数据的 `/admin`、函数 `api/search.py`（来自 `frontend/vercel/own_index.py`）、语料、编码器和 `vercel.json`（`maxDuration` 300）。

**项目负责人的步骤**（在仓库根目录执行；不要把密钥值发给任何人）：

1. `npx vercel login`（浏览器登录，仅限项目负责人）。
2. `npx vercel --cwd frontend/.local/vercel-phrase-room-own`。回答：set up and deploy → `Y`；scope → 你的账户；link to an existing project → `N`（不要连到队友的项目）；name → 例如 `phrase-room-own`；directory → `./`；modify settings → `N`。
3. 按 **项目负责人在 Vercel 上的设置** 为新项目接入 Neon，保持名称 `DATABASE_URL`。函数第一次启动时会创建请求日志、模式和每日计数的表。
4. 在包文件夹中添加生产环境变量：对 `ANTHROPIC_API_KEY`（由项目负责人粘贴密钥）、`COACH_ADMIN_TOKEN`（例如 `openssl rand -hex 24` 的输出）、`LLM_PROVIDER`（`anthropic`）、`LLM_MODEL`（`claude-haiku-5-5`）和 `COACH_DAILY_LIMIT`（`10`）分别运行 `npx vercel env add <名称> production`。接入 Neon 之后再添加 `COACH_DAILY_LIMIT`：设置了上限却没有数据库时，每个提问都会返回 503。`COACH_DAILY_TZ` 默认为 Asia/Seoul。不设置 `LLM_PROVIDER`/`LLM_MODEL` 时，函数也使用 anthropic 和 claude-haiku-5-5。
5. `npx vercel --prod --cwd frontend/.local/vercel-phrase-room-own`。重新构建后只需重复这一步。
6. 检查 `https://<域名>/`、`/admin/`、`/admin/data.json` 和 `/api/audio/alignment?chunk_id=<片段>&quote=<引用>`（已对齐的片段返回 `"status":"ready","method":"asr"`）。提问一次后，`/admin/` 的线上日志中能看到这条请求，回复的 `X-Coach-Daily-Remaining` 为 9。

**风险：** 上传超过大小上限时，用 `--max-mb 400`（或更小）重新打包，它按整集保留，先保留引用最多的。Hobby 的 CLI 上传限制不明确（文档写 100 MB，但 2026-06-17 的更新记录说取消了仅限 CLI 的限制）；这个包约上传 260 MB，可能需要 Pro。网页应用中的 APK 链接在这里是 404。字面检索在 Python 中扫描 3.6 万个片段（每次约 1.2 秒）。包中是构建时的文件，所以管理页的改动合入后要重新打包。

## 项目负责人判断题

1. 后台查找进行时，新的教练提问会等待，因为服务端每个进程只处理一个请求，否则会以忙碌拒绝。保留这一默认做法，还是允许发送并接受偶尔的忙碌回复？
2. 是否提交由加锁重新评估运行生成的 `frontend/admin/data.json`？它约 3 MB，原样包含评估问题。提交后，任何机器都能打包出相同的 `/admin`；不提交时，只能在打包时从被 git 忽略的结果文件夹生成，而这个文件夹只在一台机器上。建议：只提交这一个文件。
3. **项目负责人操作：** 按 **自有 Vercel 部署** 部署我们自己的 Vercel 项目并接入 Neon。接入 Neon 之前，部署只保留 stdout 日志行，`/admin` 也不能切换模式。管理令牌和问题保留期限已经确定（`design.md` 的决定记录）。

# 한국어

웹과 Android 앱은 `web/`의 화면을 공유한다. 중국어, 한국어 또는 영어로 여덟 가지 오프라인 상황을 검색하고 팟캐스트 원문, 출처, 라이선스를 확인할 수 있다. 북마크와 질문 기록은 현재 기기에 저장된다. 온라인 코치는 기존 ExpressionCoach와 로컬 PostgreSQL 자막 색인을 사용한다.

## 실행 및 설치

저장소 루트에서 기존 자막 데이터베이스와 로컬 임베딩 모델을 준비하고, 데모 설정에 모델을 정한다. Claude는 `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `LLM_MODEL`을, Responses 제공자는 `LLM_PROVIDER=responses`, `RESPONSES_BASE_URL`, `RESPONSES_API_KEY`, `LLM_MODEL`을 설정한다. `EMBEDDING_PROVIDER`도 설정한다. `frontend/requirements.txt`는 `translation_agent_demo/requirements-local.txt`(MiniLM, faster-whisper)를 포함한다.

```sh
uv run --python 3.11 --with-requirements frontend/requirements.txt python -m frontend.server
```

`http://127.0.0.1:8787`에서 ‘코치에게 질문’을 선택한다. 웹 앱이 캐시되면 오프라인 표현 검색도 가능하다. iPhone에서는 Safari로 HTTPS 사이트를 열고 공유 메뉴에서 홈 화면에 추가할 수 있다. 로컬에서는 `COACH_DAILY_LIMIT`를 설정하지 않으면 일일 상한이 없다.

Android 빌드에는 Linux 또는 WSL, JDK 17, Android SDK Platform/Build Tools 35가 필요하다. 스크립트는 로컬 개발 키로 APK에 서명한다. 빌드한 APK는 웹 앱 연결 설정에서 내려받을 수 있다.

```sh
ANDROID_HOME=/path/to/android-sdk bash frontend/android/build.sh
adb install -r frontend/android/build/PhraseRoom.apk
```

Android 1.3는 팀원의 Vercel에 직접 연결한다. 이 백엔드는 WSL 저장소 루트에서 `python -m frontend.vercel.package`로 배포 파일을 만들고 Vercel 프로덕션에 `RESPONSES_API_KEY`를 설정한 뒤 배포한다.

팀원의 라이브 Vercel 앱은 같은 HTTPS 주소에서 대화 화면, Android 설치 파일과 코치 API를 제공한다. 그 배포본은 검토된 자막 185개, 벡터, MiniLM 인코더를 포함하며, 서버가 질문 벡터를 계산하고 Responses 게이트웨이를 호출한다. 휴대폰에서 바로 질문할 수 있으며 컴퓨터는 꺼도 된다. 자막이나 이용 허가가 바뀌면 스냅샷을 다시 배포한다. 우리 Vercel 프로젝트는 별개다. **우리 Vercel 배포**를 참고한다.

## 단계별 응답, 모드, 요청 로그

`POST /api/search`는 `{question, context}`를 받는다. 기본 응답은 지금처럼 JSON 하나다: `{"expressions": [...], "note": ...}`. 설치된 APK도 그대로 동작한다. 클라이언트가 `Accept: application/x-ndjson`을 보내면 줄마다 JSON 객체 하나를 받는다.

| 줄 | 언제 | 필드 |
|---|---|---|
| `quick` | 선택 사항이며 다른 모든 줄보다 먼저: 빠른 모델 호출이 요청 시작 후 3초 안에 답한 경우(목표 2초). 실패하거나 늦거나 답을 거절하면 보내지 않는다 | `text`: 자연스러운 영어 표현 하나. `note`: 학습자 언어로 쓴 짧은 설명. 출처가 없는 생성된 제안이며 검증된 예문이 아니다 |
| `first` | 첫 단계에서 예문 1~3개가 검증됨 | `expressions`: 검증된 예문만 담으며, 이후 바뀌지 않는다. `pending`: `false`면 뒤에 오는 것이 없다. `note` |
| `final` | 후속 단계가 끝난 뒤. 첫 단계에서 하나도 검증되지 않았거나 요청이 거절되면 이 줄만 온다 | `expressions`: `first`가 있었으면 `first` 항목 다음에 나중에 검증된 예문만, 없었으면 전체 답. `added`: 나중에 검증된 예문의 번호. `note` |
| `error` | `final` 대신 | `code`: `timeout`, `coach_unavailable`, 또는 `model_unavailable` 같은 코치 오류 코드 |

거절은 일반 HTTP 오류이며 어떤 줄보다 먼저 온다: 401 또는 403 `pairing_required`, 403 `origin_denied`, 422 `invalid_input`, 429 `coach_busy`, 그리고 일일 상한이 있으면 429 `daily_limit` 또는 503 `daily_limit_unavailable`. JSON 응답은 이전 클라이언트가 기대하는 최종 답 전체이므로, `first` 뒤라면 스트림이 빼는 미검증 후보가 들어 있을 수 있다. 첫 단계에서 예문이 검증된 뒤 후속 단계가 실패해도 응답은 그 예문을 돌려준다. JSON 응답에는 빠른 번역이 없다.

- **빠른 번역과 병렬 검색:** 서버는 후보 호출과 동시에 빠른 호출을 시작한다. `COACH_QUICK_MODEL`과 `COACH_QUICK_PROVIDER`로 모델과 제공자를 정하고, 없으면 `LLM_MODEL`과 `LLM_PROVIDER`를 쓴다. 빠른 번역은 슬롯이 아니다. 세 표현에 들어가지 않고 `first` 항목을 바꾸지 않는다(D1). 로컬 서버와 Vercel 함수 모두 이것을 보낸다. 검색은 동시에 실행되어 `first`까지의 대기를 줄인다. trace 단계마다 `started_ms`를 기록한다. `COACH_SEARCH_WORKERS`(1–9, 기본값 6)로 동시에 실행할 검색 수를 정한다. `1`이면 하나씩 차례로 실행하고, 다른 값이면 시작하지 않는다. 로컬에서는 동시에 실행되는 검색마다 데이터베이스 연결을 따로 쓴다. 측정한 시간은 `design.md`(첫 답 더 빨리 보기)에 있다.
- **빠른 첫 단계(PR ⑦):** `COACH_FIRST_STAGE=fast`(앱 기본값)이면 후보 호출이 짧은 설명이 붙은 후보 3개를 스트리밍으로 보낸다. 후보가 완성되는 대로 검색하고, 후보마다 짧은 선택 호출을 따로 한다. 선택에는 구절마다 핵심 구절 중심으로 300자로 자른 스팬을 최대 3개 보여 준다(Claude Haiku 5.5, 사고 없음). 첫 검증 예문 0.4초 뒤 `first`를 보내고 빈 자리는 후속 단계가 채운다. `first`는 p50 4.1초(`full`은 14.6초), quick은 약 1초지만, 한 번에 검증되는 예문은 줄었다. 1–2초 목표는 달성하지 못했다(자세한 내용은 `design.md`의 빠른 첫 단계). 설정은 시작할 때 읽는다(다른 값이면 시작하지 않는다): `COACH_FIRST_STAGE`는 `fast` 또는 `full`(평가한 첫 단계: 후보 6개, 고정 프롬프트. 평가는 항상 이것을 실행). `fast`일 때 `COACH_FIRST_CANDIDATES`(3–6, 기본값 3), `COACH_FIRST_SPANS`(1–12, 기본값 3), `COACH_FIRST_SPAN_CHARS`(120–800, 기본값 300). 병렬 경로를 끄는 설정은 없고, 되돌리기는 `full`이다. 리터럴 검색을 빠르게 하려면 마이그레이션 `014_corpus_text_trgm.sql`을 적용한다. Vercel에서는 Settings → Environment Variables에서 바꾼 뒤 다시 배포한다.
- **모드:** `COACH_SYSTEM`은 `agent`(잠금 agent, 기본값) 또는 `baseline`이다. `COACH_CONTINUATION`은 `on`(기본값) 또는 `off`다. `off`는 첫 단계만 실행하며, 평가되지 않은 설정이다. 서버는 시작할 때 두 값을 읽고, 다른 값이면 시작하지 않는다. 로컬에서는 시작하기 전에 정한다. 예: `COACH_SYSTEM=baseline python -m frontend.server --port 8790`. 데이터베이스가 있으면 `/admin`에서 바꾼 모드가 재배포 없이 `COACH_SYSTEM`보다 우선한다(**실제 요청 로그와 모드 전환** 참고). 데이터베이스가 없으면 Vercel의 Settings → Environment Variables에서 `COACH_SYSTEM`을 바꾼 뒤 다시 배포한다.
- **제한:** 작업은 요청 시작 280초 뒤에 멈춘다. Vercel의 `maxDuration`이 300초이기 때문이다. 이때 스트림은 `code`가 `timeout`인 `error` 줄로 끝난다. 로컬 서버는 느린 제공자나 릴레이를 위해 `--deadline` 또는 `COACH_DEADLINE_SECONDS`(1–3600초)를 받는다. 프로세스당 한 번에 요청 하나만 처리한다. 클라이언트가 떠나면 작업은 다음 모델 호출이나 검색 전에 멈춘다. 자리는 작업이 실제로 멈춘 뒤에만 돌아오고, 로그 줄과 DB 행은 그대로 남는다.
- **일일 상한:** `COACH_DAILY_LIMIT`(기본값은 미설정, 상한 없음)는 모든 학습자를 합친 하루 요청 수를 제한하며, 데이터베이스 테이블 `coach_daily_usage`에서 센다. `COACH_DAILY_TZ`(기본값 `Asia/Seoul`)가 하루의 시작을 정한다. 접근, 입력, 사용 중 검사를 통과한 요청은 모델 호출 전에 한 번 센다. 상한을 넘으면 429 `daily_limit`. 상한이 있는데 데이터베이스가 없으면 모든 요청이 503 `daily_limit_unavailable`이다. 응답에는 `X-Coach-Daily-Limit`과 `X-Coach-Daily-Remaining`이 붙는다. 우리 배포는 10을 쓴다(`design.md`의 일일 상한).
- **요청 로그:** 접근 검사를 통과한 요청마다 stdout에 JSON 한 줄을 출력한다. Vercel에서는 런타임 로그에서 `coach_request`로 검색한다. Vercel 런타임 로그는 Hobby에서 1시간, Pro에서 1일 동안 보관된다. 데이터베이스가 있으면 요청이 질문 전체와 함께 한 행으로도 저장된다(**실제 요청 로그와 모드 전환** 참고).

| 필드 | 뜻 |
|---|---|
| `event`, `ts`, `request_id` | `coach_request`, 시작 시각(UTC), 임의 id |
| `mode`, `mode_source`, `continuation_setting`, `transport` | `agent` 또는 `baseline`; `db` 또는 `env`; `on` 또는 `off`; `ndjson` 또는 `json` |
| `first_stage` | `full`, 또는 `fast/<후보 수>c/<스팬 수>s/<글자 수>/p`(기본 `fast/3c/3s/300/p`, `/p`는 병렬). stdout에만 있고 데이터베이스 열은 아니다 |
| `status`, `error_code` | `ok`, `declined`, `invalid_input`, `busy`, `daily_limit`, `error`, `timeout`, `disconnected` 중 하나; 오류 코드 |
| `verified_first`, `added_final`, `verified_final` | 첫 단계에서 검증된 예문 수; `first` 뒤에 추가된 예문 수(`first`가 없으면 0); 학습자가 최종으로 받는 검증된 예문 수 |
| `continuation`, `invariant_ok` | `skipped`(모두 검증), `ran`, `off`, `none`(거절 또는 첫 단계 실패); 최종 답이 `first` 항목을 유지했는지 |
| `quick_ms` | `quick` 줄까지의 밀리초. 보내지 않았으면 `null`. 생성된 제안이므로 첫 답으로 치지 않는다 |
| `first_ms`, `total_ms` | `first` 줄까지의 밀리초(`ndjson`에만 있음. `first`가 없을 때와 `json`에서는 `null`인데, `json` 클라이언트는 끝나기 전에 아무것도 보지 못하기 때문이다)와 끝까지의 밀리초. 첫 답을 보는 시간은 `first_ms`이고, `null`이면 `total_ms`다 |
| `llm_calls`, `searches`, `input_tokens`, `output_tokens`, `cached_input_tokens` | 시도한 모델 호출과 검색 수; 제공자가 보고한 토큰 수 |
| `disconnected`, `question_head` | 클라이언트가 일찍 떠났는지; 질문의 앞 40자(맥락과 답은 넣지 않음) |

## 학습자 앱: 단계별 표시

웹과 Android 클라이언트는 NDJSON을 요청한다(`Accept: application/x-ndjson, application/json;q=0.9`). 서버가 JSON으로 답하면(이전 배포, 또는 릴레이의 `202` 작업) 클라이언트는 예전의 한 번 응답 흐름을 쓴다. 설치된 APK는 JSON 흐름을 그대로 쓴다. 이 클라이언트를 배포하려면 APK를 다시 빌드한다. 서비스 워커 캐시는 `phrase-room-shell-v11`이다.

| 도착한 것 | 학습자가 보는 것 |
|---|---|
| 아직 없음 | 기다림 문구와 경과 초. 30초가 지나면 예문을 찾느라 조금 더 걸린다고 알린다 |
| `quick` | 빠른 번역과 설명을 바로 보여 주고, 팟캐스트 예문이 아닌 생성된 제안이라고 표시한다. 기다림 문구는 `first`나 `final`이 올 때까지 남는다 |
| `first`, `pending: false` | 검증된 예문을 답으로 보여 준다. 공지는 없다 |
| `first`, `pending: true` | 검증된 예문만 보여 주고, 그 아래에 '찾는 중' 빈 자리를 두며, 채팅 위에 공지를 띄운다: **팟캐스트 예문을 더 찾는 중** · 이 화면을 열어 두면 끝날 때 알려드릴게요 |
| 이어서 `final` | 채팅의 답은 바뀌지 않는다. `added` 번호의 예문은 **팟캐스트** 탭으로 가고, 탭에 배지가 붙는다. 빈 자리와 공지가 그곳을 가리킨다. 추가된 것이 없으면 두 곳 모두 그렇게 알린다 |
| 이어서 `error` 또는 스트림 끊김 | 처음 예문은 그대로 둔다. 공지와 빈 자리에 **다시 찾기**를 두고, 오류 색은 쓰지 않는다 |
| `final`만 | 예전처럼 전체 답을 한 번에 보여 준다. 검증된 예문이 없는 항목에는 '원문 미확인' 문구가 그대로 붙는다 |
| `error`만, 또는 HTTP 거절 | 기존 오류 문구와 **재시도** |
| 429 `daily_limit` | 오늘 질문 수(하루 횟수 포함)를 모두 썼으니 내일 다시 시도하라는 중국어 또는 한국어 안내 |

- **기록:** 기기 기록은 답마다 처음 항목, 추가 항목, 단계(`pending`, `done`, `stopped`, `incomplete`)를 보관한다. 기록 화면은 두 묶음을 모두 보여 주고, 어느 쪽 카드든 저장할 수 있다. 후속 질문의 맥락은 지금처럼 첫 항목을 쓴다.
- **화면을 떠났을 때:** 서버는 학습자가 나중에 받아 갈 답을 남기지 않는다(D5). 저장된 로그 행은 `/admin`에서만 쓴다. 다음에 앱을 열 때 아직 `pending`인 기록은 `incomplete`가 된다. 공지에서 **처음 결과 보기**와 **다시 찾기**를 고를 수 있고, 다시 찾기는 같은 질문을 그때 보낸 맥락과 함께 다시 보낸다.
- **한 번에 한 검색:** 서버는 프로세스당 요청 하나만 처리한다. 그래서 백그라운드 검색이 끝날 때까지 새 코치 질문은 기다리며, 입력창 아래에 그 이유를 보여 준다. 표현 모음 검색은 막지 않는다.
- **일일 횟수:** 상한이 있으면 입력창 아래 줄에 오늘 남은 질문 수가 보인다.
- **접근성과 배치:** polite 라이브 영역 하나가 답이 도착할 때만 읽어 준다(처음 예문, 검색 끝). 공지는 다시 그려지는 화면 밖에 있고, 다시 그릴 때 입력창의 커서를 유지한다. 채팅 화면에도 탭을 보여 주므로 **팟캐스트** 탭의 배지를 바로 보고 누를 수 있다. 공지와 답 아래 빈 자리도 그 탭으로 연결된다. 글자가 아주 크거나 화면이 낮으면 입력창을 아래에 고정하지 않는다.
- **확인:** 서버 테스트가 스트리밍을 다룬다. 화면 상태는 저장소 밖 도구로 헤드리스 브라우저에서 확인했다. `ask()`(300초 중단, 동시 검색 제한, JSON·릴레이 대체 흐름)에는 자동 테스트가 없다.

## 팟캐스트 음성 구간

검증된 팟캐스트 출처가 있는 카드는 게시자 음성 파일에서 해당 구간을 재생할 수 있다. 계약(필드, 위치 우선순위, `GET /api/audio/alignment`), 로컬 적용 수치, 알려진 차이는 `design.md`(**팟캐스트 음성 구간**)에 있다.

**DB마다 한 번 설정한다.** 마이그레이션 010–014는 `initialize_schema`와 `compose.yaml`에 없으므로 직접 적용한다. 011은 로컬 서버가 직접 만들고, 012번은 일부러 비워 두었다. 저장소 루트에서 실행한다. 잡은 `python` 바로 앞에 `uv run --python 3.11 --with-requirements translation_agent_demo/requirements.txt`를, `frontend.audio_align`은 `--with-requirements frontend/requirements.txt`를 붙인다(faster-whisper가 필요). DB URL과 무료 Podcast Index 키는 데모 설정에 있다.

```sh
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/010_episode_audio.sql
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/013_transcript_time_anchors.sql
psql <DATABASE_URL> -f translation_agent_demo/storage/migrations/014_corpus_text_trgm.sql   # 리터럴 검색 가속
python -m translation_agent_demo.jobs.podcast_audio backfill --dry-run    # 음성이 없는 에피소드 수
python -m translation_agent_demo.jobs.podcast_audio backfill [--feed-ids 1,2] [--interval 0.5]
python -m translation_agent_demo.jobs.podcast_audio anchors [--dry-run]   # 대본 시간 표시
python -m frontend.audio_align <chunk_id>... [--ids-file FILE]            # 선택: 청크 미리 정렬
```

| 설정 | 뜻 |
|---|---|
| `COACH_AUDIO_ALIGN` | `on`(로컬 기본값) 또는 `off`. 음성 인식에는 faster-whisper와 데이터베이스도 필요하므로 Vercel에서는 돌지 않는다 |
| `COACH_ALIGN_MODEL` | faster-whisper 모델, 기본 `base.en` |

- **백필:** 피드마다 아카이브 한 페이지를 읽고, 남은 에피소드는 하나씩 조회한다(`/episodes/byid`). 요청 간격은 `--interval`초, 최대 3,000회다. 401/403이면 멈추고, 개수만 출력한다. 그 뒤로는 `podcast_sync`가 가져온 페이지마다 enclosure를 저장한다. 마이그레이션 010이 없으면 저장을 건너뛰고 동기화는 계속한다.
- **시간 표시:** 검색 가능한 처리 버전의 준비된 빌드마다 게시자 시간 표시를 저장한다. 로컬에서 돌고 다시 돌려도 안전하다. 바뀌지 않은 문서는 쓰지 않는다.
- **위치:** 저장된 정렬(ASR 또는 자막 시각)을 먼저, 그다음 시간 표시 사이 보간, 마지막으로 문자 위치 × 에피소드 길이를 쓴다. 각 citation에 `audio_url`, `audio_start_ms`, `audio_end_ms`, `audio_estimated`가 실린다. `null`과 `false`는 음성 없음이다. 로컬 서버는 `GET /api/audio/alignment`에 시간 표시로 바로 답하고 백그라운드에서 청크를 정렬한다(작업자 두 개). 스트림은 학습자가 재생을 누르기 전에 인용한 청크를 큐에 넣는다.
- **플레이어:** **听这一段 / 이 부분 듣기**는 카드 아래에 공유 플레이어 하나를 연다. **■ 关闭 / 닫기**로 닫는다. 기본으로 반복 재생한다. 범위는 인용, 모든 줄, 누른 한 줄 중에서 고른다. 속도는 0.75×, 1×, 1.25×이며 기억된다. 자막은 지금 말하는 줄을 따라간다. 추정한 시작은 **大致位置 / 대략 위치 · m:ss**로 보인다. 정렬 답이 없으면 citation의 범위, 또는 시작부터 20초를 재생한다. 탭을 옮기면 재생이 멈추고, 재생할 수 없는 파일이면 짧은 안내가 뜬다. `<audio preload="none">` 하나는 학습자가 누르기 전까지 아무것도 불러오지 않고, 서비스 워커는 음성을 캐시하지 않는다.
- **스냅샷:** 두 패키저 모두 `passages.json`의 각 구간에 네 필드를 붙이고, 번들에 든 청크의 저장된 정렬을 `corpus/alignments.json`에 넣는다. Vercel 함수는 음성 인식 없이 이것으로 답한다. 정확한 위치를 주려면 청크를 먼저 정렬한다.
- **라이선스:** 앱은 게시자의 파일을 원래 URL에서 재생하며, 내려받거나 캐시하거나 재배포하지 않는다. 대본 라이선스는 음성에 적용되지 않고, 음성은 게시자의 조건을 따른다.
- **확인:** 단위 테스트가 위치, 시간 표시, 정렬 답, 검색 필드, citation, 스냅샷을 다룬다. 헤드리스 Chrome에서 음성 인식 구간과 시간 표시 구간이 모두 게시자 파일에서 재생됐다. 표본 URL 16개는 Range 요청에 모두 206으로 답했다.

## 어드민 화면(/admin)

어드민 화면은 보기에 보호가 없다(D4). 주소를 아는 사람은 누구나 볼 수 있고, 화면에도 그렇게 적혀 있다. 앱과 같은 배포에 들어간다. 평가 데이터는 실행 기록 하나로, `frontend/admin_data.py`가 만든 `data.json`이다. 데이터베이스가 있으면 실제 요청도 보여 주고 모드를 바꿀 수 있다(**실제 요청 로그와 모드 전환** 참고).

| 위치 | 화면 | 데이터 |
|---|---|---|
| 로컬 서버 | 어드민 화면 폴더(`frontend/admin/`), 주소 `/admin/` | 같은 폴더의 `/admin/data.json`, 분리된 경우 `data-traces.json`도 |
| 로컬 미리보기 | `COACH_ADMIN_DIR=<화면 폴더>` | `COACH_ADMIN_DATA=<data.json이 있는 폴더>` |
| Vercel | `public/admin/`, 정적 파일 | 패키징 스크립트가 `public/admin/`에 만든다 |

화면은 시안 B(Phrase Room 브랜드)에 시안 A의 노선도와 시안 C의 스윔레인 타임라인을 더한 것이다(D7). 탭은 네 개다.

| 탭 | 보여 주는 것 |
|---|---|
| **모드 비교** | 같은 실행의 `baseline`과 `agent`를 같은 기준으로 나란히 비교하고, 데이터를 만든 모드를 표시한다 |
| **요청 로그** | 실행의 모든 요청: 상태, 예문, 시간, 토큰, 후속 단계, 잠금 표시. 사용자 열은 없다(D3) |
| **지표** | 시간과 토큰의 p50 · p95 · p99. 최종 시간은 두 모드가 모두 후속 단계를 실행한 과제끼리만 비교한다 |
| **실행 그래프** | 요청 한 건을 구성요소 노선도, 스윔레인 타임라인, 단계 상세 패널로 보여 준다 |

- **언어:** 머리말의 전환 버튼으로 한국어, 중국어, 영어 중 하나로 볼 수 있다. `?lang=ko|zh|en`은 그 링크에만 적용되고 저장되지 않는다. 머리말에서 고른 언어는 브라우저에 저장된다. 기본은 한국어다.
- **모든 시안의 규칙:** `data.json`을 상대 경로로 읽고, `meta.schema_version`이 1이 아니면 버전이 맞지 않는다는 안내만 보여 준다. 글자는 `textContent`와 DOM 호출로만 쓰고, 콘텐츠 보안 정책(CSP)을 유지한다. 웹폰트는 SRI가 붙은 jsdelivr에서 읽고, 막히면 시스템 글꼴을 쓴다. 모든 `/admin` 응답은 `noindex`다.
- **데이터 생성기 안전장치:** `frontend/admin_data.py`는 trace 단계마다 허용 목록의 필드만 남긴다. 출력에 비밀처럼 보이는 값(API 키, 토큰, PEM 블록, 비밀번호가 든 데이터베이스 URL)이나 로컬 홈 경로가 있으면 아무것도 쓰지 않고 멈춘다.
- **경로:** 화면은 `data.json`을 상대 경로로 읽는다. 그래서 `/admin`은 `/admin/`으로 이동한다(로컬 서버와 `vercel.json` 모두). 변수로 지정한 폴더는 있어야 하고, 데이터 폴더에는 `data.json`이 있어야 한다. 아니면 서버가 시작하지 않는다.
- **패키징:** `python -m frontend.vercel.package --admin-run <run> --admin-results <결과 루트>`는 배포 모드로 데이터를 만든다. 모드는 `--coach-system`, 없으면 `COACH_SYSTEM`, 그것도 없으면 `agent`다. `COACH_ADMIN_RUN`, `COACH_ADMIN_RESULTS`도 쓸 수 있다. 실행을 지정하지 않으면 `frontend/admin/data.json`이 있을 때 그것을 넣고, 없으면 데이터 없이 만들며 어느 쪽인지 출력한다. 이전 패키지의 데이터는 항상 먼저 지운다. 그래서 패키징하는 기기에는 그 실행 폴더나 커밋된 `frontend/admin/data.json`이 있어야 한다(판단 질문 2). 우리 패키지는 미리 만든 파일을 `--admin-data`로 받는다.
- **크기:** 어드민 파일은 정적 파일이라 함수 크기는 그대로다. 제출 실행의 데이터는 `public/`에 2.9 MB(gzip 0.26 MB)를 더한다.
- **미리보기 패키지:** `--skip-apk`와 `--skip-search-data`는 Android SDK, 코퍼스, 인코더 없이 패키지를 만든다. 배포 폴더가 아닌 `--out`이 필요하고, 이 패키지는 질문에 답하지 못한다.
- **알려진 차이:** 팀원의 코퍼스 내보내기는 아직 `sudo -u postgres psql`(WSL)을 쓴다. 읽는 스키마 `evaluation_zh_local_v1`은 macOS의 Docker 데이터베이스에 없으므로, 그 패키지는 당분간 WSL에서 만든다. 서버 테스트는 화면이 제공되고 위 규칙을 지키는지 확인한다. 화면의 JavaScript에는 자동 테스트가 없고 브라우저에서 확인했다.

### 로컬 포트에서 실제 데이터로 확인하기

실행 기록 하나로 데이터를 한 번 만든 뒤, 시안이나 모드마다 다른 포트로 서버를 하나씩 띄운다. 각 줄은 저장소 루트에서 `python` 바로 앞에 `uv run --python 3.11 --with-requirements frontend/requirements.txt`를 넣어 실행한다. 재평가 결과를 볼 때 `<run>`은 `evaluation/results` 아래의 그 실행 폴더 `lock-20261122`다.

```sh
python -m frontend.admin_data --results evaluation/results --run <run> --tasks evaluation/data/tasks.jsonl --out <데이터 폴더>
COACH_ADMIN_DATA=<데이터 폴더> python -m frontend.server --port 8788
COACH_ADMIN_DATA=<데이터 폴더> COACH_ADMIN_DIR=<시안 폴더> python -m frontend.server --port 8789
COACH_SYSTEM=baseline COACH_ADMIN_DATA=<데이터 폴더> python -m frontend.server --port 8790
```

- 포트마다 `/`에 학습자 앱, `/admin/`에 어드민 화면이 있다. 8788은 `frontend/admin`, 8789는 다른 시안 폴더, 8790은 baseline으로 답하는 학습자 앱이다.
- `/admin/`을 열어도 코치에게 질문하지 않으므로 모델 설정이 필요 없다. 데이터베이스가 설정되어 있으면 실제 요청과 모드 전환이 그것을 쓴다. 학습자 앱에서 질문하면 유료 모델 호출이 생기고, '실행 및 설치'의 설정이 필요하다.
- 평가 데이터는 만들 때의 모드를 보여 준다. 모드는 `--coach-system`, 없으면 `COACH_SYSTEM`, 그것도 없으면 `agent`다.

## 실제 요청 로그와 모드 전환

데이터베이스가 있으면 서버는 코치 요청을 모두 저장하고 모드를 데이터베이스에서 읽는다. 없으면 둘 다 꺼지고 앱은 이전처럼 동작한다. 계약은 `design.md`(모드와 요청 로그, 어드민 API)에 있다.

- **데이터베이스 주소:** `COACH_LOG_DATABASE_URL`, 없으면 `DATABASE_URL`, 없으면 `POSTGRES_URL`. 로컬에서는 `.env`의 `DATABASE_URL`(Docker Postgres)을 추가 작업 없이 쓴다. 서버는 시작할 때 `coach_request_log`, `coach_settings`, `coach_mode_changes`, `coach_daily_usage`가 없으면 만든다. `frontend/sql/request_log.sql`에 같은 SQL이 있다.
- **실제 모드:** 데이터베이스의 `coach_system` 설정, 없으면 `COACH_SYSTEM`, 없으면 `agent`. 10초 동안 캐시하며, 데이터베이스 오류 때는 `COACH_SYSTEM`으로 돌아간다. `GET /admin/mode`는 모드, 출처(`db` 또는 `env`), 전환 기록을 보여 준다.
- **어드민 토큰:** `COACH_ADMIN_TOKEN`을 설정하면 `POST /admin/mode`에 `X-Admin-Token` 헤더가 필요하다. Vercel에서 토큰이 없으면 전환이 꺼진다(403 `admin_token_required`, `"writable": false`). 토큰 없는 로컬 서버는 그대로 열려 있다. 보기는 계속 공개다.
- **공개 데이터:** 질문은 원문 그대로 저장되고 `/admin`은 보호가 없으므로, 주소를 아는 사람은 누구나 읽을 수 있다. 행은 과목 기간 동안 보관하고 그 뒤 책임자가 지운다(`design.md`의 D2/D4 예외).

| 저장되는 열 | 뜻 |
|---|---|
| `id`, `created_at` | 행 번호와 저장 시각 |
| `mode`, `mode_source`, `transport` | `agent` 또는 `baseline`; `db` 또는 `env`; `ndjson` 또는 `json` |
| `status`, `error_code` | stdout 로그 줄과 같음 |
| `question` | 원문 그대로의 질문 전체 |
| `quick_ms`, `first_ms`, `total_ms` | `quick` 줄까지의 시간(보내지 않았으면 `null`); `first` 줄까지의 시간(없으면 `null`); 끝까지의 시간 |
| `llm_calls`, `searches`, `input_tokens`, `output_tokens` | stdout 로그 줄과 같음 |
| `verified_first`, `added_final`, `verified_final`, `continuation` | stdout 로그 줄과 같음 |
| `result` | 답의 표현과 trace가 든 JSON. `/admin`이 이것으로 요청 로그와 실행 그래프를 만든다 |

```sh
curl -s 'http://127.0.0.1:8787/admin/requests.json?limit=20'
curl -s http://127.0.0.1:8787/admin/mode
curl -s -X POST -H 'Content-Type: application/json' -H "X-Admin-Token: $COACH_ADMIN_TOKEN" \
  -d '{"mode": "baseline"}' http://127.0.0.1:8787/admin/mode
```

### 책임자의 Vercel 설정(Neon 무료)

무료 Hobby 플랜은 멤버를 초대할 수 없으므로, 프로젝트 책임자가 Vercel 대시보드에서 프로젝트마다 한 번 진행한다.

1. 프로젝트 → **Storage**(또는 **Integrations** → **Browse Marketplace**) → **Neon** → **Free** 플랜으로 데이터베이스를 만들어 이 프로젝트에 연결한다. Production과 Preview를 모두 고른다.
2. 변수 접두사는 비워 둔다. **Settings → Environment Variables**에서 Neon이 추가한 변수 이름을 확인한다. `DATABASE_URL`이나 `POSTGRES_URL`은 그대로 쓰인다. 필요하면(예: 그 이름을 다른 용도로 쓰고 있으면) 같은 연결 문자열로 `COACH_LOG_DATABASE_URL`을 추가한다.
3. `COACH_ADMIN_TOKEN`(긴 임의 값)을 추가한다. 없으면 Vercel에서 모드 전환이 꺼진 채로 남는다.
4. **Redeploy**. 새 변수는 새 배포에만 적용된다.
5. 확인: `GET /admin/mode`가 `"writable": true`를 보여 주고, 질문 하나를 한 뒤 `GET /admin/requests.json`에 그 요청이 보인다.

로컬에서는 할 일이 없다. `.env`의 Docker Postgres를 쓴다.

## 우리 Vercel 배포

팀원 프로젝트와 별개인 새 Vercel 프로젝트다. 승인된 Changelog 청크 36,397개 전부를 MiniLM 벡터, 음성 위치, 미리 계산한 ASR 정렬과 함께 싣는다. 크기는 약 461 MB로 Vercel Python 한도 500 MB 안이다. 내용과 크기는 `design.md`(우리 Vercel 배포)에 있다. 패키지는 로컬에서 빌드하고 확인했으며 배포하지 않았다.

**다시 빌드하기(우리가 실행).** `python` 바로 앞에 `uv run --python 3.11 --with-requirements frontend/requirements.txt`를 붙인다. `<run>`은 D6 실행 폴더(`…/evaluation/results/lock-20261122`)다.

```sh
python -m frontend.vercel.own_snapshot align --run <run>                              # 인용 청크의 정확한 ASR 위치, 저장된 것은 건너뜀
python -m frontend.vercel.own_snapshot package --run <run> --admin-data <data.json>   # frontend/.local/vercel-phrase-room-own에 생성
```

출력에는 웹앱(`public/`, APK 없음), D6 데이터가 든 `/admin`, 함수 `api/search.py`(`frontend/vercel/own_index.py`에서 복사), 코퍼스, 인코더, `vercel.json`(`maxDuration` 300)이 들어 있다.

**책임자 절차**(저장소 루트에서. 비밀값은 누구에게도 보내지 않는다):

1. `npx vercel login`(브라우저 인증, 책임자만).
2. `npx vercel --cwd frontend/.local/vercel-phrase-room-own`. 답: set up and deploy → `Y`, scope → 본인 계정, link to an existing project → `N`(팀원 프로젝트에 연결하지 않음), name → 예: `phrase-room-own`, directory → `./`, modify settings → `N`.
3. **책임자의 Vercel 설정**대로 새 프로젝트에 Neon을 연결한다. 이름은 `DATABASE_URL` 그대로 둔다. 요청 로그, 모드, 일일 카운트 테이블은 함수가 처음 시작할 때 만든다.
4. 패키지 폴더에서 프로덕션 변수를 넣는다. `ANTHROPIC_API_KEY`(책임자가 키를 붙여 넣음), `COACH_ADMIN_TOKEN`(예: `openssl rand -hex 24` 결과), `LLM_PROVIDER`(`anthropic`), `LLM_MODEL`(`claude-haiku-5-5`), `COACH_DAILY_LIMIT`(`10`)마다 `npx vercel env add <이름> production`을 실행한다. `COACH_DAILY_LIMIT`는 Neon을 연결한 뒤에 넣는다. 상한이 있는데 데이터베이스가 없으면 모든 질문이 503이 된다. `COACH_DAILY_TZ`의 기본값은 Asia/Seoul이다. `LLM_PROVIDER`/`LLM_MODEL`을 빼도 함수는 anthropic과 claude-haiku-5-5를 쓴다.
5. `npx vercel --prod --cwd frontend/.local/vercel-phrase-room-own`. 다시 빌드한 뒤에는 이 단계만 반복한다.
6. `https://<도메인>/`, `/admin/`, `/admin/data.json`, `/api/audio/alignment?chunk_id=<청크>&quote=<인용>`(정렬된 청크는 `"status":"ready","method":"asr"`)을 확인한다. 질문 한 번 뒤 `/admin/` 실시간 로그에 요청이 보이고, 응답의 `X-Coach-Daily-Remaining`이 9이면 된다.

**위험:** 업로드가 크기 한도를 넘으면 `--max-mb 400`(또는 더 작게)으로 다시 패키징한다. 많이 인용된 에피소드부터 통째로 남긴다. Hobby의 CLI 업로드 한도는 불분명하다(문서에는 100 MB, 2026-06-17 변경 기록에는 CLI 전용 한도 제거). 이 패키지는 약 260 MB를 올리며 Pro가 필요할 수 있다. 웹앱의 APK 링크는 여기서 404다. 리터럴 검색은 파이썬으로 청크 3.6만 개를 훑는다(검색당 약 1.2초). 패키지는 빌드 시점의 파일을 담으므로, 어드민 화면 작업이 들어간 뒤 다시 패키징한다.

## 프로젝트 책임자 판단 질문

1. 백그라운드 검색 중에는 새 코치 질문이 기다린다. 서버가 프로세스당 요청 하나만 처리해서, 보내면 busy로 거절되기 때문이다. 이 기본값을 유지할까요, 아니면 질문을 보내게 하고 가끔 나오는 busy 응답을 감수할까요?
2. 잠금 재평가 실행으로 만든 `frontend/admin/data.json`을 커밋할까요? 약 3 MB이고 평가 질문 원문이 그대로 들어 있습니다. 커밋하면 어느 기기에서나 같은 `/admin`을 패키징할 수 있습니다. 커밋하지 않으면 패키징할 때 git이 무시하는 결과 폴더에서 만들어야 하는데, 그 폴더는 한 기기에만 있습니다. 추천: 그 파일 하나만 커밋한다.
3. **책임자 작업:** **우리 Vercel 배포**대로 우리 Vercel 프로젝트를 배포하고 Neon을 연결합니다. Neon을 연결하기 전까지 배포는 stdout 로그 줄만 남기고, `/admin`은 모드를 바꿀 수 없습니다. 어드민 토큰과 질문 보관 기간은 정해졌습니다(`design.md`의 결정 기록).
