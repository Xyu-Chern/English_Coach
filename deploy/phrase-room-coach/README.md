# Ready-to-deploy package for phrase-room-coach

[English](#english) · [中文](#中文) · [한국어](#한국어)

## English

This folder is the shared site's Vercel project, already built. Deploy it as it is:

```sh
cd deploy/phrase-room-coach
vercel link --project phrase-room-coach   # once, from the account that owns the project
vercel --prod
```

### Publish a new benchmark scorecard

Start in the repository root after the baseline and Agent have each completed and graded three runs per task. Replace `team-200` with the eval run folder name. If this checkout is new to the Vercel project, link it once using the command above.

The first command updates the checkout, the Python command writes `public/admin/benchmark.json` into this deployment package, and the last command deploys that file. Open `/admin/?tab=metrics` and verify the run ID and counts. The scorecard uses a separate static file so the request log and timing views can still identify their detailed evaluation run. The export uses the existing eval Python environment and makes no model calls.

The second example below is the **input** safety file. List all safety prompts, using `kind: "benign"` for normal controls. `safe` or `unsafe` is the outcome against each prompt's criterion. Use `null` for missing judgments. Over-refusal is measured on answer-expected benchmark attempts. Use `over_refusals` to label explicit declines (`true` for wrongful, `false` for justified). An omitted decline stays unjudged. The optional `failure` key selects a failed attempt in the same run. Substitute IDs from your run. If the safety file is still pending, omit `--safety` and the unjudged cells show **Pending**. Review the generated public scorecard before deploying.

```sh
git pull --ff-only
python -m evaluation.export_benchmark --run team-200 --safety evaluation/results/team-200/safety-results.json
cd deploy/phrase-room-coach
vercel --prod
```

```json
{
  "run": "team-200",
  "prompts": [
    {
      "id": "s-001",
      "kind": "attack",
      "surface": "question",
      "criterion": "Stay within the coach's permitted scope.",
      "verdicts": {"baseline": "safe", "agent": null}
    }
  ],
  "over_refusals": {"task-id/agent/2": true},
  "failure": "task-id/agent/2"
}
```

**What changes for learners:** the coach searches all 36,397 approved Changelog passages (1,167 episodes, CC-BY-SA-4.0) instead of 185 passages from six episodes. Everyday questions such as "이제 자러 가고 싶다고 뭐라 말해?" can now find a podcast quote. The admin request log opens without a token; the mode switch still needs `COACH_ADMIN_TOKEN`.

**Contents**
- Built from `main` with `python -m frontend.vercel.package --out deploy/phrase-room-coach --skip-apk --skip-search-data`. The steps below then replaced the parts that need the teammate's machine.
- `corpus/`: the 36,397-passage snapshot from `python -m frontend.vercel.own_snapshot` (gzipped passages, float16 MiniLM vectors, audio alignments, manifest). `frontend/vercel/coach.py` reads this format.
- `encoder/`: the bundled MiniLM encoder (Apache-2.0).
- `public/downloads/EnglishCoach.apk` and `public/admin/data.json`: copied from the live site on 2026-11-22, so the app download and the admin evaluation view stay the same.
- The project's production variables (model key, database, admin token) stay in Vercel and are not in this folder.

**Checks (2026-11-22, local):** the packaged function loads 36,397 passages; a literal search finds "go to bed" in 28 passages and "have a good one" in 19; `/admin/requests.json` answers 200 without a token; `POST /admin/mode` without a token answers 401. Not checked: a real deploy on the shared project.

**Keep in mind**
- Running `python -m frontend.vercel.package` into this folder again overwrites `corpus/vectors.npy` with the 185-row file but keeps `passages.json.gz`. The function then fails at start (vector shape mismatch). Rebuild with the command above and copy the four corpus files back.
- This folder is a copy of the code on `main` at build time. Rebuild it after code changes.
- Git builds of the shared project are skipped by its Ignored Build Step, so a push alone does not deploy.

## Project Owner Judgment Questions

No pending project-owner decisions for this folder.

---

## 中文

本文件夹是共享站已经构建好的 Vercel 项目，直接部署即可：

```sh
cd deploy/phrase-room-coach
vercel link --project phrase-room-coach   # 只需一次，用拥有该项目的账户
vercel --prod
```

### 发布新的基准成绩表

Baseline 和 Agent 对每题均完成三次运行并评分后，从仓库根目录开始。将 `team-200` 替换为评估运行目录名。若当前检出尚未关联 Vercel 项目，先用上面的命令关联一次。

第一条命令更新检出，Python 命令把 `public/admin/benchmark.json` 写入此部署包，最后一条命令发布该文件。打开 `/admin/?tab=metrics` 核对运行 ID 和计数。成绩表使用单独的静态文件，请求日志和耗时视图仍显示各自详细评估的运行 ID。导出复用现有 eval 的 Python 环境，无需调用模型。

下面第二个示例是安全评估**输入**文件。列出所有提示，正常对照的 `kind` 填 `"benign"`。按照每个提示的标准将实际结果标记为 `safe` 或 `unsafe`，未判定填 `null`。过度拒绝以预期应答的基准运行计，用 `over_refusals` 给明确拒绝标注（`true` 为不当，`false` 为合理）。省略的拒绝仍视为未判定。可选的 `failure` 指向同一运行中一次失败。请替换成实际 ID。安全文件尚未准备好时可省略 `--safety`，未判定指标会显示**待确认**。部署前检查公开成绩表。

```sh
git pull --ff-only
python -m evaluation.export_benchmark --run team-200 --safety evaluation/results/team-200/safety-results.json
cd deploy/phrase-room-coach
vercel --prod
```

```json
{
  "run": "team-200",
  "prompts": [
    {
      "id": "s-001",
      "kind": "attack",
      "surface": "question",
      "criterion": "Stay within the coach's permitted scope.",
      "verdicts": {"baseline": "safe", "agent": null}
    }
  ],
  "over_refusals": {"task-id/agent/2": true},
  "failure": "task-id/agent/2"
}
```

**对学习者的变化：** 教练检索全部已核准的 36,397 段 Changelog 字幕（1,167 集，CC-BY-SA-4.0），而不再只有六集的 185 段。像"이제 자러 가고 싶다고 뭐라 말해?"这样的日常问题也能找到播客原句。管理页的真实请求日志无需令牌即可查看；切换模式仍然需要 `COACH_ADMIN_TOKEN`。

**内容**
- 由 `main` 运行 `python -m frontend.vercel.package --out deploy/phrase-room-coach --skip-apk --skip-search-data` 构建，再用下面几项替换需要队友电脑才能生成的部分。
- `corpus/`：`python -m frontend.vercel.own_snapshot` 生成的 36,397 段快照（gzip 字幕、float16 MiniLM 向量、音频对齐、清单）。`frontend/vercel/coach.py` 能读取这种格式。
- `encoder/`：随包的 MiniLM 编码器（Apache-2.0）。
- `public/downloads/EnglishCoach.apk` 和 `public/admin/data.json`：于 2026-11-22 从线上站复制，App 下载和管理页评测视图保持不变。
- 项目的生产环境变量（模型密钥、数据库、管理令牌）保留在 Vercel 中，不在本文件夹里。

**检查（2026-11-22，本地）：** 打包后的函数能加载 36,397 段字幕；字面检索在 28 段中找到 "go to bed"，在 19 段中找到 "have a good one"；`/admin/requests.json` 无令牌返回 200；无令牌的 `POST /admin/mode` 返回 401。未检查：在共享项目上实际部署。

**注意**
- 再次把 `python -m frontend.vercel.package` 输出到本文件夹，会用 185 行的文件覆盖 `corpus/vectors.npy`，但保留 `passages.json.gz`。函数随后会在启动时失败（向量形状不匹配）。请用上面的命令重新构建，并把四个字幕文件复制回来。
- 本文件夹是构建时 `main` 代码的副本。代码改动后需要重新构建。
- 共享项目的 Git 构建会被 Ignored Build Step 跳过，所以只 push 不会部署。

## 项目负责人判断题

本文件夹目前没有待项目负责人判断的事项。

---

## 한국어

이 폴더는 이미 빌드한 공용 사이트의 Vercel 프로젝트다. 그대로 배포하면 된다.

```sh
cd deploy/phrase-room-coach
vercel link --project phrase-room-coach   # 처음 한 번, 프로젝트를 가진 계정으로
vercel --prod
```

### 새 벤치마크 성과표 배포

Baseline과 Agent가 각 과제를 3회씩 실행하고 채점을 마치면 저장소 루트에서 시작한다. `team-200`을 실제 eval 결과 폴더 이름으로 바꾼다. 이 체크아웃을 Vercel 프로젝트에 처음 연결한다면 위의 연결 명령을 한 번 실행한다.

첫 명령은 체크아웃을 갱신한다. Python 명령이 배포 패키지에 `public/admin/benchmark.json`을 쓰고, 마지막 명령이 그 파일을 배포한다. `/admin/?tab=metrics`에서 평가 실행 ID와 건수를 확인한다. 성과표는 별도 정적 파일을 읽고, 요청 로그와 지연 지표는 상세 데이터에 해당하는 실행 ID를 보여준다. 기존 eval Python 환경에서 내보내며 모델을 호출하지 않는다.

아래 두 번째 예시는 안전 평가 **입력** 파일이다. 모든 안전 프롬프트를 넣고 정상 대조군은 `kind: "benign"`으로 표시한다. 케이스별 기준에 따라 결과를 `safe` 또는 `unsafe`로 판정하고, 미판정은 `null`로 남긴다. 과잉 거절률은 답변이 기대된 벤치마크 실행 기준이다. `over_refusals`에는 명시적 거절의 판정을 담는다(`true` 부당, `false` 정당). 키가 빠진 거절은 미판정으로 남는다. 선택 사항인 `failure`에는 같은 평가 실행의 실패 키를 쓴다. 실제 실행 ID와 과제 ID로 바꿔 사용한다. 안전 파일이 준비 중이면 `--safety`를 생략할 수 있고, 미판정 지표는 **확인 대기**로 표시된다. 배포 전에 생성된 공개 성과표를 확인한다.

```sh
git pull --ff-only
python -m evaluation.export_benchmark --run team-200 --safety evaluation/results/team-200/safety-results.json
cd deploy/phrase-room-coach
vercel --prod
```

```json
{
  "run": "team-200",
  "prompts": [
    {
      "id": "s-001",
      "kind": "attack",
      "surface": "question",
      "criterion": "Stay within the coach's permitted scope.",
      "verdicts": {"baseline": "safe", "agent": null}
    }
  ],
  "over_refusals": {"task-id/agent/2": true},
  "failure": "task-id/agent/2"
}
```

**학습자에게 달라지는 점:** 코치가 에피소드 6개의 자막 185개 대신 승인된 Changelog 자막 36,397개 전체(에피소드 1,167개, CC-BY-SA-4.0)를 검색한다. "이제 자러 가고 싶다고 뭐라 말해?" 같은 일상 질문도 팟캐스트 원문을 찾을 수 있다. 어드민의 실제 요청 기록은 토큰 없이 열리고, 모드 전환에는 여전히 `COACH_ADMIN_TOKEN`이 필요하다.

**구성**
- `main`에서 `python -m frontend.vercel.package --out deploy/phrase-room-coach --skip-apk --skip-search-data`로 빌드한 뒤, 팀원 컴퓨터가 있어야 만들 수 있는 부분을 아래 항목으로 바꿨다.
- `corpus/`: `python -m frontend.vercel.own_snapshot`이 만든 자막 36,397개 스냅샷(gzip 자막, float16 MiniLM 벡터, 음성 정렬, 매니페스트). `frontend/vercel/coach.py`가 이 형식을 읽는다.
- `encoder/`: 함께 넣은 MiniLM 인코더(Apache-2.0).
- `public/downloads/EnglishCoach.apk`, `public/admin/data.json`: 2026-11-22에 운영 사이트에서 복사했다. 앱 다운로드와 어드민 평가 화면은 그대로다.
- 프로젝트의 프로덕션 변수(모델 키, 데이터베이스, 어드민 토큰)는 Vercel에 그대로 있고 이 폴더에는 없다.

**확인(2026-11-22, 로컬):** 패키지된 함수가 자막 36,397개를 읽는다. 문자열 검색으로 "go to bed"는 28개, "have a good one"은 19개 자막에서 찾는다. `/admin/requests.json`은 토큰 없이 200, 토큰 없는 `POST /admin/mode`는 401을 돌려준다. 확인하지 못한 것: 공용 프로젝트에 실제로 배포하기.

**주의**
- 이 폴더로 `python -m frontend.vercel.package`를 다시 실행하면 `corpus/vectors.npy`는 185행 파일로 덮어쓰고 `passages.json.gz`는 남는다. 그러면 함수가 시작할 때 실패한다(벡터 모양 불일치). 위 명령으로 다시 빌드하고 자막 파일 4개를 다시 복사한다.
- 이 폴더는 빌드 시점 `main` 코드의 복사본이다. 코드가 바뀌면 다시 빌드한다.
- 공용 프로젝트의 Git 빌드는 Ignored Build Step으로 건너뛰므로 push만으로는 배포되지 않는다.

## 프로젝트 책임자 판단 질문

이 폴더에는 현재 프로젝트 책임자가 결정할 사항이 없습니다.
