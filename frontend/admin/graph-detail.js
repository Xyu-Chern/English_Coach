/* 실행 그래프 · 단계 상세 패널: 고른 노드(질문 · 조립/응답 · 여러 스팬 묶음 · 단계 하나)나 스윔레인 막대의 입력 요약과 출력.
   화면 문구는 i18n-graph.js의 "graph.detail.*"(gtext("detail") = 읽는 순간의 언어). 데이터 문자열은 텍스트 노드로만 넣는다. */
import { fill, fmtN, h, icon, isObj, sec, secU, sum } from "./ui.js";
import { D, firstVerified, lostFirst, spansOf } from "./data.js";
import {
  KIND, actionOf, chip, contChip, enT, exPlain, foot, hl, judgeText, kk, kv, lockChip, lockOne, lostTag, modeBadge,
  mono, slotTag, stageTitle,
} from "./parts.js";
import {
  REJ, SMODE, actSummary, actTarget, chgEl, errText, firstSlotNote, judgeLock, noQuestion, outcomeChip, preMarks,
  prevVerify, refSource, slotBadge, slotBadges, spanSummary, usedBy, whyEls,
} from "./graph-model.js";
import { gtext } from "./i18n-graph.js";

export const DETAIL_TEXT = gtext("detail");
const X = DETAIL_TEXT;

const txt = (...k) => h("p.txt", ...k);
const jumpBtn = (id, ...l) => h("button.jump", { type: "button", "data-jump": id }, ...l);
const list = (arr, f) => (arr.length ? h("ol.dl", arr.map(f)) : null);
const arr = v => (Array.isArray(v) ? v : []);
const enBlock = t => t && h("p.en-block", { lang: "en" }, t);
const quote = q => q && h("span.snip", { lang: "en" }, `“${q}”`);
const rejEl = rs => (Array.isArray(rs) && rs.length ? h("span.rej", rs.map(z => REJ[z] || z).join(", ")) : null);
const H3 = (k, ic, lab, ...rest) => h("h3", h("span.kb.k-" + k, icon(ic), lab), ...rest);
const sec4 = (t, ...k) => h("section", h("h4", t), ...k);

/* host에 상세를 그린다. node = 노선도 노드({key, kind, title, code, spans, why}), spanId = 고른 스팬(없으면 노드 전체) */
export function drawDetail(host, r, node, spanId) {
  const sp = spansOf(r.id), s = spanId ? sp.find(x => x.id === spanId) : null;
  if (s) {
    const back = node && node.spans.length > 1 &&
      h("button.jump.gd-back", { type: "button", "data-node": node.key }, X.back(node.title));
    return fill(host, back, spanDetail(s, r, sp));
  }
  if (!node) return fill(host, h("p.empty", X.pick));
  if (node.key === "req") return fill(host, reqDetail(r));
  if (node.key === "asm") return fill(host, respDetail(r, node));
  if (node.spans.length === 1) return fill(host, spanDetail(node.spans[0], r, sp));
  if (node.spans.length > 1) return fill(host, groupDetail(node, r));
  const k = KIND[node.kind] ? node.kind : "noop";
  return fill(host, H3(k, KIND[k][1], KIND[k][0], node.title), node.code && h("p.mono.muted.small", node.code),
    txt(X.idle), node.why && h("p.txt.muted", node.why));
}

function reqDetail(r) {
  return [H3("request", "user", KIND.request[0], X.req), h("section", h("h4", X.input), txt(r.question ?? noQuestion())),
    kv([[X.mode, modeBadge(r.mode)], [X.task, mono(r.task_id)], [X.attempt, r.attempt, h("small", X.attemptUnit)],
      [X.category, mono(r.category || "—")],
      [X.langExpect, `${r.language || "—"} · ${r.expect === "decline" ? X.expDecline : X.expAnswer}`],
      [X.reqId, mono(r.id)]])];
}

