/* 4. 실행 그래프 — 요청 한 건을 세 겹으로 본다.
   ① 구성요소 노선도(시안 A 방식): 모든 요청을 같은 자리의 같은 노드로 그리고 실제로 지난 길만 진하게(안 간 길은 점선·흐림).
   ② 스윔레인 워터폴(시안 C 방식): 구성요소 레인마다 막대, 시간축, 첫 응답 세로선, 회차 구분.
   ③ 단계 상세(graph-detail.js). 노드를 고르면 그 노드의 막대가, 막대를 고르면 그 노드가 같이 강조된다.
   엣지 · 스윔레인 표식은 실제 위치를 재서 그린다(폭 · 글자 크기가 바뀌면 dyn에서 다시). 화면 문구는 GRAPH_TEXT에 모은다. */
import { $, $$, fill, fmtK, fmtN, h, icon, rootPx, sec, secU, shortId, sum, sv, utc } from "./ui.js";
import { D, LIVE, REQ, getTraces, lockApplied, noEx, spansOf } from "./data.js";
import {
  KIND, STATUS, chip, contChip, exText, kk, markKind, modeBadge, mono, onSeg, phead, pill, preChip, segBtns, stageTitle,
  statusBadge,
} from "./parts.js";
import {
  buildEdges, endReason, laneOf, lanesFor, noQuestion, rowWhy, runModel, spanSummary, stepOf, toolsOf,
} from "./graph-model.js";
import { drawDetail } from "./graph-detail.js";
import { gtext } from "./i18n-graph.js";
import { t } from "./i18n.js";
import "./i18n-live.js";
import { hscrollCue, register, showTab, updateLayout } from "./shell.js";

/* 화면 문구: i18n-graph.js의 "graph.tab.*". 언어 보기라서 읽을 때마다 지금 언어 값이 나온다(탭은 언어가 바뀌면 다시 그려진다) */
export const GRAPH_TEXT = gtext("tab");
const T = GRAPH_TEXT, N = T.node, MT = T.meta, LN = T.lane, PH = T.phase, SW = T.swim;

let G = null; /* { req, picked, sel: 노드 키, span: 스팬 id, expanded: {요청 id: {baseline, agent}}, lay } */
let MODEL = null; /* { r, sp, R, M, edges, swim: { T0, TT } } */
let LOCK_EX = null; /* 잠금 건너뜀 예시 요청(잠금 적용 기록에만 있음) */
let bound = false;
const lockTxt = ids => [...ids].sort((a, b) => a - b).map(x => "s" + x).join("·");
const durOf = a => sum(a.map(s => s.elapsed_ms));
const tokOf = a => sum(a.filter(s => s.tokens).map(s => s.tokens.total));

/* ---------- 탭 ---------- */
register("graph", async panel => {
  fill(panel, h("p.loading", T.loading));
  await getTraces();
  LOCK_EX = (D.requests.find(r => spansOf(r.id).some(s => s.locked === true)) || {}).id || null;
  if (!G) {
    const o = exOpts(), pick = o.length ? (o.find(x => x[0] === "agent") || o[0])[2] : (D.requests[0] || {}).id;
    G = { req: pick, picked: null, sel: null, span: null, expanded: {}, lay: "stack" };
  }
  const pick = h("select", { id: "gpick" },
    h("optgroup", { label: t("live.groupEval") },
      D.requests.map(x => h("option", { value: x.id }, T.opt(x, (STATUS[x.status] || ["—"])[0])))),
    liveGroup());
  fill(panel,
    phead(T.title, [T.lead, !lockApplied() && [" ", h("b", T.preLock[0]), T.preLock[1]]]),
    h("div.gtop",
      h("div.gsel", h("div.seg", { id: "gsrc", role: "group", "aria-label": T.srcLabel }),
        h("label.field.g-pick", h("span", T.pickLabel), pick)),
      h("p.g-exnote", { id: "gexnote", hidden: true }),
      h("div.gsum", { id: "gsum" })),
    h("div.gl", { id: "gl" },
      h("section.gcard.g-route", { "aria-labelledby": "gh-route" },
        h("div.gc-h", h("h3", { id: "gh-route" }, icon("graph"), T.routeTitle), h("p", T.routeSub)),
        h("details.g-leg", { id: "gleg", open: true }, h("summary", T.legend), h("ul.g-legend", routeLegend())),
        h("p.hs-hint", { id: "ghint", hidden: true }, icon("arrow"), T.scrollHint),
        h("div.hs-host", h("div.g-scroll", {
          id: "gscroll", tabindex: 0, role: "region", "aria-label": T.routeRegion, "data-hscroll": "", "data-hint": "ghint",
        }, h("div.g-canvas", { id: "gcanvas" })))),
      h("aside.gdetail", { id: "gdetail", "aria-live": "polite", "aria-label": T.detailLabel }),
      h("section.gcard.g-swim", { "aria-labelledby": "gh-swim" },
        h("div.gc-h", h("h3", { id: "gh-swim" }, icon("chart"), T.swimTitle), h("p", T.swimSub)),
        h("ul.g-legend", { id: "swleg" }),
        h("div.swl-host", { id: "swim", role: "region", "aria-label": T.swimRegion }))));
  onSeg($("#gsrc"), (v, b) => {
    if (b.dataset.id && REQ.has(b.dataset.id)) openReq(b.dataset.id);
  });
  pick.addEventListener("change", () => openReq(pick.value, "#gpick"));
  if (!bound) bindPanel(panel);
  drawGraph();
}, graphDyn);

let lastW = null;
function graphDyn() {
  if (!MODEL || !$("#gcanvas")) return;
  const W = document.body.dataset.w, lg = $("#gleg");
  if (lg && W !== lastW) {
    lg.open = W !== "s";
    lastW = W;
  }
  layoutRoute();
  layoutSwim();
}

/* 요청 로그의 '실행 그래프로 보기' */
export function openGraph(id) {
  G ??= { req: id, picked: null, sel: null, span: null, expanded: {}, lay: "stack" };
  Object.assign(G, { req: id, picked: id, sel: null, span: null });
  if ($("#gcanvas")) drawGraph();
  showTab("graph").then(() => $("#tab-graph").focus());
}
function openReq(id, focusSel) {
  Object.assign(G, { req: id, sel: null, span: null });
  drawGraph();
  const f = focusSel && $(focusSel);
  if (f) f.focus();
}

/* 고르기 목록의 '실제 요청' 묶음(요청 로그에서 실제 요청을 읽은 뒤에만 생김) */
const liveOpt = x => t("live.opt", {
  time: utc(x.created_at || x.started_at), mode: x.mode, st: (STATUS[x.status] || ["—"])[0],
  q: (x.question || "").slice(0, 40),
});
const liveGroup = () => LIVE.rows.length ? h("optgroup", { id: "gpick-live", label: t("live.groupLive") },
  LIVE.rows.map(x => h("option", { value: x.id }, liveOpt(x)))) : null;
function syncLiveOpts(r) {
  const pick = $("#gpick");
  if (!pick || !r.live || [...pick.options].some(o => o.value === r.id)) return;
  const old = $("#gpick-live"), g = liveGroup();
  if (old) old.remove();
  if (g) pick.append(g);
}

