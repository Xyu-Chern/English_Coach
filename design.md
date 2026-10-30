# AI English Speaking Phrase Agent — Design

> **Status:** Updated draft. English version first; Chinese and Korean versions follow. This design prioritizes Agent development. A user interface is an optional final stretch goal.

### Current minimal demo slice

The approved first code demo is isolated in `translation_agent_demo/`. It accepts user text and returns an English translation using an LLM, with no retrieval, external tools, or Agent framework. Its purpose is to demonstrate strict task boundaries and modular provider design. It is a prototype slice and does not replace the expression-retrieval MVP defined below.

## 1. Project goal

Build a Python Agent/API that helps learners around IELTS 7 recall natural spoken English expressions. A learner submits an idea in Chinese, the Agent interprets the intended meaning and context, searches a curated expression library through a typed tool, checks whether the results are relevant, and returns grounded English expressions or asks a clarifying question.

The portfolio should make the Agent behavior reviewable: tool inputs and outputs, retrieval evidence, workflow decisions, failure handling, and evaluation results should be visible and reproducible.

## 2. Target user and core scenario

- **User:** an English learner with approximately IELTS 7 proficiency who sometimes cannot recall an appropriate spoken expression quickly.
- **Core request:** “I know what I mean in Chinese, but what is a natural way to say it in English in this situation?”
- **Input:** a Chinese idea and optional situation/topic, such as everyday conversation or IELTS speaking.
- **Output:** the best matching stored English expression, its Chinese meaning and usage context; optionally up to two useful alternatives. When context or evidence is insufficient, the Agent asks a short question or reports that no close match was found.

## 3. MVP boundary

### P0 — required

- Python API for phrase search
- A bounded Agent workflow that interprets the query, calls a typed expression-search tool, checks evidence, and returns a structured result
- A curated, attributable expression dataset with metadata
- A search evaluation set with expected relevant results and no-match cases
- A comparison between a simple retrieval baseline and the Agent workflow
- Defined behavior for ambiguity, low-confidence matches, malformed input, and search-service failures
- Clear setup and architecture documentation

### P1 — if time allows after P0

- Persistent learner records or a `save_expression` tool/API
- Authentication and per-user data isolation
- Agent tracing for model calls, tool calls, retrieved records, latency, and token/cost usage
- Deployment of the API for a reviewer

### P2 — optional after the three-week core is complete

- Minimal browser interface for trying the API
- Full responsive web app or native mobile application
- Speech input, pronunciation scoring, broad tutoring chat, multi-agent orchestration, or spaced repetition

The project does not need a Next.js front end to demonstrate Agent development. Use an API client, command-line demo, or API documentation as the initial interface. Add a user interface only if the P0 work is complete and time remains.

## 4. Agent workflow

```mermaid
flowchart TD
  A[Chinese idea + optional context] --> B[Validate request]
  B --> C[Interpret intent and context]
  C --> D[Call typed search_expressions tool]
  D --> E[Retrieve and rank stored expressions]
  E --> F{Evidence relevant and sufficient?}
  F -->|Yes| G[Return grounded expression(s)]
  F -->|Need context| H[Ask one clarifying question]
  F -->|No useful match| I[Return no-match and invite refinement]
  G --> J[Record trace and evaluation fields]
  H --> J
  I --> J
```

Keep the model's autonomy bounded. The Agent may interpret intent, choose search filters, and decide whether to answer or clarify. It must not invent a database result, change user data without an explicit tool call, or retry indefinitely. A deterministic workflow should enforce schemas, permissions, step limits, and failure behavior.

## 5. Search tool and expression data

### `search_expressions`

The tool accepts a normalized intent, optional situation/topic, and bounded result count. It returns stored expression IDs, English text, Chinese meaning, usage notes, metadata, and relevance scores. It has a narrow read-only responsibility.

### Expression record

- `id`
- `english_text`
- `chinese_meaning`
- `usage_note`
- `example_text` (optional)
- `topic`, `situation`, and `register`
- `difficulty` or learner level
- `source` and reuse/license information
- searchable text and optional embedding
- timestamps and dataset version

Start with a small reviewed dataset; a proposed planning target is 100–300 expressions. The actual size and source depend on the course rules and available materials. Do not import content without checking reuse rights.

### Retrieval approach

1. Validate and normalize the Chinese query and optional context.
2. Retrieve candidates using lexical search and multilingual semantic search where available.
3. Apply relevant metadata filters and rank candidates.
4. Apply a confidence threshold selected by reviewing evaluation results.
5. Return only stored records. If retrieval is weak, clarify or report no match.

Begin with the simplest measurable baseline. Add query rewriting, reranking, or a vector database only if the evaluation set shows a meaningful need.

