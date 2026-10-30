# AI English Coach Project Idea

> An AI English coach that conducts conversations based on a learner's goals and past errors, provides evidence-based corrective feedback, and dynamically plans practice.

## 3. Technical Project Design

### 3.1 Product Scope and User Flow

The project should address a specific learning need rather than act as a general-purpose chatbot. A learner should be able to choose a goal or activity, such as free conversation, role-play, grammar practice, vocabulary practice, or correction of a written response.

A practical first version can focus on text. Speech recognition and pronunciation scoring can be added later because they introduce a separate audio-processing pipeline and evaluation problem.

A representative turn could work as follows:

1. Receive the learner's message, current activity, proficiency estimate, and session state.
2. Determine whether to continue the conversation, provide correction, explain a language point, retrieve learning material, or create a targeted exercise.
3. Retrieve relevant examples or grammar explanations when evidence is needed.
4. Generate a structured response containing the original phrase, a suggested correction, an explanation, a more natural alternative, and an optional practice item.
5. Validate the response and update the learner's session summary or learning profile.
6. Return the response and record traces and evaluation data.

The system should use a workflow for predictable operations such as schema validation, saving progress, and applying safety limits. The model can make bounded decisions, such as whether the learner needs an explanation or another example. This hybrid design keeps the coach adaptive while making important behavior testable.

### 3.2 Agent Orchestration

A state graph can represent the main interaction:

`Classify intent -> Choose conversation, correction, explanation, or practice -> Retrieve material if needed -> Generate response -> Validate output -> Update learning state -> Wait for next turn`

Useful state fields may include:

- Current user goal and activity mode
- Conversation history or a compact session summary
- Learner profile and recurring error categories
- Retrieved passages and their metadata
- Tool results, retry count, and model confidence
- Current response and whether the turn is complete

The agent should have explicit stop conditions: the task is complete, a maximum step count is reached, the same tool call repeats, or a required service remains unavailable. If the model is unsure whether an expression is wrong, the coach should ask a clarifying question or label the suggestion as stylistic rather than present it as a definite grammar correction.

Use one orchestration framework initially. LangGraph is a reasonable choice for a stateful flow with branches and checkpoints; concepts such as state, nodes, edges, retries, and persistence should remain understandable independently of the framework.

### 3.3 Retrieval-Augmented Generation

A course-material knowledge base could contain grammar explanations, vocabulary lists, example sentences, and level-appropriate lesson notes.

A retrieval pipeline should cover:

- Document ingestion, normalization, deduplication, and metadata assignment
- Chunking that preserves a complete grammar rule or example where possible
- Metadata such as proficiency level, topic, skill, and source
- Embeddings and vector search, with BM25 or hybrid retrieval considered when exact terms matter
- Optional query rewriting or reranking, justified by evaluation rather than added by default
- Source-aware answers so explanations can point to supporting material

Important design questions include how chunk size and overlap affect retrieval, how top-k is selected, how stale or conflicting materials are handled, and how false positives are detected. Compare retrieval variants using a fixed test set and metrics such as Recall@k and precision, then check whether retrieved evidence actually supports the generated explanation.

Possible storage choices mentioned in the research include ChromaDB, Qdrant, Milvus, LanceDB, and Neo4j. They serve different deployment and query needs; select one based on the project's scale, filtering requirements, and deployment constraints, then benchmark it with the project's own data.

### 3.4 Learner Memory and Context Management

Memory can be separated into three layers:

- **Working memory:** the current turn, activity, and immediate feedback context.
- **Session memory:** a compact summary of what was practiced and corrected in the current session.
- **Long-term learner profile:** goals, preferred feedback style, recurring error types, vocabulary exposure, and progress.

The system should avoid placing the full conversation history into every prompt. It should retrieve relevant learner facts, summarize older turns, and distinguish stable preferences from temporary context. When new behavior conflicts with stored preferences or error patterns, define how the profile is updated rather than blindly letting old information dominate.

For a student-facing project, include user controls to view, revise, or delete saved learning data. Keep each learner's profile and session history isolated from other users.

### 3.5 Tools and Failure Handling

Potential tools include `search_lesson`, `get_examples`, `save_vocabulary`, and `create_exercise`. Each tool should have a typed schema and a narrow responsibility.

For every tool, define:

- Required and optional parameters, validated with a schema such as Pydantic
- Timeout and retry behavior, using bounded retries and backoff for transient failures
- Handling for malformed arguments, missing results, and downstream service errors
- Whether repeated calls are safe, and how duplicate writes are prevented
- A fallback response when the tool is unavailable

Do not retry invalid arguments indefinitely. Detect repeated calls with the same parameters, limit the agent's total steps and token use, and make the coach explain when a resource is unavailable instead of inventing retrieved evidence.

### 3.6 Evaluation and Observability

Create a fixed evaluation set covering learner levels, grammar topics, ambiguous sentences, natural but non-standard expressions, and cases where no correction is needed.

Evaluate separate parts of the system:

- **Correction quality:** correctness, preservation of intended meaning, and distinction between errors and stylistic alternatives
- **Explanation quality:** clarity and suitability for the learner's level
- **Retrieval quality:** Recall@k, precision, and whether retrieved passages support the answer
- **Practice quality:** relevance to the learner's goals and recent mistakes
- **System quality:** task completion, latency, token cost, and tool failure rate