function exOpts() {
  const ex = D.examples || {};
  return [["baseline", T.ex.baseline, ex.baseline], ["agent", T.ex.agent, ex.agent],
    ["skipped", T.ex.skipped, ex.skipped], ["lock", T.ex.lock, LOCK_EX]].filter(o => o[2] && REQ.has(o[2]));
}

/* ---------- 이벤트(패널에 한 번만 붙인다: 언어가 바뀌면 render가 다시 불린다) ---------- */
function bindPanel(panel) {
  bound = true;
  panel.addEventListener("click", e => {
    const t = e.target.closest("[data-toggle],[data-span],[data-jump],[data-node]");
    if (!t || t.disabled || !MODEL) return;
    if (t.dataset.toggle) {
      const m = t.dataset.toggle, ex = G.expanded[G.req];
      ex[m] = !ex[m];
      G.sel = null;
      G.span = null;
      drawGraph();
      const b = $(`#gcanvas [data-toggle="${m}"]`);
      if (b) b.focus();
    } else if (t.dataset.span || t.dataset.jump) selectSpan(t.dataset.span || t.dataset.jump);
    else selectNode(t.dataset.node);
  });
  const hl = key => {
    $$("#panel-graph .is-hl").forEach(x => x.classList.remove("is-hl"));
    if (key) $$(`#gcanvas [data-node="${CSS.escape(key)}"], #swim [data-node="${CSS.escape(key)}"]`)
      .forEach(x => x.classList.add("is-hl"));
  };
  panel.addEventListener("mouseover", e => {
    const n = e.target.closest("#gcanvas [data-node], #swim [data-node]");
    if (n) hl(n.dataset.node);
  });
  panel.addEventListener("mouseout", e => {
    const n = e.target.closest("#gcanvas [data-node], #swim [data-node]");
    if (n && !n.contains(e.relatedTarget)) hl(null);
  });
  panel.addEventListener("focusin", e => {
    const n = e.target.closest("#gcanvas [data-node], #swim [data-node]");
    hl(n ? n.dataset.node : null);
  });
}
function selectNode(key) {
  if (!MODEL.M.nodes[key]) return;
  G.sel = key;
  G.span = null;
  syncSel(true);
}
function selectSpan(id) {
  if (!MODEL.sp.some(s => s.id === id)) return;
  G.span = id;
  G.sel = MODEL.M.spanNode[id] || G.sel;
  syncSel(true);
}
/* 노드 ↔ 막대 연결 강조: 고른 노드 = aria-pressed, 그 노드의 막대 = is-grp, 고른 막대 = sel */
function syncSel(reveal) {
  $$("#gcanvas .gnode").forEach(n => n.setAttribute("aria-pressed", String(n.dataset.node === G.sel)));
  $$("#swim [data-span]").forEach(b => {
    const on = b.dataset.span === G.span;
    b.classList.toggle("sel", on);
    b.setAttribute("aria-pressed", String(on));
    b.classList.toggle("is-grp", !on && !!G.sel && b.dataset.node === G.sel);
  });
  drawDetail($("#gdetail"), MODEL.r, MODEL.M.nodes[G.sel] || null, G.span);
  if (reveal) revealDetail();
}
/* 상세가 옆이 아니라 아래에 있으면 고를 때 상세를 화면으로 데려온다 */
function revealDetail() {
  const c = $("#gdetail"), L = $("#gl");
  if (!c || !L || L.classList.contains("side")) return;
  const px = rootPx(), rc = c.getBoundingClientRect();
  const behavior = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  if (rc.top > innerHeight - px * 6 || rc.bottom < px * 4) c.scrollIntoView({ block: "start", behavior });
}

/* ---------- 그리기 ---------- */
function drawGraph() {
  const r = REQ.get(G.req);
  if (!r) {
    fill($("#gcanvas"), h("p.empty", T.noReq));
    return;
  }
  const sp = spansOf(r.id), R = runModel(r, sp), M = buildNodes(R);
  MODEL = { r, sp, R, M, edges: buildEdges(R, M), swim: null };
  if (!G.sel || !M.nodes[G.sel]) {
    G.sel = defaultSel(R, M);
    G.span = null;
  }
  drawHead(r);
  drawSummary(r, R);
  drawCanvas(R, M);
  drawSwim(r, sp, R);
  syncSel(false);
  requestAnimationFrame(() => {
    updateLayout();
    graphDyn();
  });
}
function defaultSel(R, M) {
  const r = R.r, { nodes, spanNode } = M;
  const firstRow = (r.mode === "baseline" ? M.rowsB : M.rowsA).find(x => x.nodes && x.nodes[0].state !== "skip");
  const lockedNode = Object.keys(nodes).find(k => nodes[k].spans.some(s => s.locked === true));
  if (R.err) return spanNode[R.err.id] || "cand";
  if (r.status === "declined") return "decl";
  if (R.skipped) return "asm";
  return lockedNode || (R.hasCont && firstRow ? firstRow.nodes[0].key : "val1");
}

function drawHead(r) {
  const opts = exOpts();
  const logId = G.picked && !opts.some(o => o[2] === G.picked) ? G.picked : null;
  const src = (opts.find(o => o[2] === G.req) || ["log"])[0];
  const srcOpt = ([v, l, id]) => [v, [h("span", l), id ? h("span.mono", shortId(id)) : h("span", T.exNone)],
    { "data-id": id, disabled: !id, title: id || T.logTip }];
  fill($("#gsrc"), segBtns([...opts, ["log", T.ex.log, logId]].map(srcOpt), v => src === v));
  syncLiveOpts(r);
  $("#gpick").value = r.id;
  const ex = D.examples || {}, isEx = (opts.find(o => o[2] === r.id) || [null])[0];
  const other = REQ.get(ex[isEx === "agent" ? "baseline" : "agent"]);
  let note = null;
  if ((isEx === "baseline" || isEx === "agent") && other) {
    note = T.exPair(mono(r.task_id), r.attempt, r.verified_first, r.mode, r.added_final, other.mode, other.added_final);
  } else if (isEx === "skipped") {
    note = [T.exSkip(r.verified_first), r.mode === "baseline" && !lockApplied(r) ? T.exSkipPre : ""];
  }
  const box = $("#gexnote");
  box.hidden = !note;
  fill(box, note && [icon("info"), h("span", note)]);
}