## 6. Proposed technical shape

| Area | Proposed starting point | Notes |
|---|---|---|
| Language/API | Python + FastAPI | Typed HTTP API and convenient integration with Agent and retrieval libraries |
| Agent | One bounded workflow; framework choice remains open | Use the course-required framework if there is one; otherwise compare a small LangGraph workflow with a simple custom workflow before choosing |
| Data | Start with the simplest database permitted by the course; PostgreSQL/pgvector is a deployment-ready option | Keep the retrieval interface independent of the storage choice |
| Model | Select an available model/provider after checking course access, cost, and language quality | Keep model calls behind a small adapter |
| Demo | OpenAPI/Swagger UI, a small CLI, or a minimal API client | A full front end is optional and last priority |
| Evaluation | A versioned query set plus a repeatable evaluation script or documented procedure | Compare the same queries and dataset across retrieval variants |

These are proposals, not decisions about vendors. Prefer tools required or already supported by the course.

## 7. API outline

- `POST /api/search` — accept a Chinese idea, optional context, and bounded result count; return structured results, a clarification request, or a no-match response.
- Optional later: `POST /api/saved-expressions` and `GET /api/saved-expressions` — persist and retrieve a learner's saved expressions.
- Optional later: authentication endpoints or integration with a managed identity provider.

The search response should distinguish `matched`, `needs_clarification`, and `no_match` outcomes. Do not use a client-supplied user ID as proof of identity.

## 8. Evaluation and acceptance

Build a fixed set of Chinese queries covering paraphrases, ambiguous meaning, context-sensitive expressions, several topic areas, and cases with no suitable stored result. A proposed starting size is 30–50 queries, adjusted to the time and data available.

Measure:

- Recall@k and Precision@k for retrieved expressions
- Whether the Agent preserves the user's intended meaning
- Whether retrieved expressions preserve intent and fit the requested situation and register
- Whether it asks for clarification or abstains on ambiguous/no-match cases
- Tool selection/argument validity, step count, latency, and model/tool failure behavior

Compare the Agent with a simple retrieval baseline on the same dataset. Review weak cases manually and record the prompt, model, dataset, and search version. Do not treat an LLM judge as ground truth.

The three-week core is complete when the API can perform the intended flow, results are grounded in stored records, no-match and failure paths are defined, and the evaluation comparison is reproducible.

## 9. Reliability and safety

- Validate request size, required fields, result limits, and tool arguments.
- Bound Agent steps, retries, latency, and model/tool usage per request.
- Retry only transient failures; do not endlessly retry invalid tool arguments.
- Return a useful error or fallback when the model or search service is unavailable.
- Treat user input and imported learning materials as untrusted data.
- Keep credentials outside source control and avoid logging secrets or unnecessary learner content.
- If persistence is added, enforce ownership on every read/write and define deletion behavior.

## 10. Interview readiness and relationship to `idea.md`

The original idea document describes a broader English coach. This MVP deliberately narrows the product to Chinese-to-English expression retrieval so the Agent, its search tool, and its evaluation can be built and explained well within the course project.

| Interview area from `idea.md` | Evidence this project should produce | Boundary to explain honestly |
|---|---|---|
| Product and architecture (Q1–7) | Target user, request-to-response flow, typed tool boundary, bounded Agent decisions, and reason for using one workflow | Voice input and mid-session activity switching are future work; the API should keep input handling separable from learning logic |
| Feedback and model behavior (Q8–14) | Preserve intended meaning, return only retrieved expressions, ask when ambiguous, and use a structured response | The MVP finds expressions; it does not claim to diagnose grammar mistakes or grade writing |
| RAG and learning materials (Q15–23) | Source/rights notes, expression metadata, lexical vs semantic baseline, retrieval metrics, threshold selection, and evidence grounding | A phrase library uses records rather than long-document chunks; reranking and query rewriting need evidence before adoption |
| Tools and reliability (Q24–32) | Typed `search_expressions` schema, bounded steps/retries, malformed-input handling, no-match fallback, and traces that help replay a failure | Write-tool idempotency matters only if persistence/save tools are added |
| Memory and personalization (Q33–39) | A clear boundary between per-request context and future learner memory; a documented path for save/history and user controls | Long-term profile, cross-session personalization, authentication, and deletion are not P0 unless the course requires them |
| Evaluation (Q40–46) | Fixed labeled queries, baseline comparison, Recall@k/Precision@k, human review, versioned regression cases, and latency/cost records | Report actual measurements and limitations; do not claim quality improvements without evidence |
| Backend, scale, and security (Q47–54) | API validation, identity/data isolation design if persistence is enabled, secret handling, timeouts, bounded work, and graceful degradation | High-concurrency load testing and production operations are outside the three-week core; explain what would be added and why |
| Ownership and trade-offs (Q55–60) | Keep a short decision/failure log and prepare a walkthrough connecting a design choice, the failure it prevents, and measured evidence | Only describe implementation and results that were actually completed by the project owner |

