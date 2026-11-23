/* English Coach 어드민 · 시안 B — 진입점이자 공용 코어(DOM · 형식 · 데이터 · 공용 조각 · 탭 틀 · 시작). 보기는 공개(D4).
   - 같은 폴더의 data.json(계약 v1)을 상대 경로로 읽고, 서버가 있으면 requests.json · mode도 상대 경로로 읽는다.
   - 모듈(빌드 도구 · 외부 라이브러리 없음): i18n.js → admin.js → tab-flags · tab-logs · tab-metrics · tab-graph.
     탭은 render(panel)(처음 열 때 · 언어가 바뀌면 다시)과 선택적인 dyn()(폭 · 글자 크기가 바뀔 때)을 export한다.
     탭 모듈은 admin.js를 되돌아 import한다(순환). 그래서 탭 모듈 맨 위 코드에서는 admin.js 값을 읽지 않는다.
   - 보안: 데이터 문자열은 textContent · setAttribute · DOM API로만 넣는다. 화면 숫자는 모두 data.json 값에서 계산한다.
   - 검수 훅: window.__tabs · __showTab(id) · __setLang(code) · __ready, ?tab= · ?scale= · ?lang=,
     postMessage {type:"font-scale"|"show-tab"}. */
import { HTML_LANG, LANGS, LANG_NAMES, fmtDateTime, fmtNum, lang, onLang, setLang, t, tx } from "./i18n.js";
import * as flags from "./tab-flags.js";
import * as logs from "./tab-logs.js";
import * as metrics from "./tab-metrics.js";
import * as graph from "./tab-graph.js";

/* ---------- DOM ---------- */
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const isObj = v => v != null && typeof v === "object" && !Array.isArray(v);
export const isNum = v => typeof v === "number" && Number.isFinite(v);
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k != null && k !== false && k !== "") el.append(k instanceof Node ? k : String(k));
  }
  return el;
}
/* h("span.chip.ok", { title }, ...자식): 문자열 자식은 텍스트 노드가 된다.
   특수 속성: on = 이벤트 처리기, css = style.setProperty(CSSOM이라 CSP의 인라인 스타일 금지에 걸리지 않음). */