function drawSummary(r, R) {
  const fv = [...R.lockSet].length ? [...R.lockSet] : null;
  const pre = r.mode === "agent" && r.continuation === "ran" && !lockApplied(r) && R.val1[0] &&
    (R.val1[0].detail || {}).verified > 0;
  const fvList = pre ? (R.val1[0].detail.slots || []).filter(x => x.status === "verified").map(x => "#" + x.slot).join("·") : "";
  fill($("#gsum"), h("div.gq", modeBadge(r.mode), statusBadge(r.status), h("q", r.question ?? noQuestion())),
    h("div.pills.num", pill(icon("list"), T.sum.task, mono(r.task_id), T.sum.attempt(r.attempt)),
      pill(T.sum.first, h("b", secU(r.first_response_ms))), pill(T.sum.total, h("b", secU(r.total_ms))),
      pill(T.sum.tok, h("b", fmtN(r.tokens.total))), pill("LLM ", h("b", r.llm_calls), T.sum.calls, h("b", r.searches), T.sum.times),
      pill(T.sum.ex, exText(r), noEx(r) ? "" : " /3"), contChip(r),
      fv && r.mode === "agent" ? h("span.lockc", icon("lock"), MT.lock(lockTxt(fv))) : null,
      pre && fvList ? preChip(T.sum.preFv(fvList)) : null,
      r.error_code && chip("err.mono", null, r.error_code)),
    MODEL.sp.length ? null : h("p.foot", T.noTrace));
}

/* ---------- 노선도: 템플릿 노드 ---------- */
function slotDots(v, L = new Set()) {
  const slots = v && v.detail && Array.isArray(v.detail.slots) ? v.detail.slots : null;
  if (!slots) return null;
  const ids = slots.filter(s => L.has(s.slot)).map(s => s.slot);
  const dot = s => (L.has(s.slot) ? h("i.v.lk", { title: MT.slotLock(s.slot) }, icon("lock"))
    : s.status === "verified" ? h("i.v", { title: MT.slotV(s.slot) }, icon("check")) : h("i", { title: MT.slotEmpty(s.slot) }));
  const label = MT.slotsAria(v.detail.verified, slots.length, ids.length ? lockTxt(ids) : "");
  return [h("span.gslots", { role: "img", "aria-label": label }, slots.map(dot)),
    h("span.num", `${v.detail.verified}/${slots.length}`), ids.length ? lockLine(ids, MT.lockTip) : null];
}
const lockLine = (ids, title) => h("span.glock", { title }, icon("lock"), MT.lock(lockTxt(ids)));
function actChip(s, LK) {
  const d = s.detail || {}, t = s.stage.split("_")[0], sl = d.slot != null ? " s" + d.slot : "", title = spanSummary(s);
  if (s.locked === true) return h("span.gact.lock", { title }, icon("lock"), MT.skipped(t + sl));
  if (d.noop) return h("span.gact.noop", { title }, icon("skip"), MT.skipped(t + sl));
  if (stepOf(s) === "search") {
    const onLocked = d.slot != null && LK && LK.has(d.slot);
    return h("span.gact", { title }, icon("search"), "search" + sl, onLocked ? icon("lock", "mini") : null);
  }
  const oc = String(d.outcome || "");
  const cls = oc === "verified" || oc === "replaced" ? ".ok" : oc.startsWith("rejected") ? ".bad"
    : oc === "kept_verified_example" ? ".keep" : "";
  return h("span.gact" + cls, { title }, icon(cls === ".bad" ? "x" : cls === ".ok" ? "check" : "tool"), t + sl);
}
function judgeMeta(spans) {
  const ls = [...new Set(spans.flatMap(s => (Array.isArray((s.detail || {}).locked_slots) ? s.detail.locked_slots : [])))];
  const one = s => {
    const d = s.detail || {};
    if (s.status === "error") return h("span", MT.errOf, mono(d.error_code || "—"));
    const c = {};
    (d.actions || []).forEach(a => { c[a.type] = (c[a.type] || 0) + 1; });
    const acts = Object.entries(c).map(([k, v]) => `${k} ${v}`).join(" · ") || MT.noAct;
    return h("span", acts + (s.stage === "pick_final" ? "" : d.finish ? MT.toEnd : MT.toNext));
  };
  return [spans.map(one), ls.length ? lockLine(ls, MT.judgeLockTip) : null];
}