This project is interview-ready when each in-scope claim can be supported by a design artifact, a trace, or an evaluation result, and deferred features are described as deliberate scope decisions rather than completed capabilities.

## 11. Project Owner Judgment Questions

1. Should the first release focus on daily conversation, IELTS speaking, or both?
2. Should each response show one best expression or also include up to two alternatives?
3. Should each query support optional situation/topic context?
4. Is phrase saving/history part of the required product behavior, or a later extension?
5. Which expression-library fields are essential to help the learner choose a phrase?

---

# AI 英语口语表达 Agent — 设计文档

> **状态：**更新后的草案。英文版在前，其后依次为中文版和韩文版。本设计优先展示 Agent 开发；用户界面是最后的可选扩展。

### 当前最小 Demo 切片

已确认的首个代码 Demo 独立放在 `translation_agent_demo/` 中。它接收用户文本，只使用 LLM 返回英文翻译，不接检索、外部工具或 Agent 框架。这个 Demo 用于展示严格的任务边界和可替换的模型供应商设计。它是一个原型切片，不会替代下文定义的表达检索 MVP。

## 1. 项目目标

构建一个 Python Agent/API，帮助雅思水平约为 7 分的学习者快速想起自然的英语口语表达。学习者用中文描述想法后，Agent 理解意图和语境，通过有明确类型定义的工具搜索整理好的表达库，判断结果是否相关，然后返回有依据的英语表达，或提出澄清问题。

作品集需要让评审者看清 Agent 的行为：工具输入与输出、检索证据、工作流决策、故障处理和评估结果都应可查看、可重现。

## 2. 目标用户与核心场景

- **用户：**英语水平约为雅思 7 分、有时无法快速想起合适口语表达的学习者。
- **核心需求：**“我知道自己想用中文表达什么，但在这个情境下，用英语怎么说才自然？”
- **输入：**中文想法，可选场景/话题，例如日常交流或雅思口语。
- **输出：**最匹配的库内英语表达、中文含义和使用语境；也可以给出最多两个有用的替代说法。语境或证据不足时，Agent 应简短追问，或者说明没有找到足够接近的表达。

## 3. MVP 范围边界

### P0 — 必须完成

- 用于表达搜索的 Python API
- 有明确边界的 Agent 工作流：理解查询、调用类型明确的表达搜索工具、检查证据并返回结构化结果
- 经过整理且来源可追溯、带有元数据的表达数据集
- 包含预期相关结果和无匹配案例的搜索评估集
- 对比简单检索基线和 Agent 工作流
- 为歧义、低置信度匹配、无效输入和搜索服务故障定义处理方式
- 清晰的配置和架构文档

### P1 — P0 完成后有时间再做

- 持久化学习记录，或 `save_expression` 工具/API
- 身份验证和逐用户数据隔离
- Agent 调用追踪：模型调用、工具调用、检索记录、延迟及令牌/成本使用情况
- 部署 API，方便评审者体验

### P2 — 三周核心目标完成后的可选项

- 用于试用 API 的简易浏览器界面
- 完整的响应式网页应用或原生移动应用
- 语音输入、发音评分、泛化辅导聊天、多智能体编排或间隔重复系统

展示 Agent 开发不要求使用 Next.js 前端。初期可通过 API 客户端、命令行演示或 API 文档来试用。只有完成 P0 且仍有时间时，才添加用户界面。

## 4. Agent 工作流

```mermaid
flowchart TD
  A[中文想法 + 可选语境] --> B[校验请求]
  B --> C[理解意图和语境]
  C --> D[调用类型明确的 search_expressions 工具]
  D --> E[检索并排序库内表达]
  E --> F{证据是否充分且相关？}
  F -->|是| G[返回有依据的表达]
  F -->|需要语境| H[提出一个澄清问题]
  F -->|没有合适结果| I[说明无匹配并邀请用户补充]
  G --> J[记录追踪和评估字段]
  H --> J
  I --> J
```

限制模型的自主范围。Agent 可以理解意图、选择搜索筛选条件，并决定回答还是澄清；不得编造数据库结果、未经明确工具调用就修改用户数据，也不得无限重试。工作流应通过确定性逻辑执行结构校验、权限、步骤上限和故障处理。

## 5. 搜索工具与表达数据

### `search_expressions`

