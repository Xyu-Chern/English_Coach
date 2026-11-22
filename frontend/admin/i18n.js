/* Phrase Room 어드민 · 화면 언어(한국어 · 中文 · English). 다른 모듈을 import하지 않는 잎 모듈.
   사용법
   - 사전 등록(모듈 맨 위에서 한 번): register({ ko: { "logs.title": "요청 로그" }, zh: { … }, en: { … } })
   - 문구: t("logs.count", { n: fmtNum(300) }) → 문자열.  tx(key, { b: h("b", …) }) → [문자열 | Node] 배열(h()의 자식으로).
   - 값은 "{name}" 자리표시가 있는 문자열, 또는 p => 문자열(복수형 등). 자리표시 값이 함수면 그릴 때 호출한다.
   - 서식: fmtNum(n, Intl 옵션) · fmtDate(ts) · fmtDateTime(ts)(UTC 표기). 언어 코드 lang(), Intl 로케일 locale().
   - 언어 변경: setLang("en"). 바뀌면 onLang(fn) 구독자 → window "langchange" 이벤트 순으로 알리고,
     shell.js가 지금 탭을 처음부터 다시 그린다(render(panel)를 다시 부름. 다른 탭은 다음에 열 때).
   키 이름 규칙: "<영역>.<이름>"(camelCase, 필요하면 한 단계 더). 영역 = app(머리말 · 틀) · tab(탭 이름) · common(여러 탭 공통)
     · unit(단위) · data(data.js) · parts · flags · logs · metrics · graph(각 모듈). 자기 영역 키는 자기 모듈에서 register한다.
   빠진 키는 ko 값 → 키 이름 순으로 대신 보이고 window.__i18nMissing(Set, "언어:키")에 남는다(콘솔 출력 없음).
   언어 결정 순서: ?lang=ko|zh|en > localStorage > ko. ?lang은 저장하지 않고, 머리말에서 직접 고른 언어만 저장한다.
   학습자 질문 원문과 모델 출력(판단 이유 등)은 데이터 그대로 둔다(번역하지 않음). */

export const LANGS = ["ko", "zh", "en"];
export const LANG_NAMES = { ko: "한국어", zh: "中文", en: "English" };
export const HTML_LANG = { ko: "ko", zh: "zh-CN", en: "en" };
const LOCALE = { ko: "ko-KR", zh: "zh-CN", en: "en-US" };
const STORE = "phrase-room-admin.lang";
const DICT = { ko: {}, zh: {}, en: {} };
const KEYLIKE = /^[a-z][\w-]*(\.[\w-]+)+$/i;
const subs = [];
const missing = new Set();
window.__i18nMissing = missing;

function stored() {
  try {
    return localStorage.getItem(STORE);
  } catch {
    return null;
  }
}
function initial() {
  const q = new URLSearchParams(location.search).get("lang");
  return [q, stored()].find(v => LANGS.includes(v)) || "ko";
}
let cur = initial();
document.documentElement.lang = HTML_LANG[cur];

export const lang = () => cur;
export const locale = () => LOCALE[cur];

export function register(dict) {
  for (const l of LANGS) if (dict && dict[l]) Object.assign(DICT[l], dict[l]);
}

function lookup(key) {
  const own = DICT[cur][key];
  if (own !== undefined) return own;
  if (KEYLIKE.test(key)) missing.add(`${cur}:${key}`);
  return DICT.ko[key] ?? key;
}
const val = p => (typeof p === "function" ? p() : p);

export function t(key, params = {}) {
  const v = lookup(key);
  if (typeof v === "function") return String(v(params));
  return String(v).replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(val(params[k])) : m));
}

/* 자리표시에 Node(굵은 글씨 등)를 넣을 때: 문자열과 Node가 섞인 배열을 돌려준다 */
export function tx(key, params = {}) {
  const v = lookup(key);
  if (typeof v === "function") {
    const r = v(params);
    return Array.isArray(r) ? r : [r];
  }
  return String(v).split(/\{(\w+)\}/)
    .map((s, i) => (i % 2 ? (s in params ? val(params[s]) : `{${s}}`) : s))
    .filter(x => x !== "" && x != null);
}

export function setLang(l) {
  if (!LANGS.includes(l) || l === cur) return false;
  cur = l;
  document.documentElement.lang = HTML_LANG[l];
  try {
    localStorage.setItem(STORE, l);
  } catch {
    /* 저장할 수 없는 환경(사생활 보호 모드 등)이면 이번 창에서만 바뀐다 */
  }
  const u = new URL(location.href);
  if (u.searchParams.has("lang")) {
    u.searchParams.set("lang", l);
    history.replaceState(history.state, "", u);
  }
  for (const fn of [...subs]) {
    try {
      fn(l);
    } catch (e) {
      console.error(e);
    }
  }
  dispatchEvent(new CustomEvent("langchange", { detail: { lang: l } }));
  return true;
}

