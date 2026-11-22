/* Phrase Room 어드민 · 공용 도우미(데이터와 무관한 모듈, i18n.js만 import): DOM 만들기, 아이콘, 숫자 형식, 퍼센타일.
   보안: 문자열은 텍스트 노드와 setAttribute로만 넣는다(HTML 문자열을 해석하는 API는 쓰지 않음).
   형식 함수(fmtN · secU · utc)는 지금 화면 언어(i18n.js)를 따른다. */
import { fmtDateTime, fmtNum, t } from "./i18n.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const isObj = v => v != null && typeof v === "object" && !Array.isArray(v);
export const isNum = v => typeof v === "number" && Number.isFinite(v);

function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k != null && k !== false && k !== "") el.append(k instanceof Node ? k : String(k));
  }
  return el;
}

/* h("span.chip.ok", { title }, ...자식): 문자열 자식은 텍스트 노드가 된다.
   특수 속성: on = 이벤트 처리기, css = style.setProperty(CSSOM이라 CSP의 인라인 스타일 금지에 걸리지 않음). */
export function h(sel, ...args) {
  const [tag, ...cls] = sel.split(".");
  const el = document.createElement(tag || "div");
  if (cls.length) el.className = cls.join(" ");
  if (isObj(args[0]) && !(args[0] instanceof Node)) {
    for (const [k, v] of Object.entries(args.shift())) {
      if (v == null || v === false) continue;
      if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (k === "css") for (const [p, x] of Object.entries(v)) el.style.setProperty(p, x);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  return add(el, args);
}

export function sv(tag, attrs, ...kids) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, String(v));
  return add(el, kids);
}

export function fill(el, ...kids) {
  el.replaceChildren();
  return add(el, kids);
}

