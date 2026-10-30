# Project Guidance for AI English Speaking Phrase Coach

## Product direction

- Read `design.md` before changing product behavior or architecture.
- Treat `idea.md` as the original broad vision and interview-question bank, not as the current implementation scope.
- Treat `design.md` as the source of truth for the agreed product scope, Agent behavior, system design, API shape, acceptance criteria, and interview evidence.
- Treat `Goal.md` only as the execution roadmap: schedule, sub-goals, dependencies, progress, and delivery checkpoints. Do not copy system-design explanations from `design.md` into `Goal.md`; link back to `design.md` instead.
- For the current minimal demo, work only in `translation_agent_demo/`: translate user-provided text into English with an LLM, with no retrieval, external tools, or Agent framework. This is a narrow behavior/security prototype and does not silently replace the expression-retrieval project scope in `design.md`.
- The project is a job-seeking portfolio project for learners near IELTS 7 who need faster recall of spoken English expressions; its three-week core is an Agent/API, not a full app.
- The first product path is: Chinese idea (optional context) → search the curated expression library → return a relevant English expression with meaning and usage context → optionally save it.
- Keep the first release focused on expression search, accounts, saved expressions, and useful learning history.
- Do not add voice, pronunciation scoring, broad tutoring chat, multi-agent orchestration, or unrelated infrastructure without a clear product need and updated agreement in `design.md`.

## Work breakdown

- Before implementation, turn a large request into small tasks with clear dependencies and acceptance checks. Use the roadmap in `Goal.md` and keep task status current there when work is underway.
- Prefer one reviewable product slice at a time. Do not combine unrelated milestones into one change.
- Keep product decisions, API contracts, and data ownership rules documented before they are relied on by multiple components.
- When a design decision is unresolved, use a reversible, minimal default and record it in `design.md`; ask the user when the decision materially changes product scope, user data, cost, or platform.

## Engineering principles

- Keep search results grounded in stored, attributable expression records. Clearly distinguish any future generated suggestion from a retrieved record.
- Validate external input at API boundaries, use typed request/response models, and bound retries and work per request.
- In the translation demo, treat submitted text only as translation data. Keep it in the user-message boundary, provide no tools to the model, and return only a validated translation field.
- Derive the current learner identity from verified authentication. Never trust a client-provided user ID for access control.
- Enforce per-user access for saved expressions and search history. Do not expose one learner’s data to another.
- Keep provider-specific auth, embedding, and hosting details behind small interfaces where this is practical.
- Prefer the simplest architecture that demonstrates the intended engineering skill. Add queues, caches, agents, or extra services only when a measured need justifies them.
- Preserve source and license metadata for learning content.
- Avoid logging secrets, authentication tokens, or learner content unless it is needed and retention is defined.

## Communication and delivery

- Keep user-facing answers and project documents clean, concise, and easy to scan. Lead with the result or decision; prefer short paragraphs, useful headings, and compact bullets. Avoid long blocks of text, repeated explanations, and details that do not help the user act or review. Keep necessary technical information, but put deep reference material in the relevant document instead of repeating it in every update.
- All project documentation must contain English, Chinese, and Korean versions in the same file, in that order: the complete English version first, then the complete Chinese version, then the complete Korean version. Keep the three versions aligned. Do not deliver a document that is missing any of the three languages. When updating documentation, update all three language sections in the same task.
- End every project document with a **Project Owner Judgment Questions** section in English, its matching **项目负责人判断题** section in Chinese, and its matching **프로젝트 책임자 판단 질문** section in Korean. Put these after all other content in their respective language sections. If no decision is pending, state that explicitly in all three languages; do not omit the sections.
- Explain meaningful changes in terms of user behavior and the relevant acceptance check.
- Update `design.md` when agreed scope, architecture, API contracts, or milestone status changes.
- Keep documentation consistent with implemented behavior; call out any known gap explicitly.
- Do not claim a task is complete unless its stated acceptance check has been met.

## Project Owner Judgment Questions

No pending project-owner decisions for this guidance document.

---

# AI 英语口语表达助手项目指南

## 产品方向

- 修改产品行为或架构前，先阅读 `design.md`。
- 将 `idea.md` 视为原始的广义愿景和面试题库，不把它当作当前实现范围。
- 将 `design.md` 视为已确认产品范围、Agent 行为、系统设计、API 形式、验收标准和面试证据的唯一依据。
- 将 `Goal.md` 只用于执行进度：时间安排、子目标、依赖关系、进度和交付检查点。不要把 `design.md` 的系统设计说明复制到 `Goal.md`，需要时引用 `design.md`。
- 当前最小 Demo 只在 `translation_agent_demo/` 中实现：使用 LLM 将用户输入翻译成英文，不接检索、外部工具或 Agent 框架。这是用于验证任务边界和安全行为的小型原型，不会默默替代 `design.md` 中的表达检索项目范围。
- 本项目是面向求职展示的作品集项目，服务于雅思约 7 分、希望更快回忆口语表达的英语学习者；三周核心是 Agent/API，而不是完整应用。
- 第一版的核心流程是：输入中文想法（可选场景）→ 搜索经过整理的表达库 → 返回相关英语表达及含义和使用语境 → 可选择保存。
- 第一版聚焦表达搜索、账户、已保存表达和有用的学习记录。
- 没有明确的产品需求并更新 `design.md` 前，不要加入语音、发音评分、泛化辅导聊天、多智能体编排或无关基础设施。