工具接收规范化后的意图、可选场景/话题和有上限的结果数量。它返回库内表达 ID、英文文本、中文含义、用法说明、元数据和相关度分数。该工具只负责只读搜索。

### 表达记录

- `id`
- `english_text`：英文表达
- `chinese_meaning`：中文含义
- `usage_note`：用法说明
- `example_text`：例句，可选
- `topic`、`situation` 和 `register`：话题、场景和语域
- `difficulty` 或学习者水平
- `source` 和重用/许可信息
- 可搜索文本及可选向量嵌入
- 时间戳和数据集版本

从小型人工审核数据集开始；建议先按 100–300 条表达做计划。实际规模和来源取决于课程要求及可用材料。导入内容前要检查重用权利。

### 检索方案

1. 校验并规范化中文查询和可选语境。
2. 在条件允许时，结合词法搜索和多语言语义搜索检索候选项。
3. 应用相关元数据筛选并为候选结果排序。
4. 根据评估结果选择置信度阈值。
5. 只返回库内记录。检索结果较弱时，应澄清或说明无匹配。

先从最简单且可衡量的基线开始。只有评估集显示确有明显需求时，才增加查询改写、重排或向量数据库。

## 6. 建议的技术形态

| 领域 | 初步建议 | 说明 |
|---|---|---|
| 语言/API | Python + FastAPI | 提供类型明确的 HTTP API，便于集成 Agent 和检索库 |
| Agent | 一个边界明确的工作流；框架待定 | 如果课程指定框架，优先使用；否则先比较小型 LangGraph 工作流和简单自定义工作流 |
| 数据 | 先用课程允许的最简单数据库；PostgreSQL/pgvector 可作为可部署方案 | 检索接口不依赖特定存储方案 |
| 模型 | 确认课程访问权限、成本和中文效果后再选模型/API | 将模型调用封装在小型适配层后 |
| 演示方式 | OpenAPI/Swagger UI、小型命令行程序或简易 API 客户端 | 完整前端是可选项，优先级最低 |
| 评估 | 有版本记录的查询集，以及可重复运行的评估脚本或流程 | 使用同一组查询和数据集比较不同检索方案 |

这些都是建议，不代表已经选定供应商。优先使用课程要求或已经提供的工具。

## 7. API 草案

- `POST /api/search`：接收中文想法、可选语境和有上限的结果数量；返回结构化结果、澄清请求或无匹配状态。
- 后续可选：`POST /api/saved-expressions` 和 `GET /api/saved-expressions`，用于持久化并读取学习者保存的表达。
- 后续可选：身份验证接口或托管身份服务集成。

搜索响应应区分 `matched`、`needs_clarification` 和 `no_match` 三种结果。不能把客户端提供的用户 ID 当作身份凭证。

## 8. 评估与验收

建立固定的中文查询集，覆盖不同说法、含义模糊、依赖语境的表达、多个话题，以及表达库中没有合适结果的情况。初步建议为 30–50 条查询，再根据时间和数据调整。

至少衡量：

- 检索表达的 Recall@k 和 Precision@k
- Agent 是否保留用户本来的意思
- 检索表达是否保留原意，并符合用户要求的场景和语域
- 在歧义或无匹配情况下，Agent 是否会澄清或明确拒答
- 工具选择与参数是否合法、步骤数、延迟，以及模型/工具故障时的表现

在相同数据集上对比 Agent 和简单检索基线。人工复核效果较差的案例，并记录提示词、模型、数据集和搜索版本。不要把 LLM 评审分数当成绝对真值。

三周核心目标的完成标准是：API 能完成预期流程；返回内容有库内记录作为依据；无匹配和故障路径有明确处理；评估对比可以重复进行。

## 9. 可靠性与安全

- 校验请求大小、必填字段、结果数量限制和工具参数。
- 限制每次请求的 Agent 步骤、重试次数、延迟和模型/工具使用量。
- 只对暂时性故障重试；无效工具参数不得无限重试。
- 模型或搜索服务不可用时，返回有用的错误说明或降级结果。
- 将用户输入和导入的学习材料视为不可信数据。
- 不把凭证提交到源码管理，并避免记录密钥和不必要的学习者内容。
- 如果添加持久化存储，对每次读写执行所有权校验，并明确数据删除方式。

## 10. 面试准备及与 `idea.md` 的对应关系

原始 idea 文档描述的是更完整的英语教练。本 MVP 有意缩小为“中文想法检索英语表达”，以便在课程项目时间内把 Agent、搜索工具和评估做扎实，并能清楚讲解。

