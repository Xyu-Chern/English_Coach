/* 1. 모드 비교 — 맨 위 '현재 모드' 카드(서버 mode API, mode-card.js) + 같은 평가 실행 기록에서 baseline과 agent를
   같은 기준으로 비교하는 요약 한 화면. */
import { fill, fmtN, h, icon, nr, pct, secU, usd } from "./ui.js";
import { DIST, MODES, POP, ST, lockApplied } from "./data.js";
import { foot, hscroll, modeBadge, phead, popNote, runBar } from "./parts.js";
import { modeCard } from "./mode-card.js";
import { register } from "./shell.js";
import { t, tx } from "./i18n.js";
import "./i18n-tabs.js";

/* 화면 문자열: i18n-tabs.js의 "flags.*" 키. 탭 이름표는 같은 파일의 "tab.flags"가 정한다. */
const T = (k, p) => t("flags." + k, p);
const TX = (k, p) => tx("flags." + k, p);
const n = k => `n=${fmtN(k)}`;
const P95 = "p95 ";

/* ---------- 숫자 · 차이 ---------- */
const sign = v => (v > 0 ? "+" : v < 0 ? "−" : "±");
const rate = (a, b) => (b ? (a / b) * 100 : null);
const dSec = (b, a) =>
  (b == null || a == null ? "—" : sign(a - b) + t("unit.sec", { n: (Math.abs(a - b) / 1000).toFixed(1) }));
const dPP = (b, a) => (b == null || a == null ? "—" : sign(a - b) + T("pp", { v: Math.abs(a - b).toFixed(1) }));
const dNum = (b, a, unit = "") => (b == null || a == null ? "—" : `${sign(a - b)}${fmtN(Math.abs(a - b))}${unit}`);
/* 단위가 문장인 차이(예: "+3단계" · "+3 steps") */
const dKey = (b, a, key) => (b == null || a == null ? "—" : sign(a - b) + T(key, { n: fmtN(Math.abs(a - b)) }));
const dUsd = (b, a) => `${sign(a - b)}${usd(Math.abs(a - b))}`;
const rateTxt = (a, b) => (b ? `${pct(a, b)}%` : "—");
let B = null, A = null; /* 모드별 묶음(ST는 data.json을 읽은 뒤에 채워져서 그릴 때 잡는다) */

register("flags", panel => {
  B = ST.baseline;
  A = ST.agent;
  fill(panel,
    phead(T("title"), T("lead")),
    modeCard(), /* 서버의 현재 모드(읽기 · 바꾸기) — 아래 비교는 평가 실행 기록 */
    runBar(),
    popNote(),
    h("div.kpis", kpis(B, A)),
    h("div.fgrid", timeCard(), qualCard()));
});

/* ---------- 머리 숫자 4개 ---------- */
function kpis(b, a) {
  const kRow = (m, v, k) => h("div.kr", modeBadge(m), h("span.v.num", v), h("span.n.num", k));
  const kpi = (title, rows, sub) => h("div.kpi", h("h3", title), rows, h("p.sub", sub));
  const both = f => MODES.map(m => f(m, ST[m]));
  const p50 = k => both((m, x) => nr(x[k], 50));
  const [f0, f1] = p50("first"), [l0, l1] = p50("final"), [t0, t1] = p50("ttok");
  const secRow = key => both((m, x) =>
    kRow(m, secU(nr(x[key], 50)), `${P95}${secU(nr(x[key], 95))} · ${n(x[key].length)}`));
  return [
    kpi(T("kpiJudge"), both((m, x) => kRow(m, rateTxt(x.pass, x.graded), `${x.pass}/${x.graded}`)),
      T("kpiJudgeSub", {
        d: dPP(rate(b.pass, b.graded), rate(a.pass, a.graded)), sb: rateTxt(b.strict, b.strictN),
        sa: rateTxt(a.strict, a.strictN),
      })),
    kpi(T("kpiFirst"), secRow("first"), T("kpiFirstSub", { d: dSec(f0, f1) })),
    kpi(T("kpiFinal"), secRow("final"), T("kpiFinalSub", { d: dSec(l0, l1), n: fmtN(POP.common) })),
    kpi(T("kpiTok"), both((m, x) => kRow(m, fmtN(nr(x.ttok, 50)), n(x.ttok.length))),
      T("kpiTokSub", { d: dNum(t0, t1), cb: usd(b.cost), ca: usd(a.cost) })),
  ];
}