export function h(sel, ...args) {
  const [tag, ...cls] = sel.split("."), el = document.createElement(tag || "div");
  if (cls.length) el.className = cls.join(" ");
  if (isObj(args[0]) && !(args[0] instanceof Node)) {
    for (const [k, v] of Object.entries(args.shift())) {
      if (v == null || v === false) continue;
      if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (k === "css") for (const [p, x] of Object.entries(v)) el.style.setProperty(p, x);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  return add(el, args);
}
export function sv(tag, attrs, ...kids) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, String(v));
  return add(el, kids);
}
export const fill = (el, ...kids) => (el.replaceChildren(), add(el, kids));
/* 아이콘: 24 × 24 경로 문자열 상수(createElementNS로 그림) */
const C = (x, y, r) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0z`;
const RR = (x, y, w, hh, r) =>
  `M${x + r} ${y}h${w - 2 * r}a${r} ${r} 0 0 1 ${r} ${r}v${hh - 2 * r}a${r} ${r} 0 0 1 ${-r} ${r}` +
  `h${2 * r - w}a${r} ${r} 0 0 1 ${-r} ${-r}v${2 * r - hh}a${r} ${r} 0 0 1 ${r} ${-r}z`;
const PATHS = {
  server: RR(4, 4, 16, 6.5, 1.5) + RR(4, 13.5, 16, 6.5, 1.5) + "M7.5 7.25h.01M7.5 16.75h.01M11 7.25h5.5M11 16.75h5.5",
  mic: RR(9, 3, 6, 11, 3) + "M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21", pair: "M4.5 9h13l-3.5-3.5M19.5 15h-13l3.5 3.5",
  list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01", x: "M6.5 6.5l11 11M17.5 6.5l-11 11",
  chart: "M4 20V4M4 20h16M8.5 16v-5M12.5 16V8M16.5 16v-3", check: "M5 12.5l4.5 4.5L19 7.5",
  graph: C(6, 6, 2.5) + C(18, 12, 2.5) + C(6, 18, 2.5) + "M8.3 7.2 15.7 10.8M8.3 16.8l7.4-3.6",
  clock: C(12, 12, 8.5) + "M12 7.5V12l3 2", hour: "M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9",
  alert: "M12 4 2.8 19.5h18.4zM12 10v4.5M12 17.2v.01", ban: C(12, 12, 8.5) + "M6 6l12 12",
  spark: "M12 3.5c.6 3.9 2.6 5.9 6.5 6.5-3.9.6-5.9 2.6-6.5 6.5-.6-3.9-2.6-5.9-6.5-6.5 3.9-.6 5.9-2.6 6.5-6.5z" +
    "M18.5 16.5l.6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9-1.9-.6 1.9-.6z",
  bubble: "M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5h-7l-5 4v-4H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 " +
    "5 4.5zM8.5 10.5h.01M12 10.5h.01M15.5 10.5h.01",
  search: C(11, 11, 6.5) + "M16 16l4.5 4.5", shield: "M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6zM9 12l2 2 4-4",
  tool: "M14.5 5.5a4 4 0 0 0-5 5L4 16l4 4 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-2.5-.5-.5-2.5z",
  box: "M4 8 12 4l8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8", bolt: "M13 3 5 13.5h6L10 21l8-10.5h-6z",
  arrow: "M5 12h14M13 6l6 6-6 6", user: C(12, 8, 3.5) + "M5 20c1-4 4-6 7-6s6 2 7 6",
  gear: C(12, 12, 3) +
    "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1",
  loop: "M4.5 12a7.5 7.5 0 0 1 13-5.1M19.5 12a7.5 7.5 0 0 1-13 5.1M18 3.5v4h-4M6 20.5v-4h4",
  send: "M12 19V5M6 11l6-6 6 6", plus: "M12 5.5v13M5.5 12h13",
  info: C(12, 12, 8.5) + "M12 11v5M12 8h.01", skip: "M4.5 6.5 11 12l-6.5 5.5zM12.5 6.5 19 12l-6.5 5.5z",
  lock: RR(5, 10.5, 14, 10, 2) + "M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3M12 14.5v2",
  globe: C(12, 12, 8.5) +
    "M3.5 12h17M12 3.5c2.4 2.3 3.5 5.2 3.5 8.5s-1.1 6.2-3.5 8.5c-2.4-2.3-3.5-5.2-3.5-8.5s1.1-6.2 3.5-8.5z",
};
const ICON_ATTRS = { viewBox: "0 0 24 24", "aria-hidden": "true", fill: "none", stroke: "currentColor",
  "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round" };
export const icon = (name, cls) =>
  sv("svg", { class: cls ? `ic ${cls}` : "ic", ...ICON_ATTRS }, sv("path", { d: PATHS[name] || "" }));

/* ---------- 숫자 · 형식(지금 화면 언어를 따른다) ---------- */
export const sec = ms => (isNum(ms) ? (ms / 1000).toFixed(1) : "—");
export const secU = ms => (isNum(ms) ? t("unit.sec", { n: sec(ms) }) : "—");
export const fmtN = n => fmtNum(n);
export const fmtK = n => (!isNum(n) ? "—" : n < 1000 ? String(Math.round(n))
  : (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k");
export const pct = (a, b) => (b ? ((a / b) * 100).toFixed(1) : "—");
export const usd = v => (isNum(v) ? "$" + v.toFixed(v < 0.1 ? 4 : 2) : "—");
export const utc = ts => (typeof ts === "string" && ts.length >= 16 ? fmtDateTime(ts) : "—"); /* 언어별 날짜 + 시:분 UTC */
export const shortId = id => String(id).slice(0, 8);
export const sum = a => a.reduce((x, y) => x + (isNum(y) ? y : 0), 0);
/* nearest-rank: evaluation/report.py의 nearest_rank와 같다 — ⌈p/100 × n⌉번째로 작은 값(보간 없음) */
export function nr(arr, p) {
  const a = arr.filter(isNum).sort((x, y) => x - y);
  return a.length ? a[Math.min(a.length, Math.max(1, Math.ceil(+((p / 100) * a.length).toFixed(9)))) - 1] : null;
}
export const NEED = q => Math.round(10 / (1 - q / 100)); /* 퍼센타일이 안정되는 최소 표본 = 10 / (1 − p) */
export const rootPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
export const durOf = a => sum(a.map(s => s.elapsed_ms)); /* 단계 묶음의 소요 시간 · 토큰 합 */
export const tokOf = a => sum(a.filter(s => s.tokens).map(s => s.tokens.total));

/* ---------- 데이터: data.json 형식 확인 · 지연 로드되는 trace · 실제 요청 · 파생값 ---------- */
export const MODES = ["baseline", "agent"], STATUSES = ["ok", "declined", "error"];
const CONTS = ["ran", "skipped", "none"];
/* new DataError(키, 자리표시 값): 문구는 보여 줄 때(msgOf) 지금 언어로 다시 만든다. 키 대신 문장을 넘겨도 그대로 보인다. */
class DataError extends Error {
  constructor(key, params = {}) { super(t(key, params)); Object.assign(this, { key, params }); }
  get text() { return t(this.key, this.params); }
}
/* what: 필드 경로 문자열(언어 무관) 또는 [키, 자리표시 값](언어가 바뀌면 다시 번역) */
function check(ok, what) {
  if (!ok) throw new DataError("data.err.contract", { what: Array.isArray(what) ? () => t(...what) : what });
}
/* fetch 결과 → JSON. 네트워크 · HTTP · JSON 오류를 DataError로 바꾼다. */
async function readJSON(request, url) {
  const res = await request.catch(() => { throw new DataError("data.err.network", { url }); });
  if (!res.ok) throw new DataError("data.err.http", { url, status: res.status });
  return res.json().catch(() => { throw new DataError("data.err.json", { url }); });
}
const msgOf = e => (e instanceof DataError ? e.text : t("data.err.unexpected", { msg: (e && e.message) || e }));
/* 형식 확인: 화면이 쓰는 필드의 형만 본다(모르는 키는 무시 — 계약 §2) */
const NUMS = ["attempt", "first_response_ms", "total_ms", "background_ms", "llm_calls", "searches", "added_final",
  "lost_first", "locked_noops"];
const OPTIONAL_NUMS = ["verified_first", "verified_final", "first_stage_ms", "cost_usd"];
const okAnswers = a => isObj(a) && Array.isArray(a.first) && Array.isArray(a.final);
const okSpan = s => isObj(s) && typeof s.id === "string" && typeof s.stage === "string" && isNum(s.start_ms) &&
  isNum(s.elapsed_ms) && ["first", "continuation"].includes(s.phase) &&
  (s.tokens == null || (isObj(s.tokens) && isNum(s.tokens.total)));
function checkData(d) {
  check(isObj(d.meta.run) && isObj(d.meta.lock) && isObj(d.meta.files), "meta.run · meta.lock · meta.files");
  check(isObj(d.mode) && typeof d.mode.current === "string" && isObj(d.mode.modes), "mode");
  check(Array.isArray(d.requests) && isObj(d.answers) && isObj(d.examples), "requests · answers · examples");
  const split = d.traces === null && /^[\w.-]+\.json$/.test(String(d.meta.files.traces));
  check(split || isObj(d.traces), ["data.what.traces"]);
  d.requests.forEach((r, i) => {
    const at = `requests[${i}]`;
    check(isObj(r) && typeof r.id === "string" && typeof r.task_id === "string", `${at}.id · task_id`);
    check(MODES.includes(r.mode) && STATUSES.includes(r.status) && CONTS.includes(r.continuation),
      `${at}.mode · status · continuation`);
    check(NUMS.every(k => isNum(r[k])), ["data.what.nums", { at }]);
    check(isObj(r.tokens) && ["input", "output", "total"].every(k => isNum(r.tokens[k])), `${at}.tokens`);
    check(OPTIONAL_NUMS.every(k => r[k] == null || isNum(r[k])), ["data.what.optNums", { at }]);
    check(r.question == null || typeof r.question === "string", `${at}.question`);
  });
  for (const a of Object.values(d.answers)) check(okAnswers(a), ["data.what.answers"]);
  if (d.traces) checkTraces(d.traces);
}
function checkTraces(tr) {
  for (const [id, spans] of Object.entries(tr)) {
    check(Array.isArray(spans), `traces[${id}]`);
    for (const s of spans) check(okSpan(s), ["data.what.spans", { id }]);
  }
}
/* 상태(setData 뒤에 채워짐; 다른 모듈은 읽기만 한다): D = data.json 전체 · REQ = 요청 id → 행 · ST = 모드별 묶음 ·
   SIZE = "50과제 × 3회 × 2모드 = 300건"(언어가 바뀌면 다시) · POP = 최종 시간 비교 모집단 · DIST = 첫 단계 검증 분포 */
export let D = null, REQ = new Map(), ST = {}, SIZE = "", POP = null, DIST = null;
let IDX = new Map(), UNIT = new Map(), COMMON = new Set();
const unitKey = r => `${r.task_id}#${r.attempt}`;
export const order = r => IDX.get(r); /* data.json 순서: 과제 파일 순서 → 회차 → baseline 먼저 */
export const pairOf = r => (UNIT.get(unitKey(r)) || []).find(x => x.mode !== r.mode) || null;
/* 첫 결과의 모양: 검증 1~2개 = 먼저 보내고 공지 · 0개 = 끝까지 기다려 한 번에 · 거절/첫 단계 오류 = 예문 없음 */
export const isNotice = r => r.status === "ok" && (r.verified_first === 1 || r.verified_first === 2);
export const isWait0 = r => r.status === "ok" && r.verified_first === 0;
export const noEx = r => r.status === "declined" || (r.status === "error" && r.error_phase !== "continuation");
export const contKey = r => (r.status === "error" && r.error_phase === "continuation" ? "stop" : r.continuation);
/* 잠금 적용 여부: 실제 요청(r.live)은 지금 서버 코드(D1 고정 · 추가만)라 항상 적용, 평가 기록은 meta.lock.applied */
export const lockApplied = r => (r != null && r.live === true) || D.meta.lock.applied === true;
/* 잠금 규칙에 어긋나는 기록을 부르는 말: 잠금 적용 기록이면 '잠금 위반', 아니면 '잠금 전 기록' */
export const lockWord = r => t(lockApplied(r) ? "data.lock.violation" : "data.lock.preLock");
/* 먼저 보냈다가 최종 답에서 빠진 예문(answers.first 중 verified && !in_final) */
export const lostFirst = A => (A ? A.first.filter(f => f.verified && !f.in_final) : []);
export const spansOf = id => LIVE.traces[id] || (D.traces && D.traces[id]) || [];
export const answersOf = id => (D.answers && D.answers[id]) || LIVE.answers[id] || null;
export const firstTok = id => tokOf(spansOf(id).filter(s => s.phase === "first"));
export function firstVerified(spans) {
  const v = spans.find(s => s.stage === "validate_select_1");
  return (v && v.detail && Array.isArray(v.detail.slots) ? v.detail.slots : []).filter(x => x.status === "verified")
    .map(x => x.slot);
}
/* 분리된 trace(data-traces.json): 처음 필요할 때 한 번만 읽는다. 실패하면 오류를 기억해 두고,
   '다시 불러오기'(retryTraces)를 누를 때만 다시 요청한다(행마다 404를 반복하지 않게). */
