/* 데이터: data.json(어드민 데이터 계약 v1)의 형식 확인, 지연 로드되는 trace, 파생값.
   화면 숫자는 모두 여기 값에서 계산한다(하드코딩 없음). 로더(fetch · schema_version 확인)는 admin.js에 있다. */
import { isNum, isObj, sum } from "./ui.js";
import { fmtNum, onLang, t } from "./i18n.js";

export const MODES = ["baseline", "agent"];
/* new DataError(키, 자리표시 값): 문구는 보여 줄 때(msgOf) 지금 언어로 다시 만든다. 키 대신 문장을 넘겨도 그대로 보인다. */
export class DataError extends Error {
  constructor(key, params = {}) {
    super(t(key, params));
    this.key = key;
    this.params = params;
  }
  get text() {
    return t(this.key, this.params);
  }
}
/* what: 필드 경로 문자열(언어 무관) 또는 [키, 자리표시 값](언어가 바뀌면 다시 번역) */
function check(ok, what) {
  if (!ok) throw new DataError("data.err.contract", { what: Array.isArray(what) ? () => t(...what) : what });
}

/* fetch 결과 → JSON. 네트워크 · HTTP · JSON 오류를 DataError로 바꾼다. */
export async function readJSON(request, url) {
  let res;
  try {
    res = await request;
  } catch {
    throw new DataError("data.err.network", { url });
  }
  if (!res.ok) throw new DataError("data.err.http", { url, status: res.status });
  try {
    return await res.json();
  } catch {
    throw new DataError("data.err.json", { url });
  }
}
export const msgOf = e =>
  e instanceof DataError ? e.text : t("data.err.unexpected", { msg: (e && e.message) || e });

/* ---------- 형식 확인: 화면이 쓰는 필드의 형만 본다(모르는 키는 무시 — 계약 §2) ---------- */
const NUMS = ["attempt", "first_response_ms", "total_ms", "background_ms", "llm_calls", "searches", "added_final",
  "lost_first", "locked_noops"];
const OPTIONAL_NUMS = ["verified_first", "verified_final", "first_stage_ms", "cost_usd"];

export function checkData(d) {
  check(isObj(d.meta.run) && isObj(d.meta.lock) && isObj(d.meta.files), "meta.run · meta.lock · meta.files");
  check(isObj(d.mode) && typeof d.mode.current === "string" && isObj(d.mode.modes), "mode");
  check(Array.isArray(d.requests) && isObj(d.answers) && isObj(d.examples), "requests · answers · examples");
  const split = d.traces === null && /^[\w.-]+\.json$/.test(String(d.meta.files.traces));
  check(split || isObj(d.traces), ["data.what.traces"]);
  d.requests.forEach((r, i) => {
    const at = `requests[${i}]`;
    check(isObj(r) && typeof r.id === "string" && typeof r.task_id === "string", `${at}.id · task_id`);
    check(MODES.includes(r.mode) && ["ok", "declined", "error"].includes(r.status) &&
      ["ran", "skipped", "none"].includes(r.continuation), `${at}.mode · status · continuation`);
    check(NUMS.every(k => isNum(r[k])), ["data.what.nums", { at }]);
    check(isObj(r.tokens) && ["input", "output", "total"].every(k => isNum(r.tokens[k])), `${at}.tokens`);
    check(OPTIONAL_NUMS.every(k => r[k] == null || isNum(r[k])), ["data.what.optNums", { at }]);
    check(r.question == null || typeof r.question === "string", `${at}.question`);
  });
  for (const a of Object.values(d.answers)) {
    check(isObj(a) && Array.isArray(a.first) && Array.isArray(a.final), ["data.what.answers"]);
  }
  if (d.traces) checkTraces(d.traces);
}
function checkTraces(tr) {
  for (const [id, spans] of Object.entries(tr)) {
    check(Array.isArray(spans), `traces[${id}]`);
    for (const s of spans) {
      check(isObj(s) && typeof s.id === "string" && typeof s.stage === "string" && isNum(s.start_ms) &&
        isNum(s.elapsed_ms) && ["first", "continuation"].includes(s.phase) &&
        (s.tokens == null || (isObj(s.tokens) && isNum(s.tokens.total))), ["data.what.spans", { id }]);
    }
  }
}

