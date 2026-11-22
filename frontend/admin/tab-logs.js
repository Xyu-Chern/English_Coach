/* 2. 요청 로그 — 평가 실행 기록(실제 요청 아님, D5). 사용자 열·필터 없음(D3). */
import { $, $$, fill, fmtK, fmtN, h, icon, pct, sec, secU, shortId, sum, usd } from "./ui.js";
import {
  D, REQ, firstTok, getTraces, isNotice, lockWord, lostFirst, noEx, order, pairOf, retryTraces, spansOf, contKey,
} from "./data.js";
import {
  CONT_TIP, STATUS, chip, contChip, dots, enT, exPlain, exText, foot, h4, hsHint, judgeText, kv, lostTag, modeBadge,
  mono, onSeg, phead, runBar, seg, slotTag, statusBadge, syncSeg, timeBar, warnErr,
} from "./parts.js";
import { register, updateLayout } from "./shell.js";
import { openGraph } from "./tab-graph.js";
import { t, tx } from "./i18n.js";
import "./i18n-tabs.js";

/* 화면 문자열: i18n-tabs.js의 "logs.*" 키(공용 조각은 "parts.*") */
const T = (k, p) => t("logs." + k, p);
const TX = (k, p) => tx("logs." + k, p);
const SEC = () => t("parts.secUnit");
const attempt = k => t("parts.attempt", { k });

/* 예문 필터: [값, 이름 키, 조건] */
const ADD_FILTERS = [
  ["all", "all", () => true],
  ["any", "add.any", r => r.added_final > 0],
  ["add2", "add.add2", r => r.added_final === 2],
  ["add1", "add.add1", r => r.added_final === 1],
  ["miss", "add.miss", r => isNotice(r) && r.added_final === 0],
  ["lost", "add.lost", r => r.lost_first > 0],
];
const PAGE = 100; /* 요청 표는 100행씩 그린다(300행을 한 번에 그리면 DOM이 커짐) */
const STATUSES = ["ok", "declined", "error"];
let L = null; /* 필터 · 정렬 · 고른 행 */

const taskEl = id => {
  const m = /^(.*-)([^-]+-\d+)$/.exec(id);
  return m ? [m[1], h("span.nb", m[2])] : id;
};
const field = (label, ...k) => h("div.field", h("span", label), ...k);

register("logs", panel => {
  L = {
    mode: "all", status: new Set(STATUSES), cont: "all", add: "all", q: "", sort: { key: "task", dir: 1 },
    sel: REQ.has(D.examples.agent) ? D.examples.agent : (D.requests[0] || {}).id, scrolled: false, limit: PAGE,
  };
  const contName = v => (v === "all" ? T("all") : t("parts.cont." + v));
  const contOpts = ["all", "skipped", "ran", "stop", "none"].map(v => [v, contName(v), { title: CONT_TIP[v] }]);
  fill(panel,
    phead(T("title"), T("lead")),
    runBar(),
    h("div.ltools", { role: "search", "aria-label": T("filters") },
      field(T("fMode"), seg("lf-mode", T("fMode"), [["all", T("all")], ["baseline", "baseline"], ["agent", "agent"]],
        v => L.mode === v)),
      field(T("fStatus"), seg("lf-status", T("fStatus"), STATUSES.map(v => [v, STATUS[v][0]]), v => L.status.has(v))),
      field(T("fCont"), seg("lf-cont", T("fCont"), contOpts, v => L.cont === v)),
      h("label.field", h("span", T("fEx")),
        h("select", { id: "lf-add" }, ADD_FILTERS.map(([v, k]) => h("option", { value: v }, T(k))))),
      h("label.field.grow", h("span", T("fQuery")),
        h("input", { type: "search", id: "lf-q", placeholder: T("fQueryPh"), autocomplete: "off" }))),
    /* 표 상자 폭으로 열 구성: full 전체 / c 모드·후속을 입력 칸 아래로 / n 과제도 입력 칸 위로 */
    h("div.lgrid", { id: "lgrid", "data-lc": "full", "data-steps": "56:full 34:c 0:n" },
      h("div.lmain", h("p.lcount.num", { id: "lcount", "aria-live": "polite" }),
        h("div.hs-host", h("div.tbl-wrap.fitpane", {
          id: "ltable", role: "region", "aria-label": T("listLabel"), tabindex: 0, "data-hscroll": "",
          "data-hint": "lhint",
        }))),
      h("aside.card.fitpane.ldetail", { id: "ldetail", "aria-label": T("detailLabel") })));
  const filtered = fn => v => {
    fn(v);
    L.limit = PAGE;
    syncFilters();
    drawLog();
  };
  onSeg($("#lf-mode"), filtered(v => (L.mode = v)));
  onSeg($("#lf-status"), filtered(v => {
    if (!L.status.has(v)) L.status.add(v);
    else if (L.status.size > 1) L.status.delete(v);
  }));
  onSeg($("#lf-cont"), filtered(v => (L.cont = v)));
  $("#lf-add").addEventListener("change", e => filtered(() => (L.add = e.target.value))());
  $("#lf-q").addEventListener("input", e => filtered(() => (L.q = e.target.value))());
  const tbl = $("#ltable");
  tbl.addEventListener("click", e => {
    if (e.target.closest("#lmore")) {
      L.limit += PAGE;
      drawLog();
      return;
    }
    const sb = e.target.closest("[data-sort]");
    if (sb) {
      const k = sb.dataset.sort;
      if (L.sort.key === k) L.sort.dir *= -1;
      else L.sort = { key: k, dir: k === "task" ? 1 : -1 };
      drawLog();
      return;
    }
    const tr = e.target.closest("tbody tr");
    if (tr) pickRow(tr.dataset.id);
  });
  tbl.addEventListener("keydown", e => {
    const tr = e.target.closest("tbody tr");
    if (!tr) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const sib = e.key === "ArrowDown" ? tr.nextElementSibling : tr.previousElementSibling;
      if (sib) {
        pickRow(sib.dataset.id);
        sib.focus();
      }
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      pickRow(tr.dataset.id);
    }
  });
  drawLog();
});

