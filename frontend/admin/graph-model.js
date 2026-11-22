/* 실행 그래프 모델: 스팬 → 노선도 자리(고정 템플릿) · 엣지 · 스윔레인 레인, 그리고 노드 · 상세가 같이 쓰는 해석 도우미.
   노선도 자리는 시안 A(클린 프로) 방식: 모든 요청을 같은 자리의 같은 노드로 놓고 지나간 길만 진하게 그린다.
   화면 문구는 i18n-graph.js의 "graph.model.*"(gtext("model") = 읽는 순간의 언어). */
import { h, icon } from "./ui.js";
import { firstVerified, lockApplied } from "./data.js";
import { chip, enT, lockChip, markKind, mono, preChip } from "./parts.js";
import { gtext } from "./i18n-graph.js";

export const MODEL_TEXT = gtext("model");
const T = MODEL_TEXT;
export const noQuestion = () => T.noQuestion;
export const REJ = T.rej; /* 언어 보기(읽을 때마다 지금 언어) */
export const SMODE = T.smode;
export const FINAL_TURN = 4; /* pick_final 계열의 turn 값(계약 §8) */

/* ---------- 스팬 → 단계(step): 노선도 자리 · 스윔레인 레인이 이 값으로 스팬을 고른다 ---------- */
const STEPS = [
  [/^candidates/, "cand"], [/^decline$/, "decl"], [/^search_/, "search"], [/^select_/, "select"],
  [/^revise_/, "revise"], [/^(agent_\d+|pick_final)$/, "judge"], [/^(repick|replace)_/, "tool"],
  [/^validate_/, "verify"], [/^(assemble|budget_exhausted|continuation_skipped)$/, "asm"],
];
export const stepOf = s => (STEPS.find(([re]) => re.test(s.stage)) || [null, "other"])[1];

/* 잠긴 슬롯 = 첫 단계에서 검증돼 이미 보낸 슬롯. baseline은 원래 검증 슬롯을 건드리지 않고(코드 규칙),
   agent는 잠금 적용 기록(meta.lock.applied = true)에서만 고정한다. 검증 1~2개 · 후속 실행일 때만 의미가 있다. */
export function lockedSlots(r, sp) {
  const on = (lockApplied(r) || r.mode === "baseline") && markKind(r) === "imm" && r.continuation === "ran";
  return new Set(on ? firstVerified(sp) : []);
}

/* 요청 한 건을 템플릿 자리에 놓는다. 첫 단계는 step으로, 후속은 step + turn(baseline 라운드 · agent 턴, 최종 선택은 4)으로.
   어느 자리에도 맞지 않는 스팬(조립 · 예산 소진 · 후속 생략 표시 등)은 조립 노드에 모은다. */
export function runModel(r, sp) {
  const isB = r.mode === "baseline", isA = r.mode === "agent", placed = new Set();
  const take = (phase, steps, turn) => {
    const out = sp.filter(s => s.phase === phase && steps.includes(stepOf(s)) && (turn === undefined || s.turn === turn));
    out.forEach(s => placed.add(s));
    return out;
  };
  const first = steps => take("first", steps);
  const cont = (on, steps, k) => (on ? take("continuation", steps, k) : []);
  const round = k => ({ k, revise: cont(isB, ["revise"], k), search: cont(isB, ["search"], k),
    select: cont(isB, ["select"], k), validate: cont(isB, ["verify"], k) });
  const turn = k => ({ k, judge: cont(isA, ["judge"], k), tools: cont(isA, ["search", "tool"], k),
    validate: cont(isA, ["verify"], k) });
  const m = {
    r, sp, err: sp.find(s => s.status === "error") || null, skipped: r.continuation === "skipped",
    cand: first(["cand"]), decl: first(["decl"]), srch: first(["search"]), sel1: first(["select"]),
    val1: first(["verify"]), B: [1, 2, 3].map(round), A: [1, 2, 3].map(turn), AF: turn(FINAL_TURN),
  };
  m.asm = sp.filter(s => !placed.has(s) && (s.phase !== "first" || stepOf(s) === "asm"));
  m.lockSet = lockedSlots(r, sp);
  /* 후속 단계가 실제로 일했는지: 조립 · noop 말고 다른 후속 스팬이 있으면 */
  m.hasCont = r.status !== "declined" &&
    sp.some(s => s.phase === "continuation" && stepOf(s) !== "asm" && s.kind !== "noop" && s.locked !== true);
  return m;
}

