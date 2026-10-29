# Translation Agent Demo

> Minimal, modular LLM-only translation prototype. English first; Chinese follows.

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

> 仅使用 LLM 的模块化翻译原型。英文版在前，中文版在后。

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
