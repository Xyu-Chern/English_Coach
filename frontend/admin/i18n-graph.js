/* 실행 그래프 화면 문구 사전(한국어 · 中文 · English). i18n.js만 import하는 잎 모듈.
   - 키는 "graph.<묶음>.<이름>"(묶음 = tab · model · detail). register()로 i18n.js 사전에 함께 올린다.
     단계 종류(KIND) · 상태(STATUS) · 단계 제목(stageTitle)은 parts.js("parts.*" 키)를 그대로 쓴다.
   - 값은 문자열, 위치 인자를 받는 함수(복수형 · 숫자 · DOM 조각), 또는 문자열 배열이다.
     위치 인자 함수가 있어서 그래프 모듈은 t() 대신 gtext("tab") 같은 언어 보기로 읽는다(같은 사전, 읽는 순간의 언어).
   - 빠진 값은 ko 값으로 보이고 window.__i18nMissing에 "언어:graph.…"로 남는다(i18n.js와 같은 규칙).
   - DOM 조각(과제 id 등)은 호출하는 쪽이 만들어 인자로 넘긴다. 데이터 문자열은 언제나 텍스트 노드로만 들어간다. */
import { lang, register } from "./i18n.js";

const FINAL = 4; /* pick_final 계열 turn 값(graph-model.js FINAL_TURN과 같음) */
const pl = (n, one, many = one + "s") => `${n} ${+n === 1 ? one : many}`;
const s_ = n => (+n === 1 ? "" : "s");