/* ---------- 비교 표 공용: [이름, 설명] · 모드별 칸 · 차이 칸 ---------- */
const nw = (...k) => h("span.nw", ...k);
const lab = (key, p) => [T(key), T(key + "Sub", p)];
function table(rows, extra) {
  return h("table.cmpt",
    h("thead", h("tr", h("th", T("metric")), MODES.map(m => h("th", modeBadge(m))),
      h("th", T("diffHead"), h("small", " agent − baseline")))),
    h("tbody", rows.map(([l, cell, diff]) =>
      h("tr", h("td", l[0], l[1] && h("small", l[1])), MODES.map(m => h("td.num", cell(ST[m]))),
        h("td.num", diff()))), extra));
}
/* p50(굵게) + 아래 줄 p95 · n — 시간(secU) 또는 토큰(fmtN) */
const pq = (key, f) => x => [h("b", nw(f(nr(x[key], 50)))), h("br"),
  h("small", nw(P95, f(nr(x[key], 95)), " · ", n(x[key].length)))];
const pqDiff = (key, d) => () => [h("b", nw(d(nr(B[key], 50), nr(A[key], 50)))), h("br"),
  h("small", nw(P95, d(nr(B[key], 95), nr(A[key], 95))))];

function timeCard() {
  const tSec = key => [pq(key, secU), pqDiff(key, dSec)];
  const rows = [
    [lab("rFirst"), ...tSec("first")],
    [lab("rFinal", { n: fmtN(POP.common) }), ...tSec("final")],
    [lab("rTotal"), ...tSec("total")],
    [lab("rBg"), ...tSec("bg")],
    [lab("rTok"), pq("ttok", fmtN), pqDiff("ttok", (b, a) => dNum(b, a))],
  ];
  return h("section.card", { "aria-labelledby": "h-mtime" },
    h("h3", { id: "h-mtime" }, icon("clock"), T("timeTitle"), h("small", T("timeSmall"))),
    hscroll(table(rows), "cmpTime", T("timeLabel")),
    foot(T("footCalc")),
    foot(T("footD1"), lockApplied() ? "" : T("footPre"), T("footEnv")));
}

function qualCard() {
  const rateCell = (k, d) => x => [h("b", nw(rateTxt(x[k], x[d]))), h("br"), h("small", `${x[k]}/${x[d]}`)];
  const rateDiff = (k, d) => () => h("b", nw(dPP(rate(B[k], B[d]), rate(A[k], A[d]))));
  const okN = x => x.ok.length;
  const rows = [
    [lab("rReq"), x => nw(TX("reqCell", { ok: h("b", fmtN(okN(x))), all: fmtN(x.all.length) })), () => "—"],
    [lab("rPass"), rateCell("pass", "graded"), rateDiff("pass", "graded")],
    [lab("rStrict"), rateCell("strict", "strictN"), rateDiff("strict", "strictN")],
    [lab("rSkip"), x => [h("b", nw(rateTxt(x.skip, okN(x)))), h("br"), h("small", `${x.skip}/${okN(x)}`)],
      () => h("b", nw(dPP(rate(B.skip, okN(B)), rate(A.skip, okN(A)))))],
    [lab("rDcl"), x => nw(T("dclCell", { d: fmtN(x.dcl), e: fmtN(x.err) })),
      () => nw(`${dNum(B.dcl, A.dcl)} · ${dNum(B.err, A.err)}`)],
    [lab("rCost"), x => nw(usd(x.cost)), () => nw(dUsd(B.cost, A.cost))],
    [lab("rLost"), x => [TX("lostCell", { n: h("b", fmtN(x.lost.length)), c: x.lost.length }), h("br"),
      h("small", T("rLostEx", { k: fmtN(x.lostEx) }))],
    () => nw(dNum(B.lost.length, A.lost.length, T("casesUnit")))],
    [lab("rNoop"), x => nw(T("steps", { n: fmtN(x.noops) })), () => nw(dKey(B.noops, A.noops, "steps"))],
  ];
  const common = h("tr.common", h("td", T("rCommon"), h("small", T("rCommonSub"))),
    h("td.c.num", { colspan: 3 }, h("b", pct(DIST.c3, DIST.n), "%"), " ",
      h("small.nw", T("unitsFrac", { a: fmtN(DIST.c3), n: fmtN(DIST.n) }))));
  return h("section.card", { "aria-labelledby": "h-mqual" },
    h("h3", { id: "h-mqual" }, icon("chart"), T("qualTitle"), h("small", T("qualSmall"))),
    hscroll(table(rows, common), "cmpQual", T("qualLabel")));
}
