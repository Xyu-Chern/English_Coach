"use strict";

const cat = (() => {
  const art = '<span aria-hidden="true" class="cat-art"></span>';
  const descriptions = {
    love: ["呼噜噜……它把脸贴到了你的手心。", "그르릉… 손바닥에 볼을 부벼요."],
    fish: ["啊呜！小鱼只剩一条尾巴了。", "냠! 작은 물고기가 꼬리만 남았어요."],
    play: ["扑到了！毛线球又滚走了。", "잡았다! 실뭉치가 또 데굴데굴 굴러가요."],
  };
  let napTimer, reactionTimer;
  function update(activity) {
    document.body.dataset.catActivity = activity;
    clearTimeout(napTimer);
    if (activity === "idle" || activity === "ready") {
      napTimer = setTimeout(() => { document.body.dataset.catActivity = "sleep"; }, 35000);
    }
  }
  function react(pose) {
    clearTimeout(reactionTimer);
    document.body.removeAttribute("data-cat-reaction");
    void document.getElementById("coach-pet").offsetWidth;
    document.body.dataset.catReaction = pose;
    document.getElementById("cat-caption").textContent = T(...descriptions[pose]);
    reactionTimer = setTimeout(() => {
      document.body.removeAttribute("data-cat-reaction");
      document.getElementById("cat-caption").textContent = T("喵？", "야옹?");
    }, 3200);
  }
  function open() {
    const panel = document.getElementById("cat-dialog");
    document.getElementById("cat-name").textContent = T("小蓝", "파랑이");
    document.getElementById("cat-close").setAttribute("aria-label", T("关闭", "닫기"));
    for (const [pose, zh, ko] of [["love","摸摸头","쓰다듬기"],["fish","喂小鱼","생선 주기"],["play","玩毛线","실놀이"]]) {
      panel.querySelector('[data-pose="' + pose + '"]').textContent = T(zh, ko);
    }
    const download = document.getElementById("cat-download");
    download.textContent = T("下载蓝猫表情包 ↓", "파랑이 스티커 내려받기 ↓");
    download.href = isAndroid ? onlineSite + "/blue-cat-stickers.zip" : "./blue-cat-stickers.zip";
    panel.showModal();
    react("love");
  }
  function bind() {
    const panel = document.getElementById("cat-dialog");
    document.getElementById("coach-pet").innerHTML = art;
    document.getElementById("cat-portrait").innerHTML = art;
    document.addEventListener("click", e => {
      if (e.target.closest("[data-pet-open]")) open();
    });
    panel.addEventListener("click", e => {
      const action = e.target.closest("[data-pose]");
      if (action) react(action.dataset.pose);
      if (e.target.id === "cat-close" || e.target === panel) panel.close();
    });
    panel.addEventListener("close", () => {
      clearTimeout(reactionTimer);
      document.body.removeAttribute("data-cat-reaction");
      setMascotActivity();
    });
  }
  return { art, bind, update };
})();