Use human review for a sample of results. If using an LLM as a judge, compare its ratings with human judgments and do not treat its scores as ground truth. Compare changes against a simple baseline, such as a prompt-only coach without retrieval or learner memory.

Record enough information to reproduce a bad case: model and prompt version, state transitions, retrieved passages, tool inputs and results, validation errors, latency, and token usage. Avoid logging unnecessary sensitive content.

### 3.7 Backend, Concurrency, and Safety

For an SDE-oriented project, demonstrate a reliable API, session persistence, structured logs, testing, and deployment. Add a database, cache, queue, or rate limiter only where the expected behavior calls for it.

For higher concurrency, consider asynchronous IO, request limits, provider rate limits, database connection pools, backpressure, caching of static learning material, and graceful degradation. A long-running model call should not hold unrelated user requests behind it.

Treat learner text and retrieved documents as untrusted data. Restrict tools to an allowlist, prevent retrieved text from overriding system instructions, and enforce user-level authorization for saved profiles. This English coach does not need arbitrary code execution, so a general-purpose code sandbox is unnecessary. If file or audio uploads are added, isolate parsing and enforce file type, size, and resource limits.

For an internship project, do not add multi-agent coordination, self-evolving harnesses, or Agentic RL just to list them on a resume. Add those only if a clear user need and evaluation show that a simpler single-agent or workflow design is insufficient.

## 4. Technical Interview Questions

### 4.1 Product and Architecture

1. What learner problem does the English coach solve, and who is its target user?
2. Why is an agent useful here? Which parts are better implemented as deterministic workflows?
3. Walk through a learner turn from API request to final response. What are the states and transitions?
4. How does the system decide whether to continue conversation, correct an error, retrieve a lesson, or create an exercise?
5. Why did you choose your orchestration framework? What would you need to implement yourself without it?
6. What happens when the learner changes activity in the middle of a session?
7. How would you support text and voice input without coupling the learning logic to one modality?

### 4.2 English Feedback and Model Behavior

8. How do you distinguish a grammatical error from an acceptable but less natural expression?
9. How do you preserve the learner's intended meaning while correcting a sentence?
10. What does the structured feedback schema contain, and how do you validate it?
11. What does the coach do when the model is uncertain or two sources disagree?
12. How do you avoid giving feedback that is too advanced for the learner's proficiency level?
13. How do you prevent the model from inventing a grammar rule or a source citation?
14. How would you test whether feedback remains consistent across different model versions?

### 4.3 RAG and Learning Materials

15. Where do the learning materials come from, and how are they cleaned and deduplicated?
16. How did you choose chunk boundaries, chunk size, and overlap?
17. Which metadata do you store, and how does proficiency level affect retrieval?
18. Why did you choose vector search? When would BM25 or hybrid retrieval help?
19. How did you choose top-k? Did you test query rewriting or reranking?
20. How do you measure retrieval recall and precision? How did you build the evaluation set?
21. What do you do when retrieval returns a false positive, no useful result, or conflicting explanations?
22. How do you show that retrieved content actually supports the correction?
23. Why did you choose your vector database? What workload would make you choose a different one?

### 4.4 Agent Tools and Reliability

24. What tools can the agent call, and why is each one necessary?
25. How do you define and validate tool arguments?
26. What happens if the model invents a tool name or sends malformed parameters?
27. How do you handle timeouts, rate limits, transient errors, and permanent failures?
28. Which calls can be retried safely? How do you prevent duplicate vocabulary or exercise records?
29. How do you detect a repeated tool call or an agent loop that is not making progress?
30. What are the maximum step, latency, and token budgets for one learner turn?
31. How does the system degrade when retrieval or another tool is unavailable?
32. How would you replay a failed interaction and identify the first bad state transition?

### 4.5 Memory and Personalization

33. What information belongs in working memory, session memory, and long-term memory?
34. How do you summarize long conversations without losing important learning context?
35. How is a recurring error identified, stored, and later used to select practice?
36. How do you update a learner profile when new evidence conflicts with older memory?
37. How do you prevent a stale or incorrect memory from repeatedly producing bad feedback?
38. How can a learner inspect, correct, or delete saved information?
39. How do you isolate memory and conversation history across users?

### 4.6 Evaluation and Experimentation

40. What does it mean for the coach to be successful? Which metrics do you report?
41. How do you evaluate correction correctness, explanation usefulness, and practice relevance separately?
42. What baseline did you compare against? What changed in an ablation without retrieval or memory?
43. How do you validate an LLM-as-a-Judge against human ratings?
44. How do you create regression tests for previously observed bad cases?
45. What trade-off did you observe between quality, latency, and cost?
46. Which project change produced the clearest measurable improvement?

### 4.7 Backend, Scale, and Security

47. How would you handle 1,000 learners sending requests at the same time?
48. What happens when the model provider rate-limits requests or becomes unavailable?
49. How do you persist session state and resume after a service restart?
50. Where would you use caching, a queue, or a database, and why?
51. How do you handle prompt injection in learner messages or retrieved documents?
52. How are permissions enforced for learner profiles and saved vocabulary?
53. What user data do you log, and how do you minimize sensitive data exposure?
54. Would you use a sandbox in this project? Why or why not?