export function onLang(fn) {
  subs.push(fn);
  return () => {
    const i = subs.indexOf(fn);
    if (i >= 0) subs.splice(i, 1);
  };
}

/* ---------- 언어별 서식(숫자 · 날짜). 값이 없거나 잘못되면 "—" ---------- */
const NF = new Map();
export function fmtNum(n, opts) {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  const k = cur + JSON.stringify(opts || {});
  let f = NF.get(k);
  if (!f) NF.set(k, (f = new Intl.NumberFormat(LOCALE[cur], opts)));
  return f.format(n);
}
const DATE = {
  ko: { year: "numeric", month: "2-digit", day: "2-digit" },
  zh: { year: "numeric", month: "2-digit", day: "2-digit" },
  en: { year: "numeric", month: "short", day: "numeric" },
};
const DF = new Map();
function fmtD(ts, time) {
  const d = typeof ts === "string" && ts ? new Date(ts) : ts instanceof Date ? ts : null;
  if (!d || Number.isNaN(d.getTime())) return "—";
  const k = cur + time;
  let f = DF.get(k);
  if (!f) {
    const o = { ...DATE[cur], timeZone: "UTC", ...(time ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}) };
    DF.set(k, (f = new Intl.DateTimeFormat(LOCALE[cur], o)));
  }
  return f.format(d) + (time ? " UTC" : "");
}
export const fmtDate = ts => fmtD(ts, false); /* "2026. 11. 17." · "2026/11/17" · "Nov 17, 2026" */
export const fmtDateTime = ts => fmtD(ts, true); /* 위 + " 05:30 UTC" */

