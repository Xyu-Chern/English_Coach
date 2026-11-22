/* 탭 · 머리말(언어 전환) · 레이아웃 측정 · 가로 스크롤 단서. 탭 모듈은 register(id, render, dyn)로 자기 화면을 붙인다.
   render(panel)는 처음 열 때 한 번(언어가 바뀌면 지금 탭은 바로, 다른 탭은 다음에 열 때 다시),
   dyn()은 폭·글자 크기가 바뀔 때마다(측정 후 다시 그리는 차트·연결선). */
import { $, $$, fill, h, icon, rootPx } from "./ui.js";
import { D, retryTraces, tracesFailed } from "./data.js";
import { errorBox } from "./parts.js";
import { LANGS, LANG_NAMES, HTML_LANG, lang, onLang, setLang, t } from "./i18n.js";

/* label은 지금 언어로 읽힌다. 탭 모듈이 이름을 바꾸려면 label에 i18n 키 · 함수 · 문장 중 하나를 넣는다
   (키나 함수면 언어가 바뀔 때 따라 바뀌고, 문장은 그대로 보인다). 또는 register로 tab.<id> 키를 덮어쓴다. */
const tabDef = (id, ic) => ({
  id, ic, key: "tab." + id, custom: null,
  get label() {
    const c = this.custom;
    return c == null ? t(this.key) : typeof c === "function" ? String(c()) : t(String(c));
  },
  set label(v) {
    this.custom = v;
  },
});
export const TABS = [tabDef("flags", "server"), tabDef("logs", "list"), tabDef("metrics", "chart"), tabDef("graph", "graph")];
window.__tabs = TABS.map(x => x.id);
const VIEWS = {}, rendered = {};
let curTab = null;

export function register(id, render, dyn = null) {
  VIEWS[id] = { render, dyn };
}

/* index.html의 고정 문구: data-i18n="키"(글자) · data-i18n-aria="키"(aria-label). 문서 제목도 함께. */
function paintStatic() {
  document.title = t("app.title");
  for (const el of $$("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of $$("[data-i18n-aria]")) el.setAttribute("aria-label", t(el.dataset.i18nAria));
  for (const x of TABS) {
    const s = $(`#tab-${x.id} span`);
    if (s) s.textContent = x.label;
  }
  const sw = $("#langSwitch");
  if (sw) {
    sw.setAttribute("aria-label", t("app.langLabel"));
    $$("button", sw).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.lang === lang())));
  }
}

/* 언어 전환(한국어 / 中文 / English): 각 버튼은 자기 언어 이름을 자기 lang으로 보여 준다 */
function buildLang() {
  const host = $("#langSwitch");
  if (!host) return;
  fill(host, icon("globe", "lang-ic"), LANGS.map(l => h("button", {
    type: "button", lang: HTML_LANG[l], "data-lang": l, "aria-pressed": String(l === lang()),
  }, icon("check", "ck"), LANG_NAMES[l])));
  host.addEventListener("click", e => {
    const b = e.target.closest("button[data-lang]");
    if (b) setLang(b.dataset.lang);
  });
}

/* 언어가 바뀌면: 고정 문구 → 그린 탭을 모두 '안 그림'으로 → 지금 탭만 바로 다시 그린다.
   (data.js가 먼저 등록돼 SIZE 같은 문장 파생값이 이미 바뀐 뒤에 실행된다) */
onLang(() => {
  paintStatic();
  for (const id of Object.keys(rendered)) rendered[id] = null;
  if (curTab) showTab(curTab);
});

export function buildTabs() {
  const host = $("#tabs");
  fill(host, TABS.map(x => h("button", {
    type: "button", role: "tab", id: "tab-" + x.id, "aria-controls": "panel-" + x.id, "aria-selected": "false",
    tabindex: -1, "data-tab": x.id,
  }, icon(x.ic), h("span", x.label))));
  buildLang();
  paintStatic();
  host.addEventListener("click", e => {
    const b = e.target.closest("[role=tab]");
    if (b) showTab(b.dataset.tab);
  });
  host.addEventListener("keydown", e => {
    const ids = window.__tabs, i = ids.indexOf(curTab);
    const next = {
      ArrowRight: ids[(i + 1) % ids.length], ArrowLeft: ids[(i - 1 + ids.length) % ids.length],
      Home: ids[0], End: ids[ids.length - 1],
    }[e.key];
    if (!next) return;
    e.preventDefault();
    showTab(next);
    $("#tab-" + next).focus();
  });
}

const frames = n =>
  new Promise(res => {
    const f = k => (k ? requestAnimationFrame(() => f(k - 1)) : res());
    f(n);
  });