| `idea.md` 中的面试主题 | 本项目应产出的证据 | 需要诚实说明的范围边界 |
|---|---|---|
| 产品与架构（Q1–7） | 目标用户、请求到响应的流程、类型明确的工具边界、受限的 Agent 决策，以及采用单一工作流的原因 | 语音输入和会话中途切换活动属于后续工作；API 应让输入处理与学习逻辑保持可分离 |
| 反馈与模型行为（Q8–14） | 保留原意、只返回检索表达、遇到歧义时追问、使用结构化响应 | MVP 负责查找表达，不宣称能诊断语法错误或给写作评分 |
| RAG 与学习材料（Q15–23） | 来源/许可记录、表达元数据、词法与语义基线对比、检索指标、阈值选择和证据依据 | 表达库使用记录，而不是长文档分块；只有评估证明必要时才加入重排和查询改写 |
| 工具与可靠性（Q24–32） | `search_expressions` 类型定义、有限步骤/重试、错误参数处理、无匹配降级，以及便于重现故障的追踪信息 | 只有添加保存等写入工具后，幂等写入才成为必要事项 |
| 记忆与个性化（Q33–39） | 明确区分单次请求语境与未来学习者记忆；记录保存/历史功能和用户控制的后续方案 | 长期学习者档案、跨会话个性化、身份验证和数据删除不属于 P0，除非课程要求 |
| 评估（Q40–46） | 固定标注查询集、基线对比、Recall@k/Precision@k、人工复核、带版本的回归案例，以及延迟/成本记录 | 只报告实际测量和限制；没有证据就不声称质量提升 |
| 后端、规模与安全（Q47–54） | API 校验；启用持久化时的身份/数据隔离设计；密钥处理、超时、工作量限制和降级行为 | 高并发压力测试和生产运维不属于三周核心；要说明扩展时会增加什么以及原因 |
| 项目归属与权衡（Q55–60） | 简短记录设计决策和失败案例，并准备演示，说明某个设计选择预防了什么问题及其测量证据 | 只描述项目负责人实际完成的实现和结果 |

当项目范围内的每项主张都有设计材料、追踪记录或评估结果支撑，并且后续功能被明确描述为范围选择而非已实现能力时，本项目就具备面试展示基础。

## 11. 项目负责人判断题

1. 第一版优先支持日常交流、雅思口语，还是两者都支持？
2. 每次只显示一个最佳表达，还是再提供最多两个替代说法？
3. 是否允许用户为每次查询补充场景/话题语境？
4. 保存表达/搜索历史是必需行为，还是后续扩展？
5. 哪些表达库字段对用户判断是否使用该表达最重要？

---

# AI 영어 말하기 표현 Agent — 설계 문서

> **상태:** 업데이트된 초안. 영어 버전이 먼저, 중국어 버전과 한국어 버전이 차례로 이어집니다. 이 설계는 Agent 개발을 우선합니다. 사용자 인터페이스는 마지막 선택적 확장 목표입니다.

### 현재 최소 Demo 슬라이스

승인된 첫 코드 Demo는 `translation_agent_demo/`에 따로 있습니다. 사용자 텍스트를 받아 LLM으로 영어 번역을 반환하며, 검색, 외부 도구, Agent 프레임워크는 사용하지 않습니다. 목적은 엄격한 작업 경계와 교체 가능한 모델 제공자 설계를 보여 주는 것입니다. 이는 프로토타입 슬라이스이며, 아래에 정의된 표현 검색 MVP를 대체하지 않습니다.

## 1. 프로젝트 목표

IELTS 7점 안팎의 학습자가 자연스러운 영어 구어 표현을 떠올리도록 돕는 Python Agent/API를 만듭니다. 학습자가 중국어로 생각을 입력하면 Agent가 의도한 의미와 맥락을 해석하고, 타입이 정의된 도구로 선별된 표현 라이브러리를 검색하고, 결과가 관련 있는지 확인한 뒤, 근거가 있는 영어 표현을 반환하거나 확인 질문을 합니다.

포트폴리오는 Agent의 동작을 검토할 수 있게 해야 합니다. 도구 입력과 출력, 검색 근거, 워크플로 결정, 장애 처리, 평가 결과를 확인하고 재현할 수 있어야 합니다.

## 2. 대상 사용자와 핵심 시나리오

- **사용자:** 영어 실력이 IELTS 7점 정도이며, 적절한 구어 표현을 바로 떠올리지 못할 때가 있는 학습자.
- **핵심 요청:** "중국어로는 무슨 말을 하고 싶은지 아는데, 이 상황에서 영어로 자연스럽게 말하려면 어떻게 해야 하지?"
- **입력:** 중국어로 쓴 생각과 선택적인 상황/주제(예: 일상 대화, IELTS 말하기).
- **출력:** 가장 잘 맞는 라이브러리 내 영어 표현, 그 중국어 의미와 사용 맥락. 선택적으로 유용한 대안 표현을 최대 두 개까지 제공합니다. 맥락이나 근거가 부족하면 Agent는 짧게 질문하거나, 충분히 가까운 표현을 찾지 못했다고 알립니다.