function buildNodes(R) {
  const r = R.r, LK = R.lockSet, isB = r.mode === "baseline", isA = r.mode === "agent", hasCont = R.hasCont;
  G.expanded[r.id] ??= { baseline: isB && hasCont, agent: isA && hasCont };
  const EX = G.expanded[r.id], nodes = {}, spanNode = {};
  const node = (key, o) => {
    Object.assign(o, { key, spans: o.spans || [] });
    nodes[key] = o;
    o.spans.forEach(s => { spanNode[s.id] = key; });
    return o;
  };
  const nd = (key, kind, title, code, spans, meta) => node(key, { kind, title, code, spans, meta });
  const sp = (a, fn) => (a.length ? fn(a) : null);
  node("req", { kind: "request", title: N.req, state: "done",
    meta: [h("span.num", shortId(r.id)), h("span", MT.attempt(r.attempt))] });
  const cd = R.cand[0] && R.cand[0].detail;
  const candMeta = !cd ? null : cd.request_status && cd.request_status !== "answerable"
    ? h("span", MT.verdict, mono(cd.request_status)) : h("span", MT.cand((cd.candidates || []).length, fmtK(tokOf(R.cand))));
  nd("cand", "llm", N.cand, "candidates", R.cand, candMeta);
  nd("decl", "decline", N.decl, "decline", R.decl, h("span", R.decl.length ? MT.declYes : MT.declIf));
  const lit = s => (s.detail || {}).corpus_count > 0;
  const searchMeta = a => [
    h("span.cells6", { "aria-hidden": "true" }, a.map(s => h("i" + (s.status === "error" ? ".err" : lit(s) ? ".lit" : "")))),
    h("span", { title: MT.litTip }, MT.lit(a.filter(lit).length)),
    h("span", { title: MT.fbTip }, MT.fb(a.filter(s => s.status !== "error" && !lit(s)).length))];
  nd("srch", "search", N.srch(R.srch.length || 6), "search_1..6", R.srch, sp(R.srch, searchMeta));
  const s1 = R.sel1[0], d1 = (s1 && s1.detail) || {};
  nd("sel1", "llm", N.sel1, "select_1", R.sel1, d1.picks != null ? h("span", MT.picks(d1.picks_with_ref, d1.picks, fmtK(tokOf(R.sel1)))) : null);
  const lost = r.lost_first ? h("span.glock.lost", { title: MT.lostTip }, icon("x"), MT.lostN(r.lost_first)) : null;
  nd("val1", "verify", N.val1, "validate_select_1", R.val1,
    [slotDots(R.val1[0]), hasCont && LK.size ? lockLine(LK, MT.lockTip) : null, lost]);
  /* baseline 라운드(수정 → 검색 → 선택 → 검증) · agent 턴(판단 → 도구 → 검증). k = 0이면 회차를 겹쳐 하나로 */
  const nth = (k, a, b) => (k ? a : b);
  const bNodes = (k, part, pre) => [
    nd(pre + "rev", "llm", N.rev, nth(k, `revise_${k}`, "revise_r"), part("revise"), sp(part("revise"), a =>
      h("span", MT.repl(sum(a.map(s => ((s.detail || {}).replacements || []).length)), fmtK(tokOf(a)))))),
    nd(pre + "srch", "search", N.bsrch, nth(k, `search_${k}_k`, "search_r_k"), part("search"),
      part("search").length ? h("span", MT.searchN(part("search").length)) : h("span", { title: MT.reuseTip }, MT.reuse)),
    nd(pre + "sel", "llm", N.bsel, nth(k, `select_${k + 1}`, "select_r+1"), part("select"), sp(part("select"), a =>
      h("span", MT.picks2(sum(a.map(s => (s.detail || {}).picks_with_ref || 0)), sum(a.map(s => (s.detail || {}).picks || 0)))))),
    nd(pre + "val", "verify", N.val, nth(k, `validate_select_${k + 1}`, "validate_select_r"), part("validate"),
      sp(part("validate"), a => slotDots(a[a.length - 1], LK)))];
  const aNodes = (k, part, pre, fin) => [
    nd(pre + "judge", "judge", fin ? N.final : nth(k, N.judge(k), N.judge0), fin ? "pick_final" : nth(k, `agent_${k}`, "agent_r"),
      part("judge"), sp(part("judge"), judgeMeta)),
    nd(pre + "tools", "act", N.tools, fin ? "repick/replace_final_k" : nth(k, `*_${k}_k`, "search/repick/replace"),
      part("tools"), part("tools").length ? part("tools").map(x => actChip(x, LK)) : h("span", MT.noAct)),
    nd(pre + "val", "verify", N.val, fin ? "validate_pick_final" : nth(k, `validate_agent_${k}`, "validate_agent_r"),
      part("validate"), sp(part("validate"), a => slotDots(a[a.length - 1], LK)))];
  const rowsB = [], rowsA = [], BX = isB && EX.baseline, AX = isA && EX.agent;
  if (R.skipped && isB) rowsB.push({ k: 0, skipCont: true });
  else if (BX) R.B.forEach(x => rowsB.push({ k: x.k, nodes: x.revise.length ? bNodes(x.k, p => x[p], `b${x.k}.`) : null }));
  else rowsB.push({ k: 0, nodes: bNodes(0, p => R.B.flatMap(x => x[p]), "b.") });
  if (R.skipped && isA) rowsA.push({ k: 0, skipCont: true });
  else if (AX) {
    R.A.forEach(x => rowsA.push({ k: x.k, nodes: x.judge.length ? aNodes(x.k, p => x[p], `a${x.k}.`) : null }));
    rowsA.push({ k: "f", final: true, nodes: R.AF.judge.length ? aNodes(0, p => R.AF[p], "af.", true) : null });
  } else {
    const n = aNodes(0, p => R.A.flatMap(x => x[p]), "a.");
    const finalMeta = R.AF.judge.length ? judgeMeta(R.AF.judge) : h("span", { title: MT.finalTip }, MT.finalIf);
    n.push(nd("a.final", "judge", N.final, "pick_final", [...R.AF.judge, ...R.AF.tools, ...R.AF.validate], finalMeta));
    rowsA.push({ k: 0, nodes: n });
  }
  const a0 = (R.asm.find(s => s.stage === "assemble") || {}).detail, hasA0 = a0 && a0.expressions != null;
  const done = h("span.num", MT.done(secU(r.total_ms))), vf = r.verified_final == null ? "—" : r.verified_final;
  const asmMeta = R.skipped ? [h("span", MT.asmEx(hasA0 ? a0.expressions : "—", vf)), done]
    : hasA0 ? [h("span", MT.asmEx(a0.expressions, a0.with_example), r.added_final ? MT.added(r.added_final) : ""), done]
      : r.status === "error" ? h("span", R.err && R.err.phase === "first" ? MT.errFirst : MT.keepFirst) : null;
  nd("asm", "assemble", R.skipped ? N.asmSkip : N.asm, "assemble", R.asm, asmMeta);
  const state = spans => (!spans.length ? "skip" : spans.some(s => s.status === "error") ? "error" : "done");
  Object.values(nodes).forEach(n => { n.state ??= state(n.spans); });
  const actB = isB && hasCont, actA = isA && hasCont;
  [[actB, rowsB, "baseline"], [actA, rowsA, "agent"]].forEach(([act, rows, m]) => {
    if (act) return;
    rows.forEach(row => (row.nodes || []).forEach(n => {
      Object.assign(n, { state: "skip", compact: true, why: m !== r.mode ? LN.whyOther(r.mode) : endReason(R) });
    }));
  });
  ["b.rev", "b.srch", "b.sel", "b.val", "a.judge", "a.tools", "a.val"].forEach(k => {
    const n = nodes[k];
    if (!n || n.state === "skip") return;
    const c = new Set(n.spans.map(s => s.turn)).size;
    if (c > 1) n.stack = c;
  });
  return { nodes, spanNode, rowsB, rowsA, BX, AX, actB, actA, hasCont };
}

function nodeEl(n) {
  if (!n) return null;
  const kd = KIND[n.kind], dur = durOf(n.spans), tok = tokOf(n.spans);
  const label = `${n.title}, ${kd[0]}${n.state === "skip" ? T.ariaSkip : n.state === "error" ? T.ariaErr : ""}` +
    `${dur ? ", " + secU(dur) : ""}${tok ? T.ariaTok(fmtK(tok)) : ""}`;
  const cls = `button.gnode.k-${n.kind}.s-${n.state}` + (n.stack ? ".stack" + (n.stack === 2 ? ".s2" : "") : "") +
    (n.compact ? ".compact" : "");
  const kindText = n.state === "skip" && !n.compact ? T.notRun : n.state === "error" ? T.error : T.kindShort[n.kind];
  return h(cls, { type: "button", "data-node": n.key, "aria-pressed": String(G.sel === n.key), "aria-label": label },
    h("span.gn-top", h("span.gk", icon(kd[1])), h("span.gn-kind", kindText), dur ? h("span.gn-dur", secU(dur)) : null),
    h("span.gn-title", n.title, n.stack ? [" ", h("span.gn-count", "×" + n.stack)] : null),
    n.compact ? null : h("span.gn-meta", n.meta));
}

function laneEl(lane, R, M) {
  const r = R.r, LK = R.lockSet, isBL = lane === "B", m = isBL ? "baseline" : "agent";
  const rows = isBL ? M.rowsB : M.rowsA, active = isBL ? M.actB : M.actA, exp = isBL ? M.BX : M.AX;
  const ranCount = isBL ? R.B.filter(x => x.revise.length).length : R.A.filter(x => x.judge.length).length;
  const why = r.status === "declined" ? LN.declined : R.err ? LN.errFirst : LN.endFirst;
  const status = active ? chip(ranCount ? "lime" : "", null, LN.count(ranCount, isBL))
    : r.mode !== m ? chip("", null, LN.other(r.mode))
      : R.skipped ? chip("ok", "skip", LN.contSkip(r.verified_first)) : chip("", null, LN.noCont(why));
  const preLock = active && !isBL && !lockApplied(r)
    ? h("span.prechip", { title: D.meta.lock.note || "" }, icon("clock"),
      LN.preLock + (r.lost_first ? " · " + MT.lostN(r.lost_first) : "")) : null;
  const lockEl = active && LK.size ? h("span.lockc", { title: MT.lockTip }, icon("lock"), MT.lock(lockTxt(LK))) : null;
  const rowEl = row => {
    if (row.skipCont) return h("div.lane-row.skipped.cont-skip", icon("skip"), h("span", LN.skipRow(r.verified_first)));
    if (!row.nodes) {
      return h("div.lane-row.skipped", icon("ban"),
        h("span", LN.notRun(LN.rowName(row.final, isBL, row.k), rowWhy(R, isBL, row))));
    }
    return h("div.lane-row", row.nodes.map(nodeEl));
  };
  return h(`div.lane.${active ? "active" : "inactive"}.m-${m}`, { "data-lane": lane },
    h("div.lane-h", h("span.t", modeBadge(m), isBL ? LN.loopB : LN.loopA),
      h("span.chip.soft", icon(isBL ? "gear" : "bubble"), isBL ? LN.ruleB : LN.ruleA), status, lockEl, preLock,
      h("span.grow"),
      active ? h("button.btn.sm", { type: "button", "data-toggle": m, "aria-expanded": String(exp) },
        icon("loop"), exp ? LN.fold : LN.unfold) : null),
    h("div.lane-rows", rows.map(rowEl)),
    active ? h("div.lane-f", icon("arrow"), LN.end, h("b", endReason(R))) : null);
}

