"use strict";
const $ = (id) => document.getElementById(id);
const symbols = {
  home: '<path d="M3 5h18v12H9l-5 4v-4H3z"/><path d="M7 9h10M7 13h6"/>',
  library: '<path d="M3 4h4v16H3zM9 4h4v16H9zM15 5l3-1 4 15-3 1z"/>',
  book: '<path d="M5 3h14v18l-7-5-7 5z"/>',
  saved: '<path fill="currentColor" d="M5 3h14v18l-7-5-7 5z"/>',
  settings:
    '<path d="M3 7h6m5 0h7M3 17h11m5 0h2"/><circle cx="11.5" cy="7" r="2.5"/><circle cx="16.5" cy="17" r="2.5"/>',
  lang: '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  ask: '<path d="M4 4h16v12H9l-5 4z"/><path d="M8 8h8m-8 4h5"/>',
  daily:
    '<path d="M4 9h13v5a6 6 0 0 1-6 6H9a5 5 0 0 1-5-5zM17 10h2a2.5 2.5 0 0 1 0 5h-2M7 4v2m5-3v3"/>',
  social: '<path d="M2 4h14v10H8l-4 3v-3H2zM18 8h4v11h-2v2l-5-3h-5v-2"/>',
  work: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V4h8v3M3 12c4 3 14 3 18 0M10 13h4"/>',
  sound: '<path d="M3 10v4m3-7v10m3-13v16m3-11v6m3-10v14m3-12v10m3-7v4"/>',
  podcast:
    '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21m-4 0h8"/>',
  search: '<circle cx="10" cy="10" r="6.5"/><path d="m15 15 5 5"/>',
  back: '<path d="m14 5-7 7 7 7"/>',
  check: '<path d="m4 12 5 5L20 6"/>',
  close: '<path d="m6 6 12 12m0-12L6 18"/>',
  play: '<path fill="currentColor" d="M8 5.5v13l10.5-6.5z"/>',
  pause:
    '<path fill="currentColor" d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/>',
  repeat:
    '<path d="m17 3 3 3-3 3M4 11V9a3 3 0 0 1 3-3h13M7 21l-3-3 3-3m16-2v2a3 3 0 0 1-3 3H4"/>',
};
const icon = (name) =>
  '<svg viewBox="0 0 24 24" aria-hidden="true">' + symbols[name] + "</svg>";
const esc = (val) =>
  String(val == null ? "" : val).replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
function read(key, fallback) {
  try {
    const val = localStorage.getItem("phrase-room." + key);
    return val === null ? fallback : JSON.parse(val);
  } catch {
    return fallback;
  }
}
function write(key, val) {
  try {
    localStorage.setItem("phrase-room." + key, JSON.stringify(val));
    return true;
  } catch {
    return false;
  }
}
let lang = read("language", "zh"),
  library = [],
  saved = read("saved", []),
  history = read("history", []);
if (!Array.isArray(saved)) saved = [];
if (!Array.isArray(history)) history = [];
const T = (zh, ko) => (lang === "ko" ? ko : zh);
const label = (pair) => pair[lang === "ko" ? 1 : 0];
const groupName = (g) =>
  ({
    daily: T("日常生活", "일상"),
    social: T("朋友聊天", "친구와 대화"),
    work: T("学习与工作", "학업과 업무"),
  })[g] || "";
let libraryFilter = "all",
  searchText = "",
  bookTab = "saved",
  draft = "",
  context = "",
  active = null,
  pending = false,
  failed = "",
  listError = false;
// Staged answers (D1): the first verified examples arrive at once; a background search may add
// more. notice = {kind, id} is the banner above the chat; running holds the ids still searching.
let notice = null;
// The quick translation of the request in flight (PR5): {ticket, text, note}. A model's line sent
// before any podcast check; it is generated, never a verified example.
let quick = null;
// The server's cap on questions per day for everyone (X-Coach-Daily-Limit / -Remaining): {limit,
// left} from the last coach reply; null when the server has none.
let daily = null;
const running = new Set();
const RUNNING_LIMIT = 1; // the server answers one request per process, so wait for the search to end
const SLOW_SECONDS = 30; // after this the wait line says the examples take a little longer
const app = $("app"),
  dialog = $("dialog");
function go(path) {
  if (location.hash.slice(1) === path) render();
  else location.hash = path;
}
function url(value) {
  try {
    const u = new URL(value);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "";
  } catch {
    return "";
  }
}
function link(href, text) {
  const safe = url(href);
  return safe
    ? '<a href="' +
        esc(safe) +
        '" target="_blank" rel="noopener noreferrer">' +
        esc(text) +
        "</a>"
    : "";
}
function replayLink(turn) {
  if (turn.local || (turn.stage === "pending" && !turn.replayUrl)) return "";
  if (url(turn.replayUrl)) {
    const target = new URL(turn.replayUrl);
    target.searchParams.set("lang", lang);
    return '<div class="workflow-action"><a data-replay href="' + esc(target.href) + '">' +
      T("查看本次流程", "이번 실행 과정 보기") + "</a></div>";
  }
  return '<p class="workflow-note">' + T("这条回答没有可用的流程链接。", "이 답변에는 실행 과정 링크가 없어요.") + "</p>";
}
function toast(message) {
  $("toast").textContent = message;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").textContent = ""), 2200);
}
function storeList(key, rows) {
  if (!write(key, rows))
    toast(
      T(
        "设备存储不可用，本次会话仍可使用。",
        "기기 저장소를 사용할 수 없어 이번 세션에만 보관합니다.",
      ),
    );
}
function frame(tab) {
  $("coach-pet").setAttribute("aria-label", T("和小蓝玩", "파랑이와 놀기"));
  setMascotActivity();
  document.documentElement.lang = lang === "ko" ? "ko" : "zh-CN";
  document.title = "English Coach · " + T("英语表达教练", "영어 표현 코치");
  $("nav").innerHTML = [
    ["home", "home", T("练习台", "연습")],
    ["library", "library", T("表达库", "표현 모음")],
    ["book", "book", T("学习本", "학습 노트")],
    ["podcast", "podcast", T("播客", "팟캐스트")],
  ]
    .map(
      ([id, s, name]) =>
        '<a href="#' +
        id +
        '" ' +
        (tab === id ? 'aria-current="page"' : "") +
        ">" +
        icon(s) +
        '<span class="nav-label">' +
        esc(name) +
        (id === "podcast"
          ? '<span class="pod-mark" id="pod-mark">' +
            podMark() +
            '</span><span class="sr-only" id="pod-said">' +
            podSaid() +
            "</span>"
          : "") +
        "</span>" +
        "</a>",
    )
    .join("");
  $("nav").setAttribute("aria-label", T("主导航", "주 메뉴"));
  $("language").innerHTML = icon("lang") + " " + T("한국어", "中文");
  $("settings").innerHTML = icon("settings");
  $("settings").setAttribute("aria-label", T("连接设置", "연결 설정"));
}
function tile(e) {
  return (
    '<button class="tile" data-card="' +
    esc(e.id) +
    '"><span class="tile-top"><span class="glyph ' +
    esc(e.group) +
    '">' +
    icon(e.group) +
    '</span><span class="category">' +
    groupName(e.group) +
    "</span></span><h3>" +
    esc(label(e.title)) +
    '</h3><span class="key">' +
    esc(e.key_phrase) +
    "</span></button>"
  );
}
const turns = [];
let progress = [];
function progressText() {
  if (!progress.length) return T("正在连接教练…", "코치에 연결하는 중…");
  const current = progress[progress.length - 1];
  const recent = progress.slice(-4, -1).map(step => workflowStage(step.stage, lang).label);
  return '<strong>' + workflowStage(current.stage, lang).label +
    (current.count > 1 ? ' ×' + current.count : '') + '</strong>' +
    (recent.length ? '<small>' + recent.join(' → ') + '</small>' : '');
}