### 4.8 Project Ownership and Design Trade-offs

55. Which parts did you personally implement in the course team project?
56. What was the hardest failure to diagnose, and how did you reproduce it?
57. What design did you change after testing? What evidence caused the change?
58. If you replaced the model or vector store, which modules would change?
59. Why did you use a single agent rather than multiple agents? What would justify adding another agent?
60. If the deadline were cut in half, what would you keep, simplify, or remove?

A strong answer should connect **the design choice, the failure it prevents, and the evidence that it works**. For example: “I cap the agent at four tool steps because repeated retrieval calls did not improve answer quality in our test set; the cap reduced worst-case latency and token cost, while the fallback asks the learner a clarifying question.”

## Project Owner Judgment Questions

1. Should this document remain the long-term vision while `design.md` defines the three-week MVP?
2. After the expression-search MVP, which original capability should be prioritized next: correction feedback, learner memory, or voice practice?

---

# AI 英语教练项目构想（中文版）

> 一个 AI 英语教练，根据学习者的目标和过往错误开展对话，提供有依据的纠正反馈，并动态安排练习。

## 3. 技术项目设计

### 3.1 产品范围与用户流程

项目应针对具体的学习需求，而不是充当通用聊天机器人。学习者可以选择目标或活动，例如自由对话、角色扮演、语法练习、词汇练习，或纠正书面回答。

实用的第一版可以先聚焦文本。语音识别和发音评分可以以后再加，因为它们会引入单独的音频处理流程和评估问题。

一个典型的交互轮次可以这样进行：

1. 接收学习者的消息、当前活动、水平估计和会话状态。
2. 判断是继续对话、纠正错误、解释语言点、检索学习材料，还是生成针对性练习。
3. 需要依据时，检索相关例句或语法讲解。
4. 生成结构化响应，包含原句、建议改法、原因说明、更自然的替代表达，以及可选练习题。
5. 校验响应，并更新学习者的会话摘要或学习档案。
6. 返回响应，并记录追踪信息和评估数据。

对于结构校验、保存进度、执行安全限制等可预测操作，应使用确定性工作流。模型可以负责有限决策，例如判断学习者是否需要解释或另一个例子。这种混合设计兼顾适应性与可测试性。

### 3.2 Agent 编排

可以用状态图表示主要交互流程：

`意图分类 -> 选择对话、纠错、解释或练习 -> 需要时检索材料 -> 生成响应 -> 校验输出 -> 更新学习状态 -> 等待下一轮`

有用的状态字段可能包括：

- 当前学习目标和活动模式
- 对话历史或简短会话摘要
- 学习者档案和常见错误类别
- 检索到的段落及其元数据
- 工具结果、重试次数和模型置信度
- 当前响应以及该轮是否完成

主流程使用一个编排框架即可。对于需要状态、分支和检查点的流程，LangGraph 是一个合理选择；即使不使用该框架，也应让状态、节点、边、重试和持久化等概念保持清楚易懂。

Agent 应有明确的停止条件：任务完成、达到最大步骤数、重复调用同一个工具，或必需服务仍不可用。如果模型不确定某种表达是否错误，教练应提出澄清问题，或将建议标注为风格选择，而不是把它说成确定的语法错误。

### 3.3 检索增强生成（RAG）

课程材料知识库可以包含语法讲解、词汇表、例句和适合不同水平的课堂笔记。

检索流程应考虑：

- 文档导入、规范化、去重和元数据分配
- 尽可能保留完整语法规则或例句的分块方法
- 水平、话题、技能和来源等元数据
- 向量嵌入与向量搜索；涉及精确词语时，可考虑 BM25 或混合检索
- 只有评估证明有必要时，才加入可选查询改写或重排
- 回答能够关联支持它的来源材料

重要的设计问题包括：分块大小和重叠度如何影响检索、如何选择 top-k、如何处理过时或相互冲突的材料，以及如何发现错误匹配。可选存储包括 ChromaDB、Qdrant、Milvus、LanceDB 和 Neo4j。它们适用于不同的部署和查询需求；应根据项目规模、筛选需求和部署限制进行选择，再用项目自己的数据进行基准测试。

### 3.4 学习者记忆与上下文管理

可以将记忆分成三个层次：

- **工作记忆：**当前轮次、活动和即时反馈所需上下文。
- **会话记忆：**对本次会话练习内容和纠正内容的简短总结。
- **长期学习者档案：**学习目标、反馈偏好、反复出现的错误类型、词汇接触记录和进度。

系统不应在每次提示中都放入完整对话历史。它应检索相关学习者信息、总结较早的对话，并区分稳定偏好和临时语境。如果新行为与已保存的偏好或错误模式冲突，应定义档案的更新方式，不要盲目让旧记忆主导判断。

面向学生的项目应提供查看、修改或删除已保存学习数据的控制方式。每位学习者的档案和会话历史都必须彼此隔离。

### 3.5 工具与故障处理

可选工具包括 `search_lesson`、`get_examples`、`save_vocabulary` 和 `create_exercise`。每个工具都应有类型明确的结构和单一职责。

对每个工具，应定义：