export function endReason(R) {
  const r = R.r, E = T.end;
  if (r.status === "declined") return E.declined;
  if (R.err) return E.error((R.err.detail || {}).error_code || T.noCode, R.err.stage);
  if (R.skipped) return E.skipped(r.verified_first);
  if (r.mode === "baseline") {
    const rounds = R.B.filter(x => x.revise.length);
    if (!rounds.length) return E.noLoop;
    const lastV = rounds[rounds.length - 1].validate[0];
    if (lastV && (lastV.detail || {}).verified === 3) return E.allV(rounds.length);
    return rounds.length === 3 ? E.roundsOut : E.noRep;
  }
  const turns = R.A.filter(x => x.judge.length);
  if (R.AF.judge.length) return E.turnsFinal;
  const lj = turns.length ? turns[turns.length - 1].judge[0] : null;
  if (lj && (lj.detail || {}).finish) return E.finish(turns.length);
  return turns.length === 3 ? E.turnsOut : E.done;
}
/* 실행 안 된 회차 줄의 이유 */
export function rowWhy(R, isBL, row) {
  const W = T.rowWhy;
  if (R.r.status === "declined") return W.declined;
  if (R.err) return W.error;
  if (R.skipped) return W.skipped(R.r.verified_first);
  if (isBL) {
    const prev = row.k === 1 ? R.val1[0] : R.B[row.k - 2] && R.B[row.k - 2].validate[0];
    return prev && (prev.detail || {}).verified === 3 ? W.prev3 : W.noRep;
  }
  const fin = R.A.find(x => x.judge.some(s => (s.detail || {}).finish));
  return fin ? W.finish(fin.k) : row.final ? W.noSearch : W.earlier;
}

/* ---------- 엣지(논리): flow · enter · next · loop · skiparc · exit · decl · bypass. taken = 이번 요청이 지난 길 ---------- */
export function buildEdges(R, M) {
  const { nodes, rowsB, rowsA, actB, actA } = M, edges = [];
  const E = (a, b, type, taken) => edges.push({ a, b, type, taken: !!taken });
  const ran = k => nodes[k] && nodes[k].state !== "skip";
  E("req", "cand", "flow", true);
  E("cand", "srch", "flow", ran("srch"));
  E("cand", "decl", "flow", ran("decl"));
  E("srch", "sel1", "flow", ran("sel1"));
  E("sel1", "val1", "flow", ran("val1"));
  E("decl", "asm", "decl", ran("decl"));
  const laneEdges = (rows, lane, active) => {
    const real = rows.filter(x => x.nodes);
    if (!real.length) return;
    E("val1", real[0].nodes[0].key, "enter", active && ran(real[0].nodes[0].key));
    real.forEach((row, ri) => {
      const ns = row.nodes.map(n => n.key), taken = new Set();
      const runIdx = ns.map((k, i) => (ran(k) ? i : -1)).filter(i => i >= 0);
      if (active) {
        for (let j = 0; j < runIdx.length - 1; j++) {
          const a = runIdx[j], b = runIdx[j + 1];
          if (b === a + 1) taken.add(a);
          else E(ns[a], ns[b], "skiparc", true);
        }
      }
      for (let i = 0; i < ns.length - 1; i++) E(ns[i], ns[i + 1], "flow", taken.has(i));
      const next = real[ri + 1];
      if (next) {
        const from = runIdx.length ? ns[runIdx[runIdx.length - 1]] : ns[ns.length - 1];
        E(from, next.nodes[0].key, "next", active && ran(next.nodes[0].key));
      }
    });
    const head = lane === "B" ? nodes["b.rev"] : nodes["a.judge"];
    if (real.length === 1 && head && head.stack) {
      const ns = real[0].nodes;
      E(ns[lane === "B" ? 3 : 2].key, ns[0].key, "loop", active);
    }
    const lastRan = real.flatMap(x => x.nodes).filter(n => n.state !== "skip").pop();
    const lastNodes = real[real.length - 1].nodes;
    E(lastRan ? lastRan.key : lastNodes[lastNodes.length - 1].key, "asm", "exit", active && !!lastRan && !R.err);
  };
  laneEdges(rowsB, "B", actB);
  laneEdges(rowsA, "A", actA);
  E("val1", "asm", "bypass", R.skipped);
  return edges;
}