function syncFilters() {
  syncSeg($("#lf-mode"), v => L.mode === v);
  syncSeg($("#lf-status"), v => L.status.has(v));
  syncSeg($("#lf-cont"), v => L.cont === v);
}

function logRows() {
  const q = L.q.trim().toLowerCase(), f = (ADD_FILTERS.find(x => x[0] === L.add) || ADD_FILTERS[0])[2];
  const hit = r => !q || (r.question || "").toLowerCase().includes(q) || r.task_id.toLowerCase().includes(q) ||
    r.id.toLowerCase().startsWith(q);
  const rows = D.requests.filter(r => (L.mode === "all" || r.mode === L.mode) && L.status.has(r.status) &&
    (L.cont === "all" || contKey(r) === L.cont) && f(r) && hit(r));
  /* 기본 정렬 = data.json 순서(과제 파일 순서 → 회차 → baseline 먼저) */
  const val = { first: r => r.first_response_ms, total: r => r.total_ms, tok: r => r.tokens.total,
    add: r => r.added_final }[L.sort.key];
  const byOrder = (a, b) => order(a) - order(b);
  return rows.sort((a, b) => (val ? (val(a) - val(b)) * L.sort.dir || byOrder(a, b) : byOrder(a, b) * L.sort.dir));
}

/* 고른 행은 aria-current로 표시한다(일반 표라 aria-selected는 쓰지 않음) */
const markRow = (tr, on) => {
  if (on) tr.setAttribute("aria-current", "true");
  else tr.removeAttribute("aria-current");
  tr.tabIndex = on ? 0 : -1;
};

function logRow(r, maxT) {
  const bar = (tag, v) => h(tag, { css: { width: ((v / maxT) * 100).toFixed(1) + "%" } });
  const tr = h("tr", { "data-id": r.id },
    h("td.tcell.col-tu", h("span.tk", taskEl(r.task_id)),
      h("span.trn.num", h("span", attempt(r.attempt)), h("span", r.language || ""))),
    h("td.qcell", h("span.qwho.num", h("span.mono", taskEl(r.task_id)), h("span", attempt(r.attempt))),
      h("span.qtext", r.question ?? T("noQuestion")),
      h("span.qsub", modeBadge(r.mode), statusBadge(r.status), contChip(r), h("span.vtxt.num", exText(r)))),
    h("td.col-ms", h("span.msst", modeBadge(r.mode), statusBadge(r.status))),
    h("td.r.num", secU(r.first_response_ms)),
    h("td.r.num", h("span.tt", h("span", secU(r.total_ms)),
      h("span.tt-bar", { "aria-hidden": "true" }, bar("b", r.first_response_ms), bar("i", r.background_ms)))),
    h("td.r.num", fmtN(r.tokens.total)),
    h("td.col-ms", h("span.vcell.num", contChip(r),
      h("span.vrow", { "aria-label": T("exLabel", { x: exPlain(r) }) }, dots(r), h("span.vtxt", exText(r))))));
  markRow(tr, r.id === L.sel);
  return tr;
}

