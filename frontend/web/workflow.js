"use strict";
// Each label describes an operation reported by the running coach.
function workflowStage(stage, lang) {
  const labels = {
    prepare: ["接收问题", "질문 받기"],
    model: ["想几个英文说法", "영어 표현 떠올리기"],
    search: ["找播客原句", "팟캐스트 예문 찾기"],
    select: ["挑选合适的例句", "알맞은 예문 고르기"],
    verify: ["核对原句和出处", "원문과 출처 확인하기"],
    extra: ["调整表达或例句", "표현과 예문 다듬기"],
    output: ["整理回答", "답변 정리하기"],
    decline: ["说明回答范围", "답할 수 있는 범위 안내"],
    budget: ["结束本轮查找", "이번 검색 마무리"],
  };
  let kind = "extra";
  if (stage === "prepare") kind = "prepare";
  else if (stage.startsWith("candidates")) kind = "model";
  else if (stage.startsWith("validate")) kind = "verify";
  else if (stage.includes("search")) kind = "search";
  else if (/^(select|pick_final|repick)/.test(stage)) kind = "select";
  else if (stage === "assemble") kind = "output";
  else if (stage === "decline") kind = "decline";
  else if (stage === "budget_exhausted") kind = "budget";
  return {kind, label: labels[kind][lang === "ko" ? 1 : 0]};
}