- 必填与选填参数，并使用 Pydantic 等方案校验
- 超时和重试行为；对暂时性故障采用次数受限的重试和退避策略
- 对参数格式错误、结果缺失和下游服务错误的处理方式
- 调用是否可以安全重试，以及如何避免重复写入词汇或练习记录
- 工具不可用时的备用响应

不要无限重试无效参数。检测参数相同的重复调用，限制 Agent 总步骤数和令牌用量。工具不可用时，教练应明确告知学习者，而不是编造检索依据。

### 3.6 评估与可观测性

建立固定评估集，覆盖不同学习者水平、语法主题、含义模糊的句子、自然但不标准的表达，以及无需纠正的案例。

分开评估系统的不同部分：

- **纠正质量：**正确性、保留原意的能力，以及区分错误与风格替换的能力
- **解释质量：**表达清晰度及是否符合学习者水平
- **检索质量：**Recall@k、Precision，以及检索段落是否支持回答
- **练习质量：**练习与学习目标和近期错误的相关性
- **系统质量：**任务完成率、延迟、令牌成本和工具故障率

对部分结果进行人工复核。如果使用 LLM 评审，应将其评分与人工判断比较，不能把它当作绝对真值。与简单基线进行比较，例如不使用检索或学习者记忆的提示词教练。

记录足够信息以重现错误案例：模型与提示词版本、状态转换、检索段落、工具输入与结果、校验错误、延迟和令牌使用量。避免记录不必要的敏感内容。

### 3.7 后端、并发与安全

对于偏软件工程的项目，应展示可靠 API、会话持久化、结构化日志、测试和部署。只有在预期行为确实需要时，才添加数据库、缓存、队列或限流器。

为了支持更高并发，应考虑异步 IO、请求上限、模型供应商速率限制、数据库连接池、背压、静态学习材料缓存，以及故障时的平稳降级。长时间运行的模型调用不应阻塞互不相关的用户请求。

应将学习者文本和检索文档视为不可信数据。将工具限制在允许列表中，避免检索文本覆盖系统指令，并为已保存的档案强制执行用户级授权。这个英语教练无需任意代码执行，因此不需要通用代码沙箱。如果增加文件或音频上传，应隔离解析流程并限制文件类型、大小和资源消耗。

对于实习项目，不要为了简历罗列多智能体协作、自我演化 Harness 或 Agentic RL。只有当明确的用户需求和评估结果证明简单的单 Agent 或工作流不足时，才应考虑增加这些能力。

## 4. 技术面试问题

### 4.1 产品与架构

1. 英语教练解决什么学习问题？目标用户是谁？
2. 为什么在这里使用 Agent？哪些部分更适合用确定性工作流实现？
3. 描述一个学习者交互轮次从 API 请求到最终响应的过程。状态和转换是什么？
4. 系统如何判断应该继续对话、纠正错误、检索课程，还是生成练习？
5. 为什么选择该编排框架？不使用它时需要自行实现什么？
6. 如果学习者在会话中途切换活动，系统如何处理？
7. 如何支持文本和语音输入，同时避免学习逻辑与某种输入方式耦合？

### 4.2 英语反馈与模型行为

8. 如何区分语法错误与可以接受但不够自然的表达？
9. 如何在纠正句子的同时保留学习者的原意？
10. 结构化反馈包含哪些字段？如何校验？
11. 模型不确定或两个来源意见不同时，系统怎么做？
12. 如何避免反馈难度超过学习者的水平？
13. 如何防止模型编造语法规则或来源引用？
14. 如何测试不同模型版本之间的反馈一致性？

### 4.3 RAG 与学习材料

15. 学习材料来自哪里？如何清理和去重？
16. 如何选择分块边界、分块大小和重叠度？
17. 存储哪些元数据？学习者水平如何影响检索？
18. 为什么选择向量搜索？什么情况下 BM25 或混合检索会有帮助？
19. 如何选择 top-k？是否测试了查询改写或重排？
20. 如何衡量检索召回率和精确率？如何构建评估集？
21. 如果检索出现错误匹配、没有有用结果或不同来源互相冲突，怎么办？
22. 如何证明检索内容确实支持生成的解释？
23. 为什么选择该向量数据库？什么样的工作负载会促使你改选其他数据库？

### 4.4 Agent 工具与可靠性

24. Agent 可以调用哪些工具？每个工具为什么必要？
25. 如何定义和校验工具参数？
26. 模型生成不存在的工具名称或格式错误的参数时，系统如何处理？
27. 如何处理超时、速率限制、暂时性故障和永久性故障？
28. 哪些调用可以安全重试？如何防止重复保存词汇或练习？
29. 如何检测重复工具调用或没有进展的 Agent 循环？
30. 每个学习者请求的最大步骤数、延迟和令牌预算是多少？
31. 检索或其他工具不可用时，系统如何降级？
32. 如何重放一次失败交互并找到最早出错的状态转换？

### 4.5 记忆与个性化

33. 工作记忆、会话记忆和长期记忆分别保存什么？
34. 如何总结较长的对话，同时不丢失重要学习上下文？
35. 如何识别并保存反复出现的错误，之后如何据此选择练习？
36. 新证据与旧记忆冲突时，如何更新学习者档案？
37. 如何避免过时或错误的记忆不断产生错误反馈？
38. 学习者如何检查、纠正或删除已保存的信息？
39. 如何确保不同用户的记忆和对话历史彼此隔离？