let tracesP = null, tracesErr = null;
export function getTraces() {
  if (D.traces) return Promise.resolve(D.traces);
  if (tracesErr) return Promise.reject(tracesErr);
  const url = D.meta.files.traces;
  return (tracesP ??= readJSON(fetch(url, { cache: "no-cache" }), url).then(f => {
    check(isObj(f) && isObj(f.traces), ["data.what.tracesIn", { url }]);
    const v = f.schema_version, got = JSON.stringify(v);
    if (v !== undefined && v !== 1) throw new DataError("data.err.tracesVersion", { url, got });
    checkTraces(f.traces);
    return (D.traces = f.traces);
  }).catch(e => { [tracesErr, tracesP] = [e, null]; throw e; }));
}
export const retryTraces = () => void (tracesErr = null);
/* 실제 요청(서버의 requests.json, 상대 경로): 평가 기록과 따로 둔다. 지표 · 모드 비교 탭은 평가 기록(D.requests)만 쓴다.
   실제 요청 행은 REQ에도 넣어 실행 그래프에서 열 수 있게 한다.
   state: idle → loading → ok(기록 켜짐) | off(서버에 DB 없음, enabled=false) | error(API 없음 · 형식 오류) */
export const LIVE = { state: "idle", rows: [], traces: {}, answers: {}, err: null, at: null };
let liveP = null;
export function loadLive(force = false) {
  if (force) liveP = null;
  let token;
  try { token = sessionStorage.getItem("phrase-room-admin.token"); } catch {}
  liveP ??= readJSON(fetch("requests.json?limit=300", { cache: "no-store", headers: token ? {"X-Admin-Token": token} : {} }), "requests.json").then(setLive)
    .catch(e => {
      Object.assign(LIVE, { state: "error", err: e }); liveP = null;
    }).then(() => LIVE);
  if (LIVE.state !== "ok" && LIVE.state !== "off") LIVE.state = "loading";
  return liveP;
}
/* 서버 행을 화면이 쓰는 모양으로: 빠진 숫자는 0(선택 숫자는 null), 모르는 상태는 error, 후속은 none */
function liveRow(r) {
  if (!isObj(r) || !(typeof r.id === "string" || isNum(r.id))) return null;
  const row = { ...r, id: String(r.id), live: true };
  row.task_id = typeof r.task_id === "string" ? r.task_id : ""; row.attempt = isNum(r.attempt) ? r.attempt : 1;
  if (!STATUSES.includes(row.status)) row.status = "error";
  if (!CONTS.includes(row.continuation)) row.continuation = "none";
  for (const k of NUMS) if (!isNum(row[k])) row[k] = 0;
  for (const k of OPTIONAL_NUMS) if (!isNum(row[k])) row[k] = null;
  const tk = isObj(r.tokens) ? r.tokens : {}, n = v => (isNum(v) ? v : 0);
  row.tokens = { input: n(tk.input), output: n(tk.output),
    total: isNum(tk.total) ? tk.total : n(tk.input) + n(tk.output) };
  if (typeof row.question !== "string") row.question = null;
  return row;
}
function setLive(j) {
  check(isObj(j) && (j.requests == null || Array.isArray(j.requests)), "requests.json");
  const got = JSON.stringify(j.schema_version) ?? "—";
  if (j.schema_version !== 1) throw new DataError("data.err.liveVersion", { got });
  for (const r of LIVE.rows) if (REQ.get(r.id) === r) REQ.delete(r.id);
  const on = j.enabled !== false, rows = on ? (j.requests || []).map(liveRow).filter(Boolean) : [];
  const traces = {}, answers = {};
  const entries = o => Object.entries(isObj(o) ? o : {});
  for (const [id, spans] of entries(j.traces)) if (Array.isArray(spans)) traces[id] = spans.filter(okSpan);
  for (const [id, a] of entries(j.answers)) if (okAnswers(a)) answers[id] = a;
  rows.forEach((r, i) => {
    if (!REQ.has(r.id)) REQ.set(r.id, r);
    IDX.set(r, i); /* 기본 정렬 = 서버 순서(최신순) */
  });
  Object.assign(LIVE, { state: on ? "ok" : "off", rows, traces, answers, err: null, at: new Date().toISOString() });
}
function setData(d) {
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
  const [b, a] = MODES.map(m =>
    new Set(d.requests.filter(r => r.mode === m && r.status === "ok" && r.continuation === "ran").map(unitKey)));
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
  return t("data.size", { tasks: kinds(r => r.task_id), runs: kinds(r => r.attempt), modes: kinds(r => r.mode),
    n: fmtNum(D.requests.length) });
}
onLang(() => { if (D) SIZE = sizeText(); }); /* 언어가 바뀌면 문장 파생값을 다시(아래 탭 다시 그리기보다 먼저 등록) */
function stats(m) {
  const all = D.requests.filter(r => r.mode === m), ok = all.filter(r => r.status === "ok");
  const ran = ok.filter(r => r.continuation === "ran");
  const same = ran.filter(r => COMMON.has(unitKey(r))); /* 두 모드 모두 후속 실행한 같은 단위 */
  const notice = ok.filter(isNotice), lost = all.filter(r => r.lost_first > 0), count = f => all.filter(f).length;
  return {
    all, ok, ran, same, notice, lost, graded: count(r => r.passed != null), pass: count(r => r.passed === true),
    strictN: count(r => r.strict_passed != null), strict: count(r => r.strict_passed === true),
    dcl: count(r => r.status === "declined"), err: count(r => r.status === "error"),
    skip: ok.filter(r => r.continuation === "skipped").length, lostEx: sum(lost.map(r => r.lost_first)),
    noops: sum(all.map(r => r.locked_noops)), cost: sum(all.map(r => r.cost_usd)),
    v3ran: ok.filter(r => r.verified_first === 3 && r.continuation === "ran"),
    first: ok.map(r => r.first_response_ms), /* 첫 응답(D1 가정) · 정상 전체 */
    final: same.map(r => r.total_ms), /* 최종 · 같은 단위 */
    total: ok.map(r => r.total_ms), /* 전체 완료 · 정상 전체(후속 생략 포함) = 계약 aggregates.total_ms */
    bg: notice.map(r => r.background_ms), ttok: ok.map(r => r.tokens.total), rtok: same.map(r => r.tokens.total),
  };
}