/* ---------- 스윔레인 레인(시안 C 방식): 구성요소마다 한 줄 ---------- */
export function lanesFor(mode) {
  const A = mode === "agent", L = T.lane;
  return [
    { id: "cand", kind: "llm", ic: "spark", t: L.cand, s: "candidates" },
    { id: "search", kind: "search", ic: "search", t: L.search, s: "search_*" },
    { id: "select", kind: "llm", ic: "spark", t: L.select, s: A ? "select_1 · pick_final" : "select_*" },
    { id: "judge", kind: A ? "judge" : "llm", ic: A ? "bubble" : "spark", t: A ? L.judgeA : L.judgeB,
      s: A ? "agent_r · repick · replace" : "revise_r" },
    { id: "verify", kind: "verify", ic: "shield", t: L.verify, s: "validate_*" },
    { id: "asm", kind: "assemble", ic: "box", t: L.asm, s: "assemble" },
  ];
}
export function laneOf(s) {
  const st = stepOf(s);
  if (st === "cand" || st === "decl") return "cand";
  if (s.locked === true) return "judge"; /* 잠금으로 건너뛴 행동(잠긴 슬롯 대상 search 포함)은 판단 적용 줄에 */
  if (st === "search") return "search";
  if (st === "select" || s.stage === "pick_final") return "select";
  if (["judge", "revise", "tool"].includes(st) || s.stage === "continuation_skipped" || s.kind === "budget") return "judge";
  return st === "verify" || s.kind === "verify" ? "verify" : "asm";
}

/* ---------- 결과 · 오류 이름표 ---------- */
function outcomeLabel(o) {
  if (T.outcome[o]) return T.outcome[o];
  return String(o || "").startsWith("rejected") ? T.rejected(REJ[String(o).split(":")[1]] || o) : o || "—";
}
export function outcomeChip(o) {
  if (o === "verified") return chip("ok", "check", outcomeLabel(o));
  return chip(String(o).startsWith("rejected") ? "err" : "warn", "alert", outcomeLabel(o));
}
export const searchNote = d => `${SMODE[d.search_mode] || d.search_mode || ""} · ${T.corpus(d.corpus_count ?? "—")}`;
export const errText = d => [mono(d.error_code || T.noCode), T.err[d.error_code] ? ` · ${T.err[d.error_code]}` : ""];
export const slotName = (s, slot) => (s.phase === "first" ? T.slotCand(slot) : slot == null ? T.slotNew : T.slot(slot));

/* ---------- 스팬 한 줄 요약: 데이터의 한국어 summary 대신 stage · kind · detail로 지금 언어 문장을 만든다.
   규칙은 생성기(frontend/admin_data.py summarize)와 같다. 모르는 단계면 데이터 summary(없으면 stage)로 ---------- */
