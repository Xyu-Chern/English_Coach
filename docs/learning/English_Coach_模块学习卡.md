# English Coach · 10 张模块学习卡

对应本地 `English_Coach_submission` 的 `cc8de5b`。编号沿用之前的功能图。输入和输出描述当前实现；每张卡末尾是规模更小的手敲练习。例子中的节目、引句和预期结果均为教学示意。

**先看数据怎么走**

- 准备语料：① 下载字幕 → ③ 保存原文 → ② 解析分块 → ③ 保存分块和版本 → ④ 写入向量。⑩ 定时触发这些工作。
- 回答用户：⑥ 接收问题 → ⑧ 生成候选 → ⑤ 查原文 → ⑦ 核对引用 → ⑥ 整理回答。⑨ 用同一批题目比较两种回答策略。

## 01 · 播客与字幕采集

发现已审核节目里待处理的单集，把发布方提供的字幕下载到本地语料库。

| 接口 | 说明 |
|---|---|
| 输入 | 订阅的节目 ID、数据库中的同步进度，以及用来查询单集的 Podcast Index 客户端。 |
| 输出 | 函数返回 `SyncResult`，记录看到了几集、下载几份、写入几份。字幕正文和下一轮用的同步状态写进数据库。 |
| 依赖 | Podcast Index、节目方字幕来源、③ 存储。 |
| 代码入口 | [sync_feeds()](../../translation_agent_demo/jobs/podcast_sync.py) |

**具体例子**　假设节目 42 有两集，A 已保存，B 是新发现且可下载的字幕。此次只需下载 B；成功后可以从数据库读到 B 的原文。

**手敲练习**　用两个字典模拟节目列表和已保存记录。连续同步两次，检查第二次没有重复下载。

## 02 · 字幕解析与分块

把 HTML、SRT 或 Markdown 解析为按顺序排列的发言片段（cue），再按 token 数把它们组合成可搜索的文本块。

| 接口 | 说明 |
|---|---|
| 输入 | 字幕原文、格式信息、分块大小和重叠量。Markdown 需要显式声明格式。 |
| 输出 | `parse_transcript` 返回 `ParsedTranscript`；`chunk_transcript` 返回一组 `CorpusChunk`。每块带文本、token 数和指回 cue 的字符范围。 |
| 依赖 | 解析器、语料数据类型和本地 `tiktoken` 分词器。 |
| 代码入口 | [parse_transcript()](../../translation_agent_demo/corpus/parsers.py) · [第二步 · chunk_transcript()](../../translation_agent_demo/corpus/chunking.py) |

**具体例子**　一条 SRT 字幕从 `00:00:01,000` 到 `00:00:03,000`，正文是 `That's a fair point.`。解析得到时间 1000–3000 毫秒的 cue；短句单独成块时，块仍能定位到这条 cue。

**手敲练习**　手敲一个只处理单条 SRT 的函数，先验收时间和正文，再把第二条字幕加入输入。

## 03 · 存储、版本与来源审核

保存每份原文及其修订版，另存解析产物；记录哪些节目的哪些字幕 URL 通过了来源审核。

| 接口 | 说明 |
|---|---|
| 输入 | 数据库连接、带节目 ID 和单集 ID 的字幕对象；保存解析结果时还需要文档 ID、处理版本和文本块。审核记录单独写入。 |
| 输出 | `save_transcript` 返回 `document_id` 和 `created`。数据库保留原文、版本、分块和审核范围，供后续作业按条件读取。 |
| 依赖 | PostgreSQL、数据库迁移、① 的原文和 ② 的解析结果。 |
| 代码入口 | [save_transcript()](../../translation_agent_demo/storage/corpus.py) · [保存分块](../../translation_agent_demo/storage/chunks.py) · [记录审核](../../translation_agent_demo/storage/source_reviews.py) |

**具体例子**　同一集同一正文连续保存两次，两次返回同一文档 ID，第二次 `created=False`。发布方改了正文，再保存会产生新文档版本。

**手敲练习**　先用字典实现上述三次保存，用“节目、单集、正文哈希”定位版本。检查旧正文仍能按旧 ID 取回。

