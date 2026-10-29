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