export async function showTab(id) {
  if (!window.__tabs.includes(id)) return false;
  curTab = id;
  for (const x of window.__tabs) {
    const on = x === id, b = $("#tab-" + x);
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    $("#panel-" + x).hidden = !on || !D;
  }
  if (!D) return false;
  const panel = $("#panel-" + id);
  rendered[id] ??= Promise.resolve()
    .then(() => VIEWS[id].render(panel))
    .catch(e => {
      rendered[id] = null;
      /* trace 파일을 못 읽은 경우에만 다시 불러오기 버튼(그 밖의 오류는 다시 해도 같음) */
      const retry = tracesFailed() ? () => (retryTraces(), rerender(id)) : null;
      fill(panel, errorBox(e, retry));
    });
  await rendered[id];
  if (curTab !== id) return true;
  const dyn = () => {
    updateLayout();
    if (rendered[id] && VIEWS[id].dyn) VIEWS[id].dyn();
  };
  dyn();
  await frames(2);
  if (curTab === id) dyn();
  return true;
}

/* 탭을 처음부터 다시 그린다(trace 다시 불러오기 뒤 등) */
export function rerender(id) {
  rendered[id] = null;
  if (curTab === id) showTab(id);
}

/* ---------- 레이아웃 측정(글자 크기 · 폭이 바뀌면 다시) ---------- */
export function updateLayout() {
  const px = rootPx(), main = $("#main"), cs = getComputedStyle(main);
  const w = (main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) / px;
  const W = w >= 84 ? "xl" : w >= 64 ? "l" : w >= 48 ? "m" : "s";
  const fit = innerHeight / px >= 34 && (W === "xl" || W === "l");
  document.body.dataset.w = W;
  document.body.dataset.fit = fit ? "1" : "0";
  /* data-steps="56:full 34:c 0:n": 첫 자식 폭(rem)이 기준 이상인 첫 값을 data-lc로(요청 표 열 구성) */
  for (const el of $$("[data-steps]")) {
    if (!el.offsetParent || !el.firstElementChild) continue;
    const tw = el.firstElementChild.clientWidth / px;
    const step = el.dataset.steps.split(" ").map(x => x.split(":")).find(([min]) => tw >= +min);
    if (step) el.dataset.lc = step[1];
  }
  fitPanes(px, fit);
  $$("[data-hscroll]").forEach(hscrollCue);
}

/* 화면 맞춤 패널: 남은 높이만큼. 위 도구가 길어 20rem보다 적으면 같은 묶음 전체를 대체 높이(뷰포트 78%)로 */
function fitPanes(px, fit) {
  const panes = $$(".fitpane"), keep = panes.map(el => [el.scrollTop, el.scrollLeft]);
  panes.forEach(el => el.style.removeProperty("max-height"));
  if (fit) {
    const alt = Math.min(Math.max(22 * px, 0.78 * innerHeight), innerHeight - 1.5 * px);
    const room = new Map(panes.filter(el => el.offsetParent)
      .map(el => [el, innerHeight - (el.getBoundingClientRect().top + scrollY) - 1.25 * px]));
    const short = el => {
      const host = el.closest(".lgrid,.gbody");
      return [...room].some(([e, v]) => v < 20 * px && host && host.contains(e));
    };
    for (const [el, v] of room) el.style.setProperty("max-height", (short(el) ? alt : v) + "px");
  }
  panes.forEach((el, i) => {
    if (keep[i][0]) el.scrollTop = keep[i][0];
    if (keep[i][1]) el.scrollLeft = keep[i][1];
  });
}

/* 가로 스크롤 단서: 오른쪽에 더 있으면 부모에 data-more="r", 안내 문구(data-hint) 표시 */
export function hscrollCue(el) {
  const host = el.parentElement;
  if (!host) return;
  const more = el.scrollWidth - el.clientWidth;
  host.dataset.more = more - el.scrollLeft > 2 ? "r" : "";
  const hint = el.dataset.hint && document.getElementById(el.dataset.hint);
  if (hint) hint.hidden = !(more > 2);
  if (!el.dataset.cue) {
    el.dataset.cue = "1";
    el.addEventListener("scroll", () => hscrollCue(el), { passive: true });
  }
}

let rafId = 0, lastKey = "";
export function onResize(force) {
  cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(() => {
    const key = `${$("#main").clientWidth}|${rootPx()}|${innerHeight}`;
    if (!force && key === lastKey) return;
    lastKey = key;
    updateLayout();
    if (D && curTab && rendered[curTab] && VIEWS[curTab].dyn) VIEWS[curTab].dyn();
  });
}

export function setScale(v) {
  if (v > 0 && v <= 4) document.documentElement.style.setProperty("font-size", 16 * v + "px");
}
