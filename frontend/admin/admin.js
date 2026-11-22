/* Phrase Room 어드민 · 시안 B(브랜드 확장) — 진입점(<script type="module" src="admin.js">).
   - 같은 폴더의 data.json(어드민 데이터 계약 v1)만 읽는 읽기 전용 화면. 모드 변경·저장 기능 없음(D4 · D5).
   - 모듈(빌드 도구 없음): ui(DOM · 형식) → data(형식 확인 · 파생값) → parts(공용 조각) → shell(탭 · 레이아웃)
     → tab-flags · tab-logs · tab-metrics · tab-graph(탭 4개). 외부 JS 라이브러리 없음.
   - 보안: 데이터 문자열은 textContent · DOM API로만 넣는다(HTML 문자열을 해석하는 API는 쓰지 않음).
   - 화면 언어: i18n.js(?lang=ko|zh|en > localStorage > ko). 머리말 언어 전환은 shell.js, 탭은 각 모듈이 t()로.
   - 검수 훅: window.__tabs · __showTab(id) · __setLang(code) · __ready, ?tab= · ?scale= · ?lang=,
     postMessage {type:"font-scale"|"show-tab"}. */
import { $, fill, h, icon, isObj, utc } from "./ui.js";
import { D, DataError, checkData, msgOf, readJSON, setData } from "./data.js";
import { buildTabs, onResize, setScale, showTab } from "./shell.js";
import { onLang, setLang, t, tx } from "./i18n.js";
import "./tab-flags.js";
import "./tab-logs.js";
import "./tab-metrics.js";
import "./tab-graph.js";

window.__showTab = showTab;
window.__setLang = setLang;

/* 데이터 로더: 상대 경로로 읽는다(미리보기 서버가 경로·포트만 바꿔 띄울 수 있게). 버전이 1이 아니면 그리지 않는다. */
async function loadData() {
  const d = await readJSON(fetch("data.json", { cache: "no-cache" }), "data.json");
  if (!isObj(d) || !isObj(d.meta)) throw new DataError("data.err.noMeta");
  if (d.meta.schema_version !== 1) {
    const v = JSON.stringify(d.meta.schema_version);
    throw new DataError("data.err.version", { got: v ?? (() => t("data.none")) });
  }
  checkData(d);
  return d;
}

let fatal = null; /* 그리지 못한 이유(언어가 바뀌면 같은 오류를 그 언어로 다시 보여 준다) */
function showFatal(e) {
  fatal = e;
  const box = $("#state");
  fill(box, h("h2", icon("alert"), t("app.fatalTitle")), h("p", msgOf(e)), h("p", t("app.fatalHelp")));
  box.classList.add("fail");
  box.setAttribute("role", "alert");
}

/* 머리말 아래 한 줄: 지금 열린 경로(배포에서는 /admin/, 미리보기에서는 그 폴더) · 보호 없음 · 데이터 출처(읽은 뒤) */
function paintBar() {
  fill($("#adminBar"), h("span", icon("gear"), tx("app.deploy", { path: h("b", location.pathname) })),
    h("span.ab-warn", icon("alert"), t("app.noProtection")),
    D && h("span", icon("info"), t("app.source", { run: D.meta.run.id || "—", time: utc(D.meta.generated_at) })));
}
onLang(() => {
  paintBar();
  if (fatal) showFatal(fatal);
});

/* 미리보기 창과 자동 검수가 보내는 메시지. 이 창이나 부모 프레임이 보낸 것만 받고, 출처가 다르면 ?qa=1로 연 때만 받는다
   (아무 사이트나 /admin을 iframe으로 띄워 글자 크기 · 탭을 바꾸지 못하게). */
function listen(qp) {
  const qa = qp.get("qa") === "1";
  addEventListener("message", e => {
    const ours = e.source === window || e.source === window.parent;
    if (!ours || !(e.origin === location.origin || qa) || !isObj(e.data)) return;
    const m = e.data;
    if (m.type === "font-scale" && +m.value > 0) {
      setScale(+m.value);
      onResize(true);
    } else if (m.type === "show-tab" && typeof m.id === "string") {
      showTab(m.id);
    }
  });
}

async function start() {
  buildTabs();
  paintBar();
  const qp = new URLSearchParams(location.search), scale = parseFloat(qp.get("scale"));
  if (scale > 0) setScale(scale);
  listen(qp);
  addEventListener("resize", () => onResize());
  if ("ResizeObserver" in window) {
    const ro = new ResizeObserver(() => onResize());
    ro.observe($("#remProbe"));
    ro.observe($("#main"));
  }
  if (document.fonts) {
    document.fonts.ready.then(() => onResize(true));
    document.fonts.addEventListener("loadingdone", () => onResize(true));
  }
  const first = window.__tabs.includes(qp.get("tab")) ? qp.get("tab") : "flags";
  try {
    setData(await loadData());
  } catch (e) {
    showFatal(e);
    showTab(first);
    window.__ready = true;
    return;
  }
  $("#state").hidden = true;
  paintBar();
  await showTab(first);
  window.__ready = true;
}

start();