/* ---------- 여러 탭이 같이 쓰는 화면 조각("parts.*" 문구) ---------- */
const P = (k, p) => t("parts." + k, p), PX = (k, p) => tx("parts." + k, p);
/* [이름, …] 배열인데 이름(0번)만 지금 언어로 읽히는 것(STATUS · KIND · CONT). 구조 분해 · [0] 모두 그대로 쓴다. */
const named = (key, ...rest) => Object.defineProperty([null, ...rest], 0, { get: () => t(key), enumerable: true });
export const STATUS = { ok: named("parts.status.ok", "check"), declined: named("parts.status.declined", "ban"),
  error: named("parts.status.error", "alert") };
export const modeIcon = m => (m === "agent" ? "bubble" : m === "baseline" ? "gear" : "info");
export const modeBadge = m => h(`span.mb.${MODES.includes(m) ? m : "unset"}`, icon(modeIcon(m)), m);
export const statusBadge = s => h(`span.sb.${s}`, icon(STATUS[s][1]), STATUS[s][0]);
export const chip = (cls, ic, ...k) => h("span.chip" + (cls ? "." + cls : ""), ic && icon(ic), ...k);
export const preChip = (...k) => h("span.prechip", icon("clock"), ...k);
export const mono = k => h("span.mono", k);
export const enT = (k, cls = "en") => h(`span.${cls}`, { lang: "en" }, k);
export const foot = (...k) => h("p.foot", ...k);
export const pill = (...k) => h("span.pill", ...k);
export const kv = items =>
  h("dl.kv.num", items.filter(Boolean).map(([dt, ...dd]) => h("div", h("dt", dt), h("dd", ...dd))));
export const h4 = (ic, k, small) => h("h4.card-h.sm", icon(ic), k, small && h("small", small));
export const lockOne = x => h("span.lockc", icon("lock"), P("slotN", { x }));
export const lockChip = slots =>
  h("span.lockc", icon("lock"), P("lockedSlots", { n: slots.length, list: slots.map(x => "#" + x).join("·") }));
