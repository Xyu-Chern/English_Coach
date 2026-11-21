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
  ]
    .map(
      ([id, s, name]) =>
        '<a href="#' +
        id +
        '" ' +
        (tab === id ? 'aria-current="page"' : "") +
        ">" +
        icon(s) +
        esc(name) +
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
        (turn.note ? "<p>" + esc(turn.note) + "</p>" : "") +
        (!turn.expressions.length && !turn.note
          ? T(
              "表达库里还没有匹配项。可以换个关键词或问教练。",
              "일치하는 표현이 없어요. 다른 검색어나 코치 질문을 사용해 보세요.",
            )
          : "") +
        "</div>",
    )
    .join("");
  const status =
    pending || failed
      ? '<div class="user-message">' +
        esc(lastQuestion) +
        "</div>" +
        (pending
          ? '<div class="waiting" role="status">' +
            mascot(true) +
            T("正在查找表达…", "표현을 찾고 있어요…") +
            "</div>"
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
    (pending || (staticOnly && mode === "coach" && !read("server", ""))
      ? "disabled"
      : "") +
    ">↑</button></div></form>" +
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
      '<div class="status" role="status"><span class="spinner"></span>' +
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
    (active.note ? '<p class="status">' + esc(active.note) + "</p>" : "") +
    (!active.expressions.length && !active.note
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
function render() {
  visible = [];
  const page = location.hash.slice(1) || "home",
    id = page.slice(5);
  document.body.classList.toggle("chat-home", page === "home");
  frame(
    page === "book"
      ? "book"
      : page === "library" || page.startsWith("card/")
        ? "library"
        : "home",
  );
  if (page === "library") app.innerHTML = shelf();
  else if (page === "book") app.innerHTML = notebook();
  else if (page === "answer") app.innerHTML = resultPage();
  else if (page.startsWith("card/")) {
    const e = library.find((x) => x.id === id);
    app.innerHTML =
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
  } else app.innerHTML = home();
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
async function ask(resumeId = null) {
  if (
    !draft.trim() ||
    pending ||
    (staticOnly && mode === "coach" && !read("server", ""))
  )
    return;
  if (mode === "coach" && isAndroid && !apiBase()) {
    settings();
    return;
  }
  const myTicket = ++ticket,
    q = draft.trim(),
    c = context.trim();
  lastQuestion = q;
  lastContext = c;
  draft = "";
  context = "";
  pending = true;
  active = null;
  failed = "";
  go("home");
  render();
  try {
    if (mode === "local") {
      const expressions = localAnswer(q, c);
      const answer = {
        question: q,
        context: c,
        expressions,
        local: true,
        note: null,
      };
      active = answer;
      turns.push(answer);
      history = [answer, ...history].slice(0, 35);
      storeList("history", history);
      return;
    }
    const headers = { "Content-Type": "application/json" };
    const code = privateServer(apiBase()) && read("access:" + apiBase(), "");
    if (code) headers["X-Coach-Code"] = code;
    const prior = turns[turns.length - 1];
    const followup =
      c ||
      (prior
        ? (
            T("上一轮：", "직전 대화: ") +
            prior.question.slice(0, 200) +
            " / " +
            (prior.expressions[0]?.expression || "").slice(0, 330)
          ).slice(0, 600)
        : "");
    const endpoint = apiBase() + "/api/search";
    let r = resumeId
      ? null
      : await fetch(endpoint, {
          method: "POST",
          headers,
          body: JSON.stringify({ question: q, context: followup }),
          referrerPolicy: "no-referrer",
        });
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
    const answer = {
      question: q,
      context: c,
      expressions: data.expressions,
      note: data.note,
    };
    history = [answer, ...history].slice(0, 35);
    storeList("history", history);
    if (jobId)
      fetch(endpoint + "/" + jobId, { method: "DELETE", headers }).catch(
        () => {},
      );
    if (ticket === myTicket) {
      active = answer;
      turns.push(answer);
    }
  } catch (err) {
    if (ticket === myTicket)
      failed = ["pair", "busy", "invalid", "service", "offline"].includes(
        err.message,
      )
        ? err.message
        : "net";
  } finally {
    pending = false;
    render();
    if (document.body.classList.contains("chat-home"))
      document.querySelector("#ask")?.scrollIntoView({ block: "nearest" });
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
  } else if ("history" in d) {
    ++ticket;
    active = history[Number(d.history)];
    draft = active.question;
    context = active.context || "";
    failed = "";
    go("answer");
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
  try {
    const r = await fetch("./library.json");
    if (!r.ok) throw Error();
    library = await r.json();
  } catch {
    listError = true;
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