## 3. MVP 범위

### P0 — 필수

- 표현 검색용 Python API
- 질의를 해석하고, 타입이 정의된 표현 검색 도구를 호출하고, 근거를 확인한 뒤 구조화된 결과를 반환하는, 범위가 제한된 Agent 워크플로
- 출처를 추적할 수 있고 메타데이터를 갖춘 선별된 표현 데이터셋
- 기대되는 관련 결과와 일치 없음 사례를 포함한 검색 평가 세트
- 단순 검색 베이스라인과 Agent 워크플로의 비교
- 모호성, 낮은 신뢰도의 매칭, 잘못된 입력, 검색 서비스 장애에 대한 정의된 동작
- 명확한 설정 및 아키텍처 문서

### P1 — P0 완료 후 시간이 있으면

- 영구 학습 기록 또는 `save_expression` 도구/API
- 인증과 사용자별 데이터 격리
- 모델 호출, 도구 호출, 검색된 레코드, 지연 시간, 토큰/비용 사용량에 대한 Agent 트레이싱
- 리뷰어가 사용해 볼 수 있도록 API 배포

### P2 — 3주 핵심 목표 완료 후 선택 사항

- API를 시험해 볼 수 있는 최소한의 브라우저 인터페이스
- 완전한 반응형 웹 앱 또는 네이티브 모바일 앱
- 음성 입력, 발음 채점, 범용 튜터링 채팅, 멀티 에이전트 오케스트레이션, 간격 반복 학습

Agent 개발을 보여 주는 데 Next.js 프런트엔드는 필요하지 않습니다. 초기 인터페이스로는 API 클라이언트, 명령줄 데모, API 문서를 사용합니다. P0 작업이 끝나고 시간이 남을 때만 사용자 인터페이스를 추가합니다.

## 4. Agent 워크플로

```mermaid
flowchart TD
  A[중국어 생각 + 선택적 맥락] --> B[요청 검증]
  B --> C[의도와 맥락 해석]
  C --> D[타입이 정의된 search_expressions 도구 호출]
  D --> E[라이브러리 내 표현 검색 및 순위 지정]
  E --> F{근거가 관련 있고 충분한가?}
  F -->|예| G[근거 있는 표현 반환]
  F -->|맥락 필요| H[확인 질문 하나 하기]
  F -->|유용한 결과 없음| I[일치 없음 반환 및 보완 요청]
  G --> J[트레이스와 평가 필드 기록]
  H --> J
  I --> J
```

모델의 자율성은 제한합니다. Agent는 의도를 해석하고, 검색 필터를 고르고, 답할지 확인 질문을 할지 결정할 수 있습니다. 데이터베이스 결과를 지어내거나, 명시적인 도구 호출 없이 사용자 데이터를 변경하거나, 무한히 재시도해서는 안 됩니다. 스키마, 권한, 단계 제한, 장애 처리 동작은 결정론적 워크플로가 강제해야 합니다.

## 5. 검색 도구와 표현 데이터

### `search_expressions`

이 도구는 정규화된 의도, 선택적 상황/주제, 상한이 있는 결과 개수를 입력받습니다. 라이브러리 내 표현 ID, 영어 텍스트, 중국어 의미, 사용 메모, 메타데이터, 관련도 점수를 반환합니다. 읽기 전용 검색이라는 좁은 책임만 가집니다.

### 표현 레코드

- `id`
- `english_text`: 영어 표현
- `chinese_meaning`: 중국어 의미
- `usage_note`: 사용 메모
- `example_text`: 예문(선택)
- `topic`, `situation`, `register`: 주제, 상황, 격식 수준
- `difficulty` 또는 학습자 수준
- `source`와 재사용/라이선스 정보
- 검색 가능한 텍스트와 선택적 임베딩
- 타임스탬프와 데이터셋 버전

사람이 검토한 작은 데이터셋으로 시작합니다. 계획상 제안 목표는 표현 100–300개입니다. 실제 규모와 출처는 수업 규칙과 사용 가능한 자료에 따라 달라집니다. 재사용 권리를 확인하지 않은 콘텐츠는 가져오지 않습니다.

### 검색 방식