## 04 · 向量化

把已审核、尚缺向量的文本块分批送给 embedding 模型，保存向量供检索。

| 接口 | 说明 |
|---|---|
| 输入 | 任务入口接收数据库连接、`EmbeddingProvider` 和批量上限；模型接口接收按顺序排列的文本。 |
| 输出 | 模型返回每段文本对应的向量及 token 用量；任务写入数据库并返回 `EmbedResult`，包括写入数和完整建好索引的版本数。 |
| 依赖 | ② 的文本块、③ 的审核和版本信息、embedding 服务。它与 ⑧ 的聊天模型是两个接口。 |
| 代码入口 | [embed_corpus()](../../translation_agent_demo/jobs/corpus_embed.py) · [EmbeddingProvider 接口](../../translation_agent_demo/providers/embedding_protocol.py) |

**具体例子**　假设一个已审核版本有 3 块，前 2 块已有向量。任务只发送第 3 块，写入成功后该版本才满足向量完整条件。

**手敲练习**　写一个假 embedding 函数，每段文本返回一个可识别的测试向量。检查输出顺序，并检查再次运行时没有待处理文本。

## 05 · 语料检索

给定一个意思或短语，在可搜索的原文中找到相关段落，并带回出处。

| 接口 | 说明 |
|---|---|
| 输入 | `SearchCorpusArgs`，其中 `query` 必填，可给 `literal_phrase`、语境、语言和结果数量；调用方另传数据库连接及 embedding 服务。 |
| 输出 | `SearchCorpusResult` 包含状态、检索模式和命中列表。每个命中有原文、相似度和来源。`not_ready` 表示没有符合条件的索引，`ok` 的命中列表可以为空；服务故障会抛错。 |
| 依赖 | ③ 存储、④ 向量、PostgreSQL 的 pgvector 扩展。 |
| 代码入口 | [search_corpus()](../../translation_agent_demo/tools/search_corpus.py) |

**具体例子**　传入 `query="acknowledge an objection"`、`literal_phrase="fair point"`、`limit=1`。若库中有符合条件的字面命中，返回含该短语的段落；没有时转语义检索，结果会标记 `semantic_fallback`。

**手敲练习**　先用三句本地文本实现字面检索。写两个用例，让一个命中，另一个走你预设的语义检索替身，并检查模式字段。

## 06 · 表达教练

协调候选生成、检索、选择和修正。固定流程只修补缺引文的位置；Agent 可重新检索、换引文、换表达或结束。

| 接口 | 说明 |
|---|---|
| 输入 | 构造时传 `CoachDependencies(model, search)` 和策略；每次调用 `answer(question)` 传一段学习者请求。 |
| 输出 | `RunResult` 包含状态、最多三个表达、可选引用、执行轨迹和用量。表达可以没有通过校验的例句。 |
| 依赖 | ⑤ 搜索、⑦ 引用校验、⑧ 聊天模型；`RequestSession` 管理每次请求的预算与记录。 |
| 代码入口 | [ExpressionCoach.answer()](../../translation_agent_demo/agents/coach.py) · [项目里的测试替身](../../translation_agent_demo/tests/fakes.py) |

**具体例子**　输入“会上怎么先肯定同事的意见，再委婉反对？”模型可以提出 `That's a fair point, but …`，随后搜 `fair point`。若引文通过校验，结果中会同时出现建议表达和播客原句。

**手敲练习**　先只处理一个候选。用固定返回值模拟模型和搜索，跑通“提议→检索→选择→输出”，再试一次搜索为空。

## 07 · 引用校验

把模型选中的段落编号还原成可信原文，检查可复用措辞是否出现在原文中、是否覆盖关键短语，以及同一片段是否已被引用。

| 接口 | 说明 |
|---|---|
| 输入 | 段落目录、引用编号 `ref`、候选表达、关键短语、模型摘出的措辞和两项用法说明。 |
| 输出 | 成功返回 `SourceCitation`，从原文切出引句、上下文和位置。校验失败返回 `None` 并记录原因。文字校验本身不能判定语境是否贴切。 |
| 依赖 | ⑤ 返回的原文、`SpanCatalog` 和已用片段记录。校验过程在本地执行。 |
| 代码入口 | [ExampleVerifier.verify()](../../translation_agent_demo/agents/evidence.py) |