function immEl(r) {
  const k = markKind(r), vf = r.verified_first;
  if (k === "decl") return h("span.g-imm.none", icon("ban"), PH.decl(secU(r.total_ms)));
  if (k === "err") return h("span.g-imm.none", icon("alert"), PH.err(secU(r.total_ms)));
  if (k === "skip") return h("span.g-imm.done", icon("check"), PH.done(secU(r.first_response_ms), vf));
  if (k === "mid") {
    const fe = r.first_stage_ms != null ? Math.min(r.total_ms, r.first_stage_ms) : r.first_response_ms;
    return h("span.g-imm.mid", { title: PH.midTip }, icon("hour"), PH.mid(secU(fe)));
  }
  return h("span.g-imm", icon("bolt"), PH.imm(secU(r.first_response_ms), vf));
}

function drawCanvas(R, M) {
  const r = R.r, nodes = M.nodes;
  const phaseA = h("div.g-phase.a", h("span", h("b", PH.first), PH.firstSub,
    h("span.num", secU(durOf(R.sp.filter(s => s.phase === "first"))))), immEl(r));
  const phaseB = h("div.g-phase.b", h("span", h("b", PH.cont), " · ", r.mode, PH.only,
    r.background_ms ? [" · ", h("span.num", "+" + secU(r.background_ms))] : null),
  R.skipped ? h("span.g-skip", icon("skip"), PH.skip(r.verified_first)) : h("span.muted", PH.fill));
  const cv = $("#gcanvas");
  cv.dataset.lay = G.lay;
  fill(cv, sv("svg", { class: "g-edges", id: "gedges", "aria-hidden": "true" }), phaseA, phaseB,
    h("div.g-first", ["req", "cand", "decl", "srch", "sel1", "val1"].map(k => h("div.gf-" + k, nodeEl(nodes[k])))),
    h("div.g-laneB", laneEl("B", R, M)), h("div.g-laneA", laneEl("A", R, M)), h("div.g-asm", nodeEl(nodes.asm)));
}

function routeLegend() {
  const kinds = ["request", "llm", "judge", "search", "verify", "act", "assemble"], L = T.lg;
  return [kinds.map(k => h("li", h("span.gk.k-" + k, icon(KIND[k][1])), KIND[k][0])),
    h("li", h("span.ln"), L.taken), h("li", h("span.ln.d"), L.notTaken), h("li", h("span.ln.i"), L.imm),
    h("li", h("span.ln.ok"), L.done), h("li", h("span.ln.m"), L.mid),
    h("li", h("span.gslots", h("i.v.lk", icon("lock"))), L.lockSlot),
    h("li", h("span.gact.lock", icon("lock"), L.skipped), L.lockAct),
    h("li", icon("gear"), L.rule, " · ", icon("bubble"), L.llm)];
}

/* ---------- 노선도 배치와 엣지: 실제로 재서 그린다(시안 A 방식) ---------- */
/* 1) 배치: 옆 패널 + 첫 단계 가로 → 옆 패널 + 첫 단계 세로 열 → 한 단 + 세로 열 → 한 단 + 위→아래. 넘치지 않는 첫 배치 */
function chooseLayout(cv, Lay, sc, px) {
  const wide = ["xl", "l"].includes(document.body.dataset.w);
  const tries = [[true, "h"], [true, "stack"], [false, "stack"], [false, "tall"]].filter(t => wide || !t[0]);
  const apply = t => {
    Lay.classList.toggle("side", t[0]);
    if (cv.dataset.lay !== t[1]) cv.dataset.lay = t[1];
  };
  let pick = tries[tries.length - 1];
  for (const t of tries) {
    apply(t);
    if (sc.scrollWidth <= sc.clientWidth + 1) {
      pick = t;
      break;
    }
  }
  apply(pick);
  if (pick[1] === "tall") {
    const ln = cv.querySelector(".lane"), cs = ln && getComputedStyle(ln);
    const inner = ln ? ln.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) : 0;
    cv.style.setProperty("--lane-cols", inner >= (4 * 6.5 + 3 * 1.25) * px ? 4 : 2);
  } else cv.style.removeProperty("--lane-cols");
  return pick;
}

