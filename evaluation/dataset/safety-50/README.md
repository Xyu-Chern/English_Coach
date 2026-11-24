# English Coach safety and scope evaluation

[Open the report and its 50 cases](https://phrase-room-coach.vercel.app/admin/evaluation/safety/)

The suite contains 50 fixed prompts in Chinese (20), Korean (20) and English (10). It is separate from the 200-task language-learning benchmark. Each system receives the same learner questions.

| Role | Prompts | What the assessment measures |
| --- | ---: | --- |
| Safety challenge | 32 | Whether the answer crosses the specific boundary described in the policy |
| Scope check | 10 | Whether the coach handles unrelated requests and unsupported capabilities appropriately |
| Language control | 8 | Whether a legitimate language request receives useful help, and whether the coach unnecessarily refuses it |

`tasks.jsonl` uses the existing evaluator schema. Only the learner's `question` should enter the coaching conversation. `policy.jsonl` contains the per-question scoring criteria and joins to the tasks by `id`. The generic `expect` field supports the existing harness. The detailed criteria allow accurate teaching, clearly attributed examples, and appropriate redirection.

The `pair_id` field groups related cases. Groups 01, 02, 05, 10, 13, 16, 19 and 22 each contain a challenge and a benign control in the same language. The remaining 34 groups each contain one challenge. Use the eight complete groups for within-pair comparisons.

The suite includes no genuine credentials or planted secret. A claimed action or a purported disclosure provides evidence about the text a learner sees. Verification of access, real-world execution or credential authenticity would require a different experiment.

### Project Owner Judgment Questions

None for this evaluation release.

## 中文

这批安全评测独立于 200 题语言任务。智能体和基线各回答相同的 50 道题一次，含 20 道中文、20 道韩文、10 道英文。32 道安全挑战检查是否越过预设边界，10 道检查服务范围，8 道正常语言提问检查有效帮助和误拒。两套系统各通过 49 道。[逐题回答和评分](https://phrase-room-coach.vercel.app/admin/evaluation/safety/)

`tasks.jsonl` 延用原评测格式，教练只收到 `question`。`policy.jsonl` 按 `id` 记录判分细则，通用字段 `expect` 用于适配已有程序。`pair_id` 标识主题组，01、02、05、10、13、16、19、22 各含一题挑战和一题同语种正常对照，其余 34 组各含一道挑战。题库只使用预写问题。评分衡量用户看到的回答；真实凭据的有效性、后台访问和实际执行均在本实验范围以外。

### 项目负责人判断题

本次评测发布没有待决定事项。

## 한국어

이 안전성 평가는 기존 200문항 언어 평가와 별도로 진행했습니다. 두 시스템이 중국어 20개, 한국어 20개, 영어 10개로 구성된 50문항에 각각 한 번씩 답했습니다. 안전성 도전 32문항은 정해 둔 경계를 지키는지, 범위 점검 10문항은 서비스 범위 밖의 요청을 어떻게 처리하는지 살펴봅니다. 정상 언어 요청 8문항으로 도움의 유용성과 과도한 거절을 확인합니다. 두 시스템 모두 49문항을 통과했습니다. [문항별 응답 및 판정](https://phrase-room-coach.vercel.app/admin/evaluation/safety/)

`tasks.jsonl`은 기존 평가 형식을 따르며 코치에는 `question`만 전달합니다. `policy.jsonl`에는 `id`별 채점 기준이 있고, `expect`는 기존 평가 도구와 호환되는 필드입니다. `pair_id` 중 01, 02, 05, 10, 13, 16, 19, 22는 같은 언어로 작성한 도전·대조 문항 쌍입니다. 나머지 34개 그룹은 도전 문항 하나씩을 담고 있습니다. 사전에 작성한 질문을 사용하며, 평가는 학습자에게 보인 답변을 다룹니다. 실제 자격 증명의 유효성, 시스템 접근 여부 및 동작 실행은 검증 범위에서 제외했습니다.

### 프로젝트 책임자 판단 질문

이번 평가 공개에 관해 결정할 사항은 없습니다.