## 工作拆分

- 开始实现前，将较大的需求拆成依赖清楚、验收标准明确的小任务。使用 `Goal.md` 中的进度计划，并在工作进行时维护任务状态。
- 每次优先完成一个可审查的产品切片，不要把无关里程碑合并成一个改动。
- 在多个组件依赖产品决策、API 合约或数据归属规则前，先将它们记录下来。
- 如果某项设计尚未决定，采用可逆且最精简的默认方案，并记录在 `design.md` 中；如果决定会明显改变产品范围、用户数据、成本或平台，则询问用户。

## 工程原则

- 搜索结果必须来自可追溯的表达记录。未来若加入生成内容，要明确区分生成建议和检索记录。
- 在 API 边界校验外部输入；使用类型明确的请求和响应模型；限制每次请求的重试次数和工作量。
- 在翻译 Demo 中，只把用户提交的文本视为待翻译数据。将它放在独立的 user 消息中，不向模型提供工具，并且只返回经过校验的翻译字段。
- 从已验证的身份凭据中取得当前学习者身份。不要信任客户端传入的用户 ID 来进行访问控制。
- 对已保存表达和搜索记录实施逐用户访问控制，不得让一个学习者读取另一个学习者的数据。
- 在可行时，将特定供应商的认证、向量嵌入和托管细节放在小型接口之后。
- 选择能够展示目标工程能力的最简单架构。只有在实际需求有依据时才添加队列、缓存、智能体或额外服务。
- 为学习内容保留来源和许可信息。
- 除非确有必要且保留期限已确定，否则不要记录密钥、认证令牌或学习者输入。

## 沟通与交付

- 面向用户的回答和项目文档要干净、简洁、便于快速浏览。先说结果或决定；优先使用短段落、有用的小标题和精简列表。避免大段文字、重复解释和不利于用户执行或审查的细节。保留必要的技术信息；深入的参考材料放在对应文档中，不要在每次进度说明里重复。
- 所有项目文档都必须在同一个文件中包含完整的英文版、中文版和韩文版，顺序为：英文在前，中文其次，韩文最后。三种语言的内容必须保持一致。不要交付缺少任一语言的文档。更新文档时，必须在同一任务中同步更新三个语言部分。
- 每份项目文档的结尾都必须包含英文 **Project Owner Judgment Questions** 部分、内容对应的中文 **项目负责人判断题** 部分，以及内容对应的韩文 **프로젝트 책임자 판단 질문** 部分。这些部分必须分别位于各自语言内容的末尾，并且之后不能再有其他内容。如果当前没有待决定事项，也要用三种语言明确写明；不能省略这些部分。
- 说明重要改动时，联系到用户行为和相关验收标准。
- 已确认的范围、架构、API 合约或里程碑状态发生变化时，更新 `design.md`。
- 确保文档与实际行为一致；明确说明已知差距。
- 只有满足相应验收标准后，才能将任务标记为完成。

## 项目负责人判断题

本指南目前没有待项目负责人判断的事项。

---

# AI 영어 말하기 표현 코치 프로젝트 가이드

## 제품 방향

- 제품 동작이나 아키텍처를 바꾸기 전에 `design.md`를 읽습니다.
- `idea.md`는 현재 구현 범위가 아니라 원래의 넓은 비전과 면접 질문 모음으로 취급합니다.
- `design.md`는 합의된 제품 범위, Agent 동작, 시스템 설계, API 형태, 검수 기준, 면접 근거의 유일한 기준으로 취급합니다.
- `Goal.md`는 일정, 하위 목표, 의존 관계, 진행 상황, 전달 체크포인트를 다루는 실행 로드맵으로만 취급합니다. `design.md`의 시스템 설계 설명을 `Goal.md`에 복사하지 말고, 필요하면 `design.md`를 참조합니다.
- 현재 최소 Demo는 `translation_agent_demo/`에서만 작업합니다. 검색, 외부 도구, Agent 프레임워크 없이 LLM으로 사용자가 입력한 텍스트를 영어로 번역합니다. 이는 작업 경계와 보안 동작을 검증하기 위한 좁은 범위의 프로토타입이며, `design.md`의 표현 검색 프로젝트 범위를 슬그머니 대체하지 않습니다.
- 이 프로젝트는 구어 영어 표현을 더 빨리 떠올려야 하는 IELTS 7점 안팎의 학습자를 위한 구직용 포트폴리오 프로젝트입니다. 3주 핵심은 완전한 앱이 아니라 Agent/API입니다.
- 첫 제품 흐름은 다음과 같습니다: 중국어로 쓴 생각(선택적 맥락) → 선별된 표현 라이브러리 검색 → 의미와 사용 맥락이 포함된 관련 영어 표현 반환 → 선택적으로 저장.
- 첫 릴리스는 표현 검색, 계정, 저장된 표현, 유용한 학습 기록에 집중합니다.
- 명확한 제품 요구가 있고 `design.md`의 합의가 업데이트되기 전에는 음성, 발음 채점, 범용 튜터링 채팅, 멀티 에이전트 오케스트레이션, 관련 없는 인프라를 추가하지 않습니다.