/* 머리 숫자 카드(모드 비교 · 지표): 모드별 줄(kRow) · 카드(kpi) */
export const kRow = (m, v, k) => h("div.kr", modeBadge(m), h("span.v.num", v), h("span.n.num", k));
export const kpi = (title, rows, ...sub) => h("div.kpi", h("h3", title), rows, h("p.sub", ...sub));
export const nEq = k => `n=${fmtN(k)}`;
/* 탭 머리말 + 데이터 출처 칩(자세한 출처 문장은 data.json meta.source를 title로) */
export const phead = (title, p, ...extra) => h("div.phead", h("h2", title), h("p", p),
  h("span.src-chip", { title: D.meta.source || "" }, icon("info"), P("source")), ...extra);
/* 평가 실행 띠: data.json에 담긴 평가 실행 기록 하나. 잠금 판정 이름표: 적용 · 잠금 전 · 근거 없음 */
export function runBar() {
  const a = D.meta.lock.applied;
  const [label, ic] = a === true ? [P("lockApplied"), "lock"] : a === false ? [P("lockPre"), "clock"]
    : [P("lockNone"), "info"];
  return h("div.runbar", h("span.rl", P("runLabel")),
    h("span.runpill", icon("check"), h("b", D.meta.run.id || "—"), D.meta.run.date || "", h("span.sub", SIZE)),
    h(lockApplied() ? "span.lockc" : "span.prechip", { title: D.meta.lock.note || "" }, icon(ic), label),
    h("p.runnote", icon("info"), h("span", P("runNote"))));
}
/* 최종 시간 모집단 안내: 두 모드의 후속 실행 단위가 다르면(잠금 전 기록 등) 같은 단위로만 비교한다는 경고 */
export const popNote = () => (POP.same ? null : h("p.warnline.pop", icon("alert"), h("span",
  h("b", P(lockApplied() ? "popHead" : "popHeadPre")),
  P("popBody", { b: fmtNum(POP.baseline), a: fmtNum(POP.agent), c: fmtNum(POP.common) }))));
/* 가로 스크롤 상자(표): 오른쪽에 더 있으면 흐림 단서와 안내 문구(hscrollCue가 갱신) */
export const hsHint = (id, tag = "p") => h(`${tag}.hs-hint`, { id, hidden: true }, icon("arrow"), P("hsHint"));
export const hscroll = (el, key, label) => [h("div.hs-host", h("div.pct-wrap",
  { id: key, role: "region", "aria-label": label, tabindex: 0, "data-hscroll": "", "data-hint": key + "-hint" }, el)),
hsHint(key + "-hint")];
/* 오류 안내: 패널 전체(errorBox) · 한 줄(warnErr). retry가 있으면 '다시 불러오기' 버튼 */
const retryBtn = (retry, cls = "") =>
  retry && h("button.btn" + cls, { type: "button", on: { click: retry } }, icon("loop"), t("common.retry"));
const errorBox = (e, retry) => h("div.state.fail", { role: "alert" },
  h("h2", icon("alert"), t("common.renderFailed")), h("p", msgOf(e)), retryBtn(retry));
export const warnErr = (e, retry, lead = "") =>
  h("div.warnline.err", icon("alert"), h("span", lead, msgOf(e)), retryBtn(retry, ".sm"));
/* 세그먼트 버튼(필터 · 추이 · 예시 고르기 공용): opts = [[값, 이름, 추가 속성]] */
export const segBtns = (opts, on) => opts.map(([v, label, attrs]) =>
  h("button", { type: "button", "data-v": v, "aria-pressed": String(on(v)), ...attrs }, icon("check", "ck"), label));
export const seg = (id, label, opts, on) => h("div.seg", { id, role: "group", "aria-label": label }, segBtns(opts, on));
export const syncSeg = (el, on) =>
  $$("button", el).forEach(b => b.setAttribute("aria-pressed", String(on(b.dataset.v))));
export const onSeg = (el, fn) => el.addEventListener("click", e => {
  const b = e.target.closest("button");
  if (b && !b.disabled) fn(b.dataset.v, b);
});
/* 후속 단계 칩 · 예문 수. CONT_TIP[키] = 후속 단계 설명(title, 읽을 때마다 지금 언어) */
const CONT = { skipped: named("parts.cont.skipped", "skp", "skip"), ran: named("parts.cont.ran", "ran", "loop"),
  stop: named("parts.cont.stop", "stop", "alert"), none: named("parts.cont.none", "none", "ban") };
export const CONT_TIP = Object.defineProperties({}, Object.fromEntries(["all", "skipped", "ran", "stop", "none"]
  .map(k => [k, { get: () => P("contTip." + k), enumerable: true }])));
export function contChip(r) {
  const k = contKey(r), [label, cls, ic] = CONT[k] || CONT.none;
  let tip = CONT_TIP[k] || "", extra = null;
  if (k === "ran" && isWait0(r)) [extra, tip] = [P("wait"), P("waitTip")];
  else if (k === "ran") {
    extra = [" · ", h("b", "+" + r.added_final)];
    tip = P("addTip", { k: r.added_final }) + (r.verified_first === 3 ? P("v3Tip", { w: lockWord(r) }) : "");
  } else if (k === "none") tip = P(r.status === "declined" ? "declTip" : "errTip");
  return h(`span.cchip.${cls}`, { title: tip }, icon(ic), label, extra);
}
export function exText(r) {
  if (noEx(r)) return ["—"];
  if (isWait0(r)) return PX("exWait", { n: h("b", r.verified_final ?? "—") });
  const lost = r.lost_first > 0 && [" · ", h("span.lost", PX("exLost", { n: h("b", r.lost_first) }))];
  return [PX("exFirst", { f: h("b", r.verified_first ?? "—"), a: h("b", r.added_final) }), lost];
}
export function exPlain(r) {
  if (noEx(r)) return P("none");
  if (isWait0(r)) return P("exWait", { n: r.verified_final ?? "—" });
  return P("exFirst", { f: r.verified_first, a: r.added_final }) +
    (r.lost_first > 0 ? ` · ${P("exLost", { n: r.lost_first })}` : "");
}
export function dots(r) {
  if (noEx(r)) return null;
  const kept = isWait0(r) ? r.verified_final || 0 : Math.max(0, (r.verified_first || 0) - r.lost_first);
  const added = isWait0(r) ? 0 : r.added_final, dot = i => h("i" + (i < kept ? ".on" : i < kept + added ? ".add" : ""));
  return h("span.dots3", { "aria-hidden": "true" }, [0, 1, 2].map(dot));
}
export const judgeText = r =>
  (r.passed == null ? "—" : [P(r.passed ? "pass" : "fail"), r.strict_passed ? " · strict" : ""]);