1. 중국어 질의와 선택적 맥락을 검증하고 정규화합니다.
2. 가능하면 어휘 기반 검색과 다국어 의미 검색을 함께 사용해 후보를 찾습니다.
3. 관련 메타데이터 필터를 적용하고 후보의 순위를 매깁니다.
4. 평가 결과를 검토해 정한 신뢰도 임계값을 적용합니다.
5. 라이브러리 내 레코드만 반환합니다. 검색 결과가 약하면 확인 질문을 하거나 일치 없음을 알립니다.

측정 가능한 가장 단순한 베이스라인부터 시작합니다. 질의 재작성, 재순위화, 벡터 데이터베이스는 평가 세트에서 의미 있는 필요가 확인될 때만 추가합니다.

## 6. 제안 기술 구성

| 영역 | 초기 제안 | 비고 |
|---|---|---|
| 언어/API | Python + FastAPI | 타입이 정의된 HTTP API를 제공하고 Agent 및 검색 라이브러리와 쉽게 통합 |
| Agent | 범위가 제한된 워크플로 하나, 프레임워크는 미정 | 수업에서 지정한 프레임워크가 있으면 사용하고, 없으면 작은 LangGraph 워크플로와 단순한 자체 워크플로를 비교한 뒤 선택 |
| 데이터 | 수업에서 허용하는 가장 단순한 데이터베이스로 시작, PostgreSQL/pgvector는 배포 가능한 선택지 | 검색 인터페이스가 특정 저장소에 의존하지 않도록 유지 |
| 모델 | 수업 접근 권한, 비용, 언어 품질을 확인한 뒤 사용 가능한 모델/제공자 선택 | 모델 호출은 작은 어댑터 뒤에 둠 |
| 데모 | OpenAPI/Swagger UI, 작은 CLI, 최소 API 클라이언트 | 완전한 프런트엔드는 선택 사항이며 우선순위가 가장 낮음 |
| 평가 | 버전이 관리되는 질의 세트와 반복 실행 가능한 평가 스크립트 또는 문서화된 절차 | 같은 질의와 데이터셋으로 검색 방식별 결과 비교 |

이는 제안일 뿐 공급업체를 결정한 것이 아닙니다. 수업에서 요구하거나 이미 지원하는 도구를 우선합니다.

## 7. API 개요

- `POST /api/search` — 중국어 생각, 선택적 맥락, 상한이 있는 결과 개수를 받아 구조화된 결과, 확인 요청, 일치 없음 응답 중 하나를 반환합니다.
- 이후 선택 사항: `POST /api/saved-expressions`와 `GET /api/saved-expressions` — 학습자가 저장한 표현을 영구 저장하고 조회합니다.
- 이후 선택 사항: 인증 엔드포인트 또는 관리형 ID 공급자 연동.

검색 응답은 `matched`, `needs_clarification`, `no_match` 결과를 구분해야 합니다. 클라이언트가 보낸 사용자 ID를 신원 증명으로 사용하지 않습니다.

## 8. 평가와 검수 기준

다르게 바꿔 말한 표현, 의미가 모호한 경우, 맥락에 따라 달라지는 표현, 여러 주제 영역, 라이브러리에 적합한 결과가 없는 경우를 포함하는 고정된 중국어 질의 세트를 만듭니다. 초기 제안 규모는 질의 30–50개이며, 시간과 데이터에 맞춰 조정합니다.

측정 항목:

- 검색된 표현의 Recall@k와 Precision@k
- Agent가 사용자가 의도한 의미를 보존하는지
- 검색된 표현이 의도를 보존하고, 요청된 상황과 격식 수준에 맞는지
- 모호하거나 일치하는 결과가 없을 때 확인 질문을 하거나 답변을 보류하는지
- 도구 선택/인자 유효성, 단계 수, 지연 시간, 모델/도구 장애 시 동작

같은 데이터셋에서 Agent와 단순 검색 베이스라인을 비교합니다. 결과가 약한 사례는 직접 검토하고 프롬프트, 모델, 데이터셋, 검색 버전을 기록합니다. LLM 평가자의 점수를 정답 기준으로 취급하지 않습니다.

3주 핵심 목표는 API가 의도한 흐름을 수행하고, 결과가 라이브러리 내 레코드에 근거하며, 일치 없음 및 장애 경로가 정의되어 있고, 평가 비교를 재현할 수 있을 때 완료됩니다.

## 9. 안정성과 안전