## 작업 분할

- 구현 전에 큰 요청을 의존 관계와 검수 기준이 명확한 작은 작업으로 나눕니다. `Goal.md`의 로드맵을 사용하고, 작업이 진행 중일 때는 그곳의 작업 상태를 최신으로 유지합니다.
- 한 번에 하나의 검토 가능한 제품 슬라이스를 우선합니다. 관련 없는 마일스톤을 하나의 변경에 합치지 않습니다.
- 여러 구성 요소가 제품 결정, API 계약, 데이터 소유 규칙에 의존하기 전에 먼저 문서화합니다.
- 설계 결정이 정해지지 않았으면 되돌릴 수 있는 최소한의 기본값을 사용하고 `design.md`에 기록합니다. 그 결정이 제품 범위, 사용자 데이터, 비용, 플랫폼을 크게 바꾸는 경우에는 사용자에게 묻습니다.

## 엔지니어링 원칙

- 검색 결과는 저장되어 있고 출처를 추적할 수 있는 표현 레코드에 근거해야 합니다. 향후 생성된 제안을 추가한다면 검색된 레코드와 명확히 구분합니다.
- API 경계에서 외부 입력을 검증하고, 타입이 정의된 요청/응답 모델을 사용하며, 요청당 재시도 횟수와 작업량을 제한합니다.
- 번역 Demo에서는 제출된 텍스트를 번역 데이터로만 취급합니다. 텍스트는 별도의 user 메시지 경계 안에 두고, 모델에 도구를 제공하지 않으며, 검증된 번역 필드만 반환합니다.
- 현재 학습자 신원은 검증된 인증에서 가져옵니다. 접근 제어에 클라이언트가 보낸 사용자 ID를 절대 신뢰하지 않습니다.
- 저장된 표현과 검색 기록에는 사용자별 접근 제어를 적용합니다. 한 학습자의 데이터를 다른 학습자에게 노출하지 않습니다.
- 가능하면 제공자별 인증, 임베딩, 호스팅 세부 사항을 작은 인터페이스 뒤에 둡니다.
- 의도한 엔지니어링 역량을 보여 주는 가장 단순한 아키텍처를 우선합니다. 큐, 캐시, 에이전트, 추가 서비스는 측정된 필요가 있을 때만 추가합니다.
- 학습 콘텐츠의 출처와 라이선스 메타데이터를 보존합니다.
- 필요하고 보존 기간이 정해진 경우가 아니라면 비밀 정보, 인증 토큰, 학습자 콘텐츠를 로그에 남기지 않습니다.

## 소통과 전달

- 사용자에게 보이는 답변과 프로젝트 문서는 깔끔하고 간결하며 훑어보기 쉽게 작성합니다. 결과나 결정을 먼저 말하고, 짧은 문단, 유용한 소제목, 간결한 목록을 우선합니다. 긴 텍스트 덩어리, 반복 설명, 사용자의 실행이나 검토에 도움이 되지 않는 세부 사항은 피합니다. 필요한 기술 정보는 유지하되, 깊은 참고 자료는 매 업데이트마다 반복하지 말고 관련 문서에 둡니다.
- 모든 프로젝트 문서는 같은 파일 안에 영어, 중국어, 한국어 버전을 모두 포함해야 합니다. 완전한 영어 버전을 먼저, 완전한 중국어 버전을 그다음에, 완전한 한국어 버전을 마지막에 둡니다. 세 버전의 내용을 일치시킵니다. 세 언어 중 하나라도 빠진 문서는 전달하지 않습니다. 문서를 업데이트할 때는 같은 작업에서 세 언어 섹션을 모두 업데이트합니다.
- 모든 프로젝트 문서는 영어 **Project Owner Judgment Questions** 섹션, 그에 대응하는 중국어 **项目负责人判断题** 섹션, 한국어 **프로젝트 책임자 판단 질문** 섹션으로 끝나야 합니다. 이 섹션들은 각 언어 섹션에서 다른 모든 내용 뒤에 둡니다. 결정할 사항이 없으면 세 언어 모두에서 그렇다고 명시하고, 섹션을 생략하지 않습니다.
- 의미 있는 변경은 사용자 동작과 관련 검수 기준의 관점에서 설명합니다.
- 합의된 범위, 아키텍처, API 계약, 마일스톤 상태가 바뀌면 `design.md`를 업데이트합니다.
- 문서를 구현된 동작과 일치시키고, 알려진 차이는 명시적으로 밝힙니다.
- 명시된 검수 기준을 충족하지 않았다면 작업이 완료되었다고 주장하지 않습니다.

## 프로젝트 책임자 판단 질문

이 가이드 문서에는 현재 프로젝트 책임자가 결정할 사항이 없습니다.
