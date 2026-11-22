/* 여러 탭이 같이 쓰는 화면 조각: 배지 · 칩 · 카드 · 실행 띠 · 후속/예문 표시 · 단계 이름표 · 시간 막대 · 세그먼트 버튼 */
import { $$, h, icon, secU, sum } from "./ui.js";
import { D, MODES, POP, SIZE, contKey, isWait0, lockApplied, lockWord, msgOf, noEx } from "./data.js";
import { fmtNum, t, tx } from "./i18n.js";
import "./i18n-tabs.js";

/* 화면 문자열: i18n-tabs.js의 "parts.*" 키(지금 언어로 그릴 때마다 읽는다) */
const P = (k, p) => t("parts." + k, p);
const PX = (k, p) => tx("parts." + k, p);
/* [이름, …] 배열인데 이름(0번)만 지금 언어로 읽히는 것(STATUS · KIND · CONT). 구조 분해 · [0] 모두 그대로 쓴다. */
const named = (key, ...rest) => Object.defineProperty([null, ...rest], 0, { get: () => t(key), enumerable: true });

/* ---------- 배지 · 칩 · 카드 ---------- */
export const STATUS = {
  ok: named("parts.status.ok", "check"), declined: named("parts.status.declined", "ban"),
  error: named("parts.status.error", "alert"),
};
export const modeCls = m => (MODES.includes(m) ? m : "unset");
export const modeIcon = m => (m === "agent" ? "bubble" : m === "baseline" ? "gear" : "info");
export const modeBadge = m => h(`span.mb.${modeCls(m)}`, icon(modeIcon(m)), m);
export const statusBadge = s => h(`span.sb.${s}`, icon(STATUS[s][1]), STATUS[s][0]);
export const chip = (cls, ic, ...t) => h("span.chip" + (cls ? "." + cls : ""), ic && icon(ic), ...t);
export const preChip = (...t) => h("span.prechip", icon("clock"), ...t);
export const mono = t => h("span.mono", t);
export const enT = (t, cls = "en") => h(`span.${cls}`, { lang: "en" }, t);
export const foot = (...k) => h("p.foot", ...k);
export const pill = (...k) => h("span.pill", ...k);
export const kv = items =>
  h("dl.kv.num", items.filter(Boolean).map(([dt, ...dd]) => h("div", h("dt", dt), h("dd", ...dd))));
export const card = (id, ic, title, small, ...body) =>
  h("section.card", { "aria-labelledby": id }, h("h3", { id }, icon(ic), title, small && h("small", small)), ...body);
export const h4 = (ic, t, small) => h("h4.card-h.sm", icon(ic), t, small && h("small", small));
export const lockOne = x => h("span.lockc", icon("lock"), P("slotN", { x }));
export const lockChip = slots =>
  h("span.lockc", icon("lock"), P("lockedSlots", { n: slots.length, list: slots.map(x => "#" + x).join("·") }));

/* 잠금 판정 이름표: [이름, 아이콘] */
export function lockLabel() {
  const a = D.meta.lock.applied;
  if (a === true) return [P("lockApplied"), "lock"];
  return a === false ? [P("lockPre"), "clock"] : [P("lockNone"), "info"];
}
export function lockBadge() {
  const [label, ic] = lockLabel();
  return h(lockApplied() ? "span.lockc" : "span.prechip", { title: D.meta.lock.note || "" }, icon(ic), label);
}

/* 탭 머리말 + 데이터 출처 칩(자세한 출처 문장은 data.json meta.source를 title로) */
export const phead = (title, p, ...extra) =>
  h("div.phead", h("h2", title), h("p", p),
    h("span.src-chip", { title: D.meta.source || "" }, icon("info"), P("source")), ...extra);

/* 평가 실행 띠: data.json에 담긴 평가 실행 기록 하나 */
export const runBar = () =>
  h("div.runbar", h("span.rl", P("runLabel")),
    h("span.runpill", icon("check"), h("b", D.meta.run.id || "—"), D.meta.run.date || "", h("span.sub", SIZE)),
    lockBadge(),
    h("p.runnote", icon("info"), h("span", P("runNote"))));

/* 최종 시간 모집단 안내: 두 모드의 후속 실행 단위가 다르면(잠금 전 기록 등) 같은 단위로만 비교한다는 경고 */
export function popNote() {
  if (POP.same) return null;
  return h("p.warnline.pop", icon("alert"), h("span",
    h("b", P(lockApplied() ? "popHead" : "popHeadPre")),
    P("popBody", { b: fmtNum(POP.baseline), a: fmtNum(POP.agent), c: fmtNum(POP.common) })));
}

