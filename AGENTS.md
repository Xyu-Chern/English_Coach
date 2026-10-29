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
- All project documentation must contain both English and Chinese versions in the same file, with the complete English version first and the complete Chinese version after it. Keep the two versions aligned. Do not deliver a single-language-only document. When updating documentation, update both language sections in the same task.
- End every project document with a **Project Owner Judgment Questions** section in English and its matching **项目负责人判断题** section in Chinese. Put these after all other content in their respective language sections. If no decision is pending, state that explicitly in both languages; do not omit the sections.
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
- 所有项目文档都必须在同一个文件中包含完整英文版和中文版：英文在前，中文在后。两种语言的内容必须保持一致。不要只交付单一语言版本。更新文档时，必须在同一任务中同步更新两个语言部分。
- 每份项目文档的结尾都必须包含英文 **Project Owner Judgment Questions** 部分，以及内容对应的中文 **项目负责人判断题** 部分。这两个部分必须分别位于各自语言内容的末尾，并且之后不能再有其他内容。如果当前没有待决定事项，也要用中英文明确写明；不能省略这两个部分。
- 说明重要改动时，联系到用户行为和相关验收标准。
- 已确认的范围、架构、API 合约或里程碑状态发生变化时，更新 `design.md`。
- 确保文档与实际行为一致；明确说明已知差距。
- 只有满足相应验收标准后，才能将任务标记为完成。

## 项目负责人判断题

本指南目前没有待项目负责人判断的事项。