function respDetail(r, node) {
  const steps = node.spans.length > 1 && sec4(X.asmSpans, h("ol.dl", node.spans.map(s => spanRow(s, r))));
  const one = node.spans.length === 1 ? stageDetail(node.spans[0], r, spansOf(r.id))[1] : null;
  return [H3("assemble", "send", KIND.assemble[0], X.resp),
    kv([[X.firstResp, sec(r.first_response_ms), h("small", X.sec)], [X.total, sec(r.total_ms), h("small", X.sec)],
      [X.examples, exPlain(r)], [X.tokens, fmtN(r.tokens.total)], [X.cont, contChip(r)], [X.judge, judgeText(r)]]),
    one && one.length ? h("section", one) : null, answersList(r), steps];
}

const spanRow = (s, r) => {
  const k = kk(s);
  return h("li", h("span.t", h("span.kb.k-" + k, icon(KIND[k][1]), KIND[k][0]), jumpBtn(s.id, stageTitle(s, r.mode)),
    h("span.muted.num", secU(s.elapsed_ms))), h("span.muted.small", spanSummary(s)));
};
function groupDetail(node, r) {
  const k = KIND[node.kind] ? node.kind : "noop", tok = sum(node.spans.filter(s => s.tokens).map(s => s.tokens.total));
  return [H3(k, KIND[k][1], KIND[k][0], node.title), node.code && h("p.mono.muted.small", node.code),
    kv([[X.groupCount, node.spans.length, h("small", X.groupUnit)],
      [X.groupTook, sec(sum(node.spans.map(s => s.elapsed_ms))), h("small", X.sec)], tok ? [X.tokens, fmtN(tok)] : null]),
    sec4(X.group(node.spans.length), h("ol.dl", node.spans.map(s => spanRow(s, r)))), foot(X.groupHint)];
}

function spanDetail(s, r, sp) {
  const k = kk(s), d = s.detail || {}, [inp, out] = stageDetail(s, r, sp);
  const turn = s.turn == null ? ""
    : ` · ${s.turn === 4 ? X.final : r.mode === "agent" ? X.turn(s.turn) : X.round(s.turn)}`;
  return [H3(k, KIND[k][1], KIND[k][0], stageTitle(s, r.mode)),
    h("p.mono.muted.small", `${s.stage} · ${s.phase === "first" ? X.first : X.contPhase}${turn}`),
    kv([[X.start, "+" + sec(s.start_ms), h("small", X.sec)], [X.took, sec(s.elapsed_ms), h("small", X.sec)],
      [X.tokIn, s.tokens ? fmtN(s.tokens.input) : "—"], [X.tokOut, s.tokens ? fmtN(s.tokens.output) : "—"],
      d.model && [X.model, mono(d.model)]]),
    inp.some(Boolean) && sec4(X.inSum, inp), sec4(k === "judge" ? X.outJudge : X.outRes, out)];
}

function answersList(r) {
  const A = D.answers[r.id];
  if (!A || (!A.final.length && !A.first.length)) return foot(X.noAnswer);
  const where = f => (f.episode || f.show) &&
    h("span.muted.small", icon("mic"), " ", [f.episode, f.show].filter(Boolean).join(" · "));
  return h("section", h("h4", X.finalSlots), h("ol.dl",
    A.final.map(f => h("li", h("span.t", slotTag(r, f)), h("span.en", { lang: "en" }, hl(f.expression, f.key_phrase)),
      quote(f.quote), where(f))),
    lostFirst(A).map(f => h("li", h("span.t", lostTag()), enT(f.expression), quote(f.quote)))));
}