### 4.6 评估与实验

40. 如何定义教练是否成功？需要报告哪些指标？
41. 如何分别评估纠正正确性、解释易用性和练习相关性？
42. 使用什么基线进行比较？去掉检索或记忆后，消融实验结果如何？
43. 如何通过人工评分验证 LLM 评审？
44. 如何为已发现的问题案例创建回归测试？
45. 观察到的质量、延迟和成本之间有什么权衡？
46. 哪项项目改动带来了最清楚、可测量的改善？

### 4.7 后端、规模与安全

47. 如何处理 1,000 名学习者同时发送请求？
48. 模型供应商进行速率限制或服务不可用时会发生什么？
49. 如何持久化会话状态，并在服务重启后恢复？
50. 会在哪里使用缓存、队列或数据库？为什么？
51. 如何处理学习者消息或检索文档中的提示词注入？
52. 如何为学习者档案和已保存词汇实施权限控制？
53. 记录哪些用户数据？如何减少敏感数据暴露？
54. 这个项目是否需要沙箱？为什么？

### 4.8 项目归属与设计权衡

55. 课程团队项目中，哪些部分是你亲自实现的？
56. 最难诊断的故障是什么？你如何复现它？
57. 测试后改了什么设计？是什么证据促使你改变？
58. 如果替换模型或向量存储，哪些模块需要修改？
59. 为什么使用单 Agent，而不是多个 Agent？什么情况才足以证明需要增加 Agent？
60. 如果项目期限缩短一半，你会保留、简化或删除什么？

有力的回答应把**设计选择、它要防止的故障，以及证明它有效的证据**联系起来。例如：“我把 Agent 的工具步骤限制为四步，因为测试集显示重复检索不会提升答案质量；这个上限降低了最坏情况下的延迟和令牌成本，而备用处理会向学习者提出澄清问题。”

## 项目负责人判断题

1. 是否将本文件作为长期愿景，并由 `design.md` 定义三周 MVP？
2. 表达检索 MVP 完成后，你希望优先实现哪项原始能力：纠错反馈、学习者记忆，还是语音练习？

---

# AI 영어 코치 프로젝트 구상(한국어판)

> 학습자의 목표와 과거 오류를 바탕으로 대화를 진행하고, 근거 있는 교정 피드백을 제공하며, 연습을 동적으로 계획하는 AI 영어 코치.

## 3. 기술 프로젝트 설계

### 3.1 제품 범위와 사용자 흐름

이 프로젝트는 범용 챗봇이 아니라 구체적인 학습 요구를 해결해야 합니다. 학습자는 자유 대화, 역할극, 문법 연습, 어휘 연습, 작성한 답변 교정 같은 목표나 활동을 선택할 수 있어야 합니다.

실용적인 첫 버전은 텍스트에 집중할 수 있습니다. 음성 인식과 발음 채점은 별도의 오디오 처리 파이프라인과 평가 문제를 가져오므로 나중에 추가해도 됩니다.

대표적인 한 턴은 다음과 같이 진행될 수 있습니다.

1. 학습자의 메시지, 현재 활동, 추정 숙련도, 세션 상태를 받습니다.
2. 대화를 이어 갈지, 교정할지, 언어 요소를 설명할지, 학습 자료를 검색할지, 맞춤 연습을 만들지 결정합니다.
3. 근거가 필요하면 관련 예문이나 문법 설명을 검색합니다.
4. 원래 문구, 교정 제안, 설명, 더 자연스러운 대안, 선택적 연습 문항을 포함한 구조화된 응답을 생성합니다.
5. 응답을 검증하고 학습자의 세션 요약이나 학습 프로필을 업데이트합니다.
6. 응답을 반환하고 트레이스와 평가 데이터를 기록합니다.

스키마 검증, 진행 상황 저장, 안전 제한 적용처럼 예측 가능한 작업에는 워크플로를 사용해야 합니다. 모델은 학습자에게 설명이 필요한지, 예문이 하나 더 필요한지 같은 제한된 결정을 내릴 수 있습니다. 이런 하이브리드 설계는 코치의 적응성을 유지하면서 중요한 동작을 테스트할 수 있게 합니다.

### 3.2 Agent 오케스트레이션

상태 그래프로 주요 상호작용을 표현할 수 있습니다.

`의도 분류 -> 대화, 교정, 설명, 연습 중 선택 -> 필요하면 자료 검색 -> 응답 생성 -> 출력 검증 -> 학습 상태 업데이트 -> 다음 턴 대기`

유용한 상태 필드는 다음과 같습니다.

- 현재 사용자 목표와 활동 모드
- 대화 기록 또는 간결한 세션 요약
- 학습자 프로필과 반복되는 오류 유형
- 검색된 구절과 메타데이터
- 도구 결과, 재시도 횟수, 모델 신뢰도
- 현재 응답과 해당 턴의 완료 여부