- 요청 크기, 필수 필드, 결과 개수 제한, 도구 인자를 검증합니다.
- 요청당 Agent 단계, 재시도, 지연 시간, 모델/도구 사용량을 제한합니다.
- 일시적인 장애만 재시도하고, 잘못된 도구 인자는 끝없이 재시도하지 않습니다.
- 모델이나 검색 서비스를 사용할 수 없으면 유용한 오류 또는 대체 응답을 반환합니다.
- 사용자 입력과 가져온 학습 자료를 신뢰할 수 없는 데이터로 취급합니다.
- 자격 증명은 소스 관리 밖에 두고, 비밀 정보나 불필요한 학습자 콘텐츠를 로그에 남기지 않습니다.
- 영구 저장을 추가하면 모든 읽기/쓰기에서 소유권을 확인하고 삭제 동작을 정의합니다.

## 10. 면접 준비와 `idea.md`와의 관계

원래 아이디어 문서는 더 넓은 범위의 영어 코치를 설명합니다. 이 MVP는 수업 프로젝트 기간 안에 Agent, 검색 도구, 평가를 제대로 만들고 설명할 수 있도록 제품을 중국어→영어 표현 검색으로 의도적으로 좁혔습니다.

| `idea.md`의 면접 영역 | 이 프로젝트가 만들어야 할 근거 | 솔직하게 설명할 범위 경계 |
|---|---|---|
| 제품과 아키텍처(Q1–7) | 대상 사용자, 요청에서 응답까지의 흐름, 타입이 정의된 도구 경계, 제한된 Agent 결정, 단일 워크플로를 쓰는 이유 | 음성 입력과 세션 중 활동 전환은 향후 작업이며, API는 입력 처리와 학습 로직을 분리할 수 있게 유지해야 함 |
| 피드백과 모델 동작(Q8–14) | 의도한 의미 보존, 검색된 표현만 반환, 모호할 때 질문, 구조화된 응답 사용 | MVP는 표현을 찾아 줄 뿐, 문법 오류 진단이나 작문 채점을 한다고 주장하지 않음 |
| RAG와 학습 자료(Q15–23) | 출처/권리 메모, 표현 메타데이터, 어휘 기반 대 의미 기반 베이스라인, 검색 지표, 임계값 선택, 근거 연결 | 표현 라이브러리는 긴 문서 청크가 아닌 레코드를 사용하며, 재순위화와 질의 재작성은 근거가 있어야 도입 |
| 도구와 안정성(Q24–32) | 타입이 정의된 `search_expressions` 스키마, 제한된 단계/재시도, 잘못된 입력 처리, 일치 없음 대체 응답, 장애 재현에 도움이 되는 트레이스 | 쓰기 도구의 멱등성은 영구 저장/저장 도구를 추가할 때만 중요함 |
| 메모리와 개인화(Q33–39) | 요청별 맥락과 향후 학습자 메모리 사이의 명확한 경계, 저장/기록 기능과 사용자 제어에 대한 문서화된 방향 | 장기 프로필, 세션 간 개인화, 인증, 삭제는 수업에서 요구하지 않는 한 P0가 아님 |
| 평가(Q40–46) | 고정된 레이블 질의, 베이스라인 비교, Recall@k/Precision@k, 사람의 검토, 버전이 관리되는 회귀 사례, 지연 시간/비용 기록 | 실제 측정값과 한계를 보고하고, 근거 없이 품질 향상을 주장하지 않음 |
| 백엔드, 확장성, 보안(Q47–54) | API 검증, 영구 저장 활성화 시 신원/데이터 격리 설계, 비밀 정보 처리, 타임아웃, 작업량 제한, 우아한 성능 저하 | 고동시성 부하 테스트와 운영 환경 관리는 3주 핵심 범위 밖이며, 무엇을 왜 추가할지 설명 |
| 주도성과 트레이드오프(Q55–60) | 짧은 결정/실패 로그를 유지하고, 설계 선택·그것이 막는 장애·측정 근거를 연결하는 시연 설명 준비 | 프로젝트 책임자가 실제로 완료한 구현과 결과만 설명 |

범위 안의 모든 주장이 설계 산출물, 트레이스, 평가 결과로 뒷받침되고, 보류된 기능이 완성된 기능이 아니라 의도적인 범위 결정으로 설명될 때 이 프로젝트는 면접에서 보여 줄 준비가 된 것입니다.

## 11. 프로젝트 책임자 판단 질문

1. 첫 릴리스는 일상 대화, IELTS 말하기, 또는 둘 다 중 무엇에 집중해야 합니까?
2. 각 응답에 가장 좋은 표현 하나만 보여 줄까요, 아니면 대안을 최대 두 개까지 함께 보여 줄까요?
3. 각 질의에서 선택적 상황/주제 맥락을 지원해야 합니까?
4. 표현 저장/기록은 필수 제품 동작입니까, 아니면 이후 확장입니까?
5. 학습자가 표현을 고르는 데 꼭 필요한 표현 라이브러리 필드는 무엇입니까?