/* 최종 답 슬롯의 상태 칩 */
export function slotTag(r, f) {
  if (f.added) return chip("new", "plus", P("tagAdded"));
  if (!f.verified) return chip("", "x", P("tagNoEx"));
  if (r.verified_first === 0) return chip("ok", "check", P("tagOnce"));
  if (f.from_first) return lockApplied(r) ? chip("ok", "lock", P("tagLocked")) : chip("ok", "check", P("tagKept"));
  return chip("ok", "check", P("tagVerified"));
}
export const lostTag = () => chip("warn", "alert", P("tagLost"));
/* 문자열 안의 핵심 구절을 <mark>로(텍스트 노드로만) */
export function hl(text, kp) {
  const s = String(text ?? ""), k = kp ? String(kp) : "", i = k ? s.toLowerCase().indexOf(k.toLowerCase()) : -1;
  return i < 0 ? [s] : [s.slice(0, i), h("mark", s.slice(i, i + k.length)), s.slice(i + k.length)];
}
/* 단계 종류: KIND[k] = [이름, 아이콘]. 스팬 → 종류: 오류 → 잠금 → 후속 생략 → decision(토큰 있으면 판단, 없으면 도구 적용)
   → 계약 kind(모르는 kind · request는 noop) */
const KIND_ICON = { request: "user", llm: "spark", judge: "bubble", search: "search", act: "tool", verify: "shield",
  assemble: "box", decline: "ban", budget: "alert", noop: "clock", error: "alert", lock: "lock", skip: "skip" };
export const KIND = Object.fromEntries(Object.entries(KIND_ICON).map(([k, ic]) => [k, named("parts.kind." + k, ic)]));
export const kk = s => (s.status === "error" ? "error" : s.locked === true ? "lock"
  : s.stage === "continuation_skipped" ? "skip" : s.kind === "decision" ? (s.tokens ? "judge" : "act")
    : KIND[s.kind] && s.kind !== "request" ? s.kind : "noop");
/* 단계 제목: [묶음(common = 두 모드 공통), stage 정규식, 제목]. 배열 순서 = 매칭 우선순위 */
const ROUND = m => m[1] - 1, TT = (k, p) => P("title." + k, p);
const STAGES = [
  ["common", /^candidates(_retry)?$/, m => (m[1] ? TT("candRetry") : P("stage.cand"))],
  ["common", /^decline$/, () => P("stage.dcl")],
  ["common", /^search_(\d+)$/, m => TT("candidate", { r: ROUND(m) })],
  ["common", /^select_1$/, () => P("stage.sel1")],
  ["common", /^validate_select_1$/, () => TT("v1")],
  ["baseline", /^revise_(\d+)$/, m => TT("revise", { r: m[1] })],
  ["baseline", /^search_(\d+)_\d+$/, m => TT("round", { what: P("stage.bs"), r: m[1] })],
  ["baseline", /^select_(\d+)$/, m => TT("round", { what: P("stage.bsel"), r: ROUND(m) })],
  ["baseline", /^validate_select_(\d+)$/, m => TT("round", { what: P("stage.bv"), r: ROUND(m) })],
  ["agent", /^(?:agent_(\d+)|pick_final)$/, m => (m[1] ? TT("turn", { t: m[1] }) : TT("pickFinal"))],
  ["agent", /^search_(\d+)_\d+$/, m => TT("searchTurn", { t: m[1] })],
  ["agent", /^(repick|replace)_(?:\d+|final)_\d+$/, m => TT(m[1] === "repick" ? "repick" : "replace")],
  ["agent", /^validate_(?:agent_(\d+)|pick_final)$/, m => (m[1] ? TT("verifyTurn", { t: m[1] }) : TT("verifyFinal"))],
  ["common", /^(assemble|budget_exhausted)$/, m => (m[1] === "assemble" ? P("stage.asm") : TT("budget"))],
];
/* 도구 행동 이름: detail.action, 없으면 stage 앞부분(잠긴 슬롯 대상 search noop 등) */
export const actionOf = s => (s.detail || {}).action || s.stage.split("_")[0];
export function stageTitle(s, mode) {
  if (s.locked === true) return TT("lockSkip", { a: actionOf(s), s: (s.detail || {}).slot ?? "—" });
  if (s.stage === "continuation_skipped") return TT("contSkip");
  const def = STAGES.find(([grp, re]) => (grp === "common" || grp === mode) && re.test(s.stage));
  return def ? def[2](def[1].exec(s.stage)) : s.label || s.stage;
}
/* 첫 결과 시점의 종류: 거절 · 첫 단계 오류 · 후속 생략 · 검증 0개(대기) · 3개 검증 · 1~2개(즉시) */
export const markKind = r => (r.status === "declined" ? "decl"
  : r.status === "error" && r.error_phase !== "continuation" ? "err" : r.continuation === "skipped" ? "skip"
    : r.verified_first === 0 ? "mid" : r.verified_first === 3 ? "v3" : "imm");
