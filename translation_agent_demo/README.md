# translation_agent_demo — the coach package

> English first; Chinese and Korean follow.

## What it is now

This folder began as an LLM-only translation prototype. It now holds the expression coach that the learner clients (`frontend/`) and the evaluation (`evaluation/`) use: the agents, the search tool, PostgreSQL storage, jobs and migrations. Product scope, contracts and decisions are in `design.md`; client and deployment steps are in `frontend/README.md`. The first translation CLI is still here.

## Layout

- `agents/` — `ExpressionCoach`: the shared first stage (`systems/first_stage.py`; the app's parallel fast path is `systems/parallel_first_stage.py`), the baseline and the locked agent (`systems/`), prompts, schemas, evidence checks, tools, session limits and traces.
- `tools/search_corpus.py` — the typed, read-only search tool over the transcript index.
- `storage/` — PostgreSQL access: transcripts, chunks, embeddings, retrieval, feed reviews, podcast sync, and episode audio with transcript time markers (`episode_audio.py`).
- `storage/migrations/` — 001–009 are applied by `initialize_schema` and `compose.yaml`. 010 (episode audio), 013 (time markers) and 014 (trigram index for the literal search) must be applied by hand; 011 (audio alignment cache) is created by the local server. 012 is intentionally unused.
- `providers/` — model adapters (OpenAI-compatible, Responses, Anthropic, Google), embeddings (OpenAI, Google, local MiniLM), Podcast Index and transcript sources.
- `jobs/` — command-line jobs: `podcast_sync`, `podcast_backfill`, `podcast_audio` (`backfill`, `anchors`), `corpus_build`, `corpus_embed`, `seed_changelog`.
- `corpus/` — transcript parsing and chunking.
- `compose.yaml`, `docker/`, `Dockerfile.sync` — the local Docker Postgres and its sync worker.
- `config.py`, `guardrails.py`, `prompts.py`, `service.py`, `cli.py` — the original translation CLI.
- `tests/` — unit tests.

## Install and run

Run everything from the repository root with Python 3.11. Copy `.env.example` to `.env` here and set the model, the database URL and the keys you need (no secrets in git).

- `requirements.txt` — the coach and its jobs: `uv run --python 3.11 --with-requirements translation_agent_demo/requirements.txt python -m translation_agent_demo.jobs.<job>`.
- `requirements-local.txt` — adds the local MiniLM encoder and faster-whisper (local audio alignment). `frontend/requirements.txt` includes it.
- Audio jobs: `python -m translation_agent_demo.jobs.podcast_audio backfill|anchors [--dry-run]` (details in `frontend/README.md`, Podcast audio clips).
- Tests (142 passed on 2026-11-22): `uv run --python 3.11 --with-requirements frontend/requirements.txt python -m unittest discover -s translation_agent_demo/tests -t .`
- Translation CLI: `python -m translation_agent_demo "今天天气如何？"` returns only the English translation. It needs an OpenAI-compatible `/chat/completions` endpoint with JSON mode, gives the model no tools, and validates a reply that holds only `translation`.

## Limits

The coach's guarantees and known gaps are in `design.md`. The translation CLI reduces task drift with prompt and schema constraints, but an LLM can still mistranslate or disobey; it claims no formal guarantee against adversarial input.

## Project Owner Judgment Questions

No pending decisions in this file. The old questions on the CLI's first provider are settled: the project uses Claude Haiku 5.5 and a Responses gateway (`design.md`).

---

# translation_agent_demo — 教练代码包

> 英文版在前，其后依次为中文版和韩文版。

## 现在是什么

这个文件夹最初是只用 LLM 的翻译原型。现在它存放学习端（`frontend/`）和评估（`evaluation/`）使用的表达教练：agents、检索工具、PostgreSQL 存储、任务和迁移。产品范围、接口约定和决定见 `design.md`；客户端和部署步骤见 `frontend/README.md`。最初的翻译 CLI 仍保留在这里。

## 结构

- `agents/` — `ExpressionCoach`：两个系统共用的第一阶段（`systems/first_stage.py`；应用的并行快速路径是 `systems/parallel_first_stage.py`）、baseline 和加锁的 agent（`systems/`）、提示词、schema、证据核对、工具、会话限制和 trace。
- `tools/search_corpus.py` — 基于字幕索引的类型化只读检索工具。
- `storage/` — PostgreSQL 访问：字幕、片段、向量、检索、节目审核、播客同步，以及带文字稿时间标记的节目音频（`episode_audio.py`）。
- `storage/migrations/` — 001–009 由 `initialize_schema` 和 `compose.yaml` 应用。010（节目音频）、013（时间标记）和 014（字面检索的 trigram 索引）需要手动应用；011（音频对齐缓存）由本地服务创建。编号 012 有意空缺。
- `providers/` — 模型适配器（OpenAI-compatible、Responses、Anthropic、Google）、向量（OpenAI、Google、本地 MiniLM）、Podcast Index 和字幕来源。
- `jobs/` — 命令行任务：`podcast_sync`、`podcast_backfill`、`podcast_audio`（`backfill`、`anchors`）、`corpus_build`、`corpus_embed`、`seed_changelog`。
- `corpus/` — 字幕解析和切分。
- `compose.yaml`、`docker/`、`Dockerfile.sync` — 本地 Docker Postgres 及其同步任务。
- `config.py`、`guardrails.py`、`prompts.py`、`service.py`、`cli.py` — 最初的翻译 CLI。
- `tests/` — 单元测试。

## 安装与运行

所有命令都在仓库根目录用 Python 3.11 运行。在本文件夹把 `.env.example` 复制为 `.env`，填写模型、数据库 URL 和需要的密钥（密钥不进 git）。

- `requirements.txt` — 教练及其任务：`uv run --python 3.11 --with-requirements translation_agent_demo/requirements.txt python -m translation_agent_demo.jobs.<任务>`。
- `requirements-local.txt` — 另加本地 MiniLM 编码器和 faster-whisper（本地音频对齐）。`frontend/requirements.txt` 包含它。
- 音频任务：`python -m translation_agent_demo.jobs.podcast_audio backfill|anchors [--dry-run]`（细节见 `frontend/README.md` 的“播客音频片段”）。
- 测试（2026-11-22 通过 142 个）：`uv run --python 3.11 --with-requirements frontend/requirements.txt python -m unittest discover -s translation_agent_demo/tests -t .`
- 翻译 CLI：`python -m translation_agent_demo "今天天气如何？"` 只返回英文翻译。它需要支持 JSON 模式的 OpenAI-compatible `/chat/completions` 接口，不向模型提供工具，并校验只含 `translation` 的回复。

## 限制

教练的保证和已知差距见 `design.md`。翻译 CLI 用提示词和 schema 约束减少任务偏离，但 LLM 仍可能翻译错误或违背指令；它不声称能对抗恶意输入并提供形式化保证。

## 项目负责人判断题

本文件没有待决定事项。关于 CLI 首次使用哪个服务商的旧问题已经解决：项目使用 Claude Haiku 5.5 和 Responses 网关（`design.md`）。

---

# translation_agent_demo — 코치 패키지

> 영어 버전이 먼저, 중국어 버전과 한국어 버전이 차례로 이어집니다.

## 지금의 역할

이 폴더는 LLM만 쓰는 번역 프로토타입으로 시작했습니다. 지금은 학습 클라이언트(`frontend/`)와 평가(`evaluation/`)가 쓰는 표현 코치, 즉 agents, 검색 도구, PostgreSQL 저장소, 잡, 마이그레이션이 있습니다. 제품 범위, 계약, 결정은 `design.md`에, 클라이언트와 배포 절차는 `frontend/README.md`에 있습니다. 처음의 번역 CLI도 남아 있습니다.

## 구성

- `agents/` — `ExpressionCoach`: 두 시스템이 공유하는 첫 단계(`systems/first_stage.py`; 앱의 병렬 빠른 경로는 `systems/parallel_first_stage.py`), baseline과 잠금 agent(`systems/`), 프롬프트, 스키마, 근거 검증, 도구, 세션 한도, trace.
- `tools/search_corpus.py` — 자막 색인을 읽기만 하는 타입 지정 검색 도구.
- `storage/` — PostgreSQL 접근: 대본, 청크, 임베딩, 검색, 피드 검토, 팟캐스트 동기화, 대본 시간 표시를 포함한 에피소드 음성(`episode_audio.py`).
- `storage/migrations/` — 001–009는 `initialize_schema`와 `compose.yaml`이 적용한다. 010(에피소드 음성), 013(시간 표시), 014(리터럴 검색용 trigram 인덱스)는 직접 적용해야 하고, 011(음성 정렬 캐시)은 로컬 서버가 만든다. 012번은 일부러 비워 두었다.
- `providers/` — 모델 어댑터(OpenAI 호환, Responses, Anthropic, Google), 임베딩(OpenAI, Google, 로컬 MiniLM), Podcast Index와 대본 출처.
- `jobs/` — 명령줄 잡: `podcast_sync`, `podcast_backfill`, `podcast_audio`(`backfill`, `anchors`), `corpus_build`, `corpus_embed`, `seed_changelog`.
- `corpus/` — 대본 파싱과 청크 분할.
- `compose.yaml`, `docker/`, `Dockerfile.sync` — 로컬 Docker Postgres와 동기화 작업자.
- `config.py`, `guardrails.py`, `prompts.py`, `service.py`, `cli.py` — 처음의 번역 CLI.
- `tests/` — 단위 테스트.

## 설치와 실행

모든 명령은 저장소 루트에서 Python 3.11로 실행합니다. 이 폴더에서 `.env.example`을 `.env`로 복사하고 모델, 데이터베이스 URL, 필요한 키를 설정합니다(비밀값은 git에 넣지 않습니다).

- `requirements.txt` — 코치와 잡: `uv run --python 3.11 --with-requirements translation_agent_demo/requirements.txt python -m translation_agent_demo.jobs.<잡>`.
- `requirements-local.txt` — 로컬 MiniLM 인코더와 faster-whisper(로컬 음성 정렬)를 더합니다. `frontend/requirements.txt`가 이것을 포함합니다.
- 음성 잡: `python -m translation_agent_demo.jobs.podcast_audio backfill|anchors [--dry-run]`(자세한 내용은 `frontend/README.md`의 팟캐스트 음성 구간).
- 테스트(2026-11-22에 142개 통과): `uv run --python 3.11 --with-requirements frontend/requirements.txt python -m unittest discover -s translation_agent_demo/tests -t .`
- 번역 CLI: `python -m translation_agent_demo "今天天气如何？"`는 영어 번역만 돌려줍니다. JSON 모드를 지원하는 OpenAI 호환 `/chat/completions` 엔드포인트가 필요하고, 모델에 도구를 주지 않으며, `translation`만 담은 답인지 검증합니다.

## 한계

코치의 보장과 알려진 차이는 `design.md`에 있습니다. 번역 CLI는 프롬프트와 스키마 제약으로 작업 이탈을 줄이지만, LLM은 여전히 잘못 번역하거나 지시를 따르지 않을 수 있습니다. 적대적인 입력에 대한 형식적 보장은 주장하지 않습니다.

## 프로젝트 책임자 판단 질문

이 파일에는 결정할 사항이 없습니다. CLI의 첫 제공자에 관한 예전 질문은 정해졌습니다. 프로젝트는 Claude Haiku 5.5와 Responses 게이트웨이를 씁니다(`design.md`).