/* ======================================================================= 한국어 */
const KO = {
  tab: {
    loading: "단계 기록(trace)을 불러오는 중이에요…",
    title: "실행 그래프 — 요청 한 건이 어떤 구성요소를 거쳤나",
    lead: "위는 구성요소 노선도(고정 템플릿 위에 실제로 지난 길만 진하게), 아래는 레인별 시간 흐름이에요. " +
      "노드나 막대를 누르면 옆(좁은 화면에선 노선도 아래)에 입력·출력·판단 이유가 나오고, 노드와 막대가 함께 강조돼요.",
    preLock: ["agent 판단은 잠금 규칙을 넣기 전 기록", "이라 먼저 보낸 슬롯을 겨눈 행동도 기록대로 보여 줘요."],
    srcLabel: "보여 줄 요청",
    ex: { baseline: "baseline 예시", agent: "agent 예시", skipped: "후속 생략 예시", lock: "잠금 건너뜀 예시", log: "로그에서 고른 요청" },
    exNone: "· 없음",
    logTip: "요청 로그에서 행을 고르고 ‘실행 그래프로 보기’를 누르세요",
    pickLabel: "다른 요청 열기",
    opt: (x, st) => `${x.task_id} ${x.attempt}회차 · ${x.mode} · ${st} · ${x.continuation === "skipped" ? "생략 · " : ""}` +
      String(x.question || "").slice(0, 26),
    exPair: (task, n, vf, m1, a1, m2, a2) => ["두 예시는 같은 질문 · 같은 첫 단계 기록(과제 ", task,
      ` ${n}회차)이고 후속 경로만 달라요. 첫 단계 검증 ${vf}개 → ${m1} 추가 ${a1}개 · ${m2} 추가 ${a2}개.`],
    exSkip: vf => `첫 단계에서 ${vf}/3 검증 → 후속 단계를 실행하지 않고 바로 완료해요.`,
    exSkipPre: " 잠금 전 기록이라 agent에는 생략 예시가 없어 baseline 요청을 보여 줘요.",
    noReq: "보여 줄 요청이 없어요.",
    noTrace: "이 요청의 단계 기록이 없어요.",
    sum: {
      task: "평가 기록 ", attempt: n => ` · ${n}회차`, first: "첫 응답 ", total: "전체 ", tok: "토큰 ", calls: "회 · 검색 ",
      times: "회", ex: "예문 ", preFv: list => `잠금 전 기록 · 먼저 보낸 슬롯 ${list}`,
    },
    routeTitle: "구성요소 노선도", routeSub: "고정 템플릿 위의 실제 경로 · 안 간 길은 점선 · 노드를 누르면 상세",
    legend: "범례", routeRegion: "구성요소 노선도 (가로 스크롤)",
    scrollHint: "노선도가 화면보다 넓어요 · 옆으로 밀어 후속 단계를 보세요",
    detailLabel: "선택한 단계 상세",
    swimTitle: "스윔레인 · 레인별 시간", swimSub: "x = 요청 시작부터 지난 시간 · 막대를 누르면 상세와 노선도 노드가 함께 강조돼요",
    swimRegion: "스윔레인 워터폴",
    lg: {
      taken: "실행된 경로", notTaken: "실행 안 된 경로", imm: "즉시 결과 시점(검증 1~2개)", done: "즉시 완료(검증 3개 · 후속 생략)",
      mid: "첫 단계 끝 · 예문 0개(대기)", lockSlot: "잠긴 슬롯(이미 보냄 · 바꾸지 않음)", lockAct: "잠금으로 건너뛴 행동(noop)",
      skipped: "건너뜀", rule: "코드 규칙", llm: "LLM 판단",
      first: "첫 응답 시점", turn: "라운드 · 턴 경계", dia: "0초 검증(슬롯 수)", sq: "0초 도구 적용(코드)",
      zone: "후속 생략(실행 안 함, 폭은 표시용)", link: "판단 → 도구 호출",
    },
    kindShort: {
      request: "입력", llm: "LLM", judge: "판단", search: "검색", verify: "검증", act: "도구", assemble: "조립", decline: "거절",
    },
    notRun: "안 함", error: "오류", ariaSkip: ", 실행 안 됨", ariaErr: ", 오류", ariaTok: t => `, 토큰 ${t}`,
    node: {
      req: "질문", cand: "후보 생성", decl: "거절 판정", srch: n => `검색 도구 ×${n}`, sel1: "예문 선택", val1: "코드 검증",
      rev: "수정 제안", bsrch: "추가 검색", bsel: "예문 선택", val: "코드 검증", judge: k => `판단 · 턴 ${k}`, judge0: "판단",
      final: "최종 선택", tools: "도구 행동", asm: "조립 · 응답", asmSkip: "응답 · 즉시 완료",
    },
    meta: {
      attempt: n => `${n}회차`, verdict: "판정 ", cand: (n, t) => `후보 ${n}개 · ${t}`, declYes: "범위 밖 → 종료", declIf: "범위 밖이면",
      lit: n => `코퍼스 일치 ${n}`, litTip: "핵심 구절이 코퍼스에 그대로 있으면 ‘코퍼스 일치’",
      fb: n => `대체 검색 ${n}`, fbTip: "핵심 구절이 코퍼스에 없어 의미 검색으로 대체",
      picks: (a, b, t) => `인용 ${a}/${b} · ${t}`, picks2: (a, b) => `인용 ${a}/${b}`, repl: (n, t) => `대체 ${n}개 · ${t}`,
      searchN: n => `${n}회`, reuse: "기존 구간 재사용 시 생략", reuseTip: "수정 제안이 이미 찾은 인용 구간(ref)을 가리키면 검색 없이 바로 채택",
      noAct: "행동 없음", finalIf: "3턴 모두 계속 + 3턴째 검색 시", finalTip: "3턴 모두 finish 없이 끝나고 3턴째에 검색이 실행됐을 때만 실행",
      errOf: "오류 ", toEnd: " → 종료", toNext: " → 계속",
      asmEx: (e, w) => `표현 ${e} · 예문 ${w}`, added: n => ` (추가 ${n})`, done: t => `완료 ${t}`,
      errFirst: "오류 안내 반환", keepFirst: "먼저 보낸 답 유지",
      lock: list => `잠금 ${list}`, lockTip: "첫 단계에서 검증돼 학습자에게 보낸 슬롯 · 후속에서 바꾸지 않음",
      judgeLockTip: "판단 입력에 넣은 잠긴 슬롯", lostN: n => `보낸 예문 ${n}개 바뀜`,
      lostTip: "잠금 전 기록: 먼저 보낸 검증 예문이 최종 답에서 빠짐",
      slotLock: n => `s${n} 잠금(첫 단계 검증 · 이미 보냄)`, slotV: n => `s${n} 검증`, slotEmpty: n => `s${n} 빈 자리`,
      slotsAria: (v, n, lk) => `검증 ${v}/${n}${lk ? ", 잠금 " + lk : ""}`, skipped: t => `${t} 건너뜀`,
    },
    lane: {
      loopB: " · 수정 루프", loopA: " · 판단 루프", ruleB: "코드 규칙이 다음 단계 결정", ruleA: "LLM이 다음 행동 결정",
      count: (n, b) => `${n}/3 ${b ? "회차" : "턴"}`, other: m => `이 요청은 ${m} 모드 · 실행 안 됨`,
      contSkip: vf => `후속 생략 · 검증 ${vf}/3`, noCont: why => `후속 없음 · ${why}`, declined: "거절", errFirst: "첫 단계 오류",
      endFirst: "첫 단계에서 종료", preLock: "잠금 전 기록", fold: "회차 접기", unfold: "회차 펼치기",
      skipRow: vf => `후속 단계 생략 — 첫 단계에서 ${vf}/3 검증 · 공지 없이 첫 단계 답으로 바로 완료`,
      rowName: (final, b, k) => (final ? "최종 선택(pick_final)" : b ? `${k}회차` : `턴 ${k}`),
      notRun: (name, why) => `${name} — 실행 안 됨 · ${why}`, end: "종료 이유: ",
      whyOther: m => `이 요청은 ${m} 모드라 이 루프를 실행하지 않았어요.`,
    },
    phase: {
      first: "첫 단계", firstSub: " · 두 모드 공통 · ", cont: "후속 단계", only: " 전용", fill: "빈 자리만 채우기",
      skip: vf => `생략 · 검증 ${vf}/3`,
      decl: t => `거절 · ${t}에 종료`, err: t => `첫 단계 오류 · ${t}`, done: (t, vf) => `즉시 완료 ${t} · 검증 ${vf}/3`,
      mid: t => `첫 단계 끝 ${t} · 예문 0개 → 대기`, midTip: "첫 단계 검증 예문 0개: 확인 안 된 후보는 보여 주지 않고 최종까지 대기",
      imm: (t, vf) => `즉시 결과 ${t} · 검증 ${vf}개 먼저`,
    },
    swim: {
      who: "학습자 화면", seg: "구간", time: "시간", segFirst: "첫 단계", segSkip: "후속 생략 · 실행 안 함",
      turn: (a, t) => (t === FINAL ? "최종 선택" : `${a ? "턴" : "라운드"} ${t}`),
      turnShort: (a, t) => (t === FINAL ? "F" : `${a ? "T" : "R"}${t}`),
      empty: "실행 안 함", emptyDecl: "거절 경로 · 실행 안 함", emptyEnd: why => `실행 안 함 · ${why}`,
      zone: vf => `후속 생략 · 첫 단계 ${vf}/3 검증`, zoneShort: "후속 생략",
      tok: (i, o) => ` · 토큰 ${i}/${o}`, errA: " · 오류", lockA: " · 잠금으로 건너뜀",
      inst: (skip, t, vf) => `${skip ? "첫 결과 = 최종" : "첫 결과"} ${t} · 예문 ${vf}개${skip ? " · 공지 없음" : ""}`,
      instShort: (skip, t, vf) => `${skip ? "첫 결과=최종" : "첫 결과"} ${t} · ${vf}개`,
      fin: {
        decl: "거절 안내", errCont: "후속 실패 · 첫 결과 유지", err: "오류 안내", once: "최종 결과(한 번에)",
        added: n => `팟캐스트 탭 +${n}`, all: "최종 답", none: "더 못 찾음 · 공지 닫힘",
      },
      tick: s => `${s}초`,
    },
  },
  model: {
    noQuestion: "(질문 원문 없음)",
    rej: {
      unknown_or_reused_ref: "없는 구간이거나 이미 쓴 구간", explanation_missing: "설명 누락",
      reusable_wording_not_in_span: "재사용 문구가 구간에 없음", wording_lacks_key_phrase: "문구에 핵심 구절 없음",
    },
    outcome: {
      verified: "검증 통과", removed: "예문 제거", replaced: "표현 새로 씀(예문은 다음 턴)",
      kept_verified_example: "기존 검증 예문 유지(가드)",
    },
    rejected: x => `기각 · ${x}`,
    smode: { literal: "문자 일치", semantic_fallback: "의미 검색(대체)", semantic: "의미 검색" },
    err: {
      search_unavailable: "검색 도구 응답 없음", model_unavailable: "모델 응답 없음",
      invalid_model_output: "모델 출력 형식 오류", model_output_truncated: "모델 출력이 잘림", model_refused: "모델 거부",
      corpus_not_ready: "코퍼스 준비 안 됨",
    },
    noCode: "코드 없음",
    corpus: n => `코퍼스 ${n}건`,
    slotCand: n => `후보 ${n}`, slotNew: "새 표현", slot: n => `슬롯 ${n}`,
    slotNoEx: n => `슬롯 #${n} 예문 없음`, slotTag: n => `슬롯 #${n}`,
    tagFixed: " 고정", tagChanged: " 바뀜", tagSent: " 먼저 보냄",
    firstSlotHit: "먼저 보낸 슬롯 대상", lockViolation: "잠금 위반 기록이에요.", wouldNoop: "잠금이면 건너뛰었을 행동이에요(noop).",
    judgeLocked: "판단 입력에 잠긴 슬롯으로 들어갔어요.", preLock: "잠금 전 기록",
    judgeUnaware: list => `먼저 보낸 슬롯 ${list}을 모르고 내린 판단이에요.`,
    prevExpr: "직전 표현", newExpr: "→ 새 표현", expr: "표현",
    why: "왜 이렇게 판단했나", whyNone: "판단 원문이 기록되지 않았어요.", whyFirst: "왜 이렇게 판단했나 · 판단 원문 첫 문장",
    verb: {
      searchNew: "새 표현 검색", search: n => `슬롯 ${n} 검색`, replace: n => `슬롯 ${n} 표현 새로 쓰기`,
      repick: n => `슬롯 ${n} 예문 다시 고르기`,
    },
    act: {
      missing: list => `직전 검증에서 슬롯 ${list}에 예문이 없어요.`, allOk: "직전 검증에서 슬롯 3개 모두 예문이 확인됐어요.",
      hit: (n, locked) => ` 그중 ${n}개는 먼저 보낸 슬롯 대상이에요(${locked ? "잠금으로 건너뜀" : "잠금이면 건너뜀"}).`,
      picked: (n, list, hit) => `행동 ${n}개(${list})를 골랐어요.${hit}`, none: "추가 행동은 고르지 않았어요.",
      final: "3턴을 다 써서 최종 선택으로 마무리해요.", finish: "여기서 끝내기로 판단했어요(finish=true).",
      next: "결과를 보고 다음 턴에 다시 판단해요(finish=false).",
    },
    end: {
      declined: "거절 판정 → 바로 조립", error: (code, stage) => `오류로 중단 · ${code} @ ${stage}`,
      skipped: n => `첫 단계에서 ${n}/3 검증 → 후속 단계 생략`, noLoop: "수정 루프 없음",
      allV: n => `${n}회차에 3/3 검증 → 종료`, roundsOut: "3회차 소진 → 종료", noRep: "새 대체 표현 없음 → 종료",
      turnsFinal: "3턴 소진 → 최종 선택 후 종료", finish: n => `턴 ${n}에서 finish=true (모델이 종료 판단)`,
      turnsOut: "3턴 소진 → 종료", done: "종료",
    },
    rowWhy: {
      declined: "거절로 후속 없음", error: "오류로 중단", skipped: n => `검증 ${n}/3 → 후속 생략`,
      prev3: "직전 검증에서 3/3 확인", noRep: "새 대체 표현 없음", finish: n => `턴 ${n}에서 finish=true`,
      noSearch: "3턴째에 검색이 없어 생략", earlier: "이전 턴에서 종료",
    },
    lane: {
      cand: "후보 LLM", search: "검색 도구", select: "선택 LLM", judgeA: "판단 LLM · 도구 적용", judgeB: "수정 LLM",
      verify: "코드 검증", asm: "조립 · 응답",
    },
    /* 스팬 한 줄 요약(데이터의 한국어 summary 대신 stage · kind · detail로 만든다. 생성기 summarize()와 같은 규칙) */
    sum: {
      error: c => `오류로 중단: ${c}`, locked: "고정된 슬롯이라 건너뜀 (잠금 규칙)",
      contSkip: "첫 단계에서 3개 모두 검증되어 후속 단계 생략", noop: x => `변화 없는 행동이라 건너뜀 (${x})`,
      skipped: x => `건너뜀 (${x})`, candDecl: st => `요청 판정: ${st} → 거절 경로`,
      cand: (n, k) => `후보 표현 ${n}개 생성 (유형 ${k})`, decl: st => `거절 안내 반환 (${st})`,
      search: (first, slot, kp, hits, cc, mode) =>
        `${first ? "후보 검색" : "추가 검색"}${slot != null ? ` 슬롯 ${slot}` : ""} '${kp}': 결과 ${hits}건, 코퍼스 일치 ${cc}건 (${mode})`,
      verify: (v, n, rej, guard, noops) => `코드 검증: 검증 예문 ${v}/${n}` + (rej ? `, 거부 ${rej}건` : "") +
        (guard ? `, 가드 ${guard}건` : "") + (noops ? `, 건너뛴 행동 ${noops}건` : ""),
      sel1: (n, r) => `예문 선택: 후보 ${n}개 중 ${r}개에 인용 구간 지정`, sel: (n, r) => `교체 표현 ${n}개에 예문 선택 (${r}개 인용 지정)`,
      revise: (n, r) => `미검증 슬롯 대체 표현 ${n}개 제안` + (r ? ` (기존 구간 바로 지정 ${r}개)` : ""),
      noAct: "행동 없음", final: w => `마지막 선택 호출: ${w}`, judge: (w, fin) => `에이전트 판단: ${w} → ${fin ? "종료" : "계속"}`,
      repick: (s, o) => `슬롯 ${s} 예문 재선택 → ${o}`, replace: (s, e, o) => `슬롯 ${s} 표현 교체 '${e}' → ${o}`, noResult: "결과 없음",
      asm: (e, w) => `최종 답 구성: 표현 ${e}개, 예문 ${w}개`, budget: c => `예산 소진(${c}) → 현재 초안으로 마무리`,
    },
  },
  detail: {
    pick: "노드나 막대를 고르면 상세가 나와요.",
    back: t => `${t} 전체 보기`,
    req: "질문", input: "입력", mode: "적용 모드", task: "평가 과제", attempt: "회차", attemptUnit: "회차", category: "분류",
    langExpect: "언어 · 기대", expDecline: "거절", expAnswer: "답변", reqId: "요청 ID",
    resp: "조립 · 응답", firstResp: "첫 응답", total: "전체", sec: "초", examples: "예문", tokens: "토큰", cont: "후속",
    judge: "심사", noAnswer: "보낸 답 문구가 없어요(거절·오류).", finalSlots: "최종 답 (슬롯 순서)",
    asmSpans: "조립 단계 기록",
    first: "첫 단계", contPhase: "후속 단계", turn: n => `턴 ${n}`, round: n => `라운드 ${n}`, final: "최종",
    start: "시작", took: "소요", tokIn: "토큰 입력", tokOut: "토큰 출력", model: "모델",
    inSum: "입력 요약", outJudge: "출력 · 판단 이유", outRes: "출력 · 결과",
    group: n => `단계 ${n}개`, groupTook: "합계", groupCount: "실행", groupUnit: "회",
    groupHint: "단계를 누르면 그 단계의 입력·출력이 나와요.",
    idle: "이 요청에서는 실행되지 않았어요.",
    skipIn: v => ["첫 단계 코드 검증 결과 예문 ", v, " → 채울 빈 슬롯이 없음"],
    skipOut: "후속 단계를 실행하지 않고 첫 답이 곧 최종이에요. 공지·팟캐스트 탭 추가 없음.",
    verdict: "판정 ",
    asm: (e, w) => ["표현 ", e, "개 · 예문 ", w, "개로 답을 조립(검증 안 된 표현은 뒤로)"],
    code: "코드 ",
    cand: { q: "학습자 질문 원문", kind: " · 질문 유형 ", status: "요청 판정 ", n: i => `후보 ${i}` },
    search: {
      slotFirst: "후보", slotCont: "답 슬롯", newExpr: "새 표현", policy: "쿼리 방식", key: "핵심 구절 ",
      reason: "판단 LLM이 준 이유", hits: "결과 ", corpus: "건 · 코퍼스 일치 ", unit: "건",
      rawOnlyEx: "결과 원문은 대표 요청(예시)에만 들어 있어요.", usedBy: " 이 결과를 근거로 쓴 단계: ",
      unused: "이 결과는 예문 근거로 쓰이지 않았어요.",
    },
    select: { cand: i => `후보 ${i}`, noRef: "인용 없음", input: "후보 표현 + 직전 검색 결과의 구간(span) 목록", picks: "인용 구간 지정 " },
    verify: {
      input: "선택·수정 결과를 코드가 검사해요(LLM 아님).", locked: "첫 단계 값으로 고정된 슬롯이에요.",
      excluded: n => `기각된 선택 ${n}건`, guard: n => `가드로 유지 ${n}건`, verified: "검증 예문 ",
    },
    judgeD: {
      slotNew: "새 표현", slot: n => `슬롯 ${n}`, reason: t => `이유: ${t}`, prev: "직전 검증 상태 ",
      budget: "남은 예산 안에서 search · repick · replace 중 고르기", actSum: "행동 요약", raw: "모델 판단 원문 (영어)",
    },
    revise: {
      slot: n => `슬롯 ${n}`, newSearch: "새로 검색", prev: "직전 검증 ",
      rule: t => `예문 없는 슬롯이 남아 있고 라운드 ${t} ≤ 3 → 코드가 수정 LLM을 호출`,
    },
    act: {
      picked: (a, slot) => ["판단 LLM이 고른 ", a, ` · 슬롯 ${slot}`],
      lockNoop: "먼저 보낸 검증 예문이라 적용하지 않음(noop)", lockFoot: "시간·토큰을 쓰지 않는 코드 단계예요.",
      ref: "근거 구간 ",
    },
  },
};