/* ---------- 아이콘: 24 × 24 경로 문자열 상수(createElementNS로 그림) ---------- */
const C = (x, y, r) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0z`;
const RR = (x, y, w, hh, r) =>
  `M${x + r} ${y}h${w - 2 * r}a${r} ${r} 0 0 1 ${r} ${r}v${hh - 2 * r}a${r} ${r} 0 0 1 ${-r} ${r}` +
  `h${2 * r - w}a${r} ${r} 0 0 1 ${-r} ${-r}v${2 * r - hh}a${r} ${r} 0 0 1 ${r} ${-r}z`;
const PATHS = {
  server: RR(4, 4, 16, 6.5, 1.5) + RR(4, 13.5, 16, 6.5, 1.5) + "M7.5 7.25h.01M7.5 16.75h.01M11 7.25h5.5M11 16.75h5.5",
  mic: RR(9, 3, 6, 11, 3) + "M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21",
  pair: "M4.5 9h13l-3.5-3.5M19.5 15h-13l3.5 3.5",
  list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
  chart: "M4 20V4M4 20h16M8.5 16v-5M12.5 16V8M16.5 16v-3",
  graph: C(6, 6, 2.5) + C(18, 12, 2.5) + C(6, 18, 2.5) + "M8.3 7.2 15.7 10.8M8.3 16.8l7.4-3.6",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6.5 6.5l11 11M17.5 6.5l-11 11",
  clock: C(12, 12, 8.5) + "M12 7.5V12l3 2",
  hour: "M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9",
  alert: "M12 4 2.8 19.5h18.4zM12 10v4.5M12 17.2v.01",
  ban: C(12, 12, 8.5) + "M6 6l12 12",
  spark:
    "M12 3.5c.6 3.9 2.6 5.9 6.5 6.5-3.9.6-5.9 2.6-6.5 6.5-.6-3.9-2.6-5.9-6.5-6.5 3.9-.6 5.9-2.6 6.5-6.5z" +
    "M18.5 16.5l.6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9-1.9-.6 1.9-.6z",
  bubble:
    "M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5h-7l-5 4v-4H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z" +
    "M8.5 10.5h.01M12 10.5h.01M15.5 10.5h.01",
  search: C(11, 11, 6.5) + "M16 16l4.5 4.5",
  tool: "M14.5 5.5a4 4 0 0 0-5 5L4 16l4 4 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-2.5-.5-.5-2.5z",
  shield: "M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6zM9 12l2 2 4-4",
  box: "M4 8 12 4l8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8",
  bolt: "M13 3 5 13.5h6L10 21l8-10.5h-6z",
  arrow: "M5 12h14M13 6l6 6-6 6",
  user: C(12, 8, 3.5) + "M5 20c1-4 4-6 7-6s6 2 7 6",
  gear:
    C(12, 12, 3) +
    "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1",
  loop: "M4.5 12a7.5 7.5 0 0 1 13-5.1M19.5 12a7.5 7.5 0 0 1-13 5.1M18 3.5v4h-4M6 20.5v-4h4",
  send: "M12 19V5M6 11l6-6 6 6",
  info: C(12, 12, 8.5) + "M12 11v5M12 8h.01",
  lock: RR(5, 10.5, 14, 10, 2) + "M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3M12 14.5v2",
  skip: "M4.5 6.5 11 12l-6.5 5.5zM12.5 6.5 19 12l-6.5 5.5z",
  plus: "M12 5.5v13M5.5 12h13",
  globe: C(12, 12, 8.5) + "M3.5 12h17M12 3.5c2.4 2.3 3.5 5.2 3.5 8.5s-1.1 6.2-3.5 8.5c-2.4-2.3-3.5-5.2-3.5-8.5s1.1-6.2 3.5-8.5z",
};
const ICON_ATTRS = {
  viewBox: "0 0 24 24", "aria-hidden": "true", fill: "none", stroke: "currentColor", "stroke-width": 1.8,
  "stroke-linecap": "round", "stroke-linejoin": "round",
};
export const icon = (name, cls) =>
  sv("svg", { class: cls ? `ic ${cls}` : "ic", ...ICON_ATTRS }, sv("path", { d: PATHS[name] || "" }));

/* ---------- 숫자 · 형식 ---------- */
export const sec = ms => (isNum(ms) ? (ms / 1000).toFixed(1) : "—");
export const secU = ms => (isNum(ms) ? t("unit.sec", { n: sec(ms) }) : "—");
export const fmtN = n => fmtNum(n);
export function fmtK(n) {
  if (!isNum(n)) return "—";
  if (n < 1000) return String(Math.round(n));
  return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k";
}
export const pct = (a, b) => (b ? ((a / b) * 100).toFixed(1) : "—");
export const usd = v => (isNum(v) ? "$" + v.toFixed(v < 0.1 ? 4 : 2) : "—");
/* ISO 시각 → 언어별 날짜 + 시:분 UTC("2026. 11. 17. 05:30 UTC" · "2026/11/17 05:30 UTC" · "Nov 17, 2026, 05:30 UTC") */
export const utc = ts => (typeof ts === "string" && ts.length >= 16 ? fmtDateTime(ts) : "—");
export const shortId = id => String(id).slice(0, 8);
export const sum = a => a.reduce((x, y) => x + (isNum(y) ? y : 0), 0);
export const mean = a => (a.length ? sum(a) / a.length : null);

/* nearest-rank: evaluation/report.py의 nearest_rank와 같다 — ⌈p/100 × n⌉번째로 작은 값(보간 없음) */
export function nr(arr, p) {
  const a = arr.filter(isNum).sort((x, y) => x - y);
  if (!a.length) return null;
  const k = Math.ceil(+((p / 100) * a.length).toFixed(9));
  return a[Math.min(a.length, Math.max(1, k)) - 1];
}
/* 퍼센타일이 안정되는 최소 표본 = 10 / (1 − p) */
export const NEED = q => Math.round(10 / (1 - q / 100));
export const rootPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
