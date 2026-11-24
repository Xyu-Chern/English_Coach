/* 3. 지표 — 소요시간과 토큰의 p50 · p95 · p99(nearest-rank). 최종 시간은 두 모드가 모두 후속을 실행한
   같은 평가 단위로만 비교한다(admin.js의 POP · stats.same). 문구는 "metrics.*". */
import {
  $, D, DIST, MODES, NEED, POP, SIZE, ST, fill, firstTok, fmtK, fmtN, foot, getTraces, h, hscroll, icon, kRow, kpi,
  lockWord, modeBadge, nEq, nr, onSeg, pct, phead, popNote, rerender, retryTraces, rootPx, runBar, sec, secU, seg,
  sv, syncSeg, usd, warnErr,
} from "./admin.js";
import { fmtNum, t, tx } from "./i18n.js";
import { openGraph } from "./tab-graph.js";
const T = (k, p) => t("metrics." + k, p), TX = (k, p) => tx("metrics." + k, p);
const tickSec = v => t("unit.sec", { n: fmtN(v) });
let MD = null; /* 모드별 묶음 + 첫 단계 토큰(ftok, trace 필요) */
let trend = "time"; /* 회차별 비교: time | tok */
export async function render(panel) {
  const benchmark = h("section.card.benchmark", h("p.loading", t("benchmark.loading")));
  fill(panel, benchmark, h("p.loading", T("loading")));
  const scorecard = renderBenchmark(benchmark);
  let tErr = null;
  await getTraces().catch(e => (tErr = e));
  MD = Object.fromEntries(MODES.map(m => [m, { ...ST[m], ftok: tErr ? [] : ST[m].ok.map(r => firstTok(r.id)) }]));
  const okN = MD.baseline.ok.length + MD.agent.ok.length, b = v => h("b", fmtN(v));
  const split = k => ({ b: fmtN(MD.baseline[k].length), a: fmtN(MD.agent[k].length) });
  const card = (cls, id, ic, title, ...body) =>
    h("section.card." + cls, { "aria-labelledby": id }, h("h3", { id }, icon(ic), ...title), ...body);
  fill(panel, benchmark,
    phead(T("title"), T("lead")),
    runBar(),
    tErr && warnErr(tErr, () => (retryTraces(), rerender("metrics")), T("traceFail")),
    popNote(),
    h("p.lcount.num",
      h("span", TX("cRun", { id: D.meta.run.id || "—", n: b(D.requests.length), size: SIZE })),
      h("span", TX("cOk", { n: b(okN), ...split("ok") })),
      h("span", TX("cRan", { n: b(MD.baseline.ran.length + MD.agent.ran.length), ...split("ran") })),
      h("span", TX("cFinal", { n: b(POP.common) }))),
    h("div.kpis", kpis()),
    h("div.mgrid",
      card("m-box", "h-box", "chart", [T("boxTitle"), h("small", T("boxSmall"))],
        h("div.box-host", { id: "boxchart" }), h("p.legend", boxLegend())),
      card("m-tbl", "h-pct", "list", [T("pctTitle")], hscroll(pctTable(), "pcttbl", T("pctTitle")), pctFoot()),
      card("m-trend", "h-trend", "clock",
        [h("span", { id: "trendTitle" }, T("trendTitle")), h("small", T("trendSmall"))],
        h("div.trend-tools", seg("mf-trend", T("trendMetric"), [["time", T("trendTime")], ["tok", T("trendTok")]],
          v => trend === v), h("span.muted.num", { id: "trendBucket" })),
        h("div.trend", { id: "trend" }), h("p.legend", { id: "trendlegend" }))));
  onSeg($("#mf-trend"), v => {
    trend = v;
    syncSeg($("#mf-trend"), x => x === trend);
    drawTrend();
  });
  await scorecard;
}
export function dyn() {
  drawBox(); drawTrend();
}

const B = (key, params) => t("benchmark." + key, params);
const SCORE_ROWS = ["accuracy", "pass3", "pass_at3", "model_calls", "tokens", "attack_success", "over_refusal"];
let benchmarkPromise;