function replayUrl(runId) {
  return /^[0-9a-f-]{36}$/i.test(runId || "") ? apiBase() + "/api/search?run_id=" + encodeURIComponent(runId) : null;
}
function updateProgress(stage) {
  const last = progress[progress.length - 1];
  if (last && workflowStage(last.stage, lang).kind === workflowStage(stage, lang).kind) last.count++;
  else progress.push({stage, count: 1});
  setMascotActivity();
  const area = $("coach-progress");
  if (area) area.innerHTML = progressText();
}
function setMascotActivity() {
  const stage = progress.length && progress[progress.length - 1].stage;
  if (pending) cat.update(stage && workflowStage(stage, lang).kind === "search" ? "search" : "think");
  else cat.update(draft.trim() ? "typing" : turns.length && !failed ? "ready" : "idle");
}
function home() {
  const hasThread = turns.length || pending || failed;
  const previous = turns
    .map(
      (turn) =>
        '<div class="user-message">' +
        esc(turn.question) +
        "</div>" +
        '<div class="assistant-message">' +
        quickBubble(turn.quick, true) +
        '<div id="replay-' + esc(turn.id) + '">' + replayLink(turn) + "</div>" +

        turn.expressions.map(resultCard).join("") +
        more(turn) +
        (turn.note ? "<p>" + esc(turn.note) + "</p>" : "") +
        (!turn.expressions.length && !turn.note && !turn.stage
          ? T(
              "表达库里还没有匹配项。可以换个关键词或问教练。",
              "일치하는 표현이 없어요. 다른 검색어나 코치 질문을 사용해 보세요.",
            )
          : "") +
        "</div>",
    )
    .join("");
  const [waitText, waitTime] = waitingLine();
  const status =
    pending || failed
      ? '<div class="user-message">' +
        esc(lastQuestion) +
        "</div>" +
        quickBubble(liveQuick()) +
        (pending
          ? '<div class="waiting" role="status">' +
            cat.art +
            '<div id="coach-progress">' + progressText() + '</div>' +
            '<span class="wait-time" id="wait-time">' + waitTime + '</span></div>'

          : '<div class="status error" role="alert">' +
            esc(failedMessage()) +
            " <button data-retry>" +
            T("重试", "재시도") +
            "</button> <button data-settings>" +
            T("连接设置", "연결 설정") +
            "</button></div>")
      : "";
  return (
    '<section class="conversation ' +
    (hasThread ? "with-turns" : "welcome") +
    '">' +
    (hasThread
      ? '<div class="turn-list">' + previous + status + "</div>"
      : '<div class="greeting">' +
        '<button type="button" class="greeting-cat" data-pet-open aria-haspopup="dialog" aria-label="' + T("和小蓝玩", "파랑이와 놀기") + '">' + cat.art + "</button>" +
        "<h1>" +
        T("今天想怎么说？", "오늘은 어떤 말을 해 볼까요?") +
        "</h1></div>") +
    '<form id="ask" class="chat-form"><textarea id="question" required maxlength="1800" rows="2" aria-label="' +
    T("你的问题", "질문") +
    '" placeholder="' +
    T("写下你想说的话…", "하고 싶은 말을 적어 보세요…") +
    '">' +
    esc(draft) +
    "</textarea>" +
    '<div class="compose-actions"><div class="method" role="group" aria-label="' +
    T("回答方式", "응답 방식") +
    '">' +
    ["local", "coach"]
      .map(
        (v, i) =>
          '<button type="button" class="filter" data-mode="' +
          v +
          '" aria-pressed="' +
          (v === mode) +
          '">' +
          (i ? T("问教练", "코치에게 질문") : T("查表达库", "표현 모음 검색")) +
          "</button>",
      )
      .join("") +
    '</div><button type="submit" class="send" aria-label="' +
    T("发送", "보내기") +
    '" ' +
    (sendBlocked() ? "disabled" : "") +
    ">↑</button></div>" +
    '<p class="hold" id="hold">' +
    holdLine() +
    "</p></form>" +
    (mode === "coach" && staticOnly && !read("server", "")
      ? '<p class="cloud-pending" role="status">' +
        T(
          "云端教练尚未上线，你可以先查表达库。",
          "클라우드 코치는 준비 중이에요. 지금은 표현 모음을 검색할 수 있어요.",
        ) +
        "</p>"
      : "") +
    libraryStatus() +
    "</section>"
  );
}
// ------------------------------------------------------------ staged answers (D1)
function holding() {
  return mode === "coach" && running.size >= RUNNING_LIMIT;
}
function sendBlocked() {
  return (
    pending ||
    holding() ||
    (staticOnly && mode === "coach" && !read("server", ""))
  );
}
function holdText() {
  return T(
    "上一条的例句查找结束后即可发送",
    "앞 질문의 예문 찾기가 끝나면 보낼 수 있어요",
  );
}
function readDaily(r) {
  const limit = parseInt(r.headers.get("X-Coach-Daily-Limit") || "", 10),
    left = parseInt(r.headers.get("X-Coach-Daily-Remaining") || "", 10);
  daily = limit >= 0 ? { limit, left: left >= 0 ? left : null } : null;
}
function holdLine() {
  if (holding()) return holdText();
  return mode === "coach" && daily && daily.left !== null
    ? T("今天还可以提问 " + daily.left + " 次", "오늘 남은 질문 " + daily.left + "회")
    : "";
}
// The quick translation (PR5) has its own label and no save button: it was generated before any
// podcast check. Once verified examples arrive (done) it stays above them, smaller and muted.
function quickBubble(qk, done = false) {
  if (!qk || typeof qk.text !== "string" || !qk.text) return "";
  return (
    '<div class="quick' +
    (done ? " done" : "") +
    '"><p class="quick-label">' +
    T("快速翻译 · 尚未核对播客例句", "빠른 번역 · 팟캐스트 예문 확인 전") +
    '</p><p class="quick-text" lang="en">' +
    esc(qk.text) +
    "</p>" +
    (qk.note ? '<p class="quick-note">' + esc(qk.note) + "</p>" : "") +
    "</div>"
  );
}
function liveQuick() {
  return quick && quick.ticket === ticket ? quick : null;
}
let waitStart = 0,
  waitTick = 0;