/* ======================================================================= 中文 */
const ZH = {
  tab: {
    loading: "正在加载步骤记录（trace）…",
    title: "执行图 — 一次请求经过了哪些组件",
    lead: "上方是组件路线图（在固定模板上只加深实际走过的路径），下方是各泳道的时间流。" +
      "点击节点或条形，旁边（窄屏时在路线图下方）会显示输入、输出和判断理由，节点与条形会一起高亮。",
    preLock: ["agent 的判断是加入锁定规则之前的记录", "，因此针对已先发送槽位的操作也按记录原样显示。"],
    srcLabel: "要显示的请求",
    ex: { baseline: "baseline 示例", agent: "agent 示例", skipped: "跳过后续示例", lock: "锁定跳过示例", log: "从日志中选的请求" },
    exNone: "· 无",
    logTip: "在请求日志中选择一行，然后点击“在执行图中查看”",
    pickLabel: "打开其他请求",
    opt: (x, st) => `${x.task_id} 第 ${x.attempt} 次 · ${x.mode} · ${st} · ${x.continuation === "skipped" ? "跳过 · " : ""}` +
      String(x.question || "").slice(0, 26),
    exPair: (task, n, vf, m1, a1, m2, a2) => ["两个示例的问题和第一阶段记录相同（任务 ", task,
      `，第 ${n} 次），只是后续路径不同。第一阶段验证 ${vf} 个 → ${m1} 追加 ${a1} 个 · ${m2} 追加 ${a2} 个。`],
    exSkip: vf => `第一阶段验证 ${vf}/3 → 不执行后续阶段，直接完成。`,
    exSkipPre: " 这是锁定前的记录，agent 没有跳过示例，因此显示 baseline 请求。",
    noReq: "没有可显示的请求。",
    noTrace: "此请求没有步骤记录。",
    sum: {
      task: "评测记录 ", attempt: n => ` · 第 ${n} 次`, first: "首次响应 ", total: "总计 ", tok: "令牌 ", calls: " 次 · 检索 ",
      times: " 次", ex: "例句 ", preFv: list => `锁定前记录 · 先发送的槽位 ${list}`,
    },
    routeTitle: "组件路线图", routeSub: "固定模板上的实际路径 · 未走的路径为虚线 · 点击节点查看详情",
    legend: "图例", routeRegion: "组件路线图（可横向滚动）",
    scrollHint: "路线图比屏幕宽 · 横向滑动查看后续阶段",
    detailLabel: "所选步骤详情",
    swimTitle: "泳道 · 各泳道耗时", swimSub: "x = 从请求开始经过的时间 · 点击条形会同时高亮详情和路线图节点",
    swimRegion: "泳道瀑布图",
    lg: {
      taken: "已执行的路径", notTaken: "未执行的路径", imm: "即时结果时刻（验证 1~2 个）", done: "立即完成（验证 3 个 · 跳过后续）",
      mid: "第一阶段结束 · 0 个例句（等待）", lockSlot: "锁定槽位（已发送 · 不再修改）", lockAct: "因锁定跳过的操作（noop）",
      skipped: "已跳过", rule: "代码规则", llm: "LLM 判断",
      first: "首次响应时刻", turn: "轮次 · 回合边界", dia: "0 秒验证（槽位数）", sq: "0 秒工具应用（代码）",
      zone: "跳过后续（未执行，宽度仅为示意）", link: "判断 → 工具调用",
    },
    kindShort: {
      request: "输入", llm: "LLM", judge: "判断", search: "检索", verify: "验证", act: "工具", assemble: "组装", decline: "拒绝",
    },
    notRun: "未执行", error: "错误", ariaSkip: "，未执行", ariaErr: "，错误", ariaTok: t => `，令牌 ${t}`,
    node: {
      req: "问题", cand: "生成候选", decl: "拒绝判定", srch: n => `检索工具 ×${n}`, sel1: "选择例句", val1: "代码验证",
      rev: "提出修改", bsrch: "追加检索", bsel: "选择例句", val: "代码验证", judge: k => `判断 · 第 ${k} 回合`, judge0: "判断",
      final: "最终选择", tools: "工具操作", asm: "组装 · 响应", asmSkip: "响应 · 立即完成",
    },
    meta: {
      attempt: n => `第 ${n} 次`, verdict: "判定 ", cand: (n, t) => `候选 ${n} 个 · ${t}`, declYes: "超出范围 → 结束", declIf: "若超出范围",
      lit: n => `语料匹配 ${n}`, litTip: "关键短语原样出现在语料中时为“语料匹配”",
      fb: n => `替代检索 ${n}`, fbTip: "语料中没有关键短语，改用语义检索",
      picks: (a, b, t) => `引用 ${a}/${b} · ${t}`, picks2: (a, b) => `引用 ${a}/${b}`, repl: (n, t) => `替换 ${n} 个 · ${t}`,
      searchN: n => `${n} 次`, reuse: "复用已有片段时跳过", reuseTip: "修改建议若指向已找到的引用片段（ref），则不检索直接采用",
      noAct: "无操作", finalIf: "3 回合都继续 + 第 3 回合有检索时", finalTip: "仅当 3 回合都未 finish 结束且第 3 回合执行了检索时运行",
      errOf: "错误 ", toEnd: " → 结束", toNext: " → 继续",
      asmEx: (e, w) => `表达 ${e} · 例句 ${w}`, added: n => `（追加 ${n}）`, done: t => `完成 ${t}`,
      errFirst: "返回错误提示", keepFirst: "保留先发送的答案",
      lock: list => `锁定 ${list}`, lockTip: "第一阶段已验证并发送给学习者的槽位 · 后续不再修改",
      judgeLockTip: "放入判断输入的锁定槽位", lostN: n => `已发送的例句有 ${n} 个被替换`,
      lostTip: "锁定前记录：先发送的已验证例句从最终答案中消失",
      slotLock: n => `s${n} 锁定（第一阶段已验证 · 已发送）`, slotV: n => `s${n} 已验证`, slotEmpty: n => `s${n} 空位`,
      slotsAria: (v, n, lk) => `验证 ${v}/${n}${lk ? "，锁定 " + lk : ""}`, skipped: t => `${t} 已跳过`,
    },
    lane: {
      loopB: " · 修改循环", loopA: " · 判断循环", ruleB: "由代码规则决定下一步", ruleA: "由 LLM 决定下一步操作",
      count: (n, b) => `${n}/3 ${b ? "轮" : "回合"}`, other: m => `此请求为 ${m} 模式 · 未执行`,
      contSkip: vf => `跳过后续 · 验证 ${vf}/3`, noCont: why => `无后续 · ${why}`, declined: "已拒绝", errFirst: "第一阶段错误",
      endFirst: "在第一阶段结束", preLock: "锁定前记录", fold: "折叠轮次", unfold: "展开轮次",
      skipRow: vf => `跳过后续阶段 — 第一阶段验证 ${vf}/3 · 不发通知，直接以第一阶段答案完成`,
      rowName: (final, b, k) => (final ? "最终选择（pick_final）" : b ? `第 ${k} 轮` : `第 ${k} 回合`),
      notRun: (name, why) => `${name} — 未执行 · ${why}`, end: "结束原因：",
      whyOther: m => `此请求为 ${m} 模式，未执行此循环。`,
    },
    phase: {
      first: "第一阶段", firstSub: " · 两种模式共用 · ", cont: "后续阶段", only: " 专用", fill: "只填补空位",
      skip: vf => `跳过 · 验证 ${vf}/3`,
      decl: t => `拒绝 · 于 ${t} 结束`, err: t => `第一阶段错误 · ${t}`, done: (t, vf) => `立即完成 ${t} · 验证 ${vf}/3`,
      mid: t => `第一阶段结束 ${t} · 0 个例句 → 等待`, midTip: "第一阶段验证例句为 0：不显示未确认的候选，等待最终结果",
      imm: (t, vf) => `即时结果 ${t} · 先发送 ${vf} 个已验证`,
    },
    swim: {
      who: "学习者界面", seg: "阶段", time: "时间", segFirst: "第一阶段", segSkip: "跳过后续 · 未执行",
      turn: (a, t) => (t === FINAL ? "最终选择" : a ? `第 ${t} 回合` : `第 ${t} 轮`),
      turnShort: (a, t) => (t === FINAL ? "F" : `${a ? "T" : "R"}${t}`),
      empty: "未执行", emptyDecl: "拒绝路径 · 未执行", emptyEnd: why => `未执行 · ${why}`,
      zone: vf => `跳过后续 · 第一阶段验证 ${vf}/3`, zoneShort: "跳过后续",
      tok: (i, o) => ` · 令牌 ${i}/${o}`, errA: " · 错误", lockA: " · 因锁定跳过",
      inst: (skip, t, vf) => `${skip ? "首个结果 = 最终" : "首个结果"} ${t} · 例句 ${vf} 个${skip ? " · 无通知" : ""}`,
      instShort: (skip, t, vf) => `${skip ? "首个=最终" : "首个结果"} ${t} · ${vf} 个`,
      fin: {
        decl: "拒绝提示", errCont: "后续失败 · 保留首个结果", err: "错误提示", once: "最终结果（一次显示）",
        added: n => `播客标签 +${n}`, all: "最终答案", none: "未找到更多 · 通知关闭",
      },
      tick: s => `${s}秒`,
    },
  },
  model: {
    noQuestion: "（无问题原文）",
    rej: {
      unknown_or_reused_ref: "不存在或已使用的片段", explanation_missing: "缺少说明",
      reusable_wording_not_in_span: "可复用措辞不在片段中", wording_lacks_key_phrase: "措辞缺少关键短语",
    },
    outcome: {
      verified: "验证通过", removed: "例句已移除", replaced: "表达已重写（例句在下一回合）",
      kept_verified_example: "保留已验证例句（保护）",
    },
    rejected: x => `驳回 · ${x}`,
    smode: { literal: "文字匹配", semantic_fallback: "语义检索（替代）", semantic: "语义检索" },
    err: {
      search_unavailable: "检索工具无响应", model_unavailable: "模型无响应",
      invalid_model_output: "模型输出格式错误", model_output_truncated: "模型输出被截断", model_refused: "模型拒绝",
      corpus_not_ready: "语料尚未就绪",
    },
    noCode: "无代码",
    corpus: n => `语料匹配 ${n} 条`,
    slotCand: n => `候选 ${n}`, slotNew: "新表达", slot: n => `槽位 ${n}`,
    slotNoEx: n => `槽位 #${n} 无例句`, slotTag: n => `槽位 #${n}`,
    tagFixed: " 锁定", tagChanged: " 已改", tagSent: " 先发送",
    firstSlotHit: "针对先发送的槽位", lockViolation: "这是违反锁定规则的记录。", wouldNoop: "若有锁定，此操作会被跳过（noop）。",
    judgeLocked: "已作为锁定槽位放入判断输入。", preLock: "锁定前记录",
    judgeUnaware: list => `此判断不知道先发送的槽位 ${list}。`,
    prevExpr: "之前的表达", newExpr: "→ 新表达", expr: "表达",
    why: "为何这样判断", whyNone: "未记录判断原文。", whyFirst: "为何这样判断 · 判断原文第一句",
    verb: {
      searchNew: "检索新表达", search: n => `检索槽位 ${n}`, replace: n => `重写槽位 ${n} 的表达`,
      repick: n => `重新选择槽位 ${n} 的例句`,
    },
    act: {
      missing: list => `上一次验证中槽位 ${list} 没有例句。`, allOk: "上一次验证确认 3 个槽位都有例句。",
      hit: (n, locked) => ` 其中 ${n} 个针对先发送的槽位（${locked ? "因锁定跳过" : "若有锁定则跳过"}）。`,
      picked: (n, list, hit) => `选择了 ${n} 个操作（${list}）。${hit}`, none: "没有选择更多操作。",
      final: "3 回合已用完，以最终选择收尾。", finish: "判断在此结束（finish=true）。",
      next: "查看结果后在下一回合再判断（finish=false）。",
    },
    end: {
      declined: "判定拒绝 → 直接组装", error: (code, stage) => `因错误中断 · ${code} @ ${stage}`,
      skipped: n => `第一阶段验证 ${n}/3 → 跳过后续阶段`, noLoop: "无修改循环",
      allV: n => `第 ${n} 轮验证 3/3 → 结束`, roundsOut: "3 轮已用完 → 结束", noRep: "没有新的替换表达 → 结束",
      turnsFinal: "3 回合已用完 → 最终选择后结束", finish: n => `第 ${n} 回合 finish=true（模型判断结束）`,
      turnsOut: "3 回合已用完 → 结束", done: "结束",
    },
    rowWhy: {
      declined: "已拒绝，无后续", error: "因错误中断", skipped: n => `验证 ${n}/3 → 跳过后续`,
      prev3: "上一次验证已确认 3/3", noRep: "没有新的替换表达", finish: n => `第 ${n} 回合 finish=true`,
      noSearch: "第 3 回合没有检索，已跳过", earlier: "已在之前的回合结束",
    },
    lane: {
      cand: "候选 LLM", search: "检索工具", select: "选择 LLM", judgeA: "决策 LLM · 工具应用", judgeB: "修改 LLM",
      verify: "代码验证", asm: "组装 · 响应",
    },
    sum: {
      error: c => `因错误中断：${c}`, locked: "锁定槽位，已跳过（锁定规则）",
      contSkip: "第一阶段 3 个全部验证，跳过后续阶段", noop: x => `操作无变化，已跳过（${x}）`,
      skipped: x => `已跳过（${x}）`, candDecl: st => `请求判定：${st} → 拒绝路径`,
      cand: (n, k) => `生成候选表达 ${n} 个（类型 ${k}）`, decl: st => `返回拒绝提示（${st}）`,
      search: (first, slot, kp, hits, cc, mode) =>
        `${first ? "候选检索" : "追加检索"}${slot != null ? ` 槽位 ${slot}` : ""} '${kp}'：结果 ${hits} 条，语料匹配 ${cc} 条（${mode}）`,
      verify: (v, n, rej, guard, noops) => `代码验证：已验证例句 ${v}/${n}` + (rej ? `，驳回 ${rej} 条` : "") +
        (guard ? `，保护 ${guard} 条` : "") + (noops ? `，跳过操作 ${noops} 个` : ""),
      sel1: (n, r) => `选择例句：${n} 个候选中 ${r} 个指定了引用片段`, sel: (n, r) => `为 ${n} 个替换表达选择例句（${r} 个指定引用）`,
      revise: (n, r) => `为未验证槽位提出 ${n} 个替换表达` + (r ? `（直接指定已有片段 ${r} 个）` : ""),
      noAct: "无操作", final: w => `最终选择调用：${w}`, judge: (w, fin) => `Agent 判断：${w} → ${fin ? "结束" : "继续"}`,
      repick: (s, o) => `重新选择槽位 ${s} 的例句 → ${o}`, replace: (s, e, o) => `替换槽位 ${s} 的表达 '${e}' → ${o}`,
      noResult: "无结果",
      asm: (e, w) => `组成最终答案：表达 ${e} 个，例句 ${w} 个`, budget: c => `预算耗尽（${c}）→ 以当前草稿收尾`,
    },
  },
  detail: {
    pick: "选择节点或条形即可查看详情。",
    back: t => `返回 ${t} 全部`,
    req: "问题", input: "输入", mode: "适用模式", task: "评测任务", attempt: "次序", attemptUnit: "", category: "分类",
    langExpect: "语言 · 预期", expDecline: "拒绝", expAnswer: "回答", reqId: "请求 ID",
    resp: "组装 · 响应", firstResp: "首次响应", total: "总计", sec: "秒", examples: "例句", tokens: "令牌", cont: "后续",
    judge: "评审", noAnswer: "没有发送的答案文本（拒绝或错误）。", finalSlots: "最终答案（按槽位顺序）",
    asmSpans: "组装步骤记录",
    first: "第一阶段", contPhase: "后续阶段", turn: n => `第 ${n} 回合`, round: n => `第 ${n} 轮`, final: "最终",
    start: "开始", took: "耗时", tokIn: "输入令牌", tokOut: "输出令牌", model: "模型",
    inSum: "输入摘要", outJudge: "输出 · 判断理由", outRes: "输出 · 结果",
    group: n => `${n} 个步骤`, groupTook: "合计", groupCount: "执行", groupUnit: "次",
    groupHint: "点击步骤可查看该步骤的输入和输出。",
    idle: "此请求中未执行该步骤。",
    skipIn: v => ["第一阶段代码验证的例句 ", v, " → 没有需要填补的空位"],
    skipOut: "未执行后续阶段，首个答案即最终答案。没有通知，也没有新增播客标签。",
    verdict: "判定 ",
    asm: (e, w) => ["用 ", e, " 个表达 · ", w, " 个例句组装答案（未验证的表达排在后面）"],
    code: "代码 ",
    cand: { q: "学习者问题原文", kind: " · 问题类型 ", status: "请求判定 ", n: i => `候选 ${i}` },
    search: {
      slotFirst: "候选", slotCont: "答案槽位", newExpr: "新表达", policy: "查询方式", key: "关键短语 ",
      reason: "决策 LLM 给出的理由", hits: "结果 ", corpus: " 条 · 语料匹配 ", unit: " 条",
      rawOnlyEx: "只有代表请求（示例）包含结果原文。", usedBy: " 引用此结果的步骤：",
      unused: "此结果未被用作例句依据。",
    },
    select: { cand: i => `候选 ${i}`, noRef: "无引用", input: "候选表达 + 上一次检索结果的片段（span）列表", picks: "指定引用片段 " },
    verify: {
      input: "由代码检查选择·修改的结果（不是 LLM）。", locked: "这些槽位固定为第一阶段的值。",
      excluded: n => `驳回的选择 ${n} 条`, guard: n => `因保护保留 ${n} 条`, verified: "已验证例句 ",
    },
    judgeD: {
      slotNew: "新表达", slot: n => `槽位 ${n}`, reason: t => `理由：${t}`, prev: "上一次验证状态 ",
      budget: "在剩余预算内从 search · repick · replace 中选择", actSum: "操作摘要", raw: "模型判断原文（英文）",
    },
    revise: {
      slot: n => `槽位 ${n}`, newSearch: "重新检索", prev: "上一次验证 ",
      rule: t => `仍有没有例句的槽位且第 ${t} 轮 ≤ 3 → 代码调用修改 LLM`,
    },
    act: {
      picked: (a, slot) => ["决策 LLM 选择了 ", a, ` · 槽位 ${slot}`],
      lockNoop: "这是已先发送的验证例句，未应用（noop）", lockFoot: "这是不耗时间和令牌的代码步骤。",
      ref: "依据片段 ",
    },
  },
};