/* ---------- 상태(setData 뒤에 채워짐; 다른 모듈은 이 이름들을 읽기만 한다) ---------- */
export let D = null; /* data.json 전체 */
export let REQ = new Map(); /* 요청 id → 행 */
export let ST = {}; /* 모드별 묶음(stats) */
export let SIZE = ""; /* "50과제 × 3회 × 2모드 = 300건"(언어가 바뀌면 다시 만든다) */
export let POP = null; /* 최종 시간 비교 모집단: 모드별 후속 실행 단위 수 · 두 모드 공통 단위 수 */
export let DIST = null; /* 첫 단계 검증 분포(평가 단위 기준) */
let IDX = new Map(), UNIT = new Map(), COMMON = new Set();

export const unitKey = r => `${r.task_id}#${r.attempt}`;
export const order = r => IDX.get(r); /* data.json 순서: 과제 파일 순서 → 회차 → baseline 먼저 */
export const pairOf = r => (UNIT.get(unitKey(r)) || []).find(x => x.mode !== r.mode) || null;
/* 첫 결과의 모양: 검증 1~2개 = 먼저 보내고 공지 · 0개 = 끝까지 기다려 한 번에 · 거절/첫 단계 오류 = 예문 없음 */
export const isNotice = r => r.status === "ok" && (r.verified_first === 1 || r.verified_first === 2);
export const isWait0 = r => r.status === "ok" && r.verified_first === 0;
export const noEx = r => r.status === "declined" || (r.status === "error" && r.error_phase !== "continuation");
export const contKey = r => (r.status === "error" && r.error_phase === "continuation" ? "stop" : r.continuation);
export const lockApplied = () => D.meta.lock.applied === true;
/* 잠금 규칙에 어긋나는 기록을 부르는 말: 잠금 적용 기록이면 '잠금 위반', 아니면 '잠금 전 기록' */
export const lockWord = () => t(lockApplied() ? "data.lock.violation" : "data.lock.preLock");
/* 먼저 보냈다가 최종 답에서 빠진 예문(answers.first 중 verified && !in_final) */
export const lostFirst = A => (A ? A.first.filter(f => f.verified && !f.in_final) : []);
export const spansOf = id => (D.traces && D.traces[id]) || [];
export const firstTok = id => sum(spansOf(id).filter(s => s.phase === "first" && s.tokens).map(s => s.tokens.total));
export function firstVerified(spans) {
  const v = spans.find(s => s.stage === "validate_select_1");
  const slots = v && v.detail && Array.isArray(v.detail.slots) ? v.detail.slots : [];
  return slots.filter(x => x.status === "verified").map(x => x.slot);
}

/* ---------- 분리된 trace(data-traces.json): 처음 필요할 때 한 번만 읽는다 ----------
   실패하면 오류를 기억해 두고, '다시 불러오기'(retryTraces)를 누를 때만 다시 요청한다(행마다 404를 반복하지 않게). */
let tracesP = null, tracesErr = null;
export function getTraces() {
  if (D.traces) return Promise.resolve(D.traces);
  if (tracesErr) return Promise.reject(tracesErr);
  const url = D.meta.files.traces;
  tracesP ??= readJSON(fetch(url, { cache: "no-cache" }), url)
    .then(f => {
      check(isObj(f) && isObj(f.traces), ["data.what.tracesIn", { url }]);
      if (f.schema_version !== undefined && f.schema_version !== 1) {
        throw new DataError("data.err.tracesVersion", { url, got: JSON.stringify(f.schema_version) });
      }
      checkTraces(f.traces);
      return (D.traces = f.traces);
    })
    .catch(e => {
      tracesErr = e;
      tracesP = null;
      throw e;
    });
  return tracesP;
}
export const tracesFailed = () => tracesErr != null;
export function retryTraces() {
  tracesErr = null;
}