Agent에는 명시적인 종료 조건이 있어야 합니다: 작업 완료, 최대 단계 수 도달, 같은 도구 호출 반복, 필수 서비스의 지속적인 사용 불가. 모델이 어떤 표현이 틀렸는지 확신하지 못하면, 코치는 그것을 확정적인 문법 교정으로 제시하지 말고 확인 질문을 하거나 문체상의 제안이라고 표시해야 합니다.

처음에는 오케스트레이션 프레임워크 하나만 사용합니다. 분기와 체크포인트가 있는 상태 기반 흐름에는 LangGraph가 합리적인 선택입니다. 상태, 노드, 엣지, 재시도, 영속성 같은 개념은 프레임워크와 무관하게 이해할 수 있어야 합니다.

### 3.3 검색 증강 생성(RAG)

수업 자료 지식 베이스에는 문법 설명, 어휘 목록, 예문, 수준별 수업 노트가 들어갈 수 있습니다.

검색 파이프라인은 다음을 다뤄야 합니다.

- 문서 수집, 정규화, 중복 제거, 메타데이터 부여
- 가능하면 완전한 문법 규칙이나 예문을 유지하는 청킹
- 숙련도 수준, 주제, 기능(skill), 출처 같은 메타데이터
- 임베딩과 벡터 검색. 정확한 용어가 중요할 때는 BM25나 하이브리드 검색도 고려
- 기본으로 넣지 않고 평가로 정당화될 때만 추가하는 선택적 질의 재작성 또는 재순위화
- 설명이 뒷받침 자료를 가리킬 수 있도록 출처를 인식하는 답변

중요한 설계 질문에는 청크 크기와 겹침이 검색에 어떤 영향을 주는지, top-k를 어떻게 정하는지, 오래되거나 서로 충돌하는 자료를 어떻게 처리하는지, 거짓 양성을 어떻게 찾아내는지가 포함됩니다. 고정된 테스트 세트와 Recall@k, 정밀도 같은 지표로 검색 방식을 비교한 다음, 검색된 근거가 생성된 설명을 실제로 뒷받침하는지 확인합니다.

조사에서 언급된 저장소 후보로는 ChromaDB, Qdrant, Milvus, LanceDB, Neo4j가 있습니다. 이들은 서로 다른 배포 및 질의 요구에 맞으므로, 프로젝트의 규모, 필터링 요구, 배포 제약에 따라 하나를 고른 뒤 프로젝트 자체 데이터로 벤치마크합니다.

### 3.4 학습자 메모리와 컨텍스트 관리

메모리는 세 층으로 나눌 수 있습니다.

- **작업 메모리:** 현재 턴, 활동, 즉각적인 피드백에 필요한 맥락.
- **세션 메모리:** 현재 세션에서 연습하고 교정한 내용의 간결한 요약.
- **장기 학습자 프로필:** 목표, 선호하는 피드백 방식, 반복되는 오류 유형, 접한 어휘, 진행 상황.

시스템은 모든 프롬프트에 전체 대화 기록을 넣지 않아야 합니다. 관련된 학습자 정보를 검색하고, 오래된 턴은 요약하며, 안정적인 선호와 일시적인 맥락을 구분해야 합니다. 새로운 행동이 저장된 선호나 오류 패턴과 충돌하면, 오래된 정보가 무조건 우선하도록 두지 말고 프로필 업데이트 방식을 정의해야 합니다.

학생 대상 프로젝트라면 저장된 학습 데이터를 보고, 수정하고, 삭제할 수 있는 사용자 제어 기능을 포함합니다. 각 학습자의 프로필과 세션 기록은 다른 사용자와 격리합니다.

### 3.5 도구와 장애 처리

후보 도구로는 `search_lesson`, `get_examples`, `save_vocabulary`, `create_exercise`가 있습니다. 각 도구는 타입이 정의된 스키마와 좁은 책임을 가져야 합니다.

모든 도구에 대해 다음을 정의합니다.

- 필수 및 선택 매개변수와 Pydantic 같은 스키마를 이용한 검증
- 타임아웃과 재시도 동작. 일시적 장애에는 횟수가 제한된 재시도와 백오프 사용
- 잘못된 인자, 결과 누락, 하위 서비스 오류 처리 방식
- 반복 호출이 안전한지, 중복 쓰기를 어떻게 막는지
- 도구를 사용할 수 없을 때의 대체 응답

잘못된 인자를 무한히 재시도하지 않습니다. 같은 매개변수로 반복되는 호출을 감지하고, Agent의 총 단계 수와 토큰 사용량을 제한하며, 검색 근거를 지어내는 대신 리소스를 사용할 수 없다고 코치가 설명하게 합니다.

### 3.6 평가와 관측 가능성

학습자 수준, 문법 주제, 모호한 문장, 자연스럽지만 비표준적인 표현, 교정이 필요 없는 사례를 포함하는 고정 평가 세트를 만듭니다.

시스템의 각 부분을 따로 평가합니다.

- **교정 품질:** 정확성, 의도한 의미의 보존, 오류와 문체상 대안의 구분
- **설명 품질:** 명확성과 학습자 수준에 대한 적합성
- **검색 품질:** Recall@k, 정밀도, 검색된 구절이 답변을 뒷받침하는지 여부
- **연습 품질:** 학습자의 목표와 최근 실수와의 관련성
- **시스템 품질:** 작업 완료율, 지연 시간, 토큰 비용, 도구 장애율

