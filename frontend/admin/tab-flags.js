/* 1. 모드 비교 — 맨 위 '현재 모드' 카드(서버 mode API) + 같은 평가 실행 기록에서 baseline과 agent를
   같은 기준으로 비교하는 요약 한 화면. 문구는 "flags.*" · "mode.*". */
import {
  $, D, DIST, MODES, POP, ST, fill, fmtN, foot, h, hscroll, icon, isObj, kRow, kpi, lockApplied, modeBadge, modeIcon,
  nEq, nr, onSeg, pct, phead, popNote, runBar, secU, seg, usd, utc,
} from "./admin.js";
import { t, tx } from "./i18n.js";
const T = (k, p) => t("flags." + k, p), TX = (k, p) => tx("flags." + k, p), P95 = "p95 ";

/* ---------- 숫자 · 차이 ---------- */
const sign = v => (v > 0 ? "+" : v < 0 ? "−" : "±"), rate = (a, b) => (b ? (a / b) * 100 : null);
const dSec = (b, a) =>
  (b == null || a == null ? "—" : sign(a - b) + t("unit.sec", { n: (Math.abs(a - b) / 1000).toFixed(1) }));
const dPP = (b, a) => (b == null || a == null ? "—" : sign(a - b) + T("pp", { v: Math.abs(a - b).toFixed(1) }));
const dNum = (b, a, unit = "") => (b == null || a == null ? "—" : `${sign(a - b)}${fmtN(Math.abs(a - b))}${unit}`);
/* 단위가 문장인 차이(예: "+3단계" · "+3 steps") */
const dKey = (b, a, key) => (b == null || a == null ? "—" : sign(a - b) + T(key, { n: fmtN(Math.abs(a - b)) }));
const dUsd = (b, a) => `${sign(a - b)}${usd(Math.abs(a - b))}`, rateTxt = (a, b) => (b ? `${pct(a, b)}%` : "—");
let B = null, A = null; /* 모드별 묶음(ST는 data.json을 읽은 뒤에 채워져서 그릴 때 잡는다) */
export function render(panel) {
  B = ST.baseline; A = ST.agent;
  fill(panel,
    phead(T("title"), T("lead")),
    modeCard(), /* 서버의 현재 모드(읽기 · 바꾸기) — 아래 비교는 평가 실행 기록 */
    runBar(),
    popNote(),
    h("div.kpis", kpis(B, A)),
    h("div.fgrid", timeCard(), qualCard()));
}

/* ---------- 머리 숫자 4개 ---------- */
function kpis(b, a) {
  const both = f => MODES.map(m => f(m, ST[m])), p50 = k => both((m, x) => nr(x[k], 50));
  const [f0, f1] = p50("first"), [l0, l1] = p50("final"), [t0, t1] = p50("ttok");
  const secRow = key => both((m, x) =>
    kRow(m, secU(nr(x[key], 50)), `${P95}${secU(nr(x[key], 95))} · ${nEq(x[key].length)}`));
  return [
    kpi(T("kpiJudge"), both((m, x) => kRow(m, rateTxt(x.pass, x.graded), `${x.pass}/${x.graded}`)),
      T("kpiJudgeSub", {
        d: dPP(rate(b.pass, b.graded), rate(a.pass, a.graded)), sb: rateTxt(b.strict, b.strictN),
        sa: rateTxt(a.strict, a.strictN),
      })),
    kpi(T("kpiFirst"), secRow("first"), T("kpiFirstSub", { d: dSec(f0, f1) })),
    kpi(T("kpiFinal"), secRow("final"), T("kpiFinalSub", { d: dSec(l0, l1), n: fmtN(POP.common) })),
    kpi(T("kpiTok"), both((m, x) => kRow(m, fmtN(nr(x.ttok, 50)), nEq(x.ttok.length))),
      T("kpiTokSub", { d: dNum(t0, t1), cb: usd(b.cost), ca: usd(a.cost) })),
  ];
}

/* ---------- 비교 표 공용: [이름, 설명] · 모드별 칸 · 차이 칸 ---------- */
const nw = (...k) => h("span.nw", ...k), lab = (key, p) => [T(key), T(key + "Sub", p)];
function table(rows, extra) {
  return h("table.cmpt",
    h("thead", h("tr", h("th", T("metric")), MODES.map(m => h("th", modeBadge(m))),
      h("th", T("diffHead"), h("small", " agent − baseline")))),
    h("tbody", rows.map(([l, cell, diff]) =>
      h("tr", h("td", l[0], l[1] && h("small", l[1])), MODES.map(m => h("td.num", cell(ST[m]))),
        h("td.num", diff()))), extra));
}
/* 굵은 줄 + 아래 작은 줄(p50 / p95 · n, 비율 / 분수) */
const two = (big, small) => [h("b", nw(big)), h("br"), h("small", small)];
const pq = (key, f) => x => two(f(nr(x[key], 50)), nw(P95, f(nr(x[key], 95)), " · ", nEq(x[key].length)));
const pqDiff = (key, d) => () => two(d(nr(B[key], 50), nr(A[key], 50)), nw(P95, d(nr(B[key], 95), nr(A[key], 95))));
const card = (id, ic, title, small, ...body) =>
  h("section.card", { "aria-labelledby": id }, h("h3", { id }, icon(ic), title, h("small", small)), ...body);
