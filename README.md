# Phrase Room · English Coach

[English](#english) · [中文](#中文) · [한국어](#한국어)

[![Phrase Room presentation cover](docs/presentation/cover.jpg)](docs/presentation/Phrase-Room-demo.pptx)

## English

Describe something you want to say in Chinese or Korean. The coach suggests spoken English, then shows an excerpt from a podcast when it can verify the wording. For example, ask how to change the subject with *by the way*. Open the citation to see how a speaker actually used it.

| Try it | What you get |
| --- | --- |
| [Web app](https://phrase-room-coach.vercel.app) · [Android APK](https://phrase-room-coach.vercel.app/downloads/PhraseRoom.apk) | **Search library** works offline with eight saved phrase cards. On the web or Android, open **Ask Coach**, type your question and send it. No sign-in or connection code is required. |
| [Animated PowerPoint demo](docs/presentation/Phrase-Room-demo.pptx) | Five slides with English speaker notes. In PowerPoint Slide Show, click to follow *by the way* from a learner’s question to Rob Pike’s original words. Scan the final slide to try the coach. |
| [Architecture](design.md) · [Client and deployment guide](frontend/README.md) | The Vercel deployment bundles six episodes, 185 transcript passages and their vectors. The coach runs on the server and uses a Responses-compatible model. |
| [Chinese test cases](evaluation/data/tasks.zh.jsonl) · [Chinese evaluation report](docs/evaluation-zh/results.md) · [Answer replay](docs/evaluation-zh/review.html) | The harness compares the agent with a fixed workflow. The Chinese report is a partial run. Its denominators are graded attempts. |

### Project Owner Judgment Questions

None pending for this release.

## 中文

输入一句想说的中文或韩文，教练会给出自然的英语说法。比如问“怎么用 *by the way* 换个话题？”，可以先看教练给的例句，再点开出处，看播客里的人当时怎么说。

| 入口 | 怎么用 |
| --- | --- |
| [打开网页版](https://phrase-room-coach.vercel.app) · [下载安卓 APK](https://phrase-room-coach.vercel.app/downloads/PhraseRoom.apk) | **查表达库**可以离线查八张表达卡。在网页或安卓 App 点**问教练**，输入问题即可发送，免登录、免连接码。 |
| [下载全英文动效 PPT](docs/presentation/Phrase-Room-demo.pptx) | 五页，附英文演讲备注。进入 PowerPoint「幻灯片放映」，点击跟随 *by the way* 找到 Rob Pike 的播客原话。最后一页可扫码试用。 |
| [技术架构](design.md) · [运行与部署](frontend/README.md) | Vercel 上保存了六集播客、185 段字幕及对应向量。教练在云端检索并通过 Responses 接口作答，手机使用时电脑可以关机。 |
| [50 道中文评测题](evaluation/data/tasks.zh.jsonl) · [中文评测报告](docs/evaluation-zh/results.md) · [逐题回放](docs/evaluation-zh/review.html) | 同一批题比较智能体与固定流程基线。中文报告只覆盖已记录的运行，通过率按已评分的作答次数计算。 |

### 项目负责人判断题

本次发布没有待决定事项。

## 한국어

중국어나 한국어로 말하고 싶은 상황을 적으면 코치가 자연스러운 영어 표현을 제안합니다. 예를 들어 *by the way*로 화제를 바꾸는 법을 물어보세요. 출처를 펼치면 팟캐스트에서 실제로 사용한 문장을 확인할 수 있습니다.

| 바로가기 | 사용 방법 |
| --- | --- |
| [웹 앱](https://phrase-room-coach.vercel.app) · [Android APK](https://phrase-room-coach.vercel.app/downloads/PhraseRoom.apk) | **표현 모음 검색**에서는 오프라인으로 표현 카드 여덟 장을 찾을 수 있습니다. 웹이나 안드로이드 앱에서 **코치에게 질문**을 누르고 질문을 보내세요. 로그인이나 연결 코드가 필요 없습니다. |
| [영어 발표용 PowerPoint](docs/presentation/Phrase-Room-demo.pptx) | 슬라이드 다섯 장과 발표자 노트는 모두 영어입니다. 슬라이드 쇼에서 클릭하며 *by the way*가 들어간 Rob Pike의 팟캐스트 발언을 찾아가는 과정을 보세요. 마지막 장의 QR 코드로 직접 질문할 수 있습니다. |
| [시스템 설계](design.md) · [실행 및 배포](frontend/README.md) | Vercel 배포본에는 에피소드 6개, 자막 185개와 해당 벡터가 들어 있습니다. 코치는 서버에서 검색하고 Responses API로 답하므로 컴퓨터를 꺼도 됩니다. |
| [중국어 평가 문항](evaluation/data/tasks.zh.jsonl) · [중국어 평가 보고서](docs/evaluation-zh/results.md) · [문항별 응답](docs/evaluation-zh/review.html) | 같은 문항으로 에이전트와 고정된 절차를 따르는 기준 시스템을 비교합니다. 중국어 보고서는 부분 실행 결과이며 통과율의 분모는 채점된 응답 수입니다. |

### 프로젝트 책임자 판단 질문

이번 배포에서 결정할 사항은 없습니다.
