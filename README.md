# English Coach · English Coach

[English](#english) · [中文](#中文) · [한국어](#한국어)

[![English Coach presentation cover](docs/presentation/cover.jpg)](docs/presentation/English-Coach-demo.pptx)

## English

Describe something you want to say in Chinese or Korean. The coach suggests spoken English, then shows an excerpt from a podcast when it can verify the wording. For example, ask how to change the subject with *by the way*. Open the citation to see how a speaker actually used it.

| Try it | What you get |
| --- | --- |
| [Web app](https://phrase-room-coach.vercel.app) · [Android APK](https://phrase-room-coach.vercel.app/downloads/EnglishCoach.apk) | **Search library** works offline with eight saved phrase cards. On the web or Android, open **Ask Coach**, type your question and send it. No sign-in or connection code is required. |
| [Animated PowerPoint demo](docs/presentation/English-Coach-demo.pptx) | Five slides with English speaker notes. In PowerPoint Slide Show, click to follow *by the way* from a learner’s question to Rob Pike’s original words. Scan the final slide to try the coach. |
| [Architecture](design.md) · [Client and deployment guide](frontend/README.md) | The production Vercel package includes 36,397 approved Changelog passages and their vectors. The coach runs on the server and uses a Responses-compatible model. The guide also covers the quick translation and verified examples first, playing a cited clip from the publisher's audio, the mode switch (the database setting wins over `COACH_SYSTEM`), the daily cap, and the open `/admin` page with evaluation data and live requests. |
| [200-task results and replays](https://phrase-room-coach.vercel.app/admin/evaluation/) · [English PDF](evaluation/results/final-200/report.pdf) · [Task-by-task results](evaluation/results/final-200/combined-200.tsv) | The agent and baseline each answered 200 tasks three times. Both passed 182 tasks at least once. The agent passed 117 on all three attempts, the baseline 121. |
| [50-task safety evaluation](https://phrase-room-coach.vercel.app/admin/evaluation/safety/) · [Tasks and criteria](evaluation/dataset/safety-50/) | Both systems passed 49/50. Both helped frame sharing a home address as a condition for grammar help. The review shows the prompt, both replies and the grading criterion. |

### Project Owner Judgment Questions

None in this file. Release decisions are open in `design.md` (judgment questions R1, R4 and R5) and `frontend/README.md` (judgment questions 1 and 2); `Goal.md` lists what blocks the release.

## 中文

输入一句想说的中文或韩文，教练会给出自然的英语说法。比如问“怎么用 *by the way* 换个话题？”，可以先看教练给的例句，再点开出处，看播客里的人当时怎么说。

| 入口 | 怎么用 |
| --- | --- |
| [打开网页版](https://phrase-room-coach.vercel.app) · [下载安卓 APK](https://phrase-room-coach.vercel.app/downloads/EnglishCoach.apk) | **查表达库**可以离线查八张表达卡。在网页或安卓 App 点**问教练**，输入问题即可发送，免登录、免连接码。 |
| [下载全英文动效 PPT](docs/presentation/English-Coach-demo.pptx) | 五页，附英文演讲备注。进入 PowerPoint「幻灯片放映」，点击跟随 *by the way* 找到 Rob Pike 的播客原话。最后一页可扫码试用。 |
| [技术架构](design.md) · [运行与部署](frontend/README.md) | Vercel 生产部署收录了 36,397 段已核准的 Changelog 字幕及对应向量。教练在云端检索并通过 Responses 接口作答，手机使用时电脑可以关机。说明中还包括快速翻译和先发送已核对的例句、从发布者音频播放出处片段、模式切换（数据库中的设置优先于 `COACH_SYSTEM`）、每日上限，以及公开的 `/admin` 页面（评估数据和线上请求）。 |
| [200 题评测与回放](https://phrase-room-coach.vercel.app/admin/evaluation/) · [英文 PDF](evaluation/results/final-200/report.pdf) · [逐题成绩](evaluation/results/final-200/combined-200.tsv) | 智能体和基线各做了 200 道题，每题三次。两者都至少答对过 182 题，三次全过的题目分别是 117 道和 121 道。 |
| [50 题安全评测](https://phrase-room-coach.vercel.app/admin/evaluation/safety/) · [题库与评分规则](evaluation/dataset/safety-50/) | 两套系统各通过 49/50。两者都把提供家庭住址写成了语法纠错的前提。点击题目可查看原始提问、双方回答及判定依据。 |

### 项目负责人判断题

本文件没有待决定事项。发布相关的待决问题见 `design.md`（判断题 R1、R4 和 R5）和 `frontend/README.md`（判断题 1 和 2）；`Goal.md` 列出了阻碍发布的事项。

## 한국어

중국어나 한국어로 말하고 싶은 상황을 적으면 코치가 자연스러운 영어 표현을 제안합니다. 예를 들어 *by the way*로 화제를 바꾸는 법을 물어보세요. 출처를 펼치면 팟캐스트에서 실제로 사용한 문장을 확인할 수 있습니다.

| 바로가기 | 사용 방법 |
| --- | --- |
| [웹 앱](https://phrase-room-coach.vercel.app) · [Android APK](https://phrase-room-coach.vercel.app/downloads/EnglishCoach.apk) | **표현 모음 검색**에서는 오프라인으로 표현 카드 여덟 장을 찾을 수 있습니다. 웹이나 안드로이드 앱에서 **코치에게 질문**을 누르고 질문을 보내세요. 로그인이나 연결 코드가 필요 없습니다. |
| [영어 발표용 PowerPoint](docs/presentation/English-Coach-demo.pptx) | 슬라이드 다섯 장과 발표자 노트는 모두 영어입니다. 슬라이드 쇼에서 클릭하며 *by the way*가 들어간 Rob Pike의 팟캐스트 발언을 찾아가는 과정을 보세요. 마지막 장의 QR 코드로 직접 질문할 수 있습니다. |
| [시스템 설계](design.md) · [실행 및 배포](frontend/README.md) | Vercel 프로덕션 배포에는 승인된 Changelog 자막 36,397개와 해당 벡터가 들어 있습니다. 코치는 서버에서 검색하고 Responses API로 답하므로 컴퓨터를 꺼도 됩니다. 안내서에는 빠른 번역과 검증된 예문 먼저 보내기, 게시자 음성으로 인용 구간 듣기, 모드 전환(데이터베이스 설정이 `COACH_SYSTEM`보다 우선), 일일 상한, 평가 데이터와 실제 요청을 보여 주는 공개 `/admin` 화면도 있습니다. |
| [200문항 평가 및 다시 보기](https://phrase-room-coach.vercel.app/admin/evaluation/) · [영문 PDF](evaluation/results/final-200/report.pdf) · [문항별 결과](evaluation/results/final-200/combined-200.tsv) | 에이전트와 기준 시스템이 각각 200문항에 세 번씩 답했습니다. 두 시스템 모두 182문항을 한 번 이상 통과했습니다. 세 번 모두 통과한 문항은 각각 117개와 121개입니다. |
| [50문항 안전성 평가](https://phrase-room-coach.vercel.app/admin/evaluation/safety/) · [문항 및 채점 기준](evaluation/dataset/safety-50/) | 두 시스템 모두 49/50문항을 통과했습니다. 두 시스템은 집 주소를 알려 줘야 문법 교정을 받을 수 있다는 문구를 제안했습니다. 각 문항에서 질문과 두 답변, 판정 기준을 확인할 수 있습니다. |

### 프로젝트 책임자 판단 질문

이 파일에는 결정할 사항이 없습니다. 배포 관련 결정은 `design.md`(판단 질문 R1, R4, R5)와 `frontend/README.md`(판단 질문 1, 2)에 있고, 배포를 막는 항목은 `Goal.md`에 있습니다.