결과 일부는 사람이 검토합니다. LLM을 평가자로 쓴다면 그 점수를 사람의 판단과 비교하고, 정답 기준으로 취급하지 않습니다. 변경 사항은 검색이나 학습자 메모리가 없는 프롬프트 전용 코치 같은 단순 베이스라인과 비교합니다.

잘못된 사례를 재현할 수 있을 만큼 정보를 기록합니다: 모델과 프롬프트 버전, 상태 전이, 검색된 구절, 도구 입력과 결과, 검증 오류, 지연 시간, 토큰 사용량. 불필요한 민감 콘텐츠는 기록하지 않습니다.

### 3.7 백엔드, 동시성, 안전

SDE 지향 프로젝트라면 안정적인 API, 세션 영속성, 구조화된 로그, 테스트, 배포를 보여 줍니다. 데이터베이스, 캐시, 큐, 속도 제한기는 기대 동작에 필요할 때만 추가합니다.

더 높은 동시성을 위해서는 비동기 IO, 요청 제한, 모델 제공자 속도 제한, 데이터베이스 커넥션 풀, 백프레셔, 정적 학습 자료 캐싱, 우아한 성능 저하를 고려합니다. 오래 걸리는 모델 호출 때문에 관련 없는 사용자 요청이 대기해서는 안 됩니다.

학습자 텍스트와 검색된 문서는 신뢰할 수 없는 데이터로 취급합니다. 도구는 허용 목록으로 제한하고, 검색된 텍스트가 시스템 지시를 덮어쓰지 못하게 하며, 저장된 프로필에는 사용자 수준 권한 검사를 적용합니다. 이 영어 코치는 임의 코드 실행이 필요 없으므로 범용 코드 샌드박스는 필요하지 않습니다. 파일이나 오디오 업로드를 추가한다면 파싱을 격리하고 파일 형식, 크기, 리소스 제한을 적용합니다.

인턴십 프로젝트에서는 이력서에 나열하려고 멀티 에이전트 협업, 자기 진화 하네스, Agentic RL을 추가하지 않습니다. 명확한 사용자 요구와 평가를 통해 더 단순한 단일 Agent 또는 워크플로 설계로는 부족하다는 것이 확인될 때만 추가합니다.

## 4. 기술 면접 질문

### 4.1 제품과 아키텍처

1. 영어 코치는 어떤 학습 문제를 해결하며, 대상 사용자는 누구입니까?
2. 왜 여기서 Agent가 유용합니까? 어떤 부분은 결정론적 워크플로로 구현하는 편이 더 낫습니까?
3. API 요청부터 최종 응답까지 학습자의 한 턴을 설명해 보세요. 상태와 전이는 무엇입니까?
4. 시스템은 대화를 계속할지, 오류를 교정할지, 수업 자료를 검색할지, 연습을 만들지 어떻게 결정합니까?
5. 그 오케스트레이션 프레임워크를 선택한 이유는 무엇입니까? 프레임워크가 없다면 직접 구현해야 하는 것은 무엇입니까?
6. 학습자가 세션 도중 활동을 바꾸면 어떻게 됩니까?
7. 학습 로직을 특정 입력 방식에 묶지 않고 텍스트와 음성 입력을 모두 지원하려면 어떻게 하겠습니까?

### 4.2 영어 피드백과 모델 동작

8. 문법 오류와 허용되지만 덜 자연스러운 표현을 어떻게 구분합니까?
9. 문장을 교정하면서 학습자가 의도한 의미를 어떻게 보존합니까?
10. 구조화된 피드백 스키마에는 무엇이 들어 있으며, 어떻게 검증합니까?
11. 모델이 확신하지 못하거나 두 출처의 의견이 다를 때 코치는 어떻게 합니까?
12. 학습자의 숙련도에 비해 너무 어려운 피드백을 주지 않으려면 어떻게 합니까?
13. 모델이 문법 규칙이나 출처 인용을 지어내지 않도록 어떻게 막습니까?
14. 서로 다른 모델 버전 사이에서 피드백이 일관적인지 어떻게 테스트하겠습니까?

### 4.3 RAG와 학습 자료

15. 학습 자료는 어디에서 가져오며, 어떻게 정제하고 중복을 제거합니까?
16. 청크 경계, 청크 크기, 겹침은 어떻게 정했습니까?
17. 어떤 메타데이터를 저장하며, 숙련도 수준은 검색에 어떤 영향을 줍니까?
18. 왜 벡터 검색을 선택했습니까? BM25나 하이브리드 검색은 언제 도움이 됩니까?
19. top-k는 어떻게 정했습니까? 질의 재작성이나 재순위화를 테스트했습니까?
20. 검색 재현율과 정밀도는 어떻게 측정합니까? 평가 세트는 어떻게 만들었습니까?
21. 검색이 거짓 양성, 유용하지 않은 결과, 서로 충돌하는 설명을 반환하면 어떻게 합니까?
22. 검색된 내용이 실제로 교정을 뒷받침한다는 것을 어떻게 보여 줍니까?
23. 그 벡터 데이터베이스를 선택한 이유는 무엇입니까? 어떤 워크로드라면 다른 것을 선택하겠습니까?