function waitingLine() {
  const s = Math.max(0, Math.floor((Date.now() - waitStart) / 1000));
  return [
    s >= SLOW_SECONDS
      ? T("还在核对例句，需要多一点时间…", "예문을 찾느라 조금 더 걸려요…")
      : liveQuick()
        ? T("正在核对播客例句…", "팟캐스트 예문을 확인하고 있어요…")
        : T("正在查找表达…", "표현을 찾고 있어요…"),
    T(s + " 秒", s + "초"),
  ];
}
function startWaiting() {
  waitStart = Date.now();
  clearInterval(waitTick);
  waitTick = setInterval(() => {
    const text = $("wait-text"),
      time = $("wait-time");
    if (!time) return;
    const [line, seconds] = waitingLine();
    if (text && text.textContent !== line) text.textContent = line;
    time.textContent = seconds;
  }, 1000);
}
function stopWaiting() {
  clearInterval(waitTick);
}
function findEntry(id) {
  return (
    history.find((h) => h && h.id === id) || turns.find((t) => t.id === id)
  );
}
function unseen() {
  return history.reduce(
    (n, h) =>
      n + (h && h.seen === false && Array.isArray(h.added) ? h.added.length : 0),
    0,
  );
}
function podMark() {
  const n = unseen();
  if (n)
    return '<span class="badge" aria-hidden="true">' + (n > 9 ? "9+" : n) + "</span>";
  return running.size ? '<span class="dot" aria-hidden="true"></span>' : "";
}
function podSaid() {
  const n = unseen();
  if (n) return T("，" + n + " 条新例句", ", 새 예문 " + n + "개");
  return running.size ? T("，查找中", ", 찾는 중") : "";
}
function paintNav() {
  const mark = $("pod-mark"),
    said = $("pod-said");
  if (mark) mark.innerHTML = podMark();
  if (said) said.textContent = podSaid();
}
function paintComposer() {
  const send = document.querySelector("#ask .send"),
    hold = $("hold");
  if (send) send.disabled = sendBlocked();
  if (hold) hold.textContent = holdLine();
}
// The live region speaks only when an answer arrives: the first examples and the end of the search.
function say(text) {
  const live = $("announce");
  live.textContent = "";
  setTimeout(() => (live.textContent = text), 60);
}
// The empty slot under a staged answer: searching, then a pointer to what the search added.
function more(e, onPage = false) {
  if (!e.stage) return "";
  const n = Array.isArray(e.added) ? e.added.length : 0,
    text = (s) => '<span class="more-text">' + s + "</span>";
  let kind, body;
  if (e.stage === "pending") {
    kind = "pending";
    body =
      '<span class="spinner" aria-hidden="true"></span>' +
      text(T("空位 · 正在查找播客例句", "빈 자리 · 팟캐스트 예문 찾는 중"));
  } else if (n) {
    if (onPage) return "";
    kind = "added";
    body =
      icon("podcast") +
      text(T("已在播客页新增 " + n + " 条例句", "팟캐스트 탭에 예문 " + n + "개를 더했어요")) +
      '<a href="#podcast">' +
      T("查看", "보기") +
      "</a>";
  } else if (e.stage === "done") {
    kind = "none";
    body = text(T("这次没有找到更多例句", "이번에는 예문을 더 찾지 못했어요"));
  } else {
    kind = "none";
    body =
      text(T("例句查找已中断", "예문 찾기가 중단됐어요")) +
      '<button type="button" data-again="' +
      esc(e.id) +
      '">' +
      T("重新查找", "다시 찾기") +
      "</button>";
  }
  return (
    '<div class="more ' + kind + '" id="more-' + esc(e.id) + '">' + body + "</div>"
  );
}
function paintMore(e) {
  const slot = $("more-" + e.id);
  if (slot) slot.outerHTML = more(e, !document.body.classList.contains("chat-home"));
}
function renderNotice() {
  const box = $("notice"),
    e = notice && findEntry(notice.id);
  if (!e) {
    notice = null;
    box.hidden = true;
    box.className = "";
    box.innerHTML = "";
    return;
  }
  const n = Array.isArray(e.added) ? e.added.length : 0,
    again =
      '<button type="button" data-again="' +
      esc(e.id) +
      '">' +
      T("重新查找", "다시 찾기") +
      "</button>";
  const [lead, title, line, actions] = {
    running: [
      '<span class="spinner" aria-hidden="true"></span>',
      T("正在查找更多播客例句", "팟캐스트 예문을 더 찾는 중"),
      T("保持此页面打开，找到后会告诉你", "이 화면을 열어 두면 끝날 때 알려드릴게요"),
      "",
    ],
    added: [
      icon("check"),
      T("又找到 " + n + " 条播客例句", "팟캐스트 예문 " + n + "개를 더 찾았어요"),
      "",
      '<a href="#podcast">' + icon("podcast") + T("在播客页查看", "팟캐스트 탭에서 보기") + "</a>",
    ],
    none: [
      icon("check"),
      T("这次没有找到更多播客例句", "이번에는 팟캐스트 예문을 더 찾지 못했어요"),
      T("先前的结果可以照常使用", "처음 결과는 그대로 쓸 수 있어요"),
      "",
    ],
    stopped: [
      icon("podcast"),
      T("查找更多例句时中断了", "예문을 더 찾다가 중단됐어요"),
      T("现有结果可以照常使用", "지금 결과는 그대로 쓸 수 있어요"),
      again,
    ],
    reentry: [
      icon("podcast"),
      T("你离开期间，例句查找已停止", "자리를 비운 사이 예문 찾기가 멈췄어요"),
      T("先前的结果仍然保留", "처음 결과는 그대로 있어요"),
      '<button type="button" data-open="' +
        esc(e.id) +
        '">' +
        T("查看先前结果", "처음 결과 보기") +
        "</button>" +
        again,
    ],
  }[notice.kind];
  box.hidden = false;
  box.className = "notice " + notice.kind;
  box.innerHTML =
    '<div class="notice-card"><span class="notice-lead">' +
    lead +
    '</span><p class="notice-text"><b>' +
    title +
    "</b>" +
    (line ? "<span> · " + line + "</span>" : "") +
    "</p>" +
    (notice.kind === "reentry"
      ? '<p class="notice-q">' + esc(e.question) + "</p>"
      : "") +
    (actions ? '<div class="notice-actions">' + actions + "</div>" : "") +
    (notice.kind === "running"
      ? ""
      : '<button type="button" class="icon-btn notice-close" data-notice-close aria-label="' +
        T("关闭提示", "알림 닫기") +
        '">' +
        icon("close") +
        "</button>") +
    "</div>";
}
// The "podcast" tab: only the examples the background search added, grouped by question.
function podcastPage() {
  const groups = history.filter((h) => h && Array.isArray(h.added) && h.added.length),
    fresh = new Set(groups.filter((h) => h.seen === false).map((h) => h.id)),
    searching = history.filter((h) => h && running.has(h.id));
  if (fresh.size) {
    groups.forEach((h) => (h.seen = true));
    storeList("history", history);
  }
  if (notice && notice.kind === "added") notice = null;
  return (
    "<h1>" +
    T("播客例句", "팟캐스트 예문") +
    '</h1><p class="sub">' +
    T(
      "这里按问题汇总聊天回答之后新找到的例句。聊天里先收到的回答不会改变。",
      "채팅 답 뒤에 더 찾은 예문만 질문별로 모아요. 채팅에서 먼저 받은 답은 그대로예요.",
    ) +
    "</p>" +
    searching
      .map(
        (h) =>
          '<p class="status pod-running"><span class="spinner" aria-hidden="true"></span>' +
          T("查找中", "찾는 중") +
          " · " +
          esc(h.question) +
          "</p>",
      )
      .join("") +
    (groups.length
      ? groups
          .map(
            (h) =>
              '<section class="pod-group' +
              (fresh.has(h.id) ? " fresh" : "") +
              '"><h2 class="pod-q">' +
              esc(h.question) +
              '</h2><p class="pod-meta">' +
              (fresh.has(h.id)
                ? '<span class="chip-new">' + T("新增", "새로 추가") + "</span>"
                : "") +
              "<span>" +
              T(
                "新找到 " + h.added.length + " 条例句",
                "새로 찾은 예문 " + h.added.length + "개",
              ) +
              "</span><span>" +
              T(
                "聊天里先收到的 " + h.expressions.length + " 条保持不变",
                "채팅에서 먼저 받은 " + h.expressions.length + "개는 그대로예요",
              ) +
              "</span></p>" +
              h.added.map(resultCard).join("") +
              "</section>",
          )
          .join("")
      : searching.length
        ? ""
        : '<div class="empty">' +
          T(
            "还没有新找到的例句。向教练提问后，先前回答之后找到的例句会汇总在这里。",
            "아직 더 찾은 예문이 없어요. 코치에게 질문하면 처음 답 뒤에 더 찾은 예문이 여기에 모여요.",
          ) +
          "</div>")
  );
}
function libraryStatus() {
  return listError
    ? '<p class="status error">' +
        T("表达集暂时没有加载成功。", "표현 모음을 불러오지 못했어요.") +
        " <button data-reload>" +
        T("重新加载", "다시 불러오기") +
        "</button></p>"
    : "";
}
function matches(e, q) {
  return [
    e.id,
    e.expression,
    e.key_phrase,
    e.keywords,
    ...e.title,
    ...e.meaning,
  ]
    .join(" ")
    .toLocaleLowerCase()
    .includes(q.trim().toLocaleLowerCase());
}
function libraryResults() {
  const r = library.filter(
    (e) =>
      (libraryFilter === "all" || e.group === libraryFilter) &&
      matches(e, searchText),
  );
  return r.length
    ? '<div class="tiles">' + r.map(tile).join("") + "</div>"
    : '<div class="empty">' +
        T(
          "没有找到匹配的表达。可以换个词，或到练习台问教练。",
          "일치하는 표현이 없어요. 다른 단어를 입력하거나 코치에게 질문해 보세요.",
        ) +
        "</div>";
}
function shelf() {
  return (
    "<h1>" +
    T("表达库", "표현 모음") +
    '</h1><p class="sub">' +
    T(
      "按场景找用法，每张卡都能翻到播客原句。",
      "상황별 쓰임과 팟캐스트 원문을 함께 확인하세요.",
    ) +
    '</p><div class="searchbar">' +
    icon("search") +
    '<input id="query" type="search" aria-label="' +
    T("搜索表达库", "표현 검색") +
    '" value="' +
    esc(searchText) +
    '" placeholder="' +
    T("搜索场景、中文或英文短语", "상황, 한국어 또는 영어 검색") +
    '"></div><div class="filters">' +
    ["all", "daily", "social", "work"]
      .map(
        (v) =>
          '<button class="filter" data-filter="' +
          v +
          '" aria-pressed="' +
          (v === libraryFilter) +
          '">' +
          (v === "all" ? T("全部", "전체") : groupName(v)) +
          "</button>",
      )
      .join("") +
    '</div><div id="cards">' +
    libraryResults() +
    "</div>" +
    libraryStatus()
  );
}
function source(c) {
  if (!c)
    return (
      '<div class="source meta">' +
      T(
        "这条建议暂时没有核实到播客原句。",
        "이 제안과 일치하는 팟캐스트 원문을 아직 확인하지 못했어요.",
      ) +
      "</div>"
    );
  return (
    '<details class="source"><summary>' +
    T("查看播客原句", "팟캐스트 원문 보기") +
    " · " +
    esc(c.episode_title) +
    '</summary><blockquote lang="en">' +
    esc(c.quote) +
    "</blockquote>" +
    (c.source_use ? '<p class="compact">' + esc(c.source_use) + "</p>" : "") +
    '<div class="linkrow">' +
    link(c.episode_url, T("节目页面", "에피소드 페이지")) +
    link(c.transcript_url, T("字幕原文", "자막 원문")) +
    '</div><div class="meta">' +
    esc(c.attribution || "") +
    " " +
    link(c.license_url, c.license_id || T("许可", "라이선스")) +
    "</div></details>"
  );
}
function key(e) {
  return e.expression + "|" + (e.citation ? e.citation.episode_url : "");
}
let visible = [];
function resultCard(e) {
  const i = visible.push(e) - 1,
    on = saved.some((s) => key(e) === key(s));
  return (
    '<article class="answer-card"><div class="row"><div><div class="meta">' +
    esc(e.key_phrase || T("英语表达", "영어 표현")) +
    '</div><h2 class="phrase" lang="en">' +
    esc(e.expression) +
    '</h2></div><button class="icon-btn" data-save="' +
    i +
    '" aria-pressed="' +
    on +
    '" aria-label="' +
    (on ? T("取消收藏", "저장 해제") : T("收藏表达", "표현 저장")) +
    '">' +
    icon(on ? "saved" : "book") +
    "</button></div><p>" +
    esc(e.meaning ? label(e.meaning) : e.note) +
    "</p>" +
    listen(e, i) +
    source(e.citation) +
    "</article>"
  );
}
// ------------------------------------------------------------ podcast clip player (PR6 v2)
// One shared <audio preload="none"> plays the cited part of the episode. "Listen" opens a clip
// player under the card and asks the server where the quote is spoken (GET /api/audio/alignment):
// "ready" gives the caption lines around the quote with their timing; "pending" is asked again
// every 1.5 s for up to 40 s; anything else falls back to the citation's own estimate, shown as
// "rough". A "ready" answer timed from the transcript's time markers (method "anchored", no speech
// recognition) plays at once; while it says "refining" the server is still recognising the audio, so
// it is asked again in the background and a better answer replaces the lines (refinePlace).
// Loop math follows draw-lang's clipLoop: the range is the quote, the whole excerpt or one
// tapped line, played with 400 ms of padding, then repeated or stopped at its end.
const CLIP_DEFAULT_MS = 20000,
  PAD_MS = 400,
  RATES = [0.75, 1, 1.25],
  ALIGN_POLL_MS = 1500,
  ALIGN_WAIT_MS = 40000,
  REFINE_WAIT_MS = 90000,
  LOAD_TIMEOUT_MS = 15000;
const player =
  $("clip") ||
  document.body.appendChild(
    Object.assign(document.createElement("audio"), { id: "clip", preload: "none" }),
  );
const aligned = new Map(); // clip key -> ready model, so a reopened clip plays at once
let clipRate = RATES.includes(read("clip-rate", 1)) ? read("clip-rate", 1) : 1,
  clipLoop = true,
  clipFrame = 0,
  clipAttempt = 0,
  clipTimer = 0;