/* 가로 스크롤 상자(표): 오른쪽에 더 있으면 흐림 단서와 안내 문구(shell.hscrollCue가 갱신) */
export const hsHint = (id, tag = "p") => h(`${tag}.hs-hint`, { id, hidden: true }, icon("arrow"), P("hsHint"));
export const hscroll = (el, key, label) => [
  h("div.hs-host", h("div.pct-wrap", {
    id: key, role: "region", "aria-label": label, tabindex: 0, "data-hscroll": "", "data-hint": key + "-hint",
  }, el)),
  hsHint(key + "-hint"),
];

/* 오류 안내: 패널 전체(errorBox) · 한 줄(warnErr). retry가 있으면 '다시 불러오기' 버튼 */
const retryBtn = (retry, cls = "") =>
  retry && h("button.btn" + cls, { type: "button", on: { click: retry } }, icon("loop"), t("common.retry"));
export const errorBox = (e, retry) =>
  h("div.state.fail", { role: "alert" }, h("h2", icon("alert"), t("common.renderFailed")), h("p", msgOf(e)),
    retryBtn(retry));
export const warnErr = (e, retry, lead = "") =>
  h("div.warnline.err", icon("alert"), h("span", lead, msgOf(e)), retryBtn(retry, ".sm"));

/* ---------- 세그먼트 버튼(필터 · 추이 · 예시 고르기 공용): opts = [[값, 이름, 추가 속성]] ---------- */
export const segBtns = (opts, on) =>
  opts.map(([v, label, attrs]) =>
    h("button", { type: "button", "data-v": v, "aria-pressed": String(on(v)), ...attrs }, icon("check", "ck"), label));
export const seg = (id, label, opts, on) => h("div.seg", { id, role: "group", "aria-label": label }, segBtns(opts, on));
export const syncSeg = (el, on) =>
  $$("button", el).forEach(b => b.setAttribute("aria-pressed", String(on(b.dataset.v))));
export const onSeg = (el, fn) =>
  el.addEventListener("click", e => {
    const b = e.target.closest("button");
    if (b && !b.disabled) fn(b.dataset.v, b);
  });

/* ---------- 후속 단계 칩 · 예문 수 ---------- */
const CONT = {
  skipped: named("parts.cont.skipped", "skp", "skip"), ran: named("parts.cont.ran", "ran", "loop"),
  stop: named("parts.cont.stop", "stop", "alert"), none: named("parts.cont.none", "none", "ban"),
};
/* 후속 단계 설명(title): CONT_TIP[키]는 읽을 때마다 지금 언어 */
export const CONT_TIP = Object.defineProperties({}, Object.fromEntries(["all", "skipped", "ran", "stop", "none"]
  .map(k => [k, { get: () => P("contTip." + k), enumerable: true }])));
export function contChip(r) {
  const k = contKey(r), [label, cls, ic] = CONT[k] || CONT.none;
  let tip = CONT_TIP[k] || "", extra = null;
  if (k === "ran" && isWait0(r)) {
    extra = P("wait");
    tip = P("waitTip");
  } else if (k === "ran") {
    extra = [" · ", h("b", "+" + r.added_final)];
    tip = P("addTip", { k: r.added_final });
    if (r.verified_first === 3) tip += P("v3Tip", { w: lockWord(r) });
  } else if (k === "none") {
    tip = P(r.status === "declined" ? "declTip" : "errTip");
  }
  return h(`span.cchip.${cls}`, { title: tip }, icon(ic), label, extra);
}
export function exText(r) {
  if (noEx(r)) return ["—"];
  if (isWait0(r)) return PX("exWait", { n: h("b", r.verified_final ?? "—") });
  const lost = r.lost_first > 0 && [" · ", h("span.lost", PX("exLost", { n: h("b", r.lost_first) }))];
  return [PX("exFirst", { f: h("b", r.verified_first ?? "—"), a: h("b", r.added_final) }), lost];
}
export function exPlain(r) {
  if (noEx(r)) return P("none");
  if (isWait0(r)) return P("exWait", { n: r.verified_final ?? "—" });
  return P("exFirst", { f: r.verified_first, a: r.added_final }) +
    (r.lost_first > 0 ? ` · ${P("exLost", { n: r.lost_first })}` : "");
}
export function dots(r) {
  if (noEx(r)) return null;
  const kept = isWait0(r) ? r.verified_final || 0 : Math.max(0, (r.verified_first || 0) - r.lost_first);
  const added = isWait0(r) ? 0 : r.added_final;
  const dot = i => h("i" + (i < kept ? ".on" : i < kept + added ? ".add" : ""));
  return h("span.dots3", { "aria-hidden": "true" }, [0, 1, 2].map(dot));
}
export const judgeText = r =>
  r.passed == null ? "—" : [P(r.passed ? "pass" : "fail"), r.strict_passed ? " · strict" : ""];