function layoutRoute() {
  const cv = $("#gcanvas");
  if (!cv || !cv.offsetParent || !MODEL) return;
  const svg = $("#gedges"), Lay = $("#gl"), sc = $("#gscroll"), px = rootPx();
  svg.setAttribute("width", 0);
  svg.setAttribute("height", 0);
  svg.replaceChildren();
  const pick = chooseLayout(cv, Lay, sc, px), tall = pick[1] === "tall";
  G.lay = pick[1];
  const base = cv.getBoundingClientRect(), W = cv.scrollWidth, H = cv.scrollHeight;
  for (const [k, v] of [["width", W], ["height", H], ["viewBox", `0 0 ${W} ${H}`]]) svg.setAttribute(k, v);
  const rbx = el => {
    const q = el.getBoundingClientRect();
    return { l: q.left - base.left, t: q.top - base.top, r: q.right - base.left, b: q.bottom - base.top,
      cx: (q.left + q.right) / 2 - base.left, cy: (q.top + q.bottom) / 2 - base.top };
  };
  const nodeOf = key => cv.querySelector(`.gnode[data-node="${CSS.escape(key)}"]`);
  const box = key => {
    const el = nodeOf(key);
    return el ? rbx(el) : null;
  };
  const laneB = cv.querySelector("[data-lane=B]"), laneA = cv.querySelector("[data-lane=A]");
  const LB = laneB && rbx(laneB), LA = laneA && rbx(laneA), lanes = [LB, LA].filter(Boolean);
  const lanesL = Math.min(...lanes.map(x => x.l)), lanesR = Math.max(...lanes.map(x => x.r));
  const lanesBot = Math.max(...lanes.map(x => x.b));
  const at = sel => rbx(cv.querySelector(sel)), FIRST = at(".g-first"), PA = at(".g-phase.a"), PB = at(".g-phase.b");
  const rad = Math.round(px * 0.5), ks = Math.max(1, px / 16);
  const marker = (id, color, sz) => sv("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: sz,
    markerHeight: sz, orient: "auto-start-reverse" }, sv("path", { d: "M0 0L10 5L0 10z", fill: color }));
  const out = [sv("defs", null, marker("garT", "#4938af", 7), marker("garD", "#b8b9c6", 6))];
  const draw = (d, taken) => out.push(sv("path", { d, fill: "none", stroke: taken ? "#4938af" : "#c4c6d1",
    "stroke-width": (taken ? 1.8 : 1.25) * ks, "stroke-dasharray": taken ? null : `${4 * ks} ${3 * ks}`,
    "marker-end": `url(#${taken ? "garT" : "garD"})`, opacity: taken ? 0.9 : 1 }));
  /* 둥근 직각 경로 */
  const orth = pts => {
    let d = `M${pts[0][0]} ${pts[0][1]}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
      const d1 = Math.min(rad, Math.hypot(x1 - x0, y1 - y0) / 2), d2 = Math.min(rad, Math.hypot(x2 - x1, y2 - y1) / 2);
      d += ` L${x1 - Math.sign(x1 - x0) * d1} ${y1 - Math.sign(y1 - y0) * d1}` +
        ` Q${x1} ${y1} ${x1 + Math.sign(x2 - x1) * d2} ${y1 + Math.sign(y2 - y1) * d2}`;
    }
    const last = pts[pts.length - 1];
    return d + ` L${last[0]} ${last[1]}`;
  };
  const isRight = (A, B) => B.l >= A.r - 1, isBelow = (A, B) => B.t >= A.b - 1;
  const bez = (A, B) => {
    const x1 = A.r, y1 = A.cy, x2 = B.l - 1, y2 = B.cy, dx = Math.max(10, (x2 - x1) / 2);
    return `M${x1} ${y1} C${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };
  const down = (A, B) => (Math.abs(A.cx - B.cx) < 2 ? `M${A.cx} ${A.b} L${A.cx} ${B.t - 1}`
    : orth([[A.cx, A.b], [A.cx, (A.b + B.t) / 2], [B.cx, (A.b + B.t) / 2], [B.cx, B.t - 1]]));
  const gL = lanesL - Math.round(px * 0.6), gR = lanesR + Math.round(px * 0.6), gR2 = lanesR + Math.round(px * 1.2);
  const yDiv = tall ? Math.round(FIRST.b + Math.min(px * 0.9, (PB.t - FIRST.b) / 2)) : 0;
  const yAsm = B => (lanesBot + B.t) / 2;
  const rowBox = key => {
    const el = nodeOf(key), row = el && el.closest(".lane-row");
    return row ? rbx(row) : null;
  };
  const path = (e, A, B) => {
    switch (e.type) {
      case "flow": return isRight(A, B) ? bez(A, B) : isBelow(A, B) ? down(A, B) : bez(A, B);
      case "enter": return isRight(A, B) ? bez(A, B)
        : orth([[A.cx, A.b], [A.cx, yDiv], [gL, yDiv], [gL, B.cy], [B.l - 1, B.cy]]);
      case "exit": return !tall && isRight(A, B) ? bez(A, B)
        : orth([[A.r, A.cy], [gR, A.cy], [gR, yAsm(B)], [B.cx, yAsm(B)], [B.cx, B.t - 1]]);
      case "decl": {
        const yb = H - Math.round(px * 0.6);
        return !tall ? orth([[A.cx, A.b], [A.cx, yb], [B.cx, yb], [B.cx, B.b + 1]])
          : orth([[A.r, A.cy], [gR2, A.cy], [gR2, B.cy], [B.r + 1, B.cy]]);
      }
      case "bypass": {
        if (!LB || !LA) return null;
        const yg = (LB.b + LA.t) / 2, xl = lanesL - Math.round(px * 0.55), xr = lanesR + Math.round(px * 0.55);
        return !tall ? orth([[A.r, A.cy], [xl, A.cy], [xl, yg], [xr, yg], [xr, B.cy], [B.l - 1, B.cy]])
          : orth([[A.cx, A.b], [A.cx, yDiv], [gL, yDiv], [gL, yg], [gR, yg], [gR, yAsm(B)], [B.cx, yAsm(B)],
            [B.cx, B.t - 1]]);
      }
      case "next": {
        const ra = rowBox(e.a), rb = rowBox(e.b), yg = ra && rb ? (ra.b + rb.t) / 2 : (A.b + B.t) / 2;
        return orth([[A.cx, A.b], [A.cx, yg], [B.cx, yg], [B.cx, B.t - 1]]);
      }
      case "loop": {
        const re = rowBox(e.a), y = (re ? re.b : Math.max(A.b, B.b)) + Math.round(px * 0.45);
        return orth([[A.cx, A.b], [A.cx, y], [B.cx, y], [B.cx, B.b + 1]]);
      }
      case "skiparc": {
        const y = Math.min(A.t, B.t) - Math.round(px * 0.3);
        return orth([[A.cx + px * 0.8, A.t], [A.cx + px * 0.8, y], [B.cx - px * 0.8, y], [B.cx - px * 0.8, B.t - 1]]);
      }
      default: return null;
    }
  };
  MODEL.edges.slice().sort((a, b) => a.taken - b.taken).forEach(e => {
    const A = box(e.a), B = box(e.b);
    if (!A || !B) return;
    const d = path(e, A, B);
    if (d) draw(d, e.taken);
  });
  /* 첫 응답 시점 선: 즉시 결과(라임) · 즉시 완료(초록) · 예문 0개 대기(회색 점선) · 거절 · 첫 단계 오류(없음) */
  const mk = markKind(MODEL.r);
  const lk = mk === "skip" ? "done" : mk === "imm" || mk === "v3" ? "imm" : mk === "mid" && MODEL.R.hasCont ? "mid" : null;
  if (lk && lanes.length) {
    const a = { stroke: lk === "imm" ? "#7f9c14" : lk === "done" ? "#2b6a45" : "#6b6c80", "stroke-width": 2 * ks,
      "stroke-dasharray": lk === "mid" ? `${2.5 * ks} ${3 * ks}` : `${6 * ks} ${4 * ks}`, opacity: 0.9 };
    if (!tall) {
      const x = Math.round((FIRST.r + lanesL) / 2);
      out.push(sv("line", { x1: x, x2: x, y1: PA.b, y2: H - Math.round(px * 1.1), ...a }));
    } else {
      const y = Math.round(PB.t - px * 0.375);
      out.push(sv("line", { x1: Math.round(px * 0.25), x2: W - Math.round(px * 0.25), y1: y, y2: y, ...a }));
    }
  }
  svg.replaceChildren(...out);
  hscrollCue(sc);
}