// The open clip: {key, cite, phase: "finding"|"ready", model, state: "idle"|"loading"|"playing"|
// "paused"|"error", range: "match"|"all"|line index, plays, active (line index or -1), late}
let clip = null;
const msOf = (v) => (Number.isFinite(v) && v >= 0 ? v : null);
function hasAudio(c) {
  return Boolean(c && url(c.audio_url));
}
function clipKey(c) {
  return url(c.audio_url) + "#" + (c.chunk_id || msOf(c.audio_start_ms)) + "#" + (c.quote || "");
}
// What the player works on: caption lines in ms, the lines the quote overlaps (match), the quote's
// own time when known, and whether the position is only estimated.
function clipModel(src, cues, quote, method, title) {
  let match = { first: 0, last: cues.length - 1 };
  if (quote) {
    const hit = cues.flatMap((q, k) => (q.end > quote.start && q.start < quote.end ? [k] : []));
    let near = 0;
    cues.forEach((q, k) => {
      if (Math.abs(q.start - quote.start) < Math.abs(cues[near].start - quote.start)) near = k;
    });
    match = hit.length ? { first: hit[0], last: hit[hit.length - 1] } : { first: near, last: near };
  }
  return { src, cues, quote, match, method, rough: method === "estimated", title, marks: [] };
}
// The citation's own fields: one line (the quote) from audio_start_ms to audio_end_ms or +20 s.
function roughModel(c) {
  const known = msOf(c.audio_start_ms) !== null,
    start = known ? c.audio_start_ms : 0,
    stop = msOf(c.audio_end_ms),
    end = stop !== null && stop > start ? stop : start + CLIP_DEFAULT_MS;
  return clipModel(
    url(c.audio_url),
    [{ text: c.quote || "", start, end }],
    null,
    c.audio_estimated === true || !known ? "estimated" : "stored",
    c.episode_title,
  );
}
function alignedModel(c, r) {
  const src = url(r.audio_url) || url(c.audio_url),
    cues = (Array.isArray(r.cues) ? r.cues : [])
      .filter(
        (q) =>
          q &&
          typeof q.text === "string" &&
          q.text.trim() &&
          msOf(q.start_ms) !== null &&
          msOf(q.end_ms) !== null &&
          q.end_ms > q.start_ms,
      )
      .map((q) => ({ text: q.text.trim(), start: q.start_ms, end: q.end_ms }))
      .sort((a, b) => a.start - b.start)
      .slice(0, 60),
    from = msOf(r.quote_start_ms),
    to = msOf(r.quote_end_ms),
    quote = from !== null && to !== null && to > from ? { start: from, end: to } : null;
  if (!src || (!cues.length && !quote)) return null;
  const lines = cues.length ? cues : [{ text: c.quote || "", start: quote.start, end: quote.end }],
    method = ["asr", "stored", "anchored", "estimated"].includes(r.method) ? r.method : "estimated",
    m = clipModel(src, lines, quote, method, c.episode_title);
  if (cues.length) m.marks = quoteMarks(lines, m.match, c.quote || "");
  m.refining = r.refining === true;
  return m;
}
// Where the quote's words sit in the captions (ASR text can differ a little from the transcript):
// the run of caption words sharing the most words with the quote, as one [from, to) character range
// per line. Without a convincing run the quote's lines are only tinted.
function quoteMarks(cues, span, quote) {
  const words = (s) =>
    Array.from(s.matchAll(/[\p{L}\p{N}][\p{L}\p{N}'’]*/gu), (x) => ({
      w: x[0].toLowerCase().replace(/['’]/g, ""),
      i: x.index,
      j: x.index + x[0].length,
    }));
  const q = words(quote).map((x) => x.w),
    want = new Set(q),
    toks = [];
  for (let k = Math.max(0, span.first - 1); k <= Math.min(cues.length - 1, span.last + 1); k++)
    words(cues[k].text).forEach((t) => toks.push({ ...t, k }));
  let best = 0,
    at = 0;
  for (let s = 0; s < toks.length; s++) {
    let hit = 0;
    for (let t = s; t < Math.min(toks.length, s + q.length); t++) if (want.has(toks[t].w)) hit++;
    if (hit > best) [best, at] = [hit, s];
  }
  if (!q.length || best < Math.min(q.length, Math.max(2, Math.ceil(q.length / 2)))) return [];
  const run = toks.slice(at, at + q.length);
  while (run.length && !want.has(run[run.length - 1].w)) run.pop();
  while (run.length && !want.has(run[0].w)) run.shift();
  const marks = [];
  run.forEach((t) => (marks[t.k] = marks[t.k] ? [marks[t.k][0], t.j] : [t.i, t.j]));
  return marks;
}
function clipSpan(m, range) {
  if (range === "match") return m.match;
  if (range === "all") return { first: 0, last: m.cues.length - 1 };
  return { first: range, last: range };
}
function clipBounds(m, range) {
  if (range === "match" && m.quote)
    return { start: Math.max(0, m.quote.start - PAD_MS), end: m.quote.end + PAD_MS };
  const s = clipSpan(m, range);
  return { start: Math.max(0, m.cues[s.first].start - PAD_MS), end: m.cues[s.last].end + PAD_MS };
}
function mmss(ms) {
  const s = Math.floor(ms / 1000),
    two = (n) => String(n).padStart(2, "0");
  return (
    (s >= 3600 ? Math.floor(s / 3600) + ":" + two(Math.floor(s / 60) % 60) : Math.floor(s / 60)) +
    ":" +
    two(s % 60)
  );
}
// ---- clip player: markup
function listenLabel(open) {
  return open ? "■ " + T("关闭", "닫기") : "▶ " + T("听这一段", "이 부분 듣기");
}
function listen(e, i) {
  if (!hasAudio(e.citation)) return "";
  return (
    '<div class="listen-box" data-listen-box="' + i + '">' + listenBody(e.citation, i) + "</div>"
  );
}
function listenBody(c, i) {
  const open = Boolean(clip && clip.key === clipKey(c)),
    m = aligned.get(clipKey(c)) || roughModel(c);
  return (
    '<div class="listen"><button type="button" class="listen-btn" data-listen="' +
    i +
    '" aria-expanded="' +
    open +
    '">' +
    listenLabel(open) +
    "</button>" +
    (open ? "" : '<span class="listen-at' + (m.rough ? " rough" : "") + '">' + placeText(m) + "</span>") +
    "</div>" +
    (open ? clipPanel() : "")
  );
}
function placeText(m) {
  const at = m.quote ? m.quote.start : m.cues[m.match.first].start;
  return (
    (m.rough
      ? T("大致位置", "대략 위치") + " · "
      : m.method === "asr"
        ? T("已按音频校准", "음성으로 맞춘 위치") + " · "
        : m.method === "anchored"
          ? T("按文字稿时间标记", "대본 시간 표시 기준") + " · "
          : "") + mmss(at)
  );
}
function playFace() {
  return clip.state === "loading"
    ? '<span class="spinner" aria-hidden="true"></span>'
    : icon(clip.state === "playing" ? "pause" : "play");
}
function playLabel() {
  return clip.state === "playing" || clip.state === "loading"
    ? T("暂停", "일시정지")
    : T("播放", "재생");
}
function rateLabel() {
  return T("播放速度 " + clipRate + " 倍，点一下切换", "재생 속도 " + clipRate + "배, 눌러서 바꾸기");
}
function loopCount() {
  return clipLoop && clip.state !== "idle" && clip.state !== "error"
    ? T(clip.plays + " 次", clip.plays + "회")
    : "";
}
function cueClass(m, span, k) {
  return (
    "clip-cue" +
    (k >= m.match.first && k <= m.match.last ? " match" : "") +
    (k === clip.active ? " active" : "") +
    (k < span.first || k > span.last ? " out" : "")
  );
}
function cueText(m, k) {
  const t = m.cues[k].text,
    r = m.marks[k];
  return r
    ? esc(t.slice(0, r[0])) + "<mark>" + esc(t.slice(r[0], r[1])) + "</mark>" + esc(t.slice(r[1]))
    : esc(t);
}
function clipPanel() {
  if (clip.phase === "finding")
    return (
      '<div class="clip finding" data-clip-panel><p class="clip-find" role="status">' +
      '<span class="spinner" aria-hidden="true"></span><span>' +
      T("正在查找准确位置…", "정확한 위치 찾는 중…") +
      '</span></p><button type="button" class="clip-now" data-clip="rough">' +
      T("先听大致位置", "대략 위치로 먼저 듣기") +
      "</button></div>"
    );
  const m = clip.model,
    span = clipSpan(m, clip.range),
    many = m.cues.length > 1,
    seg = (v, text) =>
      '<button type="button" data-clip-range="' +
      v +
      '" aria-pressed="' +
      (clip.range === v) +
      '">' +
      text +
      "</button>";
  return (
    '<div class="clip" data-clip-panel><div class="clip-controls">' +
    '<button type="button" class="clip-play" data-clip="toggle" aria-label="' +
    playLabel() +
    '">' +
    playFace() +
    '</button><div class="clip-meta"><strong class="clip-title">' +
    esc(m.title || T("播客原声", "팟캐스트 원음")) +
    '</strong><span class="clip-at' +
    (m.rough ? " rough" : "") +
    '">' +
    placeText(m) +
    '</span></div><button type="button" class="clip-rate" data-clip="rate" aria-label="' +
    rateLabel() +
    '">' +
    clipRate +
    "×</button></div>" +
    '<div class="clip-bar"><button type="button" class="clip-loop" data-clip="loop" aria-pressed="' +
    clipLoop +
    '">' +
    icon("repeat") +
    "<span>" +
    T("循环", "반복") +
    '</span><span class="loop-count">' +
    loopCount() +
    "</span></button>" +
    (many
      ? '<div class="clip-seg" role="group" aria-label="' +
        T("循环范围", "반복 구간") +
        '">' +
        seg("match", T("这一句", "이 문장")) +
        seg("all", T("含上下文", "앞뒤 포함")) +
        "</div>"
      : "") +
    "</div>" +
    (m.rough
      ? '<p class="clip-note">' +
        (clip.late
          ? T(
              "准确位置还没准备好，先按大致位置播放。引用句可能稍早或稍晚出现。",
              "정확한 위치가 아직 준비되지 않아 대략 위치로 들려드려요. 인용 문장이 조금 앞이나 뒤에서 나올 수 있어요.",
            )
          : T(
              "大致位置：按字幕文字位置估算，引用句可能稍早或稍晚出现。",
              "대략 위치예요. 글자 위치로 추정해서 인용 문장이 조금 앞이나 뒤에서 나올 수 있어요.",
            )) +
        "</p>"
      : "") +
    '<p class="clip-note error" role="alert"' +
    (clip.state === "error" ? "" : " hidden") +
    ">" +
    T("无法加载音频，字幕仍可查看。", "오디오를 불러오지 못했어요. 자막은 그대로 볼 수 있어요.") +
    '</p><ol class="clip-cues" aria-label="' +
    (many
      ? T("字幕。点一句只循环这一句", "자막. 문장을 누르면 그 문장만 반복해요")
      : T("字幕", "자막")) +
    '">' +
    m.cues
      .map(
        (q, k) =>
          '<li><button type="button" lang="en" class="' +
          cueClass(m, span, k) +
          '" data-clip-cue="' +
          k +
          '"' +
          (k === clip.active ? ' aria-current="true"' : "") +
          ">" +
          cueText(m, k) +
          "</button></li>",
      )
      .join("") +
    "</ol></div>"
  );
}
// Rebuild the listen rows (a clip opened, closed or found its place) without redrawing the page.
function redrawClip() {
  const had = document.activeElement,
    inside = had && had.closest && had.closest("[data-listen-box]"),
    back = inside && had.dataset.listen;
  document.querySelectorAll("[data-listen-box]").forEach((box) => {
    const i = Number(box.dataset.listenBox),
      e = visible[i];
    if (e && hasAudio(e.citation)) box.innerHTML = listenBody(e.citation, i);
  });
  if (!inside) return;
  const next =
    (back !== undefined && document.querySelector('[data-listen="' + back + '"]')) ||
    document.querySelector('[data-clip="toggle"]');
  if (next) next.focus({ preventScroll: true });
}
// Repaint the open player in place: play state, loop, rate, range and the spoken line.
function paintClip() {
  if (!clip || !clip.model) return;
  const m = clip.model,
    span = clipSpan(m, clip.range);
  document.querySelectorAll("[data-clip-panel]").forEach((p) => {
    const play = p.querySelector('[data-clip="toggle"]');
    if (!play) return;
    play.innerHTML = playFace();
    play.setAttribute("aria-label", playLabel());
    const loop = p.querySelector('[data-clip="loop"]'),
      rate = p.querySelector('[data-clip="rate"]');
    loop.setAttribute("aria-pressed", String(clipLoop));
    loop.querySelector(".loop-count").textContent = loopCount();
    rate.textContent = clipRate + "×";
    rate.setAttribute("aria-label", rateLabel());
    p.querySelectorAll("[data-clip-range]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.clipRange === clip.range)),
    );
    p.querySelector(".clip-note.error").hidden = clip.state !== "error";
    p.querySelectorAll("[data-clip-cue]").forEach((b) => {
      const k = Number(b.dataset.clipCue);
      b.className = cueClass(m, span, k);
      if (k === clip.active) b.setAttribute("aria-current", "true");
      else b.removeAttribute("aria-current");
    });
  });
}
// ---- clip player: finding the place
async function fetchPlace(c) {
  const headers = {},
    code = privateServer(apiBase()) && read("access:" + apiBase(), "");
  if (code) headers["X-Coach-Code"] = code;
  const query = new URLSearchParams({
      chunk_id: String(c.chunk_id),
      quote: String(c.quote || "").slice(0, 1000),
    }),
    stop = new AbortController(),
    limit = setTimeout(() => stop.abort(), 8000);
  try {
    const r = await fetch(apiBase() + "/api/audio/alignment?" + query, {
      headers,
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal: stop.signal,
    });
    if (!r.ok) return null;
    const body = await r.json();
    return body && typeof body === "object" ? body : null;
  } catch {
    return null;
  } finally {
    clearTimeout(limit);
  }
}
async function findPlace(own) {
  const until = Date.now() + ALIGN_WAIT_MS;
  let r = null;
  for (;;) {
    r = await fetchPlace(own.cite);
    if (clip !== own || own.phase !== "finding") return;
    if (!r || r.status !== "pending" || Date.now() + ALIGN_POLL_MS > until) break;
    await new Promise((done) => setTimeout(done, ALIGN_POLL_MS));
    if (clip !== own || own.phase !== "finding") return;
  }
  const m = r && r.status === "ready" ? alignedModel(own.cite, r) : null;
  if (m) aligned.set(own.key, m);
  showClip(own, m || roughModel(own.cite), Boolean(r && r.status === "pending"));
  if (m && m.refining) refinePlace(own);
}
// The marker-timed lines are playing; ask again until recognition has finished (or failed), then
// replace the model. Playback restarts at the new range only if it was playing.
async function refinePlace(own) {
  const until = Date.now() + REFINE_WAIT_MS;
  while (Date.now() + ALIGN_POLL_MS <= until) {
    await new Promise((done) => setTimeout(done, ALIGN_POLL_MS));
    if (clip !== own) return;
    const r = await fetchPlace(own.cite);
    if (clip !== own) return;
    if (!r || r.status === "pending" || (r.status === "ready" && r.refining === true)) continue;
    const m = r.status === "ready" ? alignedModel(own.cite, r) : null;
    if (!m) break;
    const playing = own.state === "playing" || own.state === "loading";
    aligned.set(own.key, m);
    own.model = m;
    own.late = false;
    if (typeof own.range === "number") own.range = "match"; // the lines changed
    redrawClip();
    if (playing) playFrom(clipBounds(m, own.range).start);
    return;
  }
  if (clip === own && own.model) own.model.refining = false;
}
function showClip(own, model, late) {
  own.phase = "ready";
  own.model = model;
  own.late = late;
  redrawClip();
  playFrom(clipBounds(model, own.range).start); // without a fresh tap the browser may want ▶
}
function openClip(e) {
  const c = e && e.citation;
  if (!hasAudio(c)) return;
  const key = clipKey(c);
  if (clip && clip.key === key) return closeClip();
  if (clip) shutClip();
  clip = { key, cite: c, phase: "finding", model: null, state: "idle", range: "match", plays: 1, active: -1, late: false };
  const known = aligned.get(key);
  if (known || !c.chunk_id || (staticOnly && !read("server", ""))) {
    showClip(clip, known || roughModel(c), false);
    if (known && known.refining) refinePlace(clip);
    return;
  }
  redrawClip();
  findPlace(clip);
}
function shutClip() {
  ++clipAttempt;
  cancelAnimationFrame(clipFrame);
  clearTimeout(clipTimer);
  clip = null;
  player.pause();
}
function closeClip() {
  if (!clip) return;
  shutClip();
  redrawClip();
}
// ---- clip player: playback and the loop
function clipNow() {
  return player.currentTime * 1000;
}
function clipFail() {
  cancelAnimationFrame(clipFrame);
  clearTimeout(clipTimer);
  clip.state = "error";
  paintClip();
}
function playFrom(at) {
  const m = clip.model,
    mine = ++clipAttempt;
  cancelAnimationFrame(clipFrame);
  clearTimeout(clipTimer);
  clip.state = "loading";
  clip.seek = at;
  if (player.dataset.src !== m.src || player.error) {
    player.dataset.src = m.src;
    // A media fragment starts the first load at the clip; loadedmetadata seeks if it was ignored.
    player.src = new URL(m.src).hash ? m.src : m.src + "#t=" + at / 1000;
  } else if (player.readyState >= 1) player.currentTime = at / 1000;
  player.defaultPlaybackRate = clipRate;
  player.playbackRate = clipRate;
  paintClip();
  if (player.readyState < 1)
    clipTimer = setTimeout(() => {
      if (clip && mine === clipAttempt && player.readyState < 1) clipFail();
    }, LOAD_TIMEOUT_MS);
  player.play().then(
    () => {
      if (!clip || mine !== clipAttempt) return;
      clearTimeout(clipTimer);
      clip.state = "playing";
      paintClip();
      cancelAnimationFrame(clipFrame);
      clipFrame = requestAnimationFrame(clipTick);
    },
    (err) => {
      if (!clip || mine !== clipAttempt) return;
      clearTimeout(clipTimer);
      const name = err && err.name;
      if (name === "AbortError" || name === "NotAllowedError") {
        clip.state = name === "AbortError" && player.readyState ? "paused" : "idle";
        paintClip();
      } else clipFail();
    },
  );
}
// Called every frame while playing (and on timeupdate, which keeps going in a background tab).
function clipCheck() {
  if (!clip || !clip.model || clip.state !== "playing") return "stop";
  const m = clip.model,
    b = clipBounds(m, clip.range);
  let pos = clipNow();
  if (pos < b.start - 1500) {
    player.currentTime = b.start / 1000; // the browser ignored the first seek
    pos = b.start;
  }
  const span = clipSpan(m, clip.range),
    found = m.cues.findIndex((q) => pos >= q.start && pos < q.end),
    active = found >= span.first && found <= span.last ? found : -1; // not the line in the padding
  let changed = active !== clip.active;
  clip.active = active;
  if (pos >= b.end) {
    if (!clipLoop) {
      clip.state = "paused";
      player.pause();
      paintClip();
      return "stop";
    }
    player.currentTime = b.start / 1000;
    clip.plays++;
    changed = true;
  }
  if (changed) paintClip();
  return "play";
}
function clipTick() {
  if (clipCheck() === "stop") return;
  clipFrame = requestAnimationFrame(clipTick);
}
function clipToggle() {
  if (!clip || !clip.model) return;
  if (clip.state === "playing" || clip.state === "loading") {
    ++clipAttempt;
    cancelAnimationFrame(clipFrame);
    clearTimeout(clipTimer);
    clip.state = "paused";
    player.pause();
    return paintClip();
  }
  const b = clipBounds(clip.model, clip.range),
    pos = clipNow();
  if (clip.state === "paused" && pos >= b.start - PAD_MS && pos < b.end)
    return playFrom(Math.max(pos, b.start));
  clip.plays = 1;
  playFrom(b.start);
}
function clipChoose(range) {
  if (!clip || !clip.model) return;
  clip.range = range;
  clip.plays = 1;
  playFrom(clipBounds(clip.model, range).start);
}
player.addEventListener("loadedmetadata", () => {
  if (clip && clip.model && Number.isFinite(clip.seek) && Math.abs(clipNow() - clip.seek) > 300)
    player.currentTime = clip.seek / 1000;
});
player.addEventListener("timeupdate", clipCheck);
// Buffering shows the spinner; playing again (or the system media controls) resumes the loop.
player.addEventListener("waiting", () => {
  if (clip && clip.model && clip.state === "playing") {
    clip.state = "loading";
    paintClip();
  }
});
player.addEventListener("playing", () => {
  if (!clip || !clip.model || clip.state === "playing" || clip.state === "error") return;
  clip.state = "playing";
  paintClip();
  cancelAnimationFrame(clipFrame);
  clipFrame = requestAnimationFrame(clipTick);
});
player.addEventListener("pause", () => {
  if (clip && clip.model && clip.state === "playing") {
    cancelAnimationFrame(clipFrame);
    clip.state = "paused";
    paintClip();
  }
});
// The episode can end inside the padding after the last line.
player.addEventListener("ended", () => {
  if (!clip || !clip.model) return;
  const b = clipBounds(clip.model, clip.range);
  if (clipLoop) {
    clip.plays++;
    return playFrom(b.start);
  }
  clip.state = "paused";
  player.currentTime = b.start / 1000;
  paintClip();
});
player.addEventListener("error", () => {
  if (clip && clip.model && (clip.state === "loading" || clip.state === "playing")) clipFail();
});
function back(dest) {
  return (
    '<button data-go="' +
    dest +
    '" class="back plain">' +
    icon("back") +
    T("返回", "돌아가기") +
    "</button>"
  );
}
function resultPage() {
  const head =
    back("home") +
    '<h1 class="answer-title">' +
    esc(active ? active.question : draft || T("教练回答", "코치 답변")) +
    "</h1>";
  if (pending && !active)
    return (
      head +
      quickBubble(liveQuick()) +
      '<div class="status"><span class="spinner"></span>' +
      T(
        "教练正在找表达、核对字幕。你可以先浏览表达库。",
        "코치가 표현을 찾고 자막을 확인하고 있어요. 표현 모음을 먼저 둘러봐도 돼요.",
      ) +
      "</div>"
    );
  if (failed)
    return (
      head +
      '<div class="panel"><p class="error" role="alert">' +
      esc(failedMessage()) +
      '</p><div class="filters"><button class="primary" data-retry>' +
      T("重试", "재시도") +
      '</button><button class="secondary" data-settings>' +
      T("连接设置", "연결 설정") +
      '</button><button class="secondary" data-go="library">' +
      T("浏览离线表达", "오프라인 표현 보기") +
      "</button></div></div>"
    );
  if (!active)
    return (
      head +
      '<p class="empty">' +
      T("回到练习台写下你的问题。", "연습 화면에서 질문을 입력하세요.") +
      "</p>"
    );
  return (
    head +
    '<p class="sub">' +
    (active.local
      ? T(
          "表达库匹配 · 展开出处查看实际用法",
          "표현 모음 검색 결과 · 출처에서 실제 쓰임을 확인하세요",
        )
      : T(
          "教练建议 · 展开出处查看实际用法",
          "코치 제안 · 출처를 펼쳐 실제 쓰임을 확인하세요",
        )) +
    "</p>" +
    quickBubble(active.quick, true) +
    replayLink(active) +

    active.expressions.map(resultCard).join("") +
    (Array.isArray(active.added) && active.added.length
      ? '<h2 class="more-head">' +
        icon("podcast") +
        T("之后找到的播客例句", "팟캐스트에서 더 찾은 예문") +
        "</h2>" +
        active.added.map(resultCard).join("")
      : "") +
    more(active, true) +
    (active.note ? '<p class="status">' + esc(active.note) + "</p>" : "") +
    (!active.expressions.length && !active.note && !active.stage
      ? '<p class="empty">' +
        T(
          "没有找到合适的表达，试试补充场景或问在线教练。",
          "적절한 표현을 찾지 못했어요. 상황을 더 적거나 온라인 코치에게 물어보세요.",
        ) +
        "</p>"
      : "")
  );
}
function notebook() {
  const items = bookTab === "saved" ? saved : history;
  return (
    "<h1>" +
    T("我的学习本", "내 학습 노트") +
    '</h1><p class="sub">' +
    T(
      "收藏和提问记录保存在这台设备上。",
      "저장한 표현과 질문 기록은 이 기기에 보관돼요.",
    ) +
    '</p><div class="filters notebook-tabs">' +
    [
      ["saved", T("已收藏", "저장한 표현"), saved.length],
      ["history", T("提问记录", "질문 기록"), history.length],
    ]
      .map(
        ([id, n, count]) =>
          '<button class="filter" data-tab="' +
          id +
          '" aria-pressed="' +
          (bookTab === id) +
          '">' +
          n +
          " · " +
          count +
          "</button>",
      )
      .join("") +
    "</div>" +
    (!items.length
      ? '<div class="empty">' +
        (bookTab === "saved"
          ? T(
              "点表达卡上的书签，就能在这里复习。",
              "표현 카드의 북마크를 눌러 여기에 저장하세요.",
            )
          : T(
              "完成提问后，可以在这里重看回答。",
              "완료한 질문의 답변을 여기서 다시 볼 수 있어요.",
            )) +
        "</div>"
      : bookTab === "saved"
        ? items.map(resultCard).join("")
        : items
            .map(
              (h, i) =>
                '<div class="entry"><button data-history="' +
                i +
                '">' +
                esc(h.question) +
                '</button><button data-remove="' +
                i +
                '" class="icon-btn" aria-label="' +
                T("删除记录", "기록 삭제") +
                '">' +
                icon("close") +
                "</button></div>",
            )
            .join(""))
  );
}
// The question box sticks to the bottom of the chat unless it (with the phone tabs) would cover
// too much of a short or text-zoomed screen; then it stays at the end of the conversation.
function fitComposer() {
  const form = $("ask"),
    nav = $("nav");
  if (!form) return;
  const tabs = getComputedStyle(nav).position === "fixed" ? nav.offsetHeight : 0;
  document.body.classList.toggle(
    "loose-compose",
    form.offsetHeight + tabs > innerHeight * 0.4,
  );
}
const composeFit = "ResizeObserver" in window ? new ResizeObserver(fitComposer) : null;
window.addEventListener("resize", fitComposer);
function render() {
  visible = [];
  const page = location.hash.slice(1) || "home",
    id = page.slice(5);
  // Keep the learner's place in the question box when an answer redraws the page.
  const typing = document.activeElement && document.activeElement.id === "question"
    ? [document.activeElement.selectionStart, document.activeElement.selectionEnd]
    : null;
  document.body.classList.toggle("chat-home", page === "home");
  let html;
  if (page === "library") html = shelf();
  else if (page === "book") html = notebook();
  else if (page === "answer") html = resultPage();
  else if (page === "podcast") html = podcastPage();
  else if (page.startsWith("card/")) {
    const e = library.find((x) => x.id === id);
    html =
      back("library") +
      (e
        ? '<h1 class="answer-title">' +
          esc(label(e.title)) +
          '</h1><p class="sub">' +
          groupName(e.group) +
          "</p>" +
          resultCard(e)
        : '<p class="empty">' +
          T("找不到这张表达卡。", "이 표현 카드를 찾을 수 없어요.") +
          "</p>");
  } else html = home();
  frame(
    page === "book" || page === "podcast"
      ? page
      : page === "library" || page.startsWith("card/")
        ? "library"
        : "home",
  );
  app.innerHTML = html;
  renderNotice();
  if (composeFit) {
    composeFit.disconnect();
    if ($("ask")) composeFit.observe($("ask"));
  }
  const box = typing && $("question");
  if (box) {
    box.focus({ preventScroll: true });
    try {
      box.setSelectionRange(typing[0], typing[1]);
    } catch {}
  }
}
const isAndroid =
  location.origin === "http://localhost" && /; wv\)/.test(navigator.userAgent);
const hosted = location.hostname.endsWith(".chatgpt.site");
const onlineSite = "https://phrase-room-coach.vercel.app";
const defaultServer = isAndroid ? onlineSite : location.origin;
function apiBase() {
  return read("server", "") || defaultServer;
}
function privateServer(address) {
  return Boolean(address && address !== onlineSite && address !== defaultServer) ||
    (!isAndroid && /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && address === defaultServer);
}
function failedMessage() {
  return {
    offline: T(
      "电脑上的教练服务暂时离线，请稍后重试。",
      "컴퓨터의 코치 서버가 오프라인이에요. 잠시 후 다시 시도하세요.",
    ),
    pair: T("请在连接设置中输入个人连接码，再重试。", "연결 코드를 확인하세요."),
    busy: T(
      "教练正在处理另一条提问，请稍后再试。",
      "다른 질문을 처리 중이에요. 잠시 후 다시 시도하세요.",
    ),
    daily: daily
      ? T(
          "今天的提问次数（每天 " + daily.limit + " 次）已用完，请明天再试。",
          "오늘 사용 가능한 질문 수(하루 " + daily.limit + "회)를 모두 썼어요. 내일 다시 시도해 주세요.",
        )
      : T("今天的提问次数已用完，请明天再试。", "오늘 사용 가능한 질문 수를 모두 썼어요. 내일 다시 시도해 주세요."),
    invalid: T("请缩短问题后再试。", "질문을 짧게 줄여 주세요."),
    timeout: T(
      "这次没能及时找到回答，请稍后再试。",
      "시간 안에 답을 찾지 못했어요. 잠시 뒤 다시 시도해 주세요.",
    ),
    service: T(
      "教练服务暂时不可用。可以先离线浏览表达库。",
      "코치 서비스에 지금 연결할 수 없어요. 오프라인 표현 모음을 이용할 수 있어요.",
    ),
    net: T(
      "没有连上教练服务。请检查服务地址和网络。",
      "코치 서버에 연결할 수 없어요. 서버 주소와 네트워크를 확인하세요.",
    ),
  }[failed];
}
const staticOnly = !!document.querySelector('meta[name="coach-static"]');
let mode = read("mode", staticOnly ? "local" : "coach");
let lastQuestion = "",
  lastContext = "";
let ticket = 0;
function localAnswer(q, c) {
  const text = (q + " " + c).toLowerCase();
  const ranked = library
    .map((item) => {
      const terms = [
        ...item.title,
        item.key_phrase,
        ...item.keywords.split(/\s+/),
      ].map((term) => term.toLowerCase());
      const score = terms.reduce(
        (n, term) =>
          n + (term && text.includes(term) ? Math.min(9, term.length) : 0),
        0,
      );
      return { item, score };
    })
    .filter((row) => row.score >= 2)
    .sort((a, b) => b.score - a.score);
  return ranked
    .slice(0, 3)
    .filter((row) => row.score >= ranked[0].score / 2)
    .map((row) => row.item);
}
const STREAM = "application/x-ndjson";
const CLIENT_LIMIT_MS = 300000; // the server ends a request 280 s after it starts
function uid() {
  return self.crypto && crypto.randomUUID
    ? crypto.randomUUID()
    : Date.now().toString(36) + Math.random().toString(36).slice(2);
}
function verified(e) {
  return Boolean(e && e.citation && typeof e.citation.quote === "string");
}
function expressionList(list) {
  return Array.isArray(list)
    ? list.filter((e) => e && typeof e.expression === "string" && e.expression)
    : [];
}
// One NDJSON object per line, as the server writes them; blank lines are skipped.
async function* ndjson(body) {
  const reader = body.getReader(),
    decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      if (buffer.length > 1000000) throw new Error("service");
      let cut;
      while ((cut = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, cut).trim();
        buffer = buffer.slice(cut + 1);
        if (line) yield JSON.parse(line);
      }
      if (done) {
        if (buffer.trim()) yield JSON.parse(buffer);
        return;
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
// A finished first answer: it goes into the chat and the device history at once.
function answered(req, expressions, note, extra = {}) {
  const entry = {
    id: uid(),
    question: req.q,
    context: req.c,
    sent: req.sent,
    expressions,
    note: note || null,
    ...extra,
  };
  history = [entry, ...history].slice(0, 35);
  storeList("history", history);
  if (ticket === req.ticket) {
    active = entry;
    turns.push(entry);
  }
  pending = false;
  quick = null; // the entry carries it now (entry.quick), shown above its examples
  stopWaiting();
  if (entry.stage === "pending") {
    running.add(entry.id);
    notice = { kind: "running", id: entry.id };
  }
  say(
    entry.stage === "pending"
      ? T(
          "先显示已核对的 " + expressions.length + " 条例句，正在查找更多播客例句。",
          "확인된 예문 " + expressions.length + "개를 먼저 보여 드려요. 팟캐스트 예문을 더 찾는 중이에요.",
        )
      : expressions.length
        ? T("回答已送达，共 " + expressions.length + " 个表达。", "답변이 도착했어요. 표현 " + expressions.length + "개.")
        : T("回答已送达。", "답변이 도착했어요."),
  );
  render();
  if (document.body.classList.contains("chat-home"))
    document.querySelector("#ask")?.scrollIntoView({ block: "nearest" });
  return entry;
}
// The background search ended: keep the first examples, add what it verified, tell the learner.
function settle(entry, stage, added = []) {
  entry.stage = stage;
  entry.added = added;
  entry.seen = !added.length;
  running.delete(entry.id);
  if (history.includes(entry)) storeList("history", history);
  notice = {
    kind: added.length ? "added" : stage === "done" ? "none" : "stopped",
    id: entry.id,
  };
  say(
    added.length
      ? T(
          "又找到 " + added.length + " 条播客例句，可在播客页查看。",
          "팟캐스트 예문 " + added.length + "개를 더 찾았어요. 팟캐스트 탭에서 볼 수 있어요.",
        )
      : stage === "done"
        ? T("这次没有找到更多播客例句。", "이번에는 팟캐스트 예문을 더 찾지 못했어요.")
        : T(
            "查找更多例句时中断了，现有结果可以照常使用。",
            "예문을 더 찾다가 중단됐어요. 지금 결과는 그대로 쓸 수 있어요.",
          ),
  );
  // Redraw only what shows the search; a full redraw would take the learner's place in a text box.
  const page = location.hash.slice(1) || "home";
  if (["podcast", "answer", "book"].includes(page)) render();
  else {
    const replay = $("replay-" + entry.id);
    if (replay) replay.innerHTML = replayLink(entry);
    paintMore(entry);
    paintComposer();
    paintNav();
    renderNotice();
  }
}
// The quick line arrived before any answer: show it at once, labelled as not yet checked.
function showQuick(req, ev) {
  const text = typeof ev.text === "string" ? ev.text.trim().slice(0, 400) : "";
  if (!text || !pending || ticket !== req.ticket) return null;
  const note = typeof ev.note === "string" ? ev.note.trim().slice(0, 400) : "";
  quick = { ticket: req.ticket, text, note };
  say(
    T(
      "快速翻译：" + text + "。正在核对播客例句。",
      "빠른 번역: " + text + ". 팟캐스트 예문을 확인하고 있어요.",
    ),
  );
  const page = location.hash.slice(1) || "home";
  if (page === "home" || page === "answer") {
    render();
    if (page === "home") document.querySelector("#ask")?.scrollIntoView({ block: "nearest" });
  }
  return { text, note };
}
// Accept: NDJSON. quick (optional, before any answer): a generated line, shown apart from the
// examples; first: the verified examples (final); final: the whole answer, of which only the
// examples at the added indexes are new; error: the search ended. A first that is still pending
// leaves its empty slots to the background search; unverified candidates are never shown after it.
async function staged(r, req) {
  let entry = null,
    fast = null;
  const extra = (more = {}) => (fast ? { quick: fast, ...more } : more);
  try {
    for await (const ev of ndjson(r.body)) {
      if (!ev || typeof ev !== "object") continue;
      if (typeof ev.stage === "string") {
        if (req.ticket === ticket && pending) updateProgress(ev.stage);
        continue;
      }
      const replay = replayUrl(ev.run_id);
      if (ev.type === "quick") {
        if (!entry && !fast) fast = showQuick(req, ev);
      } else if (ev.type === "first" && !entry) {
        const pendingMore = ev.pending === true;
        entry = answered(
          req,
          expressionList(ev.expressions).filter(verified),
          ev.note,
          extra({replayUrl: replay, ...(pendingMore ? {stage: "pending", added: []} : {})}),
        );
        if (!pendingMore) return;
      } else if (ev.type === "final") {
        const all = Array.isArray(ev.expressions) ? ev.expressions : [];
        if (!entry) {
          answered(req, expressionList(all), ev.note, extra({replayUrl: replay}));
          return;
        }
        const shown = new Set(entry.expressions.map(key)),
          added = [];
        for (const i of Array.isArray(ev.added) ? ev.added : []) {
          const e = Number.isInteger(i) ? all[i] : null;
          if (expressionList([e]).length && verified(e) && !shown.has(key(e))) {
            shown.add(key(e));
            added.push(e);
          }
        }
        entry.replayUrl = replay;
        settle(entry, "done", added);
        return;
      } else if (ev.type === "error") {
        if (!entry)
          throw new Error(
            { timeout: "timeout", invalid_input: "invalid", coach_busy: "busy" }[ev.code] || "service",
          );
        settle(entry, "stopped");
        return;
      }
    }
    if (!entry) throw new Error("net");
    settle(entry, "stopped");
  } catch (err) {
    if (!entry) throw err;
    if (entry.stage === "pending") settle(entry, "stopped");
  }
}
// again: a stored staged answer to look for once more with its question and the context it sent.
async function ask(resumeId = null, again = null) {
  const how = again ? "coach" : mode;
  if (
    (!again && !draft.trim()) ||
    pending ||
    (staticOnly && how === "coach" && !read("server", ""))
  )
    return;
  if (how === "coach" && running.size >= RUNNING_LIMIT) {
    toast(holdText());
    return;
  }
  if (how === "coach" && isAndroid && !apiBase()) {
    settings();
    return;
  }
  const myTicket = ++ticket,
    q = again ? again.question : draft.trim(),
    c = again ? again.context || "" : context.trim();
  lastQuestion = q;
  lastContext = c;
  if (!again) {
    draft = "";
    context = "";
  }
  pending = true;
  progress = [];
  active = null;
  failed = "";
  quick = null;
  if (notice && notice.kind !== "running") notice = null;
  startWaiting();
  go("home");
  render();
  try {
    if (how === "local") {
      answered({ q, c, sent: c, ticket: myTicket }, localAnswer(q, c), null, {
        local: true,
      });
      return;
    }
    const headers = { "Content-Type": "application/json", Accept: "application/x-ndjson, application/json" };
    const code = privateServer(apiBase()) && read("access:" + apiBase(), "");
    if (code) headers["X-Coach-Code"] = code;
    const prior = turns[turns.length - 1];
    const followup = again
      ? typeof again.sent === "string"
        ? again.sent
        : c
      : c ||
        (prior
          ? (
              T("上一轮：", "직전 대화: ") +
              prior.question.slice(0, 200) +
              " / " +
              (prior.expressions[0]?.expression || "").slice(0, 330)
            ).slice(0, 600)
          : "");
    const endpoint = apiBase() + "/api/search";
    // Ask for the staged stream; a server without it (an older one, the relay) answers in JSON.
    const stop = new AbortController(),
      limit = setTimeout(() => stop.abort(), CLIENT_LIMIT_MS);
    let r;
    try {
      r = resumeId
        ? null
        : await fetch(endpoint, {
            method: "POST",
            headers: { ...headers, Accept: STREAM + ";progress=1, application/json;q=0.9" },
            body: JSON.stringify({ question: q, context: followup }),
            referrerPolicy: "no-referrer",
            signal: stop.signal,
          });
      if (r) readDaily(r);
      if (
        r &&
        r.ok &&
        r.body &&
        (r.headers.get("Content-Type") || "").toLowerCase().startsWith(STREAM)
      ) {
        await staged(r, { q, c, sent: followup, ticket: myTicket });
        return;
      }
    } finally {
      clearTimeout(limit);
    }
    const jobId = resumeId || (r.status === 202 ? (await r.json()).id : null);
    if (jobId) {
      if (!/^[a-f0-9-]{36}$/.test(jobId)) throw new Error("service");
      sessionStorage.setItem(
        "coach-job",
        JSON.stringify({ id: jobId, q, c, endpoint }),
      );
      const until = Date.now() + 31 * 60 * 1000;
      do {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        r = await fetch(endpoint + "/" + jobId, { headers, cache: "no-store" });
      } while (r.status === 202 && Date.now() < until);
      if (r.status === 202) throw new Error("service");
      sessionStorage.removeItem("coach-job");
    }
    if (
      r.status === 503 &&
      (
        await r
          .clone()
          .json()
          .catch(() => ({}))
      ).detail === "coach_offline"
    )
      throw new Error("offline");
    if (
      r.status === 429 &&
      (
        await r
          .clone()
          .json()
          .catch(() => ({}))
      ).detail === "daily_limit"
    )
      throw new Error("daily");
    if (!r.ok)
      throw new Error(
        { 401: privateServer(apiBase()) ? "pair" : "service", 403: "service", 429: "busy", 422: "invalid" }[r.status] ||
          "service",
      );
    const data = await r.json();
    if (!Array.isArray(data.expressions)) throw new Error("service");

    if (jobId)
      fetch(endpoint + "/" + jobId, { method: "DELETE", headers }).catch(
        () => {},
      );
    answered({ q, c, sent: followup, ticket: myTicket }, data.expressions, data.note, {replayUrl: replayUrl(data.run_id || r.headers.get("X-Coach-Run"))});
  } catch (err) {
    if (ticket === myTicket)
      failed =
        err.name === "AbortError"
          ? "timeout"
          : err.name === "SyntaxError"
            ? "service"
            : ["pair", "busy", "daily", "invalid", "service", "offline", "timeout"].includes(
                err.message,
              )
            ? err.message
            : "net";
  } finally {
    if (pending) {
      pending = false;
      stopWaiting();
      render();
      if (document.body.classList.contains("chat-home"))
        document.querySelector("#ask")?.scrollIntoView({ block: "nearest" });
    }
  }
}
function settings() {
  const base = read("server", "");
  dialog.innerHTML =
    '<form id="config"><h2>' +
    T("连接设置", "연결 설정") +
    '</h2><p class="compact">' +
    T(
      "离线表达库可直接使用。自建教练服务时，在这里连接。",
      "표현 모음은 오프라인으로 이용할 수 있어요. 개인 코치 서버가 있다면 연결하세요.",
    ) +
    '</p><div class="linkrow"><a href="#library" data-dismiss>' +
    T("表达库", "표현 모음") +
    '</a><a href="#book" data-dismiss>' +
    T("学习本", "학습 노트") +
    '</a></div><label class="field">' +
    T("教练服务地址", "코치 서버 주소") +
    '<input type="url" id="server" value="' +
    esc(base) +
    '" placeholder="' +
    esc(defaultServer) +
    '"></label><label class="field" id="custom-code-field">' +
    T("自建服务连接码", "연결 코드 (설정한 경우)") +
    '<input type="password" autocomplete="off" id="code" value="' +
    esc(privateServer(apiBase()) ? read("access:" + apiBase(), "") : "") +
    '"></label><div class="tools"><button type="button" class="secondary" data-close>' +
    T("关闭", "닫기") +
    '</button><button class="primary">' +
    T("保存设置", "설정 저장") +
    "</button></div></form>" +
    (isAndroid
      ? ""
      : '<div class="source"><h3>' +
        T("手机 App", "모바일 앱") +
        '</h3><a href="./downloads/EnglishCoach.apk" download>Android APK</a><p class="compact">' +
        T(
          "iPhone 可在 Safari 的分享菜单中选择「添加到主屏幕」。",
          "iPhone에서는 Safari 공유 메뉴에서 ‘홈 화면에 추가’를 선택하세요.",
        ) +
        "</p></div>");
  const syncCode = () => {
    const address = new URL($("server").value || defaultServer, location.origin).origin;
    $("custom-code-field").style.display = privateServer(address) ? "" : "none";
    $("code").value = privateServer(address) ? read("access:" + address, "") : "";
  };
  syncCode();
  $("server").addEventListener("input", () => { try { syncCode(); } catch { $("custom-code-field").style.display = "none"; } });
  if (dialog.showModal) dialog.showModal();
  else dialog.setAttribute("open", "");
}
function closeSettings() {
  if (dialog.close) dialog.close();
  else dialog.removeAttribute("open");
}
document.addEventListener("keydown", (e) => {
  if (
    e.target.id === "question" &&
    e.key === "Enter" &&
    !e.shiftKey &&
    !e.isComposing &&
    e.keyCode !== 229 &&
    matchMedia("(pointer:fine)").matches
  ) {
    e.preventDefault();
    e.target.form.requestSubmit();
  }
});
document.addEventListener("input", (ev) => {
  if (ev.target.id === "question") { draft = ev.target.value; setMascotActivity(); }
  if (ev.target.id === "context") context = ev.target.value;
  if (ev.target.id === "query") {
    searchText = ev.target.value;
    $("cards").innerHTML = libraryResults();
  }
});
document.addEventListener("submit", (e) => {
  if (e.target.id === "ask") {
    e.preventDefault();
    ask();
  }
  if (e.target.id === "config") {
    e.preventDefault();
    const s = $("server").value.trim();
    if (s) {
      const u = new URL(s);
      if (
        !url(s) ||
        u.username ||
        u.password ||
        u.pathname !== "/" ||
        u.search ||
        u.hash
      ) {
        $("server").setCustomValidity(
          T(
            "请输入 http 或 https 服务根地址。",
            "HTTP 또는 HTTPS 서버 기본 주소를 입력하세요.",
          ),
        );
        $("server").reportValidity();
        $("server").setCustomValidity("");
        return;
      }
    }
    write("server", s ? new URL(s).origin : "");
    if (privateServer(apiBase())) write("access:" + apiBase(), $("code").value);
    closeSettings();
    toast(T("设置已保存", "설정을 저장했어요"));
  }
});
document.addEventListener("click", (e) => {
  const replay = e.target.closest("a[data-replay]");
  if (replay && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    window.history.pushState({workflow: true}, "", location.href);
    const frame = document.createElement("iframe");
    frame.id = "workflow-frame";
    frame.title = T("工作流回放", "실행 과정 다시 보기");
    frame.src = replay.href;
    $("workflow-dialog").replaceChildren(frame);
    $("workflow-dialog").showModal();
    return;
  }
  if (e.target.closest("[data-dismiss]")) closeSettings();
  const b = e.target.closest("button");
  if (!b) return;
  const d = b.dataset;
  if (b.id === "language") {
    lang = lang === "zh" ? "ko" : "zh";
    write("language", lang);
    render();
  } else if (b.id === "settings" || "settings" in d) settings();
  else if ("close" in d) closeSettings();
  else if ("reload" in d) location.reload();
  else if ("retry" in d) {
    draft = lastQuestion;
    context = lastContext;
    ask();
  } else if ("mode" in d) {
    mode = d.mode;
    write("mode", mode);
    render();
  } else if ("card" in d) go("card/" + d.card);
  else if ("go" in d) go(d.go);
  else if ("filter" in d) {
    libraryFilter = d.filter;
    render();
  } else if ("tab" in d) {
    bookTab = d.tab;
    render();
  } else if ("save" in d) {
    const x = visible[Number(d.save)];
    if (!x) return;
    const exists = saved.some((s) => key(s) === key(x));
    saved = exists ? saved.filter((s) => key(s) !== key(x)) : [x, ...saved];
    storeList("saved", saved);
    toast(
      exists
        ? T("已移出学习本", "노트에서 삭제했어요")
        : T("已收藏到学习本", "학습 노트에 저장했어요"),
    );
    render();
  } else if ("history" in d || "open" in d) {
    const entry =
      "open" in d ? findEntry(d.open) : history[Number(d.history)];
    if (!entry) return;
    ++ticket;
    active = entry;
    draft = active.question;
    context = active.context || "";
    failed = "";
    go("answer");
  } else if ("listen" in d) openClip(visible[Number(d.listen)]);
  else if ("clipCue" in d) clipChoose(Number(d.clipCue));
  else if ("clipRange" in d) clipChoose(d.clipRange === "all" ? "all" : "match");
  else if (d.clip === "toggle") clipToggle();
  else if (d.clip === "loop") {
    clipLoop = !clipLoop;
    paintClip();
  } else if (d.clip === "rate") {
    clipRate = RATES[(RATES.indexOf(clipRate) + 1) % RATES.length];
    write("clip-rate", clipRate);
    player.defaultPlaybackRate = clipRate;
    player.playbackRate = clipRate;
    paintClip();
  } else if (d.clip === "rough" && clip && clip.phase === "finding")
    showClip(clip, roughModel(clip.cite), false);
  else if ("again" in d) {
    const entry = findEntry(d.again);
    if (entry) ask(null, entry);
  } else if ("noticeClose" in d) {
    notice = null;
    renderNotice();
    app.focus({ preventScroll: true });
  } else if ("remove" in d) {
    history.splice(Number(d.remove), 1);
    storeList("history", history);
    render();
  }
});
function closeReplay() {
  if (!$("workflow-dialog").open) return;
  dismissReplay();
  if (window.history.state?.workflow) window.history.back();
}
function dismissReplay() {
  $("workflow-dialog").close();
  $("workflow-dialog").replaceChildren();
  if (location.hash === "#answer") go("home");
  render();
  $("question")?.focus({preventScroll: true});
}
$("workflow-dialog").addEventListener("cancel", e => {e.preventDefault(); closeReplay()});
window.addEventListener("message", e => {
  const frame = $("workflow-frame");
  if (!frame || e.source !== frame.contentWindow || !frame.hasAttribute("src") ||
      e.origin !== new URL(frame.src).origin) return;
  if (e.data?.action === "continue-coaching") {
    if (["ko", "zh"].includes(e.data.lang)) {
      lang = e.data.lang;
      write("language", lang);
    }
    closeReplay();
  }
});
window.addEventListener("popstate", () => {
  if ($("workflow-dialog").open && !window.history.state?.workflow) {
    dismissReplay();
  }
});
window.addEventListener("hashchange", () => {
  if (clip) shutClip(); // the card with the player leaves the screen
  readPhoneLink();
  render();
  window.scrollTo(0, 0);
  app.focus({ preventScroll: true });
});
function readPhoneLink() {
  if (hosted && location.hash.startsWith("#online?")) {
    const params = new URLSearchParams(location.hash.slice(8));
    draft = (params.get("q") || "").slice(0, 1800);
    context = (params.get("c") || "").slice(0, 600);
    lang = params.get("lang") === "ko" ? "ko" : "zh";
    mode = "coach";
    window.history.replaceState(null, "", location.pathname + "#home");
  }
}
async function start() {
  cat.bind();
  if (location.hash === "#continue") {
    const preferred = new URLSearchParams(location.search).get("lang");
    if (["ko","zh"].includes(preferred)) { lang = preferred; write("language", lang); }
    mode = "coach";
    window.history.replaceState(null, "", location.pathname + "#home");
  }
  readPhoneLink();
  // Phones show the tabs fixed at the bottom; the page keeps their real height free (large text wraps them).
  if ("ResizeObserver" in window)
    new ResizeObserver(() =>
      document.documentElement.style.setProperty("--nav-h", $("nav").offsetHeight + "px"),
    ).observe($("nav"));
  try {
    const r = await fetch("./library.json");
    if (!r.ok) throw Error();
    library = await r.json();
  } catch {
    listError = true;
  }
  // A background search does not survive leaving the page (nothing is kept on the server, D5):
  // its first examples stay in the device history and the learner can look again.
  const left = history.filter((h) => h && h.stage === "pending");
  if (left.length) {
    left.forEach((h) => (h.stage = "incomplete"));
    storeList("history", history);
    notice = { kind: "reentry", id: left[0].id };
  }
  render();
  const parked = JSON.parse(sessionStorage.getItem("coach-job") || "null");
  if (parked && parked.endpoint === apiBase() + "/api/search") {
    draft = parked.q;
    context = parked.c;
    mode = "coach";
    ask(parked.id);
  }
  if ("serviceWorker" in navigator && !isAndroid)
    navigator.serviceWorker.register("./sw.js").catch(() => {});
}
start();