/* 단계 종류별 [입력 요약, 출력] */
function stageDetail(s, r, sp) {
  const k = kk(s), d = s.detail || {}, inp = [], out = [];
  if (s.status === "error") out.push(h("div.warnline.err", icon("alert"), h("span", errText(d))));
  if (/^candidates/.test(s.stage)) candidatesDetail(d, inp, out);
  else if (s.kind === "search" && s.locked !== true) searchDetail(s, d, sp, inp, out);
  else if (/^select_/.test(s.stage)) selectDetail(d, sp, inp, out);
  else if (k === "verify") verifyDetail(s, d, r, sp, inp, out);
  else if (k === "judge") judgeDetail(s, d, r, sp, inp, out);
  else if (/^revise_/.test(s.stage)) reviseDetail(s, d, sp, inp, out);
  else if (k === "act" || k === "lock") actDetail(s, k, d, r, sp, inp, out);
  else if (k === "skip") {
    inp.push(txt(X.skipIn(h("b.num", `${r.verified_first ?? "—"}/3`))));
    out.push(txt(X.skipOut));
  } else if (k === "decline") {
    out.push(txt(X.verdict, chip("warn.mono", null, d.request_status || "—")), enBlock(d.note));
  } else if (s.stage === "assemble") {
    out.push(txt(X.asm(h("b.num", d.expressions ?? "—"), h("b.num", d.with_example ?? "—"))));
  } else out.push(txt(spanSummary(s)), d.code && txt(X.code, mono(d.code)));
  return [inp, out];
}

function candidatesDetail(d, inp, out) {
  const C = X.cand, phrase = c => (typeof c === "string" ? c : (c && c.key_phrase) || "");
  const cand = (c, i) => h("li", h("span.t", h("span.muted", C.n(i)), h("span.mono", { lang: "en" }, phrase(c))),
    isObj(c) && c.expression && h("span.en", { lang: "en" }, hl(c.expression, c.key_phrase)),
    isObj(c) && c.function && h("span.muted.small", { lang: "en" }, c.function));
  inp.push(txt(C.q, d.kind ? [C.kind, mono(d.kind)] : ""));
  const tone = d.request_status === "answerable" ? "ok" : "warn";
  out.push(txt(C.status, chip(tone + ".mono", null, d.request_status || "—")), list(arr(d.candidates), cand),
    enBlock(d.status_note));
}

function searchDetail(s, d, sp, inp, out) {
  const S = X.search, users = usedBy(sp).get(s.id) || [];
  inp.push(kv([[s.phase === "first" ? S.slotFirst : S.slotCont, d.slot ?? S.newExpr],
    [S.policy, mono(d.query_policy || "—")]]),
  enBlock(d.query), txt(S.key, h("span.mono", { lang: "en" }, d.key_phrase || "—")),
  d.reason && [txt(h("b", S.reason)), enBlock(d.reason)]);
  if (s.status === "error") return;
  const hit = (x, i) => h("li",
    h("span.t", h("span.muted.num", `hit ${i + 1}`), h("b", { lang: "en" }, x.episode || ""),
      h("span.muted.mono", x.show || "")),
    h("span.snip", { lang: "en" }, hl(x.snippet, d.key_phrase)));
  out.push(txt(`${SMODE[d.search_mode] || d.search_mode || ""} · ${S.hits}`, h("b.num", d.hits ?? "—"), S.corpus,
    h("b.num", d.corpus_count ?? "—"), S.unit),
  arr(d.hit_list).length ? list(d.hit_list, hit) : foot(S.rawOnlyEx),
  users.length ? txt(icon("check"), S.usedBy, users.map((c, i) => [i ? ", " : "", jumpBtn(c.id, c.stage)]))
    : h("p.txt.muted", S.unused));
}

function selectDetail(d, sp, inp, out) {
  const S = X.select;
  const pick = p => {
    const src = refSource(p.ref, sp);
    const back = src && jumpBtn(src.span.id, `← ${src.span.stage} hit ${src.hit}`);
    const ref = p.ref ? [chip("ok.mono", null, p.ref), back] : chip("", null, S.noRef);
    return h("li", h("span.t", h("span.muted", S.cand(p.candidate)), ref), p.expression && enT(p.expression));
  };
  inp.push(txt(S.input));
  out.push(txt(S.picks, h("b.num", d.picks_with_ref ?? "—"), ` / ${d.picks ?? "—"}`), list(arr(d.pick_list), pick));
}