/* ---------- 틀(app · tab · common · unit · data) 사전. 영어 · 중국어는 직역하지 않고 그 언어로 자연스럽게 ---------- */
const plural = (n, one, many) => `${n} ${+n === 1 ? one : many}`;
register({
  ko: {
    "app.title": "Phrase Room 어드민",
    "app.eyebrow": "Phrase Room · 운영",
    "app.concept": "실제 요청과 평가 실행 기록으로 모드 · 요청 · 지표 · 실행 경로를 살펴봐요",
    "app.skip": "본문으로 건너뛰기",
    "app.tabsLabel": "어드민 화면",
    "app.langLabel": "화면 언어",
    "app.loading": "데이터(data.json)를 불러오는 중이에요…",
    "app.deploy": "{path} · 학습자 앱과 같은 Vercel 배포에 포함",
    "app.noProtection": "보호 없음 — 주소를 아는 사람은 누구나 볼 수 있음",
    "app.source": "데이터: 평가 실행 {run} · 생성 {time}",
    "app.fatalTitle": "데이터를 표시할 수 없어요",
    "app.fatalHelp": "frontend/admin/data.json을 생성기(python -m frontend.admin_data)로 다시 만들어 같은 폴더에 두고 " +
      "배포해 주세요. 이 화면은 같은 폴더의 data.json만 읽어요.",
    "tab.flags": "모드 비교",
    "tab.logs": "요청 로그",
    "tab.metrics": "지표",
    "tab.graph": "실행 그래프",
    "common.loading": "불러오는 중이에요…",
    "common.retry": "다시 불러오기",
    "common.renderFailed": "이 화면을 그리지 못했어요",
    "common.none": "없음",
    "common.noData": "표시할 데이터가 없어요",
    "unit.sec": "{n}초",
    "data.none": "없음",
    "data.err.contract": "데이터 형식이 계약(v1)과 달라요: {what}",
    "data.err.noMeta": "데이터 형식이 계약(v1)과 달라요: meta가 없어요",
    "data.err.version": "데이터 버전이 맞지 않아요: 이 화면은 schema_version 1만 읽어요(data.json 값: {got}).",
    "data.err.network": "{url} 파일을 불러오지 못했어요(네트워크 오류).",
    "data.err.http": "{url} 파일을 불러오지 못했어요(HTTP {status}). 배포에 이 파일이 포함됐는지 확인해 주세요.",
    "data.err.json": "{url} 파일이 올바른 JSON이 아니에요.",
    "data.err.tracesVersion": "{url}의 데이터 버전이 맞지 않아요({got}).",
    "data.err.unexpected": "예상하지 못한 오류가 났어요: {msg}",
    "data.what.nums": "{at}의 숫자 필드",
    "data.what.optNums": "{at}의 선택 숫자 필드",
    "data.what.answers": "answers 항목",
    "data.what.traces": "traces 또는 meta.files.traces",
    "data.what.spans": "traces[{id}]의 단계",
    "data.what.tracesIn": "{url}의 traces",
    "data.lock.violation": "잠금 위반",
    "data.lock.preLock": "잠금 전 기록",
    "data.size": "{tasks}과제 × {runs}회 × {modes}모드 = {n}건",
  },
  zh: {
    "app.title": "Phrase Room 管理后台",
    "app.eyebrow": "Phrase Room · 运营",
    "app.concept": "通过真实请求和评测运行记录，查看模式、请求、指标和执行路径",
    "app.skip": "跳到正文",
    "app.tabsLabel": "后台页面",
    "app.langLabel": "界面语言",
    "app.loading": "正在加载数据（data.json）…",
    "app.deploy": "{path} · 与学习者应用同属一个 Vercel 部署",
    "app.noProtection": "未设访问保护 — 知道网址的人都能查看",
    "app.source": "数据：评测运行 {run} · 生成于 {time}",
    "app.fatalTitle": "无法显示数据",
    "app.fatalHelp": "请用生成器（python -m frontend.admin_data）重新生成 frontend/admin/data.json，放回同一文件夹后再部署。" +
      "此页面只读取同一文件夹中的 data.json。",
    "tab.flags": "模式对比",
    "tab.logs": "请求日志",
    "tab.metrics": "指标",
    "tab.graph": "执行图",
    "common.loading": "加载中…",
    "common.retry": "重新加载",
    "common.renderFailed": "此页面未能显示",
    "common.none": "无",
    "common.noData": "暂无可显示的数据",
    "unit.sec": "{n} 秒",
    "data.none": "无",
    "data.err.contract": "数据格式与契约（v1）不符：{what}",
    "data.err.noMeta": "数据格式与契约（v1）不符：缺少 meta",
    "data.err.version": "数据版本不匹配：此页面只支持 schema_version 1（data.json 中为 {got}）。",
    "data.err.network": "无法加载 {url}（网络错误）。",
    "data.err.http": "无法加载 {url}（HTTP {status}）。请确认部署中包含该文件。",
    "data.err.json": "{url} 不是有效的 JSON。",
    "data.err.tracesVersion": "{url} 的数据版本不匹配（{got}）。",
    "data.err.unexpected": "发生意外错误：{msg}",
    "data.what.nums": "{at} 的数值字段",
    "data.what.optNums": "{at} 的可选数值字段",
    "data.what.answers": "answers 条目",
    "data.what.traces": "traces 或 meta.files.traces",
    "data.what.spans": "traces[{id}] 中的步骤",
    "data.what.tracesIn": "{url} 中的 traces",
    "data.lock.violation": "违反锁定规则",
    "data.lock.preLock": "锁定前的记录",
    "data.size": "{tasks} 个任务 × {runs} 轮 × {modes} 种模式 = {n} 条请求",
  },
  en: {
    "app.title": "Phrase Room Admin",
    "app.eyebrow": "Phrase Room · Operations",
    "app.concept": "Explore modes, requests, metrics, and execution paths from live requests and evaluation runs",
    "app.skip": "Skip to main content",
    "app.tabsLabel": "Admin views",
    "app.langLabel": "Display language",
    "app.loading": "Loading data (data.json)…",
    "app.deploy": "{path} · ships with the learner app in the same Vercel deployment",
    "app.noProtection": "No access protection — anyone with the URL can view this page",
    "app.source": "Data: evaluation run {run} · generated {time}",
    "app.fatalTitle": "Can't display the data",
    "app.fatalHelp": "Regenerate frontend/admin/data.json with the generator (python -m frontend.admin_data), put it in " +
      "the same folder, and redeploy. This page only reads data.json from its own folder.",
    "tab.flags": "Mode comparison",
    "tab.logs": "Request log",
    "tab.metrics": "Metrics",
    "tab.graph": "Run graph",
    "common.loading": "Loading…",
    "common.retry": "Try again",
    "common.renderFailed": "Couldn't render this view",
    "common.none": "None",
    "common.noData": "Nothing to show yet",
    "unit.sec": "{n}s",
    "data.none": "missing",
    "data.err.contract": "The data doesn't match the v1 contract: {what}",
    "data.err.noMeta": "The data doesn't match the v1 contract: meta is missing",
    "data.err.version": "Data version mismatch: this page only reads schema_version 1 (data.json has {got}).",
    "data.err.network": "Couldn't load {url} (network error).",
    "data.err.http": "Couldn't load {url} (HTTP {status}). Check that the file is part of the deployment.",
    "data.err.json": "{url} isn't valid JSON.",
    "data.err.tracesVersion": "{url} has an unsupported data version ({got}).",
    "data.err.unexpected": "Something unexpected went wrong: {msg}",
    "data.what.nums": "numeric fields in {at}",
    "data.what.optNums": "optional numeric fields in {at}",
    "data.what.answers": "an answers entry",
    "data.what.traces": "traces or meta.files.traces",
    "data.what.spans": "steps in traces[{id}]",
    "data.what.tracesIn": "traces in {url}",
    "data.lock.violation": "lock violation",
    "data.lock.preLock": "pre-lock record",
    "data.size": p =>
      `${plural(p.tasks, "task", "tasks")} × ${plural(p.runs, "run", "runs")} × ${plural(p.modes, "mode", "modes")} = ` +
      plural(p.n, "request", "requests"),
  },
});