/* 단계 시간 막대: 스팬 elapsed 비율 + 첫 결과 시점 */
export function timeBar(r, spans) {
  const real = durOf(spans) || 1, firstEnd = durOf(spans.filter(s => s.phase === "first"));
  const tm = secU(r.first_response_ms), mk = markKind(r), showMk = ["imm", "v3", "mid"].includes(mk) && firstEnd < real;
  const piece = (s, k = kk(s)) => h(`span.tb-seg.k-${k}`, {
    title: `${stageTitle(s, r.mode)} · ${KIND[k][0]} · ${secU(s.elapsed_ms)}`, css: { flex: `${s.elapsed_ms} 1 0` },
  });
  const mark = showMk && h("span.tb-mark" + (mk === "mid" ? ".mid" : ""),
    { "aria-hidden": "true", css: { left: ((firstEnd / real) * 100).toFixed(2) + "%" } });
  const ax = {
    imm: h("span.mk", icon("bolt"), P("mkImm", { k: r.verified_first, t: tm })),
    v3: [h("span.mk", icon("bolt"), P("mkV3", { t: tm })),
      h("span.gh", icon("loop"), P(lockApplied(r) ? "v3Violation" : "v3Pre"))],
    mid: h("span.mk.mid", icon("hour"), P("mkMid", { t: secU(firstEnd) })),
    skip: [h("span.mk", icon("bolt"), P("mkSkip", { t: tm, k: r.verified_first })),
      h("span.gh", icon("skip"), P("kind.skip"))],
    decl: chip("warn", "ban", P("mkDecl")), err: chip("err", "alert", P("mkErr")),
  }[mk];
  return h("div.tbar", h("div.tb-track",
    { role: "img", "aria-label": P("barLabel", { t: secU(r.total_ms), f: secU(r.first_response_ms) }) },
    spans.filter(s => s.elapsed_ms > 0).map(s => piece(s)), mark),
  h("div.tb-ax.num", h("span", t("unit.sec", { n: 0 })), ax, h("span", P("axTotal", { t: secU(r.total_ms) }))));
}

/* ---------- 탭 · 머리말(언어 전환) · 레이아웃 측정 · 가로 스크롤 단서 ---------- */
const TABS = [["flags", "server"], ["logs", "list"], ["metrics", "chart"], ["graph", "graph"]];
const VIEWS = { flags, logs, metrics, graph }, rendered = {};
window.__tabs = TABS.map(x => x[0]);
let curTab = null;
/* index.html의 고정 문구: data-i18n="키"(글자) · data-i18n-aria="키"(aria-label). 문서 제목 · 탭 이름 · 언어 전환도 함께. */
function paintStatic() {
  document.title = t("app.title");
  for (const el of $$("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of $$("[data-i18n-aria]")) el.setAttribute("aria-label", t(el.dataset.i18nAria));
  for (const [id] of TABS) $(`#tab-${id} span`).textContent = t("tab." + id);
  const sw = $("#langSwitch");
  sw.setAttribute("aria-label", t("app.langLabel"));
  $$("button", sw).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.lang === lang())));
}
/* 언어가 바뀌면: 고정 문구 → 그린 탭을 모두 '안 그림'으로 → 지금 탭만 바로 다시 그린다 */
onLang(() => {
  paintStatic();
  for (const id of Object.keys(rendered)) rendered[id] = null;
  if (curTab) showTab(curTab);
});
function buildTabs() {
  const host = $("#tabs"), sw = $("#langSwitch");
  fill(host, TABS.map(([id, ic]) => h("button", { type: "button", role: "tab", id: "tab-" + id,
    "aria-controls": "panel-" + id, "aria-selected": "false", tabindex: -1, "data-tab": id }, icon(ic),
  h("span", t("tab." + id)))));
  /* 언어 전환(한국어 / 中文 / English): 각 버튼은 자기 언어 이름을 자기 lang으로 보여 준다 */
  fill(sw, icon("globe", "lang-ic"), LANGS.map(l => h("button",
    { type: "button", lang: HTML_LANG[l], "data-lang": l, "aria-pressed": String(l === lang()) },
    icon("check", "ck"), LANG_NAMES[l])));
  sw.addEventListener("click", e => {
    const b = e.target.closest("button[data-lang]");
    if (b) setLang(b.dataset.lang);
  });
  paintStatic();
  host.addEventListener("click", e => {
    const b = e.target.closest("[role=tab]");
    if (b) showTab(b.dataset.tab);
  });
  host.addEventListener("keydown", e => {
    const ids = window.__tabs, i = ids.indexOf(curTab), n = ids.length;
    const keys = { ArrowRight: ids[(i + 1) % n], ArrowLeft: ids[(i - 1 + n) % n], Home: ids[0], End: ids[n - 1] };
    const next = keys[e.key];
    if (!next) return;
    e.preventDefault(); showTab(next); $("#tab-" + next).focus();
  });
}
const frames = n => new Promise(res => { const f = k => (k ? requestAnimationFrame(() => f(k - 1)) : res()); f(n); });
export async function showTab(id) {
  if (!window.__tabs.includes(id)) return false;
  curTab = id;
  for (const x of window.__tabs) {
    const on = x === id, b = $("#tab-" + x);
    b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; $("#panel-" + x).hidden = !on || !D;
  }
  if (!D) return false;
  const panel = $("#panel-" + id);
  rendered[id] ??= Promise.resolve().then(() => VIEWS[id].render(panel)).catch(e => {
    rendered[id] = null;
    /* trace 파일을 못 읽은 경우에만 다시 불러오기 버튼(그 밖의 오류는 다시 해도 같음) */
    fill(panel, errorBox(e, tracesErr != null ? () => (retryTraces(), rerender(id)) : null));
  });
  await rendered[id];
  if (curTab !== id) return true;
  const dyn = () => {
    updateLayout();
    if (rendered[id] && VIEWS[id].dyn) VIEWS[id].dyn();
  };
  dyn(); await frames(2);
  if (curTab === id) dyn();
  return true;
}
/* 탭을 처음부터 다시 그린다(trace 다시 불러오기 뒤 등) */
export function rerender(id) {
  rendered[id] = null;
  if (curTab === id) showTab(id);
}
/* 레이아웃 측정(글자 크기 · 폭이 바뀌면 다시): body[data-w]=xl|l|m|s(본문 폭 84/64/48rem) · data-fit(화면 맞춤) */
export function updateLayout() {
  const px = rootPx(), main = $("#main"), cs = getComputedStyle(main);
  const w = (main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) / px;
  const W = w >= 84 ? "xl" : w >= 64 ? "l" : w >= 48 ? "m" : "s";
  const fit = innerHeight / px >= 34 && (W === "xl" || W === "l");
  document.body.dataset.w = W; document.body.dataset.fit = fit ? "1" : "0";
  /* data-steps="56:full 34:c 0:n": 첫 자식 폭(rem)이 기준 이상인 첫 값을 data-lc로(요청 표 열 구성) */
  for (const el of $$("[data-steps]")) {
    if (!el.offsetParent || !el.firstElementChild) continue;
    const tw = el.firstElementChild.clientWidth / px;
    const step = el.dataset.steps.split(" ").map(x => x.split(":")).find(([min]) => tw >= +min);
    if (step) el.dataset.lc = step[1];
  }
  /* 화면 맞춤 패널: 남은 높이만큼. 위 도구가 길어 20rem보다 적으면 같은 묶음 전체를 대체 높이(뷰포트 78%)로 */
  const panes = $$(".fitpane"), keep = panes.map(el => [el.scrollTop, el.scrollLeft]);
  panes.forEach(el => el.style.removeProperty("max-height"));
  if (fit) {
    const alt = Math.min(Math.max(22 * px, 0.78 * innerHeight), innerHeight - 1.5 * px);
    const room = new Map(panes.filter(el => el.offsetParent)
      .map(el => [el, innerHeight - (el.getBoundingClientRect().top + scrollY) - 1.25 * px]));
    const short = (el, host = el.closest(".lgrid")) =>
      [...room].some(([e, v]) => v < 20 * px && host && host.contains(e));
    for (const [el, v] of room) el.style.setProperty("max-height", (short(el) ? alt : v) + "px");
  }
  panes.forEach((el, i) => {
    if (keep[i][0]) el.scrollTop = keep[i][0];
    if (keep[i][1]) el.scrollLeft = keep[i][1];
  });
  $$("[data-hscroll]").forEach(hscrollCue);
}
/* 가로 스크롤 단서: 오른쪽에 더 있으면 부모에 data-more="r", 안내 문구(data-hint) 표시 */
export function hscrollCue(el) {
  const host = el.parentElement;
  if (!host) return;
  const more = el.scrollWidth - el.clientWidth, hint = el.dataset.hint && document.getElementById(el.dataset.hint);
  host.dataset.more = more - el.scrollLeft > 2 ? "r" : "";
  if (hint) hint.hidden = !(more > 2);
  if (!el.dataset.cue) { el.dataset.cue = "1"; el.addEventListener("scroll", () => hscrollCue(el), { passive: true }); }
}
let rafId = 0, lastKey = "";
function onResize(force) {
  cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(() => {
    const key = `${$("#main").clientWidth}|${rootPx()}|${innerHeight}`;
    if (!force && key === lastKey) return;
    lastKey = key; updateLayout();
    if (D && curTab && rendered[curTab] && VIEWS[curTab].dyn) VIEWS[curTab].dyn();
  });
}
const setScale = v => v > 0 && v <= 4 && document.documentElement.style.setProperty("font-size", 16 * v + "px");