/* 최종 답 슬롯의 상태 칩 */
export function slotTag(r, f) {
  if (f.added) return chip("new", "plus", P("tagAdded"));
  if (!f.verified) return chip("", "x", P("tagNoEx"));
  if (r.verified_first === 0) return chip("ok", "check", P("tagOnce"));
  if (f.from_first) return lockApplied(r) ? chip("ok", "lock", P("tagLocked")) : chip("ok", "check", P("tagKept"));
  return chip("ok", "check", P("tagVerified"));
}
export const lostTag = () => chip("warn", "alert", P("tagLost"));
/* 문자열 안의 핵심 구절을 <mark>로(텍스트 노드로만) */
export function hl(text, kp) {
  const t = String(text ?? ""), k = kp ? String(kp) : "";
  const i = k ? t.toLowerCase().indexOf(k.toLowerCase()) : -1;
  return i < 0 ? [t] : [t.slice(0, i), h("mark", t.slice(i, i + k.length)), t.slice(i + k.length)];
}

/* ---------- 단계 종류와 이름표 ---------- */
/* 화면 종류: [이름, 아이콘] */
const KIND_ICON = {
  request: "user", llm: "spark", judge: "bubble", search: "search", act: "tool", verify: "shield", assemble: "box",
  decline: "ban", budget: "alert", noop: "clock", error: "alert", lock: "lock", skip: "skip",
};
export const KIND = Object.fromEntries(Object.entries(KIND_ICON).map(([k, ic]) => [k, named("parts.kind." + k, ic)]));
/* 스팬 → 화면 종류: 잠금 → 후속 생략 → decision(토큰 있으면 판단, 없으면 도구 적용) → 계약 kind */
export function dk(s) {
  if (s.locked === true) return "lock";
  if (s.stage === "continuation_skipped") return "skip";
  if (s.kind === "decision") return s.tokens ? "judge" : "act";
  return KIND[s.kind] && s.kind !== "request" ? s.kind : "noop";
}
export const kk = s => (s.status === "error" ? "error" : dk(s));

/* 단계 이름표 하나: 노선도 행(label)과 카드 제목(title)을 같이 정한다. grp = common · baseline · agent · end.
   re가 없는 행은 기록 단계가 아니라 노선도에만 있는 자리다. 배열 순서 = 노선도 순서 = 매칭 우선순위. */
const st = (key, grp, kind, re, title) => ({
  key, grp, kind, re, title,
  get label() {
    return P("stage." + key);
  },
});
const ROUND = m => m[1] - 1;
const TT = (k, p) => P("title." + k, p);
export const STAGES = [
  st("req", "common", "request"),
  st("cand", "common", "llm", /^candidates(_retry)?$/, m => (m[1] ? TT("candRetry") : P("stage.cand"))),
  st("dcl", "common", "decline", /^decline$/),
  st("s1", "common", "search", /^search_(\d+)$/, m => TT("candidate", { r: ROUND(m) })),
  st("sel1", "common", "llm", /^select_1$/),
  st("v1", "common", "verify", /^validate_select_1$/, () => TT("v1")),
  st("mk", "common", "mk"),
  st("rev", "baseline", "llm", /^revise_(\d+)$/, m => TT("revise", { r: m[1] })),
  st("bs", "baseline", "search", /^search_(\d+)_\d+$/, m => TT("round", { what: P("stage.bs"), r: m[1] })),
  st("bsel", "baseline", "llm", /^select_(\d+)$/, m => TT("round", { what: P("stage.bsel"), r: ROUND(m) })),
  st("bv", "baseline", "verify", /^validate_select_(\d+)$/, m => TT("round", { what: P("stage.bv"), r: ROUND(m) })),
  st("dec", "agent", "judge", /^(?:agent_(\d+)|pick_final)$/, m => (m[1] ? TT("turn", { t: m[1] }) : TT("pickFinal"))),
  st("as", "agent", "search", /^search_(\d+)_\d+$/, m => TT("searchTurn", { t: m[1] })),
  st("act", "agent", "act", /^(repick|replace)_(?:\d+|final)_\d+$/, m => TT(m[1] === "repick" ? "repick" : "replace")),
  st("lock", "agent", "lock"),
  st("av", "agent", "verify", /^validate_(?:agent_(\d+)|pick_final)$/,
    m => (m[1] ? TT("verifyTurn", { t: m[1] }) : TT("verifyFinal"))),
  st("skip", "end", "skip"),
  st("asm", "end", "assemble", /^(assemble|budget_exhausted)$/, m => (m[1] === "assemble" ? P("stage.asm") : TT("budget"))),
  st("resp", "end", "assemble"),
];
const inMode = (x, mode) => x.grp === "common" || x.grp === "end" || x.grp === mode;
const stageDef = (stage, mode) => STAGES.find(x => x.re && inMode(x, mode) && x.re.test(stage)) || null;
/* 도구 행동 이름: detail.action, 없으면 stage 앞부분(잠긴 슬롯 대상 search noop 등) */
export const actionOf = s => (s.detail || {}).action || s.stage.split("_")[0];
export function stageTitle(s, mode) {
  if (s.locked === true) return TT("lockSkip", { a: actionOf(s), s: (s.detail || {}).slot ?? "—" });
  if (s.stage === "continuation_skipped") return TT("contSkip");
  const def = stageDef(s.stage, mode);
  if (!def) return s.label || s.stage;
  return def.title ? def.title(def.re.exec(s.stage)) : def.label;
}
export function routeKeyOf(s, mode) {
  if (s.locked === true) return mode === "agent" ? "lock" : null;
  if (s.stage === "continuation_skipped") return "skip";
  const def = stageDef(s.stage, mode);
  return def ? def.key : null;
}

