import { fmtNum, lang, LANGS, LANG_NAMES, onLang, setLang, t } from "../i18n.js";

const copy = {
  admin: ["English Coach 어드민", "English Coach 管理页", "English Coach admin"],
  title: ["200문항 평가", "200 题评测", "200-task evaluation"],
  pdf: ["영어 보고서 (PDF)", "英文报告（PDF）", "English report (PDF)"],
  tsv: ["문항별 결과 (TSV)", "下载逐题结果（TSV）", "Download task results (TSV)"],
  json: ["전체 결과 (JSON)", "下载完整结果（JSON）", "Download full results (JSON)"],
  compare: ["에이전트와 베이스라인", "智能体与基线", "Agent and baseline"],
  scope: ["평가 세트", "题集", "Task set"],
  provenance: ["세트마다 모델, 평가 모델, 자막 자료 및 에이전트 정책이 달라요. 두 시스템의 차이는 같은 세트 안에서 비교하세요.", "不同批次采用的生成模型、评分模型、字幕库和智能体策略有所不同。请在同一批次内比较两种系统。", "Model, judge, corpus and agent policy varied across cohorts. Compare the systems within each cohort."],
  timeNote: ["지연 시간에는 병렬 실행 중 대기 시간이 포함돼요. 턴은 답변 생성에 사용한 모델 호출 수예요. 토큰은 채점을 제외하고, 새 문항에서는 Codex 컨텍스트를 포함해요.", "延迟包含并行评测中的等待时间。轮数按生成答案的模型调用次数统计。Token 排除评分用量，新增题包含 Codex 上下文。", "Latency includes waiting during parallel evaluation. Turns count generation calls. Tokens exclude grading and include Codex context for the new tasks."],
  metric: ["지표","指标","Measure"], agent: ["에이전트","智能体","Agent"], baseline: ["베이스라인","基线","Baseline"],
  accuracy: ["통과 응답 / 전체 응답 (정확도)","通过的回答 / 全部回答（准确率）","Passing answers / all answers (accuracy)"],
  any: ["1회 이상 통과 (pass@3)","至少通过一次（pass@3）","Tasks passing at least once (pass@3)"],
  every: ["3회 모두 통과 (pass^3)","三次全部通过（pass^3）","Tasks passing every trial (pass^3)"],
  flips: ["결과가 바뀐 문항 수","通过与失败均出现的题数","Tasks with mixed outcomes"],
  turns: ["평균 모델 호출 수","平均调用轮数","Mean model turns"],
  latency: ["평균 지연 시간 (초)","平均延迟（秒）","Mean latency (seconds)"],
  p95: ["p95 지연 시간 (초)","P95 延迟（秒）","95th-percentile latency (seconds)"],
  tokens: ["평균 토큰 수","平均 token 数","Mean tokens"],
  replays: ["문항별 리플레이","逐题回放","Task replays"],
  newReplay: ["새 100문항 · 중국어 및 한국어","新增 100 题 · 中文和韩文","New 100 · Chinese and Korean"],
  oldZh: ["기존 중국어 50문항","原中文 50 题","Original Chinese 50"],
  oldKo: ["기존 한국어 50문항","原韩文 50 题","Original Korean 50"],
  case: ["실패 추적 · 문 잡아 달라고 부탁하기, 1회차","失败回放 · 请对方扶一下门，第 1 次","Trace a failure · Holding the door, trial 1"],
  changesNote: ["P는 통과, F는 실패예요. 왼쪽부터 1·2·3회차 순서예요. 문항을 누르면 두 시스템의 응답을 확인할 수 있어요.", "P 表示通过，F 表示失败。从左到右是第 1、2、3 次。点击题目可查看两种系统的原始回答。", "P means pass and F means fail. Sequences show trials 1, 2 and 3. Open a task to see both systems’ answers."],
  task: ["문항","题目","Task"],
  all: ["전체 200문항","全部 200 题","All 200 tasks"],
  expansion: ["새 100문항","新增 100 题","New 100 tasks"],
  original: ["기존 100문항","原有 100 题","Original 100 tasks"],
  "expansion/zh": ["새 중국어 50문항","新增中文 50 题","New Chinese 50"],
  "expansion/ko": ["새 한국어 50문항","新增韩文 50 题","New Korean 50"],
  "original/zh": ["기존 중국어 50문항","原中文 50 题","Original Chinese 50"],
  "original/ko": ["기존 한국어 50문항","原韩文 50 题","Original Korean 50"],
};
const cohorts = ["all", "expansion", "expansion/zh", "expansion/ko", "original", "original/zh", "original/ko"];
const get = id => document.getElementById(id);
const tr = key => copy[key][LANGS.indexOf(lang())];
const num = (value, digits = 0) => fmtNum(value, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const counts = (passed, total) => num(passed) + " / " + num(total);
const columns = [
  ["accuracy", m => counts(m.passed_attempts, m.attempts) + " (" + num(m.accuracy * 100, 1) + "%)"],
  ["any", m => counts(m["pass@3"], m.tasks)], ["every", m => counts(m["pass^3"], m.tasks)],
  ["flips", m => num(m.flips.length)], ["turns", m => num(m.turns_mean, 2)],
  ["latency", m => num(m.latency_mean_s, 1)], ["p95", m => num(m.latency_p95_s, 1)],
  ["tokens", m => num(m.tokens_mean)],
];
const requested = new URLSearchParams(location.search).get("cohort");
let cohort = cohorts.includes(requested) ? requested : "all";
let data, failed = false;

function el(tag, value) {
  const node = document.createElement(tag);
  node.textContent = value;
  return node;
}
function metricRow(label, format, pair) {
  const row = document.createElement("tr");
  const heading = el("th", tr(label));
  heading.scope = "row";
  row.append(heading, el("td", format(pair.agent)), el("td", format(pair.baseline)));
  return row;
}
function taskRow(task) {
  const row = document.createElement("tr");
  const heading = document.createElement("th");
  heading.scope = "row";
  const link = el("a", task.task_id);
  const file = task.cohort.startsWith("expansion/") ? "expansion.html"
    : task.cohort === "original/ko" ? "ko.html" : "zh.html";
  link.href = file + "#" + encodeURIComponent(task.task_id) + "/1";
  link.dataset.replay = "";
  heading.append(link);
  row.append(heading);
  for (const system of ["agent", "baseline"]) {
    const sequence = [1, 2, 3].map(i => task[system + "_run_" + i]).join(" ");
    const cell = el("td", sequence);
    cell.className = "sequence" + (task[system + "_flips"] ? " mixed" : "");
    row.append(cell);
  }
  return row;
}
function render() {
  const li = LANGS.indexOf(lang());
  for (const node of document.querySelectorAll("[data-copy]")) node.textContent = tr(node.dataset.copy);
  for (const button of get("languages").children) button.setAttribute("aria-pressed", String(button.lang === lang()));
  document.title = tr("title") + " · English Coach";
  get("languages").setAttribute("aria-label", t("app.langLabel"));
  get("admin-link").href = "../?lang=" + lang();
  get("safety-link").textContent = t("app.safetyEval");
  const select = get("cohort");
  select.replaceChildren(...cohorts.map(id => new Option(tr(id), id, false, id === cohort)));
  get("status").textContent = data ? "" : t(failed ? "benchmark.invalid" : "benchmark.loading");
  if (!data) return;
  const q = data.qc;
  const reps = num(q.attempts_per_task_per_system), total = num(q.graded_attempts);
  get("coverage").textContent = [
    "시스템별 " + reps + "회 실행 · 전체 응답 " + total + "건 채점 완료",
    "每题每系统运行 " + reps + " 次，共 " + total + " 个回答已评分。",
    reps + " trials per task and system · " + total + " graded answers",
  ][li];
  get("metrics").replaceChildren(...columns.map(([label, format]) => metricRow(label, format, data.summary[cohort])));
  get("metrics-box").hidden = false;
  const mixed = data.tasks.filter(task => (cohort === "all" || task.cohort === cohort || task.cohort.startsWith(cohort + "/"))
    && (task.agent_flips || task.baseline_flips));
  get("change-summary").textContent = ["결과가 바뀐 문항 " + num(mixed.length) + "개",
    "查看 " + num(mixed.length) + " 道结果有变化的题目", "Tasks with changing verdicts (" + num(mixed.length) + ")"][li];
  document.querySelector("#changes-table tbody").replaceChildren(...mixed.map(taskRow));
  get("changes").hidden = false;
}
for (const code of LANGS) {
  const button = el("button", LANG_NAMES[code]);
  button.type = "button";
  button.lang = code;
  button.addEventListener("click", () => setLang(code));
  get("languages").append(button);
}
get("cohort").addEventListener("change", event => {
  cohort = event.target.value;
  const url = new URL(location.href);
  if (cohort === "all") url.searchParams.delete("cohort");
  else url.searchParams.set("cohort", cohort);
  history.replaceState(history.state, "", url);
  render();
});
document.addEventListener("click", event => {
  if (lang() === "en" || !event.target.closest("a[data-replay]")) return;
  try { localStorage.setItem("english-coach.review.language", lang()); } catch { /* Storage is optional. */ }
});
onLang(render);
render();
try {
  const response = await fetch("combined-200.json");
  if (!response.ok) throw new Error("Benchmark data unavailable");
  data = await response.json();
} catch { failed = true; }
render();