function drawLog() {
  const rows = logRows();
  const cnt = s => rows.filter(r => r.status === s).length, cc = v => rows.filter(r => contKey(r) === v).length;
  const legend = (cls, l) => h("span", h("span.dots3", h("i" + cls)), l);
  const b = v => h("b", fmtN(v));
  fill($("#lcount"), h("span", TX("count", { n: b(rows.length), total: fmtN(D.requests.length) })),
    STATUSES.map(s => h("span", statusBadge(s), " ", fmtN(cnt(s)))),
    h("span", TX("contCount", {
      skip: b(cc("skipped")), ran: b(cc("ran")), stop: b(cc("stop")), none: b(cc("none")),
      added: b(sum(rows.map(r => r.added_final))), lost: b(rows.filter(r => r.lost_first > 0).length),
    })),
    h("span.dlg.col-ms", { "aria-hidden": "true" },
      legend(".on", T("lgKept")), legend(".add", T("lgAdded")), legend("", T("lgEmpty"))),
    hsHint("lhint", "span"));
  const at = rows.findIndex(r => r.id === L.sel);
  if (at < 0) L.sel = rows[0] ? rows[0].id : null;
  else if (at >= L.limit) L.limit = Math.ceil((at + 1) / PAGE) * PAGE; /* 고른 행은 항상 보이게 */
  const shown = rows.slice(0, L.limit), maxT = Math.max(1, ...D.requests.map(r => r.total_ms));
  const th = (k, l, cls = "") => {
    const on = L.sort.key === k, desc = L.sort.dir < 0;
    return h("th" + cls, { "aria-sort": on ? (desc ? "descending" : "ascending") : "none" },
      h("button", { type: "button", "data-sort": k }, l, on ? (desc ? " ↓" : " ↑") : ""));
  };
  /* 머리글은 sticky라 표를 내리면 행이 그 뒤로 지나간다(의도된 겹침) */
  const table = h("table.log",
    h("thead", { "data-allow-overlap": "" }, h("tr", th("task", T("thTask"), ".col-tu"), h("th", T("thInput")),
      h("th.col-ms", T("thModeStatus")), th("first", T("thFirst"), ".r"), th("total", T("thTotal"), ".r"),
      th("tok", T("thTok"), ".r"), th("add", T("thEx"), ".col-ms"))),
    h("tbody", shown.map(r => logRow(r, maxT))));
  const next = Math.min(PAGE, rows.length - shown.length);
  const more = rows.length > shown.length && h("p.lmore",
    h("button.btn", { type: "button", id: "lmore" }, icon("plus"), T("more", { k: fmtN(next) })),
    h("span.muted.small", T("shown", { a: fmtN(shown.length), b: fmtN(rows.length) })));
  fill($("#ltable"), rows.length ? table : h("p.empty", T("empty")), more);
  drawLogDetail();
  updateLayout();
  if (!L.scrolled) {
    L.scrolled = true;
    requestAnimationFrame(() => revealRow(L.sel));
  }
}

function revealRow(id) {
  const box = $("#ltable"), tr = box && id && box.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
  if (!tr || box.scrollHeight <= box.clientHeight + 2) return;
  const head = (box.querySelector("thead") || {}).offsetHeight || 0;
  const top = tr.offsetTop - head, bottom = tr.offsetTop + tr.offsetHeight;
  if (top < box.scrollTop || bottom > box.scrollTop + box.clientHeight) {
    box.scrollTop = Math.max(0, top - tr.offsetHeight);
  }
}

function pickRow(id) {
  L.sel = id;
  $$("#ltable tbody tr").forEach(tr => markRow(tr, tr.dataset.id === id));
  drawLogDetail();
  revealRow(id);
  if (!["xl", "l"].includes(document.body.dataset.w)) $("#ldetail").scrollIntoView({ block: "nearest" });
}