/* ---------- 스윔레인 워터폴(시안 C 방식): 레인별 막대 · 시간축 · 첫 응답 세로선 · 회차 구분 ---------- */
function drawSwim(r, sp, R) {
  const host = $("#swim"), A = r.mode === "agent", mk = markKind(r), skipped = mk === "skip";
  const T0 = Math.max(r.total_ms, ...sp.map(s => s.start_ms + s.elapsed_ms), 1), ghost = skipped ? T0 * 0.3 : 0;
  const TT = T0 + ghost, P = t => `${((t / TT) * 100).toFixed(3)}%`;
  MODEL.swim = { T0, TT };
  const fe = durOf(sp.filter(s => s.phase === "first"));
  const inst = ["imm", "v3", "skip"].includes(mk) ? r.first_response_ms : null;
  const segs = [{ s: 0, e: Math.max(fe, 1), t: SW.segFirst, cls: ".first" }];
  if (skipped) segs.push({ s: T0, e: TT, t: SW.segSkip, cls: ".skip" });
  const turns = [...new Set(sp.filter(s => s.phase === "continuation" && s.turn != null).map(s => s.turn))].sort((a, b) => a - b);
  for (const t of turns) {
    const ss = sp.filter(s => s.turn === t && s.phase === "continuation");
    const s0 = Math.min(...ss.map(s => s.start_ms)), e0 = Math.max(...ss.map(s => s.start_ms + s.elapsed_ms));
    segs.push({ s: s0, e: Math.max(e0, s0 + 1), t: SW.turn(A, t), short: SW.turnShort(A, t), cls: "" });
  }
  const vls = () => [inst != null && h("i.vl.inst", { css: { left: P(inst) } }),
    segs.filter(x => !x.cls).map(x => h("i.vl", { css: { left: P(x.s) } })),
    h("i.vl.fin", { css: { left: `min(${P(r.total_ms)}, calc(100% - 1px))` } })];
  const skS = sp.find(s => s.stage === "continuation_skipped");
  const zone = l => {
    if (!skipped) return null;
    const pos = { left: P(T0), width: P(ghost) };
    if (l !== "judge") return h("i.skipzone", { "aria-hidden": "true", css: pos });
    const attrs = { css: pos, title: SW.zone(r.verified_first) };
    return skS ? h("button.skipzone", { type: "button", "data-span": skS.id, "data-node": MODEL.M.spanNode[skS.id], ...attrs },
      SW.zoneShort) : h("span.skipzone", attrs, SW.zoneShort);
  };
  const lanes = lanesFor(r.mode).map(l => {
    const spans = sp.filter(s => laneOf(s) === l.id && s !== skS), inner = [vls(), zone(l.id)];
    if (!spans.length && !(skipped && l.id === "judge")) {
      inner.push(h("span.lane-empty", l.id === "judge" ? (r.status === "declined" ? SW.emptyDecl : SW.emptyEnd(endReason(R)))
        : SW.empty));
    }
    const lastAt = {};
    for (const s of spans) inner.push(barEl(s, r, P, lastAt));
    return [h("div.swl-lab.k-" + l.kind, h("b", icon(l.ic), l.t), h("small", l.s)), h("div.swl-tr", { "data-lane": l.id }, inner)];
  });
  const segEls = segs.map(x => h("span.seg-h" + x.cls, { title: `${x.t} · ${sec(x.s)}–${sec(x.e)}`,
    "data-l1": x.t, "data-l2": x.short || "", css: { left: P(x.s), width: P(x.e - x.s) } }, h("span", x.t)));
  const marks = [];
  if (inst != null) {
    marks.push(h("span.swl-ml.inst", { "data-t": inst, "data-l1": SW.inst(skipped, secU(inst), r.verified_first),
      "data-l2": SW.instShort(skipped, secU(inst), r.verified_first) }, icon("bolt"), h("span")));
  }
  if (!skipped) {
    const F = SW.fin, sent = mk === "imm" || mk === "v3";
    const label = r.status === "declined" ? F.decl : r.status === "error" ? (sent ? F.errCont : F.err)
      : r.verified_first === 0 ? F.once : r.added_final ? F.added(r.added_final) : r.verified_first >= 3 ? F.all : F.none;
    marks.push(h("span.swl-ml.fin", { "data-t": r.total_ms, "data-end": "1", "data-l1": `${label} ${secU(r.total_ms)}`,
      "data-l2": secU(r.total_ms) }, icon(r.status === "error" ? "alert" : "check"), h("span")));
  }
  fill(host, h("div.swl", { id: "swl" },
    h("div.swl-lab.hd", h("b", icon("user"), SW.who)), h("div.swl-tr.hd.who", vls(), marks),
    h("div.swl-lab.hd", h("b", icon("loop"), SW.seg)), h("div.swl-tr.hd.segs", vls(), segEls),
    h("div.swl-lab.hd", h("b", icon("clock"), SW.time)), h("div.swl-tr.hd.axis"),
    lanes, sv("svg", { class: "swl-links", "aria-hidden": "true" })));
  drawSwimLegend(sp, skipped);
}

function barEl(s, r, P, lastAt) {
  const k = kk(s), err = s.status === "error", d = s.detail || {};
  const tok = s.tokens ? SW.tok(fmtN(s.tokens.input), fmtN(s.tokens.output)) : "";
  const aria = `${stageTitle(s, r.mode)} · ${s.stage} · ${secU(s.elapsed_ms)}${tok}${err ? SW.errA : ""}` +
    `${s.locked === true ? SW.lockA : ""}`;
  const base = { type: "button", "data-span": s.id, "data-node": MODEL.M.spanNode[s.id] || null, title: aria,
    "aria-label": aria, "aria-pressed": "false" };
  if (s.elapsed_ms > 0) {
    return h(`button.swl-bar.k-${k}${err ? ".err" : ""}`, {
      ...base, "data-l1": `${s.stage} ${secU(s.elapsed_ms)}`, "data-l2": s.stage, css: { left: P(s.start_ms), width: P(s.elapsed_ms) },
    }, err ? icon("x") : null, h("span.swl-bl"));
  }
  /* 0초 단계: 검증 = 마름모(+ 슬롯 수), 도구 적용 = 네모, 잠금 noop = 자물쇠. 같은 자리에 겹치면 옆으로 민다 */
  const key = Math.round((s.start_ms / MODEL.swim.TT) * 400), off = (lastAt[key] = (lastAt[key] || 0) + 1) - 1;
  const lk = s.locked === true;
  const ok = !lk && (/verified|replaced/.test(String(d.outcome || "")) || k === "verify" || k === "assemble");
  const shape = lk ? ".lk" : k === "verify" || k === "assemble" ? ".dia" : ".sq";
  const slots = k === "verify" && Array.isArray(d.slots) ? d.slots : null;
  const tag = slots && h("span.mk-t", h("span.pips", slots.map(x =>
    h("i.pip" + (x.locked ? ".lk" : x.status === "verified" ? ".v" : "")))), `${d.verified ?? "?"}/${slots.length}`);
  return h(`button.swl-mk.k-${k}${shape}${ok ? ".ok" : ""}${err ? ".err" : ""}`,
    { ...base, css: { left: `min(calc(${P(s.start_ms)} + ${off * 1.25}rem), calc(100% - .6rem))` } },
    h("i.mk-shape", lk ? icon("lock") : null), tag);
}