const cut = (v, n = 40) => {
  const t = String(v ?? "");
  return t.length > n ? t.slice(0, n) + "…" : t;
};
const nOf = v => (Array.isArray(v) ? v.length : typeof v === "number" ? v : 0);
const given = v => v !== undefined && v !== null && v !== false;
export function spanSummary(s) {
  const S = T.sum, d = s.detail || {}, g = String(s.stage || "");
  if (s.status === "error") return S.error(d.error_code || T.noCode);
  if (s.locked === true) return S.locked;
  if (g === "continuation_skipped") return S.contSkip;
  if (given(d.noop)) return S.noop(d.noop);
  if (given(d.skipped)) return S.skipped(d.skipped);
  if (/^candidates/.test(g)) {
    return d.request_status && d.request_status !== "answerable" ? S.candDecl(d.request_status)
      : S.cand(nOf(d.candidates), d.kind || "—");
  }
  if (g === "decline") return S.decl(d.request_status || "—");
  if (/^search_/.test(g)) {
    return S.search(s.phase === "first", d.slot ?? null, cut(d.key_phrase), nOf(d.hits), d.corpus_count ?? "-", d.search_mode || "-");
  }
  if (/^validate/.test(g)) {
    const slots = Array.isArray(d.slots) ? d.slots : [];
    const rej = slots.reduce((a, x) => a + nOf(x.rejection_reasons), 0) + nOf(d.excluded);
    return S.verify(d.verified ?? "—", slots.length, rej, nOf(d.guard), nOf(d.noops));
  }
  if (/^select_/.test(g)) return (g === "select_1" ? S.sel1 : S.sel)(d.picks ?? "—", d.picks_with_ref ?? "—");
  if (/^revise_/.test(g)) {
    const reps = Array.isArray(d.replacements) ? d.replacements : [];
    return S.revise(reps.length, reps.filter(x => x && x.ref).length);
  }
  if (/^agent_/.test(g) || g === "pick_final") {
    const c = {};
    for (const a of Array.isArray(d.actions) ? d.actions : []) c[a.type] = (c[a.type] || 0) + 1;
    const what = Object.entries(c).map(([k, v]) => `${k} ${v}`).join(", ") || S.noAct;
    return g === "pick_final" ? S.final(what) : S.judge(what, !!d.finish);
  }
  const oc = d.outcome == null ? S.noResult : outcomeLabel(d.outcome);
  if (/^repick_/.test(g)) return S.repick(d.slot ?? "—", oc);
  if (/^replace_/.test(g)) return S.replace(d.slot ?? "—", cut(d.expression), oc);
  if (g === "assemble") return S.asm(d.expressions ?? "—", d.with_example ?? "—");
  if (g === "budget_exhausted") return S.budget(d.code || "—");
  return s.summary || g;
}

/* ---------- 근거(ref) 따라가기: c2h1s1 · r1k2h1s1 · a1k2h1s1 → 그 결과를 낸 검색 스팬 ---------- */
export function refSource(ref, sp) {
  const m = /^(?:c(\d+)|r(\d+)k(\d+)|a(\d+)k(\d+))h(\d+)s(\d+)$/.exec(ref || "");
  if (!m) return null;
  const stage = m[1] != null ? `search_${+m[1] + 1}`
    : m[2] != null ? `search_${m[2]}_${m[3]}` : `search_${m[4]}_${m[5]}`;
  const span = sp.find(s => s.stage === stage);
  return span ? { span, hit: +m[6] } : null;
}
export function refsOf(s) {
  const d = s.detail || {}, out = [];
  if (d.ref) out.push(d.ref);
  for (const x of [...(d.replacements || []), ...(d.pick_list || [])]) if (x.ref) out.push(x.ref);
  return out;
}
/* 검색 스팬 id → 그 결과를 근거로 쓴 뒤 단계들 */
export function usedBy(sp) {
  const m = new Map();
  for (const s of sp) {
    for (const ref of refsOf(s)) {
      const src = refSource(ref, sp);
      if (!src) continue;
      if (!m.has(src.span.id)) m.set(src.span.id, []);
      if (!m.get(src.span.id).includes(s)) m.get(src.span.id).push(s);
    }
  }
  return m;
}
export function prevVerify(sp, s) {
  for (let j = sp.indexOf(s) - 1; j >= 0; j--) if (sp[j].kind === "verify") return sp[j];
  return null;
}

/* ---------- 잠금 전 agent 기록: 먼저 보낸 슬롯(fv)과, 단계 s 전에 repick·replace로 바뀐 슬롯 ---------- */
export function preMarks(r, sp, s) {
  if (!s || r.mode !== "agent" || s.phase !== "continuation" || lockApplied(r)) return null;
  const fv = firstVerified(sp);
  if (!fv.length) return null;
  const done = x => !/^(rejected|kept_verified)/.test(String((x.detail || {}).outcome ?? "rejected"));
  const changed = new Set(sp.slice(0, sp.indexOf(s))
    .filter(x => x.locked !== true && /^(repick|replace)_/.test(x.stage) && done(x)).map(x => x.detail.slot));
  return { fv, changed };
}
export function slotBadge(x, pm) {
  if (x.status !== "verified") return h("span.slotb.x", icon("x"), T.slotNoEx(x.slot));
  const first = pm && pm.fv.includes(x.slot);
  const tag = x.locked ? T.tagFixed : first ? (pm.changed.has(x.slot) ? T.tagChanged : T.tagSent) : "";
  return h("span.slotb.v", icon(x.locked ? "lock" : "check"), T.slotTag(x.slot) + tag);
}
export const slotBadges = (d, pm) =>
  d && Array.isArray(d.slots) ? h("span.slots", d.slots.map(x => slotBadge(x, pm))) : null;