**具体例子**　假设 `r1` 指向 `That's a fair point.`，其余字段均有效。摘录 `fair point` 可以通过；把摘录换成 `excellent point`，会得到 `reusable_wording_not_in_span`。

**手敲练习**　建立只有一条原文的目录。先验收正确摘录，再测错误措辞、未知编号、同一片段被用两次。

## 08 · 聊天模型适配

让上层使用同一种调用方式访问 OpenAI-compatible 或 Claude。供应商特有的请求格式在适配器内处理。

| 接口 | 说明 |
|---|---|
| 输入 | 工厂接收模型配置 `Settings`；生成调用接收系统提示、用户内容，可带结构化输出格式。 |
| 输出 | `chat_model(settings)` 返回适配器；它的 `complete_with_usage` 返回 `ChatCompletion`，含响应文本和供应商报告的用量。 |
| 依赖 | 配置、对应服务的客户端和凭据；离线练习可使用实现同一接口的假模型。 |
| 代码入口 | [chat_model()](../../translation_agent_demo/providers/__init__.py) · [教练依赖的模型接口](../../translation_agent_demo/agents/protocol.py) |

**具体例子**　同样的“给出一个礼貌表达”请求，工厂按配置选用 `openai` 或 `anthropic`。上层都从返回对象的 `content` 读取文本。

**手敲练习**　手敲 `FakeChatModel`，让它固定返回一条建议及一组用量。用它替换 ⑥ 的真实模型，检查调用方仍能读取同样的字段。

## 09 · 评测与结果报告

让固定流程与 Agent 从同一第一阶段结果出发，反复回答同批任务，比较质量、稳定性、耗时和成本。

| 接口 | 说明 |
|---|---|
| 输入 | 任务 JSONL、语料快照、运行配置、重复次数；评分阶段读取回答，汇总阶段读取评分记录。 |
| 输出 | 每次运行的回答、轨迹、评分，以及 Markdown/JSON 汇总和 HTML 评审页。正式生成和模型评分会调用外部服务。 |
| 依赖 | ⑥ 的两种流程、冻结的语料、生成模型、裁判模型及价格配置。 |
| 代码入口 | [main() 与各评测子命令](../../evaluation/eval.py) · [已提交的结果报告](../../evaluation/results/submission/report/results.md) |

**具体例子**　同一道题三次得到“通过、失败、通过”。按报告定义，这道题计入 pass@3（至少一次通过），不计入 pass^3（三次全部通过）。

**手敲练习**　输入两道题的布尔数组 `[True,False,True]` 和 `[True,True,True]`，手敲汇总函数。预期 pass@3 为 100%，pass^3 为 50%。

## 10 · Docker 与定时任务

启动数据库和后台任务容器，将采集、建库、向量化安排在错开的分钟运行。

| 接口 | 说明 |
|---|---|
| 输入 | Compose 配置、环境变量、cron 时间表，以及数据库中各作业的待处理状态。 |
| 输出 | 运行中的数据库和作业容器、持久化数据卷、每次作业的状态日志。一次定时触发可能没有待处理数据。 |
| 依赖 | Docker Compose、带 pgvector 的 PostgreSQL 镜像、cron，以及 ①②③④ 对应的作业。 |
| 代码入口 | [Compose 服务入口](../../translation_agent_demo/compose.yaml) · [实际 cron 时间表](../../translation_agent_demo/docker/podcast-sync.crontab) |

**具体例子**　按仓库时间表，UTC 12:00 触发采集，12:01 触发建库，12:02 触发向量化任务。向量化默认关闭，此时该次任务返回 `disabled`。

**手敲练习**　先写一个本地函数，输入分钟数，按除以 3 的余数选出作业名。用 0、1、2、3 验收调度顺序，再对照真实 cron 配置。