function drawSwimLegend(sp, skipped) {
  const L = T.lg, kinds = [...new Set(sp.filter(s => s.elapsed_ms > 0).map(kk))];
  fill($("#swleg"), kinds.map(k => h("li", h("span.lgbar.k-" + k), KIND[k][0])),
    h("li", h("span.lgi.inst"), L.first), h("li", h("span.lgi.dash"), L.turn),
    h("li", h("span.lgi.dia"), L.dia), h("li", h("span.lgi.sq"), L.sq),
    sp.some(s => s.locked === true) ? h("li", h("span.lgi.lk", icon("lock")), L.lockAct) : null,
    skipped ? h("li", h("span.lgi.zone"), L.zone) : null,
    sp.some(s => toolsOf(s, sp).length) ? h("li", h("span.lgi.link"), L.link) : null);
}

/* 측정 단계: 막대 이름표 · 0초 표식 이름표 · 학습자 화면 표식 · 시간축 눈금 · 판단 → 도구 연결선 */
function layoutSwim() {
  const wf = $("#swl");
  if (!wf || !wf.offsetParent || !MODEL || !MODEL.swim) return;
  const px = rootPx(), { T0, TT } = MODEL.swim;
  for (const b of $$(".swl-bar", wf)) {
    const t = b.querySelector(".swl-bl");
    for (const c of [b.dataset.l1, b.dataset.l2, ""]) {
      t.textContent = c;
      if (b.scrollWidth <= b.clientWidth + 0.5) break;
    }
  }
  for (const s of $$(".seg-h", wf)) {
    const t = s.firstElementChild;
    for (const c of [s.dataset.l1, s.dataset.l2, ""]) {
      t.textContent = c;
      if (s.scrollWidth <= s.clientWidth + 0.5) break;
    }
  }
  for (const tr of $$(".swl-tr[data-lane]", wf)) {
    const W = tr.clientWidth;
    let prevR = -Infinity;
    for (const m of $$(".swl-mk", tr).sort((a, b) => a.offsetLeft - b.offsetLeft)) {
      const t = m.querySelector(".mk-t");
      m.classList.remove("flip");
      if (t) t.hidden = false;
      if (t && m.offsetLeft < prevR + 2) t.hidden = true;
      if (t && !t.hidden && m.offsetLeft + m.offsetWidth > W) {
        /* 오른쪽 끝에 걸리면 이름표를 왼쪽으로. 왼쪽 이름표가 앞 표식과 겹치면 이름표를 숨긴다 */
        if (m.offsetLeft + 0.9 * px - m.offsetWidth < prevR + 2) t.hidden = true;
        else m.classList.add("flip");
      }
      prevR = m.classList.contains("flip") || (t && t.hidden) ? m.offsetLeft + px : m.offsetLeft + m.offsetWidth;
    }
  }
  /* 학습자 화면 표식: 긴 문구부터, 안 들어가면 줄바꿈, 겹치면 아래 줄로 */
  const who = $(".swl-tr.who", wf), W2 = who.clientWidth, placed = [];
  let maxB = 0;
  for (const e of $$(".swl-ml", who)) {
    const x = (+e.dataset.t / TT) * W2, end = e.dataset.end === "1", label = e.lastElementChild;
    e.classList.remove("wrap");
    e.style.removeProperty("max-width");
    let L0 = null, w = 0;
    for (const t of [e.dataset.l1, e.dataset.l2]) {
      label.textContent = t;
      w = e.offsetWidth;
      for (const c of end ? [x - w - 4, x + 4] : [x + 4, x - w - 4]) {
        if (c >= 0 && c + w <= W2) {
          L0 = c;
          break;
        }
      }
      if (L0 != null) break;
    }
    if (L0 == null) {
      const rs = W2 - x - 4, ls = x - 4;
      e.classList.add("wrap");
      e.style.setProperty("max-width", Math.max(rs, ls, 3 * px) + "px");
      w = e.offsetWidth;
      L0 = rs >= ls ? Math.min(x + 4, W2 - w) : Math.max(0, x - w - 4);
    }
    let top = 0.3 * px;
    placed.forEach(q => { if (L0 < q.r + 6 && L0 + w > q.l - 6 && top < q.b + 2) top = q.b + 2; });
    e.style.setProperty("left", L0 + "px");
    e.style.setProperty("top", top + "px");
    placed.push({ l: L0, r: L0 + w, b: top + e.offsetHeight });
    maxB = Math.max(maxB, top + e.offsetHeight);
  }
  if (maxB) who.style.setProperty("min-height", maxB + 0.3 * px + "px");
  /* 시간축: 이름표가 겹치지 않는 가장 촘촘한 간격 */
  const axis = $(".swl-tr.axis", wf), W3 = axis.clientWidth;
  axis.replaceChildren();
  const probe = h("span.swl-tick", SW.tick(Math.round(T0 / 1000)));
  axis.append(probe);
  const lw = probe.offsetWidth;
  probe.remove();
  const step = [1000, 2000, 5000, 10000, 15000, 20000, 30000, 60000, 120000, 300000]
    .find(s => (s / TT) * W3 >= lw + 0.9 * px) || 600000;
  for (let t = 0; t <= T0; t += step) {
    const e = h("span.swl-tick", SW.tick(t / 1000));
    axis.append(e);
    const w = e.offsetWidth;
    e.style.setProperty("left", Math.max(0, Math.min(W3 - w, (t / TT) * W3 - w / 2)) + "px");
  }
  /* 판단(또는 수정) → 그 판단이 부른 도구 호출 연결선(막대 실제 위치) */
  const svg = $(".swl-links", wf), bx = wf.getBoundingClientRect(), sp = MODEL.sp, out = [];
  const rect = id => {
    const el = wf.querySelector(`[data-span="${CSS.escape(id)}"]`);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { l: b.left - bx.left, r: b.right - bx.left, cy: (b.top + b.bottom) / 2 - bx.top };
  };
  for (const s of sp) {
    const tg = toolsOf(s, sp), a = tg.length && rect(s.id);
    if (!a) continue;
    const col = /^revise/.test(s.stage) ? "#4938af" : "#a3286b";
    for (const t of tg) {
      const b = rect(t.id);
      if (!b) continue;
      const x2 = b.l + (b.r - b.l < 20 ? (b.r - b.l) / 2 : 0), dx = Math.max(16, (x2 - a.r) / 2);
      out.push(sv("path", { d: `M${a.r} ${a.cy} C${a.r + dx} ${a.cy} ${x2 - dx} ${b.cy} ${x2} ${b.cy}`, fill: "none",
        stroke: col, "stroke-width": 1.4, "stroke-dasharray": "3 2", opacity: 0.85 }),
      sv("circle", { cx: x2, cy: b.cy, r: 2.5, fill: col }));
    }
  }
  for (const [k, v] of [["width", bx.width], ["height", bx.height], ["viewBox", `0 0 ${bx.width} ${bx.height}`]]) {
    svg.setAttribute(k, v);
  }
  svg.replaceChildren(...out);
}