/* 먼저 보낸 슬롯을 겨눈 repick·replace(잠금 전 기록에서만 생김) */
export function firstSlotNote(r, d, fv, s) {
  const hits = r.mode === "agent" && s.phase === "continuation" && s.locked !== true &&
    ["repick", "replace"].includes(d.action) && fv.includes(d.slot);
  if (!hits) return null;
  return h("p.lockrow", preChip(T.firstSlotHit), h("span", lockApplied(r) ? T.lockViolation : T.wouldNoop));
}
export function judgeLock(r, d, fv) {
  if (Array.isArray(d.locked_slots) && d.locked_slots.length) {
    return h("p.lockrow", lockChip(d.locked_slots), h("span", T.judgeLocked));
  }
  if (r.mode !== "agent" || !fv.length || lockApplied(r)) return null;
  return h("p.lockrow", preChip(T.preLock), h("span", T.judgeUnaware(fv.map(x => "#" + x).join("·"))));
}

/* ---------- 도구 행동 · 판단 ---------- */
export function chgEl(d) {
  const pv = d.previous_expression, ex = d.expression;
  if (!pv && !ex) return null;
  const diff = pv && pv !== ex;
  return h("div.chg", diff && h("span.from", h("span.cl", T.prevExpr), enT(pv)),
    ex && h("span.to", h("span.cl", diff ? T.newExpr : T.expr), enT(ex)));
}
export function whyEls(d) {
  if (!d.assessment) return [h("span.why", icon("bubble"), T.why), h("span.muted", T.whyNone)];
  const first = String(d.assessment).split(/(?<=[.!?])\s/)[0].replace(/…$/, "").trim();
  return [h("span.why", icon("bubble"), T.whyFirst), h("span", { lang: "en" }, `“${first}”`)];
}
/* 판단 스팬의 i번째 행동이 실제로 실행된 도구 스팬 */
export function actTarget(s, sp, i) {
  const tag = s.stage === "pick_final" ? "final" : String(s.turn);
  return sp.find(x => ["search", "repick", "replace"].some(p => x.stage === `${p}_${tag}_${i + 1}`)) || null;
}
/* 판단 스팬 → 그 판단이 부른 도구 스팬들(스윔레인 연결선) */
export function toolsOf(s, sp) {
  const m = /^(agent|revise)_(\d+)$/.exec(s.stage);
  if (m) return sp.filter(t => new RegExp(`^(search|repick|replace)_${m[2]}_\\d+$`).test(t.stage));
  return s.stage === "pick_final" ? sp.filter(t => /^(repick|replace)_final_\d+$/.test(t.stage)) : [];
}
function verbOf(a) {
  const V = T.verb;
  if (a.type === "search") return a.slot == null ? V.searchNew : V.search(a.slot);
  if (a.type === "replace") return V.replace(a.slot);
  return a.type === "repick" ? V.repick(a.slot) : String(a.type);
}
export function actSummary(s, sp, fv) {
  const d = s.detail || {}, acts = Array.isArray(d.actions) ? d.actions : [], pv = prevVerify(sp, s), A = T.act;
  const locked = new Set(d.locked_slots || fv);
  let pre = "";
  if (pv && pv.detail && Array.isArray(pv.detail.slots)) {
    const miss = pv.detail.slots.filter(x => x.status !== "verified").map(x => x.slot);
    pre = miss.length ? A.missing(miss.join("·")) : A.allOk;
  }
  const hit = acts.filter(a => a.type !== "search" && locked.has(a.slot)).length;
  const act = acts.length ? A.picked(acts.length, acts.map(verbOf).join(", "), hit ? A.hit(hit, !!d.locked_slots) : "")
    : A.none;
  const fin = s.stage === "pick_final" ? A.final : d.finish ? A.finish : A.next;
  return `${pre} ${act} ${fin}`.trim();
}
