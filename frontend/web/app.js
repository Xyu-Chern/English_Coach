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
  document.documentElement.lang = lang === "ko" ? "ko" : "zh-CN";
  document.title = "Phrase Room · " + T("英语表达教练", "영어 표현 코치");
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
function mascot(thinking = false) {
  return (
    '<span aria-hidden="true" class="mascot' +
    (thinking ? " thinking" : "") +
    '"><i class="antenna"></i><i class="headphones"></i><i class="face"><i class="eyes"></i><i class="smile"></i></i></span>'
  );
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
        (pending
          ? '<div class="waiting">' +
            mascot(true) +
            '<span id="wait-text">' +
            waitText +
            '</span><span class="wait-time" id="wait-time">' +
            waitTime +
            "</span></div>"
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
        mascot() +
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
    (holding() ? holdText() : "") +
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
let waitStart = 0,
  waitTick = 0;
function waitingLine() {
  const s = Math.max(0, Math.floor((Date.now() - waitStart) / 1000));
  return [
    s >= SLOW_SECONDS
      ? T("还在核对例句，需要多一点时间…", "예문을 찾느라 조금 더 걸려요…")
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
    if (!text || !time) return;
    const [line, seconds] = waitingLine();
    if (text.textContent !== line) text.textContent = line;
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
  if (hold) hold.textContent = holding() ? holdText() : "";
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
    source(e.citation) +
    "</article>"
  );
}
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
    paintMore(entry);
    paintComposer();
    paintNav();
    renderNotice();
  }
}
// Accept: NDJSON. first: the verified examples (final); final: the whole answer, of which only the
// examples at the added indexes are new; error: the search ended. A first that is still pending
// leaves its empty slots to the background search; unverified candidates are never shown after it.
async function staged(r, req) {
  let entry = null;
  try {
    for await (const ev of ndjson(r.body)) {
      if (!ev || typeof ev !== "object") continue;
      if (ev.type === "first" && !entry) {
        const pendingMore = ev.pending === true;
        entry = answered(
          req,
          expressionList(ev.expressions).filter(verified),
          ev.note,
          pendingMore ? { stage: "pending", added: [] } : {},
        );
        if (!pendingMore) return;
      } else if (ev.type === "final") {
        const all = Array.isArray(ev.expressions) ? ev.expressions : [];
        if (!entry) {
          answered(req, expressionList(all), ev.note);
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
  active = null;
  failed = "";
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
    const headers = { "Content-Type": "application/json" };
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
            headers: { ...headers, Accept: STREAM + ", application/json;q=0.9" },
            body: JSON.stringify({ question: q, context: followup }),
            referrerPolicy: "no-referrer",
            signal: stop.signal,
          });
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
    answered({ q, c, sent: followup, ticket: myTicket }, data.expressions, data.note);
  } catch (err) {
    if (ticket === myTicket)
      failed =
        err.name === "AbortError"
          ? "timeout"
          : err.name === "SyntaxError"
            ? "service"
            : ["pair", "busy", "invalid", "service", "offline", "timeout"].includes(
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
        '</h3><a href="./downloads/PhraseRoom.apk" download>Android APK</a><p class="compact">' +
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
  if (ev.target.id === "question") draft = ev.target.value;
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
  } else if ("again" in d) {
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
window.addEventListener("hashchange", () => {
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