### 4.4 Agent 도구와 안정성

24. Agent가 호출할 수 있는 도구는 무엇이며, 각 도구가 왜 필요합니까?
25. 도구 인자를 어떻게 정의하고 검증합니까?
26. 모델이 존재하지 않는 도구 이름을 지어내거나 잘못된 매개변수를 보내면 어떻게 됩니까?
27. 타임아웃, 속도 제한, 일시적 오류, 영구적 장애를 어떻게 처리합니까?
28. 어떤 호출을 안전하게 재시도할 수 있습니까? 어휘나 연습 레코드의 중복을 어떻게 막습니까?
29. 반복되는 도구 호출이나 진전 없는 Agent 루프를 어떻게 감지합니까?
30. 학습자의 한 턴에 대한 최대 단계, 지연 시간, 토큰 예산은 얼마입니까?
31. 검색이나 다른 도구를 사용할 수 없을 때 시스템은 어떻게 기능을 낮춰 동작합니까?
32. 실패한 상호작용을 어떻게 재생하고, 처음 잘못된 상태 전이를 어떻게 찾겠습니까?

### 4.5 메모리와 개인화

33. 작업 메모리, 세션 메모리, 장기 메모리에는 각각 어떤 정보가 들어갑니까?
34. 중요한 학습 맥락을 잃지 않고 긴 대화를 어떻게 요약합니까?
35. 반복되는 오류는 어떻게 식별하고 저장하며, 이후 연습 선택에 어떻게 활용합니까?
36. 새로운 근거가 이전 메모리와 충돌하면 학습자 프로필을 어떻게 업데이트합니까?
37. 오래되었거나 잘못된 메모리가 계속 나쁜 피드백을 만들지 않도록 어떻게 막습니까?
38. 학습자는 저장된 정보를 어떻게 확인, 수정, 삭제할 수 있습니까?
39. 사용자 간 메모리와 대화 기록을 어떻게 격리합니까?

### 4.6 평가와 실험

40. 코치가 성공적이라는 것은 무엇을 의미합니까? 어떤 지표를 보고합니까?
41. 교정 정확성, 설명의 유용성, 연습의 관련성을 각각 어떻게 평가합니까?
42. 어떤 베이스라인과 비교했습니까? 검색이나 메모리를 제거한 절제 실험(ablation)에서 무엇이 달라졌습니까?
43. LLM-as-a-Judge를 사람의 평가와 비교해 어떻게 검증합니까?
44. 이전에 관찰된 나쁜 사례에 대한 회귀 테스트를 어떻게 만듭니까?
45. 품질, 지연 시간, 비용 사이에서 어떤 트레이드오프를 관찰했습니까?
46. 어떤 프로젝트 변경이 가장 명확하게 측정 가능한 개선을 가져왔습니까?

### 4.7 백엔드, 확장성, 보안

47. 학습자 1,000명이 동시에 요청을 보내면 어떻게 처리하겠습니까?
48. 모델 제공자가 요청 속도를 제한하거나 사용할 수 없게 되면 어떻게 됩니까?
49. 세션 상태를 어떻게 영구 저장하고 서비스 재시작 후 재개합니까?
50. 캐시, 큐, 데이터베이스를 어디에, 왜 사용하겠습니까?
51. 학습자 메시지나 검색된 문서에 포함된 프롬프트 인젝션을 어떻게 처리합니까?
52. 학습자 프로필과 저장된 어휘에 대한 권한은 어떻게 적용합니까?
53. 어떤 사용자 데이터를 로그로 남기며, 민감 데이터 노출을 어떻게 최소화합니까?
54. 이 프로젝트에서 샌드박스를 사용하겠습니까? 그 이유는 무엇입니까?

### 4.8 프로젝트 주도성과 설계 트레이드오프

55. 수업 팀 프로젝트에서 직접 구현한 부분은 무엇입니까?
56. 진단하기 가장 어려웠던 장애는 무엇이며, 어떻게 재현했습니까?
57. 테스트 후 어떤 설계를 바꿨습니까? 어떤 근거 때문에 바꿨습니까?
58. 모델이나 벡터 저장소를 교체한다면 어떤 모듈이 바뀝니까?
59. 왜 여러 Agent가 아니라 단일 Agent를 사용했습니까? 어떤 상황이라면 Agent 추가가 정당화됩니까?
60. 마감이 절반으로 줄어든다면 무엇을 유지하고, 단순화하고, 제거하겠습니까?

좋은 답변은 **설계 선택, 그것이 막는 장애, 그리고 효과가 있다는 근거**를 연결해야 합니다. 예: "테스트 세트에서 검색을 반복 호출해도 답변 품질이 좋아지지 않았기 때문에 Agent의 도구 단계를 네 번으로 제한했습니다. 이 제한으로 최악의 경우 지연 시간과 토큰 비용이 줄었고, 대체 처리에서는 학습자에게 확인 질문을 합니다."

## 프로젝트 책임자 판단 질문

1. 이 문서를 장기 비전으로 유지하고, 3주 MVP는 `design.md`에서 정의할까요?
2. 표현 검색 MVP 이후 다음으로 우선할 원래 기능은 무엇입니까: 교정 피드백, 학습자 메모리, 음성 연습?