/* ---------- 시작 ---------- */
window.__showTab = showTab; window.__setLang = setLang;
/* 데이터 로더: 상대 경로로 읽는다(미리보기 서버가 경로·포트만 바꿔 띄울 수 있게). 버전이 1이 아니면 그리지 않는다. */
async function loadData() {
  const d = await readJSON(fetch("data.json", { cache: "no-cache" }), "data.json");
  if (!isObj(d) || !isObj(d.meta)) throw new DataError("data.err.noMeta");
  const got = JSON.stringify(d.meta.schema_version) ?? (() => t("data.none"));
  if (d.meta.schema_version !== 1) throw new DataError("data.err.version", { got });
  checkData(d);
  return d;
}
let fatal = null; /* 그리지 못한 이유(언어가 바뀌면 같은 오류를 그 언어로 다시 보여 준다) */
function showFatal(e) {
  const box = $("#state");
  fatal = e; fill(box, h("h2", icon("alert"), t("app.fatalTitle")), h("p", msgOf(e)), h("p", t("app.fatalHelp")));
  box.classList.add("fail"); box.setAttribute("role", "alert");
}
/* 머리말 아래 한 줄: 지금 열린 경로(배포에서는 /admin/, 미리보기에서는 그 폴더) · 보호 없음 · 데이터 출처(읽은 뒤) */
const paintBar = () => fill($("#adminBar"),
  h("span", icon("gear"), tx("app.deploy", { path: h("b", location.pathname) })),
  h("span.ab-warn", icon("alert"), t("app.noProtection")),
  D && h("span", icon("info"), t("app.source", { run: D.meta.run.id || "—", time: utc(D.meta.generated_at) })));
onLang(() => {
  paintBar();
  if (fatal) showFatal(fatal);
});
/* 미리보기 창과 자동 검수가 보내는 메시지. 이 창이나 부모 프레임이 보낸 것만 받고, 출처가 다르면 ?qa=1로 연 때만 받는다
   (아무 사이트나 /admin을 iframe으로 띄워 글자 크기 · 탭을 바꾸지 못하게). */
function listen(qp) {
  const qa = qp.get("qa") === "1";
  addEventListener("message", e => {
    const m = e.data, ours = e.source === window || e.source === window.parent;
    if (!ours || !(e.origin === location.origin || qa) || !isObj(m)) return;
    if (m.type === "font-scale" && +m.value > 0) {
      setScale(+m.value); onResize(true);
    } else if (m.type === "show-tab" && typeof m.id === "string") showTab(m.id);
  });
}
async function start() {
  buildTabs(); paintBar();
  const qp = new URLSearchParams(location.search), scale = parseFloat(qp.get("scale"));
  if (scale > 0) setScale(scale);
  listen(qp);
  addEventListener("resize", () => onResize());
  if ("ResizeObserver" in window) {
    const ro = new ResizeObserver(() => onResize());
    ro.observe($("#remProbe")); ro.observe($("#main"));
  }
  if (document.fonts) {
    document.fonts.ready.then(() => onResize(true));
    document.fonts.addEventListener("loadingdone", () => onResize(true));
  }
  const first = window.__tabs.includes(qp.get("tab")) ? qp.get("tab") : "flags";
  try {
    setData(await loadData());
  } catch (e) {
    showFatal(e); showTab(first); window.__ready = true;
    return;
  }
  $("#state").hidden = true; paintBar(); await showTab(first); window.__ready = true;
}
start();