function drawLogDetail() {
  const host = $("#ldetail"), id = L.sel, r = REQ.get(id);
  if (!r) {
    fill(host, h("p.empty", T("pickRow")));
    return;
  }
  const ftok = h("span", "…"), tbar = h("div", h("p.loading", T("traceLoading")));
  const noticeTime = r.background_ms > 0 && isNotice(r)
    ? [sec(r.background_ms), h("small", SEC())] : ["—", h("small", T("noNotice"))];
  const times = T("times");
  fill(host,
    h("div.ld-top",
      h("div.row", h("span.mono.idb", { title: r.id }, shortId(r.id)), modeBadge(r.mode), statusBadge(r.status),
        r.error_code && chip("err.mono", null, r.error_code)),
      h("button.btn.primary", { type: "button", on: { click: () => openGraph(id) } },
        icon("graph"), T("openGraph"), icon("arrow"))),
    h("p.row.meta.muted.num", icon("list"), h("span", T("evalRecord"), mono(r.task_id),
      T("meta", {
        a: r.attempt, cat: r.category || "—", lang: r.language || "—",
        exp: T(r.expect === "decline" ? "expDecline" : "expAnswer"),
      }))),
    h("p.qfull", r.question ?? T("noQuestion")),
    r.decline_note && h("p.en-block", { lang: "en" }, r.decline_note),
    kv([
      [T("kFirst"), sec(r.first_response_ms), h("small", SEC())], [T("kTotal"), sec(r.total_ms), h("small", SEC())],
      [T("kNotice"), ...noticeTime],
      [T("kTok"), fmtK(r.tokens.input), h("small", " / " + fmtK(r.tokens.output))], [T("kFirstTok"), ftok],
      [T("kCalls"), r.llm_calls, h("small", times), " · ", r.searches, h("small", times)],
      [T("kEx"), exText(r), noEx(r) ? "" : h("small", " /3")],
      [T("kCont"), contChip(r)], [T("kCost"), usd(r.cost_usd)], [T("kJudge"), judgeText(r)],
      r.lost_first > 0 && [T("kLost"), r.lost_first, h("small", T("pieces")), h("small.blk", lockWord())],
      r.locked_noops > 0 && [T("kNoop"), r.locked_noops, h("small", T("steps"))],
    ]),
    pairSection(r),
    h("section", h4("graph", T("barHead")), tbar),
    answersMini(r));
  getTraces().then(() => {
    if (L.sel !== id) return;
    const sp = spansOf(id), ft = firstTok(id);
    fill(ftok, fmtK(ft), h("small", ` (${pct(ft, r.tokens.total)}%)`));
    fill(tbar, sp.length ? timeBar(r, sp) : foot(T("noTrace")));
  }).catch(e => {
    if (L.sel !== id) return;
    fill(ftok, "—");
    fill(tbar, warnErr(e, () => (retryTraces(), drawLogDetail())));
  });
}

function pairSection(r) {
  const p = pairOf(r), other = r.mode === "agent" ? "baseline" : "agent";
  const head = h4("pair", T("pairHead"), T("pairSub", { t: r.task_id, a: r.attempt }));
  if (!p) return h("section.pairsec", head, foot(T("pairNone", { m: other })));
  const both = r.mode === "baseline" ? [r, p] : [p, r];
  const sel = x => (x === r ? ".sel" : "");
  const tr = (lab, f) => h("tr", h("td", lab), both.map(x => h("td.num" + sel(x), f(x))));
  return h("section.pairsec", head,
    h("div.pct-wrap", h("table.cmpt",
      h("thead", h("tr", h("th", T("pItem")), both.map(x => h("th" + sel(x), modeBadge(x.mode))))),
      h("tbody", tr(T("pReq"), x => mono(shortId(x.id))), tr(T("kFirst"), x => secU(x.first_response_ms)),
        tr(T("thTotal"), x => secU(x.total_ms)), tr(T("thTok"), x => fmtN(x.tokens.total)), tr(T("kEx"), exText),
        tr(T("pCont"), contChip), tr(T("pJudge"), judgeText)))),
    h("p.ld-top", h("button.btn", { type: "button", on: { click: () => pickPair(p) } }, icon("pair"),
      T("pickPair", { m: other })),
    h("span.muted.small", T("pairNote"))));
}

function pickPair(p) {
  if ($(`#ltable tr[data-id="${CSS.escape(p.id)}"]`)) return pickRow(p.id);
  Object.assign(L, { mode: "all", cont: "all", add: "all", q: "", sel: p.id });
  L.status.add(p.status);
  $("#lf-add").value = "all";
  $("#lf-q").value = "";
  syncFilters();
  drawLog();
  revealRow(p.id);
}

function answersMini(r) {
  const A = D.answers[r.id];
  if (!A || (!A.final.length && !A.first.length)) return null;
  return h("section", h4("mic", T("answers"), T("answersSub")), h("ol.answers-mini",
    A.final.map(f => h("li", slotTag(r, f), enT(f.expression))),
    lostFirst(A).map(f => h("li", lostTag(), enT(f.expression)))));
}