function timeCard() {
  const tSec = key => [pq(key, secU), pqDiff(key, dSec)];
  const rows = [
    [lab("rFirst"), ...tSec("first")],
    [lab("rFinal", { n: fmtN(POP.common) }), ...tSec("final")],
    [lab("rTotal"), ...tSec("total")],
    [lab("rBg"), ...tSec("bg")],
    [lab("rTok"), pq("ttok", fmtN), pqDiff("ttok", (b, a) => dNum(b, a))],
  ];
  return card("h-mtime", "clock", T("timeTitle"), T("timeSmall"),
    hscroll(table(rows), "cmpTime", T("timeLabel")),
    foot(T("footCalc")),
    foot(T("footD1"), lockApplied() ? "" : T("footPre"), T("footEnv")));
}
function qualCard() {
  const okN = x => x.ok.length, rateCell = (k, d) => x => two(rateTxt(x[k], d(x)), `${x[k]}/${d(x)}`);
  const rateDiff = (k, d) => () => h("b", nw(dPP(rate(B[k], d(B)), rate(A[k], d(A))))), of = k => x => x[k];
  const rows = [
    [lab("rReq"), x => nw(TX("reqCell", { ok: h("b", fmtN(okN(x))), all: fmtN(x.all.length) })), () => "—"],
    [lab("rPass"), rateCell("pass", of("graded")), rateDiff("pass", of("graded"))],
    [lab("rStrict"), rateCell("strict", of("strictN")), rateDiff("strict", of("strictN"))],
    [lab("rSkip"), rateCell("skip", okN), rateDiff("skip", okN)],
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
  return card("h-mqual", "chart", T("qualTitle"), T("qualSmall"),
    hscroll(table(rows, common), "cmpQual", T("qualLabel")));
}

/* ---------- 맨 위 '현재 모드' 카드: 서버의 mode API(상대 경로 "mode")를 읽고 바꾼다 ----------
   GET mode → { mode, source: "db" | "env", updated_at, writable, token_required, history: [{ at, from, to }] } ·
   POST mode { mode } (+ X-Admin-Token: token_required일 때만) → 200 | 400 | 401 | 409. 바꾸기 전에 확인 대화상자.
   writable=false면 읽기 전용, API가 없으면 data.json의 mode.current만. 토큰은 sessionStorage에만 둔다. */
const M = (k, p) => t("mode." + k, p), TOKEN_KEY = "phrase-room-admin.token";
/* MS: 마지막 GET/POST 결과 { data } | { err } · busy: 바꾸는 중 · msg: [종류, 키, 자리표시 값] 결과 안내(언어가 바뀌면 다시 번역) */
let MS = null, busy = false, msg = null, loading = null;
const readToken = () => { try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
const saveToken = v => { /* 저장할 수 없는 환경이면 이번 입력만 쓴다 */
  try { if (v) sessionStorage.setItem(TOKEN_KEY, v); else sessionStorage.removeItem(TOKEN_KEY); } catch { /* 무시 */ }
};
/* 응답 모양 확인: 화면이 쓰는 필드만 본다 */
function shape(j) {
  if (!isObj(j) || typeof j.mode !== "string") return null;
  const hist = Array.isArray(j.history) ? j.history.filter(x => isObj(x) && typeof x.to === "string") : [];
  return {
    mode: j.mode, source: j.source === "db" ? "db" : "env",
    updated_at: typeof j.updated_at === "string" ? j.updated_at : null, writable: j.writable === true,
    token_required: j.token_required === true, history: hist,
  };
}
function load(force = false) {
  if (loading && !force) return loading;
  loading = fetch("mode", { cache: "no-store" })
    .then(async res => {
      if (!res.ok) throw new Error("HTTP " + res.status);
      const d = shape(await res.json());
      if (!d) throw new Error("shape");
      MS = { data: d };
    })
    .catch(e => { MS = { err: e }; })
    .finally(() => { loading = null; paint(); });
  return loading;
}
/* 카드 하나를 돌려준다(탭이 다시 그려질 때마다 새로 만들고, 마지막 결과로 채운다) */
function modeCard() {
  const host = h("section.card.modecard", { id: "modeCard", "aria-labelledby": "h-mode" });
  paint(host);
  if (!MS && !loading) load();
  return host;
}
const big = cur => h("span.big." + (MODES.includes(cur) ? cur : "unset"), icon(modeIcon(cur)), cur);
const roTag = () => h("span.ro-tag", icon("lock"), M("readonly"));
function paint(host = $("#modeCard")) {
  if (!host) return;
  const head = h("h3", { id: "h-mode" }, icon("server"), M("title"), h("small", M("sub")),
    MS && !busy && h("button.btn.sm.mc-refresh", {
      type: "button", on: { click: () => (msg = null, load(true)) },
    }, icon("loop"), M("refresh")));
  if (!MS) return fill(host, head, h("p.loading", icon("loop"), M("loading")));
  if (MS.err) {
    const cur = D && D.mode ? D.mode.current : null;
    return fill(host, head, h("div.cur", cur && big(cur), roTag()),
      h("p.warnline", icon("alert"), h("span", M("unavailable"))),
      cur && h("p.foot", M("fallback", { mode: cur })));
  }
  const d = MS.data, cur = d.mode;
  const srcChip = h("span.mc-src", h("span.muted", M("srcLabel") + " "), h("b", M("src." + d.source)));
  const when = h("span.mc-when.num", d.updated_at ? M("changedAt", { t: utc(d.updated_at) }) : M("never"));
  const sw = seg("mc-sw", M("switchLabel"), MODES.map(m => [m, m, { disabled: !d.writable || busy ? "" : null }]),
    m => m === cur);
  onSeg(sw, m => {
    if (m !== cur && d.writable && !busy) ask(m);
  });
  const rows = d.history.slice(0, 5);
  fill(host, head,
    h("div.cur", big(cur), srcChip, when, !d.writable && roTag()),
    h("div.mc-row",
      h("div.field", h("span", M("switchLabel")), sw),
      h("p.d1-now.t", icon("info"), h("span", M("next")))),
    !d.writable && h("p.foot", M("readonlyBody")),
    d.writable && d.token_required && h("p.foot", icon("lock"), " ", M("tokenNote")),
    h("p.mc-msg", { role: "status", "aria-live": "polite" },
      busy ? [icon("loop"), M("saving")] : msg && h("span." + msg[0], M(msg[1], msg[2]))),
    h("div.mc-hist", h("h4.card-h.sm", icon("clock"), M("histTitle")), rows.length
      ? h("ol", rows.map(x =>
        h("li.num", h("span.muted", utc(x.at)), " ", modeBadge(x.from || "—"), " → ", modeBadge(x.to))))
      : h("p.muted.small", M("histNone"))));
}
/* 확인 대화상자(<dialog>): 모드 from → to, 다음 요청부터 적용 안내, token_required면 토큰 입력 */
function ask(to) {
  const d = MS.data, from = d.mode, back = document.activeElement;
  const tok = d.token_required && h("input", {
    type: "password", id: "mc-token", autocomplete: "off", placeholder: M("tokenPh"), value: readToken(),
  });
  const dlg = h("dialog.mc-dlg", { "aria-labelledby": "mc-dlg-h" },
    h("h3", { id: "mc-dlg-h" }, icon("alert"), M("dlgTitle")),
    h("p.mc-change", modeBadge(from), " → ", modeBadge(to)),
    h("p", M("dlgBody")),
    tok && h("label.field", h("span", M("tokenLabel")), tok),
    tok && h("p.foot", M("tokenNote")),
    h("div.mc-actions",
      h("button.btn", { type: "button", value: "cancel" }, M("cancel")),
      h("button.btn.primary", { type: "button", value: "ok" }, icon("check"), M("confirm", { to }))));
  const close = () => {
    dlg.close(); dlg.remove();
    if (back && back.isConnected) back.focus();
  };
  dlg.addEventListener("click", e => {
    const b = e.target.closest("button[value]");
    if (!b) return;
    if (b.value === "cancel") return close();
    const token = tok ? tok.value.trim() : "";
    if (tok) saveToken(token);
    close(); change(to, token);
  });
  dlg.addEventListener("cancel", e => { e.preventDefault(); close(); });
  document.body.append(dlg); dlg.showModal(); (tok && !tok.value ? tok : $("button[value=cancel]", dlg)).focus();
}
const ERR = { 400: "err.invalid", 401: "err.token", 409: "err.nodb" };
async function change(to, token) {
  busy = true; msg = null; paint();
  try {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Admin-Token"] = token;
    const body = JSON.stringify({ mode: to });
    const res = await fetch("mode", { method: "POST", headers, body, cache: "no-store" }).catch(() => null);
    if (!res) { msg = ["err", "err.network"]; return; }
    if (!res.ok) {
      if (res.status === 401) saveToken("");
      msg = ["err", ERR[res.status] || "err.http", { status: res.status }];
      return;
    }
    const d = shape(await res.json().catch(() => null));
    if (!d) { msg = ["err", "err.shape"]; return; }
    MS = { data: d }; msg = ["ok", "done", { to: d.mode }];
  } finally {
    busy = false; paint(); $("#mc-sw button[aria-pressed=true]")?.focus();
  }
}