/* ---------- 단계 시간 막대 ---------- */
/* 첫 결과 시점의 종류: 거절 · 첫 단계 오류 · 후속 생략 · 검증 0개(대기) · 3개 검증 · 1~2개(즉시) */
export function markKind(r) {
  if (r.status === "declined") return "decl";
  if (r.status === "error" && r.error_phase !== "continuation") return "err";
  if (r.continuation === "skipped") return "skip";
  return r.verified_first === 0 ? "mid" : r.verified_first === 3 ? "v3" : "imm";
}
/* 스팬 elapsed 비율 + 첫 결과 시점. big = 실행 그래프 요약(조각을 누르면 그 단계로) · sel = 고른 스팬 id */
export function timeBar(r, spans, { big = false, sel = null } = {}) {
  const real = sum(spans.map(s => s.elapsed_ms)) || 1;
  const firstEnd = sum(spans.filter(s => s.phase === "first").map(s => s.elapsed_ms));
  const mk = markKind(r), showMk = ["imm", "v3", "mid"].includes(mk) && firstEnd < real;
  const piece = s => {
    const k = kk(s);
    return h(`span.tb-seg.k-${k}` + (big && sel === s.id ? ".sel" : ""), {
      "data-span": big ? s.id : null,
      title: `${stageTitle(s, r.mode)} · ${KIND[k][0]} · ${secU(s.elapsed_ms)}`,
      css: { flex: `${s.elapsed_ms} 1 0` },
    });
  };
  const mark = showMk && h("span.tb-mark" + (mk === "mid" ? ".mid" : ""),
    { "aria-hidden": "true", css: { left: ((firstEnd / real) * 100).toFixed(2) + "%" } });
  const track = h("div.tb-track", {
    role: "img", "aria-label": P("barLabel", { t: secU(r.total_ms), f: secU(r.first_response_ms) }),
  }, spans.filter(s => s.elapsed_ms > 0).map(piece), mark);
  const tm = secU(r.first_response_ms);
  const v3 = P(lockApplied(r) ? "v3Violation" : "v3Pre");
  const ax = {
    imm: h("span.mk", icon("bolt"), P("mkImm", { k: r.verified_first, t: tm })),
    v3: [h("span.mk", icon("bolt"), P("mkV3", { t: tm })), h("span.gh", icon("loop"), v3)],
    mid: h("span.mk.mid", icon("hour"), P("mkMid", { t: secU(firstEnd) })),
    skip: [h("span.mk", icon("bolt"), P("mkSkip", { t: tm, k: r.verified_first })),
      h("span.gh", icon("skip"), P("kind.skip"))],
    decl: chip("warn", "ban", P("mkDecl")),
    err: chip("err", "alert", P("mkErr")),
  }[mk];
  return h("div.tbar" + (big ? ".big" : ""), track,
    h("div.tb-ax.num", h("span", t("unit.sec", { n: 0 })), ax, h("span", P("axTotal", { t: secU(r.total_ms) }))));
}
