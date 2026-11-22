/* 모드 비교 탭 맨 위 '현재 모드' 카드(PR④). 서버의 mode API(상대 경로 "mode")를 읽고 바꾼다.
   - GET mode → { mode, source: "db" | "env", updated_at, writable, token_required, history: [{ at, from, to }] }
   - POST mode { mode } (+ X-Admin-Token: token_required일 때만) → 200 같은 모양 | 400 | 401 | 409
   - 바꾸기 전에 확인 대화상자를 띄우고, 바뀐 모드는 다음 요청부터 적용된다고 알린다.
   - writable=false면 읽기 전용(버튼 비활성), API가 없으면(정적 미리보기) data.json의 mode.current만 보여 준다.
   - 토큰은 sessionStorage에만 둔다(탭을 닫으면 지워짐). 문자열은 textContent로만 넣는다. */
import { $, fill, h, icon, isObj, utc } from "./ui.js";
import { D, MODES } from "./data.js";
import { modeBadge, modeIcon, onSeg, seg } from "./parts.js";
import { t } from "./i18n.js";
import "./i18n-live.js";

const M = (k, p) => t("mode." + k, p);
const TOKEN_KEY = "phrase-room-admin.token";
/* MS: 마지막 GET/POST 결과 { data } | { err } · busy: 바꾸는 중 · msg: [종류, 키, 자리표시 값] 결과 안내(언어가 바뀌면 다시 번역) */
let MS = null, busy = false, msg = null, loading = null;

const readToken = () => {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
};
const saveToken = v => {
  try {
    if (v) sessionStorage.setItem(TOKEN_KEY, v);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* 저장할 수 없는 환경이면 이번 입력만 쓴다 */
  }
};

/* 응답 모양 확인: 화면이 쓰는 필드만 본다 */
function shape(j) {
  if (!isObj(j) || typeof j.mode !== "string") return null;
  const hist = Array.isArray(j.history) ? j.history.filter(x => isObj(x) && typeof x.to === "string") : [];
  return {
    mode: j.mode, source: j.source === "db" ? "db" : "env", updated_at: typeof j.updated_at === "string" ? j.updated_at : null,
    writable: j.writable === true, token_required: j.token_required === true, history: hist,
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
    .catch(e => {
      MS = { err: e };
    })
    .finally(() => {
      loading = null;
      paint();
    });
  return loading;
}

/* 카드 하나를 돌려준다(탭이 다시 그려질 때마다 새로 만들고, 마지막 결과로 채운다) */
export function modeCard() {
  const host = h("section.card.modecard", { id: "modeCard", "aria-labelledby": "h-mode" });
  paint(host);
  if (!MS && !loading) load();
  return host;
}

function paint(host = $("#modeCard")) {
  if (!host) return;
  const head = h("h3", { id: "h-mode" }, icon("server"), M("title"), h("small", M("sub")),
    MS && !busy && h("button.btn.sm.mc-refresh", {
      type: "button", on: { click: () => (msg = null, load(true)) },
    }, icon("loop"), M("refresh")));
  if (!MS) {
    fill(host, head, h("p.loading", icon("loop"), M("loading")));
    return;
  }
  if (MS.err) {
    const cur = D && D.mode ? D.mode.current : null;
    fill(host, head, h("div.cur", cur && h("span.big." + (MODES.includes(cur) ? cur : "unset"), icon(modeIcon(cur)), cur),
      h("span.ro-tag", icon("lock"), M("readonly"))),
    h("p.warnline", icon("alert"), h("span", M("unavailable"))),
    cur && h("p.foot", M("fallback", { mode: cur })));
    return;
  }
  const d = MS.data, cur = d.mode;
  const srcChip = h("span.mc-src", h("span.muted", M("srcLabel") + " "), h("b", M("src." + d.source)));
  const when = h("span.mc-when.num", d.updated_at ? M("changedAt", { t: utc(d.updated_at) }) : M("never"));
  const sw = seg("mc-sw", M("switchLabel"), MODES.map(m => [m, m, { disabled: !d.writable || busy ? "" : null }]),
    m => m === cur);
  onSeg(sw, m => {
    if (m !== cur && d.writable && !busy) ask(m);
  });
  fill(host, head,
    h("div.cur",
      h("span.big." + (MODES.includes(cur) ? cur : "unset"), icon(modeIcon(cur)), cur),
      srcChip, when,
      !d.writable && h("span.ro-tag", icon("lock"), M("readonly"))),
    h("div.mc-row",
      h("div.field", h("span", M("switchLabel")), sw),
      h("p.d1-now.t", icon("info"), h("span", M("next")))),
    !d.writable && h("p.foot", M("readonlyBody")),
    d.writable && d.token_required && h("p.foot", icon("lock"), " ", M("tokenNote")),
    h("p.mc-msg", { role: "status", "aria-live": "polite" },
      busy ? [icon("loop"), M("saving")] : msg && h("span." + msg[0], M(msg[1], msg[2]))),
    history(d.history));
}

function history(list) {
  const rows = list.slice(0, 5);
  return h("div.mc-hist", h("h4.card-h.sm", icon("clock"), M("histTitle")),
    rows.length
      ? h("ol", rows.map(x => h("li.num", h("span.muted", utc(x.at)), " ", modeBadge(x.from || "—"), " → ", modeBadge(x.to))))
      : h("p.muted.small", M("histNone")));
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
    dlg.close();
    dlg.remove();
    if (back && back.isConnected) back.focus();
  };
  dlg.addEventListener("click", e => {
    const b = e.target.closest("button[value]");
    if (!b) return;
    if (b.value === "cancel") return close();
    const token = tok ? tok.value.trim() : "";
    if (tok) saveToken(token);
    close();
    change(to, token);
  });
  dlg.addEventListener("cancel", e => {
    e.preventDefault();
    close();
  });
  document.body.append(dlg);
  dlg.showModal();
  (tok && !tok.value ? tok : $("button[value=cancel]", dlg)).focus();
}

const ERR = { 400: "err.invalid", 401: "err.token", 409: "err.nodb" };
async function change(to, token) {
  busy = true;
  msg = null;
  paint();
  try {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Admin-Token"] = token;
    let res;
    try {
      res = await fetch("mode", { method: "POST", headers, body: JSON.stringify({ mode: to }), cache: "no-store" });
    } catch {
      msg = ["err", "err.network"];
      return;
    }
    if (!res.ok) {
      if (res.status === 401) saveToken("");
      msg = ["err", ERR[res.status] || "err.http", { status: res.status }];
      return;
    }
    const d = shape(await res.json().catch(() => null));
    if (!d) {
      msg = ["err", "err.shape"];
      return;
    }
    MS = { data: d };
    msg = ["ok", "done", { to: d.mode }];
  } finally {
    busy = false;
    paint();
    const b = $("#mc-sw button[aria-pressed=true]");
    if (b) b.focus();
  }
}