/* ---------- 파생값 ---------- */
export function setData(d) {
  D = d;
  REQ = new Map(d.requests.map(r => [r.id, r]));
  IDX = new Map(d.requests.map((r, i) => [r, i]));
  UNIT = new Map();
  for (const r of d.requests) {
    const k = unitKey(r);
    if (!UNIT.has(k)) UNIT.set(k, []);
    UNIT.get(k).push(r);
  }
  /* 최종 시간은 두 모드가 모두 후속을 실행한 같은 평가 단위로만 비교한다. 잠금 전 기록은 baseline이 3개 검증 단위를
     생략하고 agent는 실행해서, 모드별 '후속 실행분'을 그대로 비교하면 서로 다른 요청 묶음을 비교하게 된다. */
  const ranUnits = m =>
    new Set(d.requests.filter(r => r.mode === m && r.status === "ok" && r.continuation === "ran").map(unitKey));
  const [b, a] = MODES.map(ranUnits);
  COMMON = new Set([...b].filter(k => a.has(k)));
  POP = { baseline: b.size, agent: a.size, common: COMMON.size };
  POP.same = b.size === COMMON.size && a.size === COMMON.size;
  ST = Object.fromEntries(MODES.map(m => [m, stats(m)]));
  /* 두 모드가 첫 단계를 공유하므로 분포는 평가 단위(과제 × 회차)마다 한 번만 센다 */
  const units = [];
  for (const rows of UNIT.values()) {
    const r = rows.find(x => x.status === "ok" && isNum(x.verified_first));
    if (r) units.push(r.verified_first);
  }
  const count = f => units.filter(f).length;
  DIST = { n: units.length, c3: count(v => v === 3), c12: count(v => v === 1 || v === 2), c0: count(v => v === 0) };
  SIZE = sizeText();
}
function sizeText() {
  const kinds = f => fmtNum(new Set(D.requests.map(f)).size);
  return t("data.size", {
    tasks: kinds(r => r.task_id), runs: kinds(r => r.attempt), modes: kinds(r => r.mode), n: fmtNum(D.requests.length),
  });
}
/* 언어가 바뀌면 문장으로 만든 파생값을 다시 만든다(shell.js의 탭 다시 그리기보다 먼저 등록됨) */
onLang(() => {
  if (D) SIZE = sizeText();
});

function stats(m) {
  const all = D.requests.filter(r => r.mode === m);
  const ok = all.filter(r => r.status === "ok");
  const ran = ok.filter(r => r.continuation === "ran");
  const same = ran.filter(r => COMMON.has(unitKey(r))); /* 두 모드 모두 후속 실행한 같은 단위 */
  const notice = ok.filter(isNotice);
  const lost = all.filter(r => r.lost_first > 0);
  const count = f => all.filter(f).length;
  return {
    all, ok, ran, same, notice, lost,
    graded: count(r => r.passed != null),
    pass: count(r => r.passed === true),
    strictN: count(r => r.strict_passed != null),
    strict: count(r => r.strict_passed === true),
    dcl: count(r => r.status === "declined"),
    err: count(r => r.status === "error"),
    skip: ok.filter(r => r.continuation === "skipped").length,
    lostEx: sum(lost.map(r => r.lost_first)),
    noops: sum(all.map(r => r.locked_noops)),
    cost: sum(all.map(r => r.cost_usd)),
    v3ran: ok.filter(r => r.verified_first === 3 && r.continuation === "ran"),
    first: ok.map(r => r.first_response_ms), /* 첫 응답(D1 가정) · 정상 전체 */
    final: same.map(r => r.total_ms), /* 최종 · 같은 단위 */
    total: ok.map(r => r.total_ms), /* 전체 완료 · 정상 전체(후속 생략 포함) = 계약 aggregates.total_ms */
    bg: notice.map(r => r.background_ms),
    ttok: ok.map(r => r.tokens.total),
    rtok: same.map(r => r.tokens.total),
  };
}