/* ======================================================================= English */
const EN = {
  tab: {
    loading: "Loading step traces…",
    title: "Run graph — which components one request went through",
    lead: "Top: the component route map (a fixed template with only the path actually taken drawn solid). " +
      "Bottom: time flow per lane. Click a node or bar to see its inputs, outputs and reasoning beside the map " +
      "(below it on narrow screens); the node and its bars are highlighted together.",
    preLock: ["Agent decisions come from runs recorded before the lock rule existed",
      ", so actions aimed at already-sent slots are shown as recorded."],
    srcLabel: "Request to show",
    ex: { baseline: "baseline example", agent: "agent example", skipped: "skipped follow-up", lock: "lock-skip example", log: "picked in log" },
    exNone: "· none",
    logTip: "Pick a row in the request log and press “View in run graph”",
    pickLabel: "Open another request",
    opt: (x, st) => `${x.task_id} run ${x.attempt} · ${x.mode} · ${st} · ${x.continuation === "skipped" ? "skipped · " : ""}` +
      String(x.question || "").slice(0, 26),
    exPair: (task, n, vf, m1, a1, m2, a2) => ["Both examples share the question and the first-stage record (task ", task,
      `, run ${n}); only the follow-up path differs. First stage verified ${vf} → ${m1} added ${a1} · ${m2} added ${a2}.`],
    exSkip: vf => `${vf}/3 verified in the first stage → done right away without the follow-up stage.`,
    exSkipPre: " These are pre-lock records, so agent has no skipped example; a baseline request is shown instead.",
    noReq: "No request to show.",
    noTrace: "No step trace for this request.",
    sum: {
      task: "Eval record ", attempt: n => ` · run ${n}`, first: "First response ", total: "Total ", tok: "Tokens ",
      calls: " calls · searches ", times: "", ex: "Examples ", preFv: list => `Pre-lock record · sent-first slots ${list}`,
    },
    routeTitle: "Component route map", routeSub: "Actual path on a fixed template · paths not taken are dashed · click a node for details",
    legend: "Legend", routeRegion: "Component route map (scrolls sideways)",
    scrollHint: "The route map is wider than the screen · scroll sideways to see the follow-up stage",
    detailLabel: "Selected step details",
    swimTitle: "Swimlanes · time per lane",
    swimSub: "x = time since the request started · click a bar to highlight its details and route-map node",
    swimRegion: "Swimlane waterfall",
    lg: {
      taken: "Path taken", notTaken: "Path not taken", imm: "Instant result (1–2 verified)",
      done: "Done at once (3 verified · follow-up skipped)", mid: "First stage ends · 0 examples (waiting)",
      lockSlot: "Locked slot (already sent · not changed)", lockAct: "Action skipped by lock (noop)",
      skipped: "skipped", rule: "Code rule", llm: "LLM decision",
      first: "First response", turn: "Round · turn boundary", dia: "0 s check (slot count)", sq: "0 s tool apply (code)",
      zone: "Follow-up skipped (not run; width is only visual)", link: "Decision → tool call",
    },
    kindShort: {
      request: "Input", llm: "LLM", judge: "Decide", search: "Search", verify: "Check", act: "Tool", assemble: "Assemble",
      decline: "Decline",
    },
    notRun: "Not run", error: "Error", ariaSkip: ", not run", ariaErr: ", error", ariaTok: t => `, ${t} tokens`,
    node: {
      req: "Question", cand: "Generate candidates", decl: "Decline check", srch: n => `Search tool ×${n}`, sel1: "Pick examples",
      val1: "Code check", rev: "Suggest fixes", bsrch: "Extra search", bsel: "Pick examples", val: "Code check",
      judge: k => `Decide · turn ${k}`, judge0: "Decide", final: "Final pick", tools: "Tool actions", asm: "Assemble · respond",
      asmSkip: "Respond · done at once",
    },
    meta: {
      attempt: n => `run ${n}`, verdict: "Verdict ", cand: (n, t) => `${pl(n, "candidate")} · ${t}`,
      declYes: "Out of scope → end", declIf: "If out of scope",
      lit: n => `corpus match ${n}`, litTip: "“Corpus match” means the key phrase appears verbatim in the corpus",
      fb: n => `fallback ${n}`, fbTip: "Key phrase not in the corpus, so semantic search was used instead",
      picks: (a, b, t) => `cited ${a}/${b} · ${t}`, picks2: (a, b) => `cited ${a}/${b}`,
      repl: (n, t) => `${pl(n, "replacement")} · ${t}`,
      searchN: n => `${n}×`, reuse: "Skipped when a found span is reused",
      reuseTip: "If a suggested fix points at a span (ref) that was already found, it is adopted without a new search",
      noAct: "No actions", finalIf: "Only if all 3 turns continue + turn 3 searched",
      finalTip: "Runs only when all 3 turns end without finish and turn 3 ran a search",
      errOf: "Error ", toEnd: " → end", toNext: " → continue",
      asmEx: (e, w) => `expressions ${e} · examples ${w}`, added: n => ` (+${n} added)`, done: t => `done ${t}`,
      errFirst: "Returns an error notice", keepFirst: "Keeps the answer sent first",
      lock: list => `locked ${list}`, lockTip: "Slot verified in the first stage and already sent to the learner · not changed later",
      judgeLockTip: "Locked slots passed into the decision input", lostN: n => `${pl(n, "sent example")} changed`,
      lostTip: "Pre-lock record: an example verified and sent first was dropped from the final answer",
      slotLock: n => `s${n} locked (verified in first stage · already sent)`, slotV: n => `s${n} verified`,
      slotEmpty: n => `s${n} empty`,
      slotsAria: (v, n, lk) => `verified ${v}/${n}${lk ? ", locked " + lk : ""}`, skipped: t => `${t} skipped`,
    },
    lane: {
      loopB: " · revise loop", loopA: " · decision loop", ruleB: "A code rule picks the next step", ruleA: "The LLM picks the next action",
      count: (n, b) => `${n}/3 ${b ? "rounds" : "turns"}`, other: m => `This request ran in ${m} mode · not run`,
      contSkip: vf => `Follow-up skipped · verified ${vf}/3`, noCont: why => `No follow-up · ${why}`, declined: "declined",
      errFirst: "first-stage error", endFirst: "ended in the first stage", preLock: "Pre-lock record",
      fold: "Collapse rounds", unfold: "Expand rounds",
      skipRow: vf => `Follow-up stage skipped — ${vf}/3 verified in the first stage · done with the first answer, no notice`,
      rowName: (final, b, k) => (final ? "Final pick (pick_final)" : b ? `Round ${k}` : `Turn ${k}`),
      notRun: (name, why) => `${name} — not run · ${why}`, end: "Why it ended: ",
      whyOther: m => `This request ran in ${m} mode, so this loop did not run.`,
    },
    phase: {
      first: "First stage", firstSub: " · shared by both modes · ", cont: "Follow-up stage", only: " only",
      fill: "fills empty slots only",
      skip: vf => `skipped · verified ${vf}/3`,
      decl: t => `declined · ended at ${t}`, err: t => `first-stage error · ${t}`, done: (t, vf) => `done at once ${t} · verified ${vf}/3`,
      mid: t => `first stage ends ${t} · 0 examples → wait`,
      midTip: "0 verified examples in the first stage: unverified candidates stay hidden until the final answer",
      imm: (t, vf) => `instant result ${t} · ${vf} verified sent first`,
    },
    swim: {
      who: "Learner view", seg: "Phase", time: "Time", segFirst: "First stage", segSkip: "Follow-up skipped · not run",
      turn: (a, t) => (t === FINAL ? "Final pick" : `${a ? "Turn" : "Round"} ${t}`),
      turnShort: (a, t) => (t === FINAL ? "F" : `${a ? "T" : "R"}${t}`),
      empty: "Not run", emptyDecl: "Decline path · not run", emptyEnd: why => `Not run · ${why}`,
      zone: vf => `Follow-up skipped · ${vf}/3 verified in first stage`, zoneShort: "Follow-up skipped",
      tok: (i, o) => ` · tokens ${i}/${o}`, errA: " · error", lockA: " · skipped by lock",
      inst: (skip, t, vf) => `${skip ? "First result = final" : "First result"} ${t} · ${pl(vf, "example")}` +
        (skip ? " · no notice" : ""),
      instShort: (skip, t, vf) => `${skip ? "First = final" : "First"} ${t} · ${vf}`,
      fin: {
        decl: "Decline notice", errCont: "Follow-up failed · first result kept", err: "Error notice",
        once: "Final result (all at once)", added: n => `Podcast tab +${n}`, all: "Final answer",
        none: "Nothing more found · notice closed",
      },
      tick: s => `${s}s`,
    },
  },
  model: {
    noQuestion: "(no question text)",
    rej: {
      unknown_or_reused_ref: "unknown or already-used span", explanation_missing: "explanation missing",
      reusable_wording_not_in_span: "reusable wording not in the span", wording_lacks_key_phrase: "wording lacks the key phrase",
    },
    outcome: {
      verified: "verified", removed: "example removed", replaced: "expression rewritten (example next turn)",
      kept_verified_example: "kept the verified example (guard)",
    },
    rejected: x => `rejected · ${x}`,
    smode: { literal: "exact match", semantic_fallback: "semantic search (fallback)", semantic: "semantic search" },
    err: {
      search_unavailable: "search tool did not respond", model_unavailable: "model did not respond",
      invalid_model_output: "invalid model output format", model_output_truncated: "model output was cut off",
      model_refused: "model refused", corpus_not_ready: "corpus not ready",
    },
    noCode: "no code",
    corpus: n => `corpus matches ${n}`,
    slotCand: n => `candidate ${n}`, slotNew: "new expression", slot: n => `slot ${n}`,
    slotNoEx: n => `slot #${n} no example`, slotTag: n => `slot #${n}`,
    tagFixed: " locked", tagChanged: " changed", tagSent: " sent first",
    firstSlotHit: "targets a sent-first slot", lockViolation: "This is a lock-violation record.",
    wouldNoop: "With the lock, this action would have been skipped (noop).",
    judgeLocked: "Passed into the decision input as locked slots.", preLock: "Pre-lock record",
    judgeUnaware: list => `This decision was made without knowing about sent-first slots ${list}.`,
    prevExpr: "Previous expression", newExpr: "→ new expression", expr: "Expression",
    why: "Why this decision", whyNone: "The reasoning text was not recorded.",
    whyFirst: "Why this decision · first sentence of the reasoning",
    verb: {
      searchNew: "search a new expression", search: n => `search slot ${n}`, replace: n => `rewrite slot ${n}`,
      repick: n => `re-pick the slot ${n} example`,
    },
    act: {
      missing: list => `The previous check found no example for slot ${list}.`,
      allOk: "The previous check confirmed examples for all 3 slots.",
      hit: (n, locked) => ` ${n} of them target sent-first slots (${locked ? "skipped by lock" : "would be skipped under the lock"}).`,
      picked: (n, list, hit) => `Picked ${pl(n, "action")} (${list}).${hit}`, none: "No further actions picked.",
      final: "All 3 turns used, so it wraps up with the final pick.", finish: "Decided to stop here (finish=true).",
      next: "Checks the result and decides again next turn (finish=false).",
    },
    end: {
      declined: "Declined → assemble right away", error: (code, stage) => `Stopped by error · ${code} @ ${stage}`,
      skipped: n => `${n}/3 verified in the first stage → follow-up skipped`, noLoop: "No revise loop",
      allV: n => `3/3 verified in round ${n} → end`, roundsOut: "3 rounds used → end", noRep: "No new replacement → end",
      turnsFinal: "3 turns used → final pick, then end", finish: n => `finish=true at turn ${n} (the model chose to stop)`,
      turnsOut: "3 turns used → end", done: "End",
    },
    rowWhy: {
      declined: "declined, no follow-up", error: "stopped by error", skipped: n => `verified ${n}/3 → follow-up skipped`,
      prev3: "previous check confirmed 3/3", noRep: "no new replacement", finish: n => `finish=true at turn ${n}`,
      noSearch: "skipped: no search in turn 3", earlier: "ended in an earlier turn",
    },
    lane: {
      cand: "Candidate LLM", search: "Search tool", select: "Select LLM", judgeA: "Decision LLM · tool apply",
      judgeB: "Revise LLM", verify: "Code check", asm: "Assemble · respond",
    },
    sum: {
      error: c => `Stopped by error: ${c}`, locked: "Skipped: locked slot (lock rule)",
      contSkip: "All 3 verified in the first stage, so the follow-up stage was skipped",
      noop: x => `Skipped: the action changes nothing (${x})`, skipped: x => `Skipped (${x})`,
      candDecl: st => `Request verdict: ${st} → decline path`,
      cand: (n, k) => `Generated ${pl(n, "candidate expression")} (type ${k})`, decl: st => `Returned a decline notice (${st})`,
      search: (first, slot, kp, hits, cc, mode) =>
        `${first ? "Candidate search" : "Extra search"}${slot != null ? ` slot ${slot}` : ""} '${kp}': ` +
        `${pl(hits, "hit")}, ${pl(cc, "corpus match", "corpus matches")} (${mode})`,
      verify: (v, n, rej, guard, noops) => `Code check: ${v}/${n} examples verified` + (rej ? `, ${rej} rejected` : "") +
        (guard ? `, ${guard} kept by guard` : "") + (noops ? `, ${pl(noops, "action")} skipped` : ""),
      sel1: (n, r) => `Example pick: cited spans for ${r} of ${pl(n, "candidate")}`,
      sel: (n, r) => `Picked examples for ${pl(n, "replacement")} (${r} cited)`,
      revise: (n, r) => `Suggested ${pl(n, "replacement")} for unverified slots` +
        (r ? ` (${r} pointing straight at a found span)` : ""),
      noAct: "no actions", final: w => `Final pick call: ${w}`, judge: (w, fin) => `Agent decision: ${w} → ${fin ? "stop" : "continue"}`,
      repick: (s, o) => `Re-picked the slot ${s} example → ${o}`, replace: (s, e, o) => `Rewrote slot ${s} as '${e}' → ${o}`,
      noResult: "no result",
      asm: (e, w) => `Final answer: ${pl(e, "expression")}, ${pl(w, "example")}`,
      budget: c => `Budget exhausted (${c}) → finished with the current draft`,
    },
  },
  detail: {
    pick: "Select a node or bar to see its details.",
    back: t => `Back to all of ${t}`,
    req: "Question", input: "Input", mode: "Mode", task: "Eval task", attempt: "Run", attemptUnit: "", category: "Category",
    langExpect: "Language · expected", expDecline: "decline", expAnswer: "answer", reqId: "Request ID",
    resp: "Assemble · respond", firstResp: "First response", total: "Total", sec: "s", examples: "Examples", tokens: "Tokens",
    cont: "Follow-up", judge: "Judge", noAnswer: "No answer text was sent (declined or error).",
    finalSlots: "Final answer (slot order)", asmSpans: "Assemble step records",
    first: "first stage", contPhase: "follow-up stage", turn: n => `turn ${n}`, round: n => `round ${n}`, final: "final",
    start: "Start", took: "Took", tokIn: "Input tokens", tokOut: "Output tokens", model: "Model",
    inSum: "Input summary", outJudge: "Output · reasoning", outRes: "Output · result",
    group: n => pl(n, "step"), groupTook: "Total", groupCount: "Runs", groupUnit: "",
    groupHint: "Click a step to see its inputs and outputs.",
    idle: "This step did not run for this request.",
    skipIn: v => ["First-stage code check: examples ", v, " → no empty slot to fill"],
    skipOut: "The follow-up stage did not run; the first answer is final. No notice, no podcast tab additions.",
    verdict: "Verdict ",
    asm: (e, w) => ["Assembled the answer from ", e, ` expression${s_(e)} · `, w, ` example${s_(w)} (unverified expressions go last)`],
    code: "Code ",
    cand: { q: "Learner's original question", kind: " · question type ", status: "Request verdict ", n: i => `candidate ${i}` },
    search: {
      slotFirst: "Candidate", slotCont: "Answer slot", newExpr: "new expression", policy: "Query policy", key: "Key phrase ",
      reason: "Reason given by the decision LLM", hits: "results ", corpus: " · corpus matches ", unit: "",
      rawOnlyEx: "Raw results are only included for the representative (example) requests.",
      usedBy: " Steps that cited these results: ", unused: "These results were not cited as example evidence.",
    },
    select: {
      cand: i => `candidate ${i}`, noRef: "no citation", input: "Candidate expressions + the span list from the previous search",
      picks: "Cited spans ",
    },
    verify: {
      input: "Code checks the select/revise output (not an LLM).", locked: "These slots are locked to their first-stage values.",
      excluded: n => `${pl(n, "rejected pick")}`, guard: n => `${n} kept by guard`, verified: "Verified examples ",
    },
    judgeD: {
      slotNew: "new expression", slot: n => `slot ${n}`, reason: t => `Reason: ${t}`, prev: "Previous check ",
      budget: "Chooses among search · repick · replace within the remaining budget", actSum: "Action summary",
      raw: "Model reasoning (English)",
    },
    revise: {
      slot: n => `slot ${n}`, newSearch: "new search", prev: "Previous check ",
      rule: t => `Slots without examples remain and round ${t} ≤ 3 → code calls the revise LLM`,
    },
    act: {
      picked: (a, slot) => ["The decision LLM picked ", a, ` · slot ${slot}`],
      lockNoop: "Not applied: this verified example was already sent (noop)", lockFoot: "A code step that uses no time or tokens.",
      ref: "Evidence span ",
    },
  },
};

