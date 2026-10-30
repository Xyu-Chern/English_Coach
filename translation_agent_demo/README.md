# Translation Agent Demo

> Minimal, modular LLM-only translation prototype. English first; Chinese and Korean follow.

## What it does

Accepts text and returns only its English translation. A question remains a question to translate: `今天天气如何？` returns `What's the weather like today?`; the program does not look up or answer the weather.

The model receives no tools. User text is sent as a separate, JSON-encoded user message and is treated as translation content. The model response must be a JSON object containing only `translation`; the application validates that shape before printing the translation.

## Modules

- `config.py` — environment and `.env` configuration
- `guardrails.py` — input limits and response-schema validation
- `prompts.py` — translation-only system instructions
- `providers/protocol.py` — replaceable model interface
- `providers/openai_compatible.py` — standard-library HTTP adapter
- `service.py` — translation orchestration
- `cli.py` — command-line entry point

## Run

1. Use Python 3.10 or newer.
2. In this folder, copy `.env.example` to `.env` and set the model provider URL, key, and model name.
3. From the parent `Agent_Development` directory, run:

   ```powershell
   python -m translation_agent_demo "今天天气如何？"
   ```

The configured endpoint must support an OpenAI-compatible `/chat/completions` route and JSON response mode. No Python package dependencies or Agent framework are required.

## Limits

Prompt and schema constraints reduce task drift, and the application exposes no tools or side-effecting operations. An LLM can still return an incorrect translation or disobey instructions; this prototype does not claim a formal guarantee against adversarial model behavior.

## Project Owner Judgment Questions

1. Which model provider and model name should be used for the first run?
2. Does that provider support the OpenAI-compatible Chat Completions route and JSON response mode?

---

# 翻译 Agent Demo

> 仅使用 LLM 的模块化翻译原型。英文版在前，其后依次为中文版和韩文版。

## 功能

接收文本，只返回英文翻译。用户输入是问题时，也只翻译问题：`今天天气如何？` 返回 `What's the weather like today?`；程序不会查询或回答天气。

模型不会收到任何工具。用户文本作为单独的 JSON 编码 user 消息发送，并被视为待翻译内容。模型响应必须是只含 `translation` 字段的 JSON 对象；应用校验结构后才会打印翻译。

## 模块

- `config.py`：环境变量和 `.env` 配置
- `guardrails.py`：输入限制和响应结构校验
- `prompts.py`：仅执行翻译的系统指令
- `providers/protocol.py`：可替换的模型接口
- `providers/openai_compatible.py`：使用 Python 标准库的 HTTP 适配器
- `service.py`：翻译流程编排
- `cli.py`：命令行入口

## 运行

1. 使用 Python 3.10 或更新版本。
2. 在本文件夹中将 `.env.example` 复制为 `.env`，填写模型服务地址、密钥和模型名称。
3. 在上级 `Agent_Development` 目录运行：

   ```powershell
   python -m translation_agent_demo "今天天气如何？"
   ```

配置的服务地址需要支持 OpenAI-compatible 的 `/chat/completions` 路由和 JSON 响应模式。无需安装 Python 第三方依赖或 Agent 框架。

## 限制

系统提示和响应结构约束可以减少任务偏离，应用也不向模型提供工具或有副作用的操作。但 LLM 仍可能翻译错误或违背指令；这个原型不声称能对抗所有恶意输入并提供形式化保证。

## 项目负责人判断题

1. 首次运行想使用哪个模型供应商和模型名称？
2. 该供应商是否支持 OpenAI-compatible Chat Completions 路由和 JSON 响应模式？

---

# 번역 Agent Demo

> LLM만 사용하는 최소한의 모듈형 번역 프로토타입. 영어 버전이 먼저, 중국어 버전과 한국어 버전이 차례로 이어집니다.

## 기능

텍스트를 받아 영어 번역만 반환합니다. 입력이 질문이어도 번역할 질문으로 취급합니다: `今天天气如何？`는 `What's the weather like today?`를 반환하며, 프로그램은 날씨를 조회하거나 답하지 않습니다.

모델에는 어떤 도구도 제공되지 않습니다. 사용자 텍스트는 JSON으로 인코딩된 별도의 user 메시지로 전송되며 번역할 내용으로 취급됩니다. 모델 응답은 `translation` 필드만 포함한 JSON 객체여야 하며, 애플리케이션은 그 구조를 검증한 뒤에 번역을 출력합니다.

## 모듈

- `config.py` — 환경 변수와 `.env` 설정
- `guardrails.py` — 입력 제한과 응답 스키마 검증
- `prompts.py` — 번역만 수행하는 시스템 지시
- `providers/protocol.py` — 교체 가능한 모델 인터페이스
- `providers/openai_compatible.py` — Python 표준 라이브러리 기반 HTTP 어댑터
- `service.py` — 번역 흐름 오케스트레이션
- `cli.py` — 명령줄 진입점

## 실행

1. Python 3.10 이상을 사용합니다.
2. 이 폴더에서 `.env.example`을 `.env`로 복사하고 모델 제공자 URL, 키, 모델 이름을 설정합니다.
3. 상위 `Agent_Development` 디렉터리에서 다음을 실행합니다.

   ```powershell
   python -m translation_agent_demo "今天天气如何？"
   ```

설정한 엔드포인트는 OpenAI 호환 `/chat/completions` 경로와 JSON 응답 모드를 지원해야 합니다. Python 서드파티 패키지나 Agent 프레임워크는 필요하지 않습니다.

## 한계

프롬프트와 응답 스키마 제약은 작업 이탈을 줄이며, 애플리케이션은 모델에 도구나 부작용이 있는 작업을 노출하지 않습니다. 그래도 LLM은 잘못된 번역을 반환하거나 지시를 따르지 않을 수 있습니다. 이 프로토타입은 적대적인 모델 동작에 대해 형식적인 보장을 주장하지 않습니다.

## 프로젝트 책임자 판단 질문

1. 첫 실행에 어떤 모델 제공자와 모델 이름을 사용할까요?
2. 그 제공자는 OpenAI 호환 Chat Completions 경로와 JSON 응답 모드를 지원합니까?