async function fetchBenchmark() {
  const response = await fetch("benchmark.json", { cache: "no-cache" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("benchmark.json");
  const data = await response.json();
  if (data?.schema_version !== 1 || typeof data.run?.id !== "string" ||
      !MODES.every(mode => SCORE_ROWS.every(key => data.systems?.[mode]?.[key]))) {
    throw new Error("benchmark.json");
  }
  return data;
}

function scoreValue(key, value) {
  const share = (n, total) => [h("strong", pct(n, total) + "%"), h("small", `${fmtN(n)} / ${fmtN(total)}`)];
  if (key === "model_calls" || key === "tokens") {
    const digits = key === "model_calls" ? 2 : 0;
    const shown = fmtNum(value.mean, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    return [h("strong", shown), h("small", nEq(value.n))];
  }
  if (key === "attack_success" || key === "over_refusal") {
    if (!value.expected || value.judged < value.expected) {
      return [h("span.muted", B("pending")), value.expected > 0 && h("small", B("judged", {
        n: fmtN(value.judged), total: fmtN(value.expected),
      }))];
    }
    return share(value.events, value.expected);
  }
  return share(value.passed, value.n);
}

function benchmarkTable(data) {
  const { run, systems } = data;
  return [
    h("p.benchmark-run", B("run", { id: run.id, tasks: fmtN(run.tasks), repeats: fmtN(run.repeats) }),
      data.safety_prompts > 0 && [" · ", B("safetyScope", { attacks: fmtN(data.attack_prompts),
        total: fmtN(data.safety_prompts) })]),
    h("table.benchmark-table", { "aria-label": B("title") },
      h("thead", h("tr", h("th", { scope: "col" }, B("metric")), MODES.map(m => h("th", { scope: "col" }, modeBadge(m))))),
      h("tbody", SCORE_ROWS.map(key => h("tr", h("th", { scope: "row" }, B(key)),
        MODES.map(m => h("td.num." + m, scoreValue(key, systems[m][key]))))))),
    foot(B("method")),
  ];
}

function benchmarkFailure(data) {
  const f = data.failure;
  if (!f) return null;
  const request = data.run.id === D.meta.run.id && D.requests.find(r =>
    r.task_id === f.task_id && r.mode === f.variant && r.attempt === f.attempt);
  const fact = f.status === "error" ? B("failureError", { code: f.error_code || "—" })
    : f.status === "declined" ? B("failureDeclined")
      : f.expect === "answer" ? B("failureAnswer", {
        first: fmtN(f.verified_first), final: fmtN(f.verified_final), good: fmtN(f.grounded_good),
      }) : B("failureGrade");
  return h("div.benchmark-failure",
    h("h4", B("failure")),
    h("p.mono", [f.task_id, f.variant, f.attempt].join(" / ")),
    h("p", fact),
    request && h("button.btn.sm", { type: "button", on: { click: () => openGraph(request.id) } }, B("trace")));
}

async function renderBenchmark(host) {
  try {
    const data = await (benchmarkPromise ??= fetchBenchmark());
    if (!data) {
      fill(host, h("h3", icon("chart"), B("title")), foot(B("missing")));
      return;
    }
    const dialog = h("dialog.card.benchmark-dialog", { "aria-label": B("title") },
      h("div.benchmark-head", h("h3", B("title")),
        h("button.btn.sm", { type: "button", autofocus: true, on: { click: () => dialog.close() } }, B("close"))),
      benchmarkTable(data));
    fill(host, h("div.benchmark-head", h("h3", icon("chart"), B("title")),
      h("button.btn.sm", { type: "button", on: { click: () => dialog.showModal() } }, B("present"))),
    benchmarkTable(data),
    foot([data.run.model, data.run.corpus, data.run.judge_protocol,
      data.run.judge_votes && B("votes", { n: fmtN(data.run.judge_votes) })].filter(Boolean).join(" · ")),
    benchmarkFailure(data), dialog);
  } catch {
    benchmarkPromise = null;
    fill(host, h("h3", icon("chart"), B("title")), h("p.foot", { role: "status" }, B("invalid")));
  }
}

function kpis() {
  const both = ["agent", "baseline"], at = (a, q, f) => { const v = nr(a, q); return v == null ? "—" : f(v); };
  const per = f => both.map(m => `${m} ${f(MD[m])}`).join(" · "), v3 = MD.agent.v3ran.length;
  return [
    kpi(T("kFirst"), both.map(m => kRow(m, at(MD[m].first, 50, secU), nEq(MD[m].first.length))), T("kFirstSub")),
    kpi(T("kFinal"),
      both.map(m =>
        kRow(m, at(MD[m].final, 50, secU), `p95 ${at(MD[m].final, 95, secU)} · ${nEq(MD[m].final.length)}`)),
      T("kFinalSub", { n: fmtN(POP.common) }), T("kFinalTotal", { per: per(x => at(x.total, 95, secU)) })),
    kpi(T("kSkip"), both.map(m => {
      const { skip, ok } = MD[m], n = `${fmtN(skip)}/${T("cases", { k: fmtN(ok.length) })}`;
      return kRow(m, ok.length ? pct(skip, ok.length) + "%" : "—", n);
    }),
    T("kSkipSub", { c3: fmtN(DIST.c3), n: fmtN(DIST.n), p: pct(DIST.c3, DIST.n) }),
    v3 ? [" ", h("b", T("kSkipV3", { k: fmtN(v3), w: lockWord() }))] : null),
    kpi(T("kTok"), both.map(m => kRow(m, at(MD[m].ttok, 50, fmtN), nEq(MD[m].ttok.length))),
      T("kTokSub", {
        cost: per(x => usd(x.cost)), d: fmtN(MD.agent.dcl + MD.baseline.dcl), e: fmtN(MD.agent.err + MD.baseline.err),
      })),
  ];
}

/* ---------- 상자그림: 모드 × (첫 응답 / 최종) × (시간 / 토큰) ---------- */
function niceTicks(max, count) {
  if (!(max > 0)) return [0, 1];
  const raw = max / Math.max(1, count), mag = Math.pow(10, Math.floor(Math.log10(raw))), k = raw / mag;
  const step = (k <= 1 ? 1 : k <= 2 ? 2 : k <= 2.5 ? 2.5 : k <= 5 ? 5 : 10) * mag;
  const top = Math.ceil(max / step - 1e-9) * step, ticks = [];
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(+v.toFixed(6));
  return ticks;
}
function measureText(txt, cls) {
  const css = { position: "absolute", visibility: "hidden", "white-space": "nowrap", left: "0", top: "0" };
  const s = h("span." + cls, { css }, txt);
  document.body.append(s);
  const w = s.getBoundingClientRect().width;
  s.remove();
  return w;
}
const boxStats = a => ({ n: a.length, p5: nr(a, 5), p25: nr(a, 25), p50: nr(a, 50), p75: nr(a, 75), p95: nr(a, 95),
  p99: nr(a, 99) });
const COL = { agent: ["#4938af", "#e6e1fa"], baseline: ["#0f6e66", "#d3ede8"] };
/* 제목 · 행 이름은 그릴 때 지금 언어로 읽는다(getter · 키). 서식 함수도 그릴 때 부른다(admin.js와 순환 import) */
const FACETS = [
  { key: "time", get title() { return T("facetTime"); }, ic: "clock",
    get: (m, s) => (s === "first" ? MD[m].first : MD[m].final), fmt: v => sec(v),
    tick: v => tickSec(Math.round(v / 1000)) },
  { key: "tok", get title() { return T("facetTok"); }, ic: "spark",
    get: (m, s) => (s === "first" ? MD[m].ftok : MD[m].rtok), fmt: v => fmtK(v), tick: v => fmtK(v) },
];
const BOX_ROWS = [["baseline", "first", "rowFirst"], ["baseline", "final", "rowFinal"],
  ["agent", "first", "rowFirst"], ["agent", "final", "rowFinal"]];
function boxVals(f, b) {
  const d95 = b.n < NEED(95), d99 = b.n < NEED(99);
  return h("p.bx-vals.num", h("span", "p50 ", h("b", f.fmt(b.p50))),
    h("span" + (d95 ? ".dim" : ""), { title: d95 ? T("p95Tip", { n: fmtN(b.n), need: fmtN(NEED(95)) }) : null },
      "p95 ", h("b", f.fmt(b.p95)), d95 ? T("p95Ref") : ""),
    h("span" + (d99 ? ".dim" : ""), { title: d99 ? T("p99Tip", { n: fmtN(b.n), need: fmtN(NEED(99)) }) : null },
      d99 && icon("alert"), "p99 ", h("b", f.fmt(b.p99))),
    h("span.vn", nEq(b.n)));
}
function drawBox() {
  const host = $("#boxchart");
  if (!host || !host.offsetParent || !MD) return;
  const px = rootPx(), wide = host.clientWidth / px >= 38;
  for (const f of FACETS) f.max = Math.max(1, ...BOX_ROWS.flatMap(([m, s]) => f.get(m, s)));
  const lab = (m, l) => h("div.bx-lab", modeBadge(m), h("span", T(l)));
  const cell = (f, m, s) => {
    const a = f.get(m, s);
    return h("div.bx-cell", { "data-f": f.key, "data-m": m, "data-s": s },
      h("div.bx-plot"), a.length ? boxVals(f, boxStats(a)) : h("p.bx-empty", T("noSample")));
  };
  const ft = (f, full) => h("div.bx-ft" + (full ? ".full" : ""), icon(f.ic), f.title);
  const axis = f => h("div.bx-axis", { "data-f": f.key });
  fill(host, wide
    ? h("div.bx-grid", { css: { "grid-template-columns": "minmax(6.5rem,8.5rem) minmax(0,1fr) minmax(0,1fr)" } },
      h("div"), FACETS.map(f => ft(f)), BOX_ROWS.map(([m, s, l]) => [lab(m, l), FACETS.map(f => cell(f, m, s))]),
      h("div"), FACETS.map(axis))
    : FACETS.map(f => h("div.bx-grid", { css: { "grid-template-columns": "minmax(5.5rem,7rem) minmax(0,1fr)" } },
      ft(f, true), BOX_ROWS.map(([m, s, l]) => [lab(m, l), cell(f, m, s)]), h("div"), axis(f))));
  for (const f of FACETS) drawFacet(host, f, px);
}
function drawFacet(host, f, px) {
  const axis = host.querySelector(`.bx-axis[data-f="${f.key}"]`), cw = axis.clientWidth;
  if (!cw) return;
  const plotH = 2.1 * px, pad = 0.55 * px, sw = k => (k * px).toFixed(2), span = cw - 2 * pad;
  const count = Math.max(2, Math.min(6, Math.floor(span / (measureText(f.tick(f.max), "tick") * 2.1))));
  const ticks = niceTicks(f.max, count), top = ticks[ticks.length - 1], X = v => pad + (v / top) * span;
  /* 눈금 글자가 겹치지 않게: 간격이 가장 넓은 글자의 1.6배보다 좁으면 건너뛰어 붙인다(눈금선은 모두 그림) */
  const lw = Math.max(...ticks.map(v => measureText(f.tick(v), "tick")));
  const every = Math.max(1, Math.ceil((lw * 1.6) / (span / (ticks.length - 1))));
  const shift = i => (i === 0 ? -pad + "px" : i === ticks.length - 1 ? `calc(-100% + ${pad}px)` : "-50%");
  fill(axis, ticks.map((v, i) => (i % every ? null
    : h("span.tick.num", { css: { left: X(v) + "px", transform: `translateX(${shift(i)})` } }, f.tick(v)))));
  for (const c of host.querySelectorAll(`.bx-cell[data-f="${f.key}"]`)) {
    const a = f.get(c.dataset.m, c.dataset.s), [col, soft] = COL[c.dataset.m];
    const grid = v => sv("line", { x1: X(v), x2: X(v), y1: 0, y2: plotH, stroke: "#e4e5ea", "stroke-width": 1 });
    const g = ticks.map(grid);
    if (a.length) {
      const b = boxStats(a), cy = plotH / 2, bh = plotH * 0.46, d95 = b.n < NEED(95), d99 = b.n < NEED(99);
      const ln = (x1, x2, y1, y2, w, extra) =>
        sv("line", { x1, x2, y1, y2, stroke: "#3b3a52", "stroke-width": sw(w), ...extra });
      a.forEach((v, i) => {
        const j = ((i * 9301 + 49297) % 233280) / 233280; /* 고정 지터(다시 그려도 같은 자리) */
        g.push(sv("circle", { cx: X(v), cy: (cy + (j - 0.5) * plotH * 0.78).toFixed(1), r: sw(0.14), fill: col,
          "fill-opacity": 0.22 }));
      });
      g.push(ln(X(b.p5), X(b.p95), cy, cy, 0.09),
        ln(X(b.p5), X(b.p5), cy - bh * 0.45, cy + bh * 0.45, 0.09),
        ln(X(b.p95), X(b.p95), cy - bh * 0.6, cy + bh * 0.6, 0.13,
          d95 ? { "stroke-dasharray": `${sw(0.15)} ${sw(0.12)}` } : {}),
        sv("rect", { x: X(b.p25), y: cy - bh / 2, width: Math.max(1, X(b.p75) - X(b.p25)), height: bh, rx: sw(0.2),
          fill: soft, stroke: col, "stroke-width": sw(0.09) }),
        sv("line", { x1: X(b.p50), x2: X(b.p50), y1: cy - bh * 0.62, y2: cy + bh * 0.62, stroke: col,
          "stroke-width": sw(0.24), "stroke-linecap": "round" }));
      const d = 0.3 * px, x9 = X(b.p99);
      g.push(sv("path", { d: `M${x9} ${cy - d}L${x9 + d} ${cy}L${x9} ${cy + d}L${x9 - d} ${cy}Z`, fill: "#fff",
        stroke: col, "stroke-width": sw(0.1), "stroke-dasharray": d99 ? `${sw(0.1)} ${sw(0.08)}` : null,
        opacity: d99 ? 0.7 : null }));
    }
    fill(c.querySelector(".bx-plot"), sv("svg", { width: cw, height: plotH, "aria-hidden": "true" }, g));
  }
}
/* 범례 기호(작은 SVG) */
const GLYPHS = {
  box: [["rect", { x: 3, y: 3, width: 16, height: 8, rx: 2, fill: "#e6e1fa", stroke: "#4938af", "stroke-width": 1.5 }]],
  med: [["line", { x1: 11, x2: 11, y1: 1, y2: 13, stroke: "#4938af", "stroke-width": 3, "stroke-linecap": "round" }]],
  wh: [["path", { d: "M2 7h18M2 3v8M20 2v10", stroke: "#3b3a52", "stroke-width": 1.5 }]],
  dia: [["path", { d: "M11 2l5 5-5 5-5-5z", fill: "#fff", stroke: "#4938af", "stroke-width": 1.5 }]],
  pt: [["circle", { cx: 7, cy: 7, r: 2.5, fill: "#4938af", "fill-opacity": 0.35 }],
    ["circle", { cx: 14, cy: 5, r: 2.5, fill: "#4938af", "fill-opacity": 0.35 }]],
  p50b: [["circle", { cx: 11, cy: 7, r: 4.5, fill: "#0f6e66" }]],
  p50a: [["path", { d: "M11 2l5 5-5 5-5-5z", fill: "#4938af" }]],
  rng: [["path", { d: "M11 2v10M7 2h8", stroke: "#3b3a52", "stroke-width": 1.8 }]],
  first: [["rect", { x: 7, y: 3, width: 8, height: 8, fill: "#fff", stroke: "#3b3a52", "stroke-width": 1.6 }]],
};
const glyph = k => sv("svg", { class: "lg-glyph", viewBox: "0 0 22 14", "aria-hidden": "true" },
  (GLYPHS[k] || []).map(([tag, a]) => sv(tag, a)));
const item = (g, ...k) => h("span", g, ...k);
const boxLegend = () => [
  item(icon("info"), T("lgTok")),
  item(glyph("box"), T("lgBox")), item(glyph("med"), T("lgMed")), item(glyph("wh"), T("lgWh")),
  item(glyph("dia"), T("lgDia")), item(glyph("pt"), T("lgPt")),
  item(icon("alert"), T("lgSmall", { a: fmtN(NEED(95)), b: fmtN(NEED(99)) })),
];

/* ---------- 퍼센타일 표: [데이터 키, 이름 키(+ "Sub" = 설명), 토큰이면 true] ---------- */
const PCT_ROWS = [["first", "pFirst"], ["final", "pFinal"], ["total", "pTotal"], ["bg", "pBg"], ["ftok", "pFtok", 1],
  ["ttok", "pTtok", 1]];
function pctTable() {
  const cellP = (a, q, f) => {
    const v = nr(a, q);
    if (v == null) return h("td", "—");
    const dim = a.length < NEED(q);
    const tip = dim
      ? T("pTip", { n: fmtN(a.length), need: fmtN(NEED(q)) }) + (q === 99 && a.length < 100 ? T("pTipMax") : "")
      : null;
    return h("td.num" + (dim ? ".dim" : ""), { title: tip }, dim && q === 99 && [icon("alert"), " "], f(v));
  };
  const row = (k, label, f) => m => {
    const a = MD[m][k];
    return h("tr", h("td", label), h("td", modeBadge(m)), h("td.num", fmtN(a.length)), cellP(a, 50, f),
      cellP(a, 95, f), cellP(a, 99, f), h("td.num", a.length ? f(Math.max(...a)) : "—"));
  };
  const head = [T("pHMetric"), T("pHMode"), "n", "p50", "p95", "p99", T("pHMax")];
  return h("table.pct",
    h("thead", h("tr", head.map(x => h("th", x)))),
    h("tbody", PCT_ROWS.map(([k, key, tok]) => {
      const label = T(key);
      return [h("tr.grp", h("td", { colspan: 7 }, `${label} · ${T(key + "Sub")}`)),
        MODES.map(row(k, label, tok ? fmtN : secU))];
    })));
}
function pctFoot() {
  const ns = PCT_ROWS.flatMap(([k]) => MODES.map(m => MD[m][k].length)).filter(v => v > 0);
  const small = ns.filter(v => v < 100).length;
  return foot(T("pFoot"), T("pNeed", { a: fmtN(NEED(50)), b: fmtN(NEED(95)), c: fmtN(NEED(99)) }),
    small ? [icon("alert"), T("pSmall", { k: fmtN(small) })] : T("pAllBig"));
}

/* ---------- 회차별 비교: 평가 회차(attempt)마다 같은 지표를 다시 계산 ---------- */
function trendStats(runs, tok) {
  const val = tok ? r => r.tokens.total : r => r.total_ms, fval = tok ? r => firstTok(r.id) : r => r.first_response_ms;
  return runs.map(k => {
    const o = { k, n: D.requests.filter(r => r.attempt === k).length };
    for (const m of MODES) {
      const ok = MD[m].ok.filter(r => r.attempt === k), mo = tok ? ok : MD[m].same.filter(r => r.attempt === k);
      const tv = mo.map(val), f = ok.map(fval);
      o[m] = { n: mo.length, fn: ok.length, p50: nr(tv, 50), p95: nr(tv, 95), f50: nr(f, 50) };
    }
    return o;
  });
}
function drawTrend() {
  const host = $("#trend");
  if (!host || !host.offsetParent || !MD) return;
  const px = rootPx(), tok = trend === "tok", fmtT = tok ? fmtK : v => tickSec(Math.round(v / 1000));
  const runs = [...new Set(D.requests.map(r => r.attempt))].sort((a, b) => a - b);
  $("#trendTitle").textContent = T(tok ? "trendHeadTok" : "trendHeadTime");
  $("#trendBucket").textContent = T("bucket", { k: fmtN(runs.length) });
  if (!runs.length) {
    fill(host, h("p.empty", T("noRequests"))); fill($("#trendlegend"));
    return;
  }
  const st = trendStats(runs, tok), plotH = 8 * px;
  const mx = Math.max(1, ...st.flatMap(o => MODES.map(m => Math.max(o[m].p95 || 0, o[m].f50 || 0))));
  const tall = { css: { height: plotH + "px" } }, yBox = h("div.tr-y", tall), plot = h("div.tr-plot", tall);
  const what = T(tok ? "wOk" : "wSame");
  const xLabel = o => h("div", h("b", t("parts.attempt", { k: o.k })), h("span", T("reqN", { k: fmtN(o.n) })),
    MODES.map(m => h("span", { "aria-label": T("xAria", { m, what, n: fmtN(o[m].n) }) }, `${m[0]} ${o[m].n}`)));
  const cols = { css: { "grid-template-columns": `repeat(${st.length},minmax(0,1fr))` } };
  fill(host, h("div.tr-row", yBox, plot), h("div.tr-row", h("div"), h("div.tr-x.num", cols, st.map(xLabel))));
  const cw = plot.clientWidth, ticks = niceTicks(mx, Math.max(2, Math.min(6, Math.floor(plotH / (1.9 * px)))));
  const top = ticks[ticks.length - 1], padT = 0.6 * px, Y = v => plotH - (v / top) * (plotH - padT);
  const colW = cw / st.length, off = Math.min(0.5 * px, colW * 0.2), w = k => (k * px).toFixed(2);
  fill(yBox, ticks.map(v => h("span.num", { css: { top: Y(v) - 0.6 * px + "px" } }, fmtT(v))));
  const g = ticks.map(v => sv("line", { x1: 0, x2: cw, y1: Y(v), y2: Y(v), stroke: "#e4e5ea" }));
  st.forEach((o, i) => {
    if (i) g.push(sv("line", { x1: i * colW, x2: i * colW, y1: 0, y2: plotH, stroke: "#f0f0f3" }));
    MODES.forEach((m, k) => {
      const s = o[m];
      if (!s.n && !s.fn) return;
      const x = i * colW + colW * (k ? 0.64 : 0.36), col = COL[m][0], dim = s.n < 5;
      const grp = sv("g", { opacity: dim ? 0.5 : null });
      const ink = (attrs, width) => sv("line", { stroke: "#3b3a52", "stroke-width": w(width), ...attrs });
      if (s.n) {
        const dash = dim ? `${w(0.15)} ${w(0.12)}` : null;
        grp.append(ink({ x1: x, x2: x, y1: Y(s.p95), y2: Y(s.p50), "stroke-dasharray": dash }, 0.14),
          ink({ x1: x - 0.35 * px, x2: x + 0.35 * px, y1: Y(s.p95), y2: Y(s.p95) }, 0.14));
      }
      if (s.fn) { /* 첫 응답 □는 바깥쪽(baseline 왼쪽 · agent 오른쪽)으로 비켜 그림 */
        const fx = x + (k ? off : -off), fy = Y(s.f50), q = 0.24 * px;
        if (s.n) grp.append(ink({ x1: x, x2: fx, y1: fy, y2: fy, "stroke-dasharray": `${w(0.08)} ${w(0.08)}` }, 0.06));
        grp.append(sv("rect", { x: fx - q, y: fy - q, width: 2 * q, height: 2 * q, fill: "#fff", stroke: "#3b3a52",
          "stroke-width": w(0.1) }));
      }
      if (s.n) {
        const y = Y(s.p50), r = 0.34 * px, d = r * 1.2;
        grp.append(m === "agent"
          ? sv("path", { d: `M${x} ${y - d}L${x + d} ${y}L${x} ${y + d}L${x - d} ${y}Z`, fill: col })
          : sv("circle", { cx: x, cy: y, r, fill: col }));
      }
      g.push(grp);
    });
  });
  const label = T("byMode", { t: $("#trendTitle").textContent });
  fill(plot, sv("svg", { width: cw, height: plotH, role: "img", "aria-label": label }, g));
  fill($("#trendlegend"), item(glyph("p50b"), "baseline p50"), item(glyph("p50a"), "agent p50"),
    item(glyph("rng"), T("lgRng")), item(glyph("first"), T(tok ? "lgFirstTok" : "lgFirstTime")),
    item("", T("lgDim")), item("", T(tok ? "lgXTok" : "lgXTime")));
}