/* ---------- i18n.js 사전에 등록(키 = graph.<경로>) ---------- */
const DICTS = { ko: KO, zh: ZH, en: EN };
const isPlain = v => v != null && typeof v === "object" && !Array.isArray(v);
const flat = (o, pre, out = {}) => {
  for (const [k, v] of Object.entries(o)) {
    if (isPlain(v)) flat(v, `${pre}${k}.`, out);
    else out[pre + k] = v;
  }
  return out;
};
register({ ko: flat(KO, "graph."), zh: flat(ZH, "graph."), en: flat(EN, "graph.") });

/* ---------- 언어 보기: gtext("tab").node.req → 읽는 순간의 언어 값(없으면 ko 값 + 빠짐 기록) ---------- */
const dig = (o, path) => path.reduce((x, k) => (x != null && Object.hasOwn(x, k) ? x[k] : undefined), o);
export function gtext(...path) {
  return new Proxy({}, {
    get(_, prop) {
      if (typeof prop !== "string") return undefined;
      const p = [...path, prop], cur = lang();
      let v = dig(DICTS[cur] || KO, p);
      if (v === undefined) {
        v = dig(KO, p);
        if (v !== undefined && !isPlain(v) && window.__i18nMissing) window.__i18nMissing.add(`${cur}:graph.${p.join(".")}`);
      }
      return isPlain(v) ? gtext(...p) : v;
    },
  });
}