function verifyDetail(s, d, r, sp, inp, out) {
  const V = X.verify, pm = preMarks(r, sp, s), slots = arr(d.slots), locked = slots.filter(x => x.locked).map(x => x.slot);
  const slot = x => h("li",
    h("span.t", slotBadge(x, pm), h("span.mono", { lang: "en" }, x.key_phrase || ""),
      x.ref && h("span.muted.mono", x.ref)),
    x.expression && enT(x.expression), quote(x.quote), rejEl(x.rejection_reasons));
  inp.push(txt(V.input), locked.length && h("p.lockrow", lockChip(locked), h("span", V.locked)));
  const extra = [d.excluded ? V.excluded(d.excluded) : "", d.guard ? V.guard(d.guard) : ""].filter(Boolean);
  out.push(txt(V.verified, h("b.num", `${d.verified ?? "—"}/${slots.length || 3}`)), list(slots, slot),
    extra.length ? txt(extra.join(" · ")) : null);
}

function judgeDetail(s, d, r, sp, inp, out) {
  const J = X.judgeD, pv = prevVerify(sp, s), fv = firstVerified(sp);
  const act = (a, i) => {
    const tgt = actTarget(s, sp, i);
    return h("li", h("span.t", h("b.mono", String(a.type)), h("span", a.slot == null ? J.slotNew : J.slot(a.slot)),
      a.key_phrase && h("span.mono", { lang: "en" }, a.key_phrase), tgt && jumpBtn(tgt.id, `→ ${tgt.stage}`)),
    a.query && h("span.snip", { lang: "en" }, a.query),
    a.reason && h("span.muted.small", { lang: "en" }, J.reason(a.reason)));
  };
  inp.push(txt(J.prev), pv && slotBadges(pv.detail, preMarks(r, sp, pv.phase === "continuation" ? pv : s)),
    judgeLock(r, d, fv), txt(J.budget));
  out.push(h("div.bubble", whyEls(d)), h("p.act-sum", h("b", J.actSum), h("span", actSummary(s, sp, fv))),
    list(arr(d.actions), act), txt("finish = ", h("b.mono", d.finish === undefined ? "—" : String(d.finish))),
    d.assessment && h("details", { open: true }, h("summary", J.raw), enBlock(d.assessment)));
}

function reviseDetail(s, d, sp, inp, out) {
  const R = X.revise, pv = prevVerify(sp, s);
  const rep = x => {
    const src = refSource(x.ref, sp);
    const ref = x.ref ? [chip("mono", null, x.ref), src && jumpBtn(src.span.id, `← ${src.span.stage}`)]
      : chip("wait", null, R.newSearch);
    return h("li", h("span.t", h("span", R.slot(x.replaces)), h("span.mono", { lang: "en" }, x.key_phrase || ""), ref),
      x.expression && enT(x.expression));
  };
  inp.push(txt(R.prev), pv && slotBadges(pv.detail), h("p.rule", icon("gear"), h("span", R.rule(s.turn))));
  out.push(arr(d.replacements).length ? list(d.replacements, rep) : txt(spanSummary(s)));
}

function actDetail(s, k, d, r, sp, inp, out) {
  const A = X.act, src = refSource(d.ref, sp);
  inp.push(txt(A.picked(h("b.mono", actionOf(s)), d.slot ?? "—")), enBlock(d.reason));
  if (k === "lock") {
    out.push(h("p.lockrow", lockOne(d.slot), h("span", A.lockNoop)), foot(A.lockFoot));
    return;
  }
  out.push(txt(outcomeChip(d.outcome)), firstSlotNote(r, d, firstVerified(sp), s),
    d.ref && txt(A.ref, mono(d.ref), src && [" · ", jumpBtn(src.span.id, `${src.span.stage} hit ${src.hit}`)]),
    chgEl(d), rejEl(d.rejection_reasons));
}
