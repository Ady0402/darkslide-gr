"use strict";
// First-use guide overlay and the "import passed" arrow.
// Positions are measured from the real controls, never hard-coded.

window.DarkslideGuide = (function () {
  const PAD = 6;
  const GAP = 16;
  const CARD_W = 360;
  const FLOWS = {
    start: [
      { target: () => document.querySelector("#models .model.on"), title: "先选你的相机",
        text: "目前支持 GR III（固件 2.10），其他机型会陆续加入。" },
      { target: () => document.getElementById("drop"), title: "把官方固件拖到这里",
        text: "从理光官网下载 GR III 2.10 的 fwdc239b.bin。工具会核对是不是官方原件，文件只留在你的电脑上。" },
    ],
    work: [
      { target: () => document.getElementById("slots"), title: "选一个预设",
        text: "格子里是相机的 14 个预设。亮的卡片可以改，暗的、带小锁的暂不开放。" },
      { target: () => document.querySelector(".edit-col"), title: "换图标、改预设名",
        text: "上传图片或用原厂风格做图标；预设名只能用英文，长度不超过原厂名，下面会实时检查。" },
      { target: () => document.getElementById("btnGenerate"), title: "改完点“生成”",
        text: "可以一次改好几个预设。生成前会跑 7 项检查，全部通过才给你下载。" },
    ],
  };
  const TOTAL = FLOWS.start.length + FLOWS.work.length - 1; // card numbering: 1,2 then 3,3,4
  const NUMBERS = { start: [1, 2], work: [3, 3, 4] };

  let layer, spot, card, flow, index, onEnd, arrowEl, arrowTarget;

  function build() {
    if (layer) return;
    layer = document.createElement("div");
    layer.className = "guide-layer";
    layer.hidden = true;
    spot = document.createElement("button");
    spot.className = "guide-spot";
    spot.setAttribute("aria-label", "关闭指引");
    spot.addEventListener("click", () => finish(false));
    card = document.createElement("div");
    card.className = "guide-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.innerHTML =
      '<div class="guide-bar"></div><div class="guide-body">' +
      '<div class="guide-head"><span class="mono guide-label"></span><span class="mono guide-num"></span></div>' +
      '<div class="guide-title"></div><div class="guide-text"></div>' +
      '<div class="guide-actions"><button class="guide-next">知道了</button><button class="guide-skip">不再提示</button></div></div>';
    card.querySelector(".guide-next").addEventListener("click", next);
    card.querySelector(".guide-skip").addEventListener("click", () => finish(true));
    layer.append(spot, card);
    document.body.append(layer);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !layer.hidden) finish(false);
      if (e.key === "Escape" && arrowEl) hideArrow();
    });
  }

  function start(name, done) {
    build();
    flow = name;
    index = 0;
    onEnd = done;
    layer.hidden = false;
    show();
  }

  function show() {
    const step = FLOWS[flow][index];
    const el = step.target();
    if (!el) { next(); return; }
    el.scrollIntoView({ block: "center" });
    const n = NUMBERS[flow][index];
    card.querySelector(".guide-label").textContent = "GUIDE " + n + " / " + (TOTAL - 0);
    card.querySelector(".guide-num").textContent = String(n).padStart(2, "0");
    card.querySelector(".guide-title").textContent = step.title;
    card.querySelector(".guide-text").textContent = step.text;
    card.classList.remove("in");
    place();
    void card.offsetWidth;
    card.classList.add("in");
    card.querySelector(".guide-next").focus({ preventScroll: true });
  }

  function place() {
    if (layer && !layer.hidden) {
      const el = FLOWS[flow][index].target();
      if (!el) return;
      const r = el.getBoundingClientRect();
      const s = { x: r.left - PAD, y: r.top - PAD, w: r.width + PAD * 2, h: r.height + PAD * 2 };
      // keep the whole frame inside the window (targets at the very edge)
      const vwin = window.innerWidth, vhin = window.innerHeight;
      if (s.x < 2) { s.w -= 2 - s.x; s.x = 2; }
      if (s.y < 2) { s.h -= 2 - s.y; s.y = 2; }
      if (s.x + s.w > vwin - 2) s.w = vwin - 2 - s.x;
      if (s.y + s.h > vhin - 2) s.h = vhin - 2 - s.y;
      Object.assign(spot.style, { left: s.x + "px", top: s.y + "px", width: s.w + "px", height: s.h + "px" });
      const vw = window.innerWidth, vh = window.innerHeight;
      const ch = card.offsetHeight || 220;
      const space = { right: vw - (s.x + s.w), left: s.x, below: vh - (s.y + s.h), above: s.y };
      let x, y;
      if (space.right >= CARD_W + GAP * 2) { x = s.x + s.w + GAP; y = s.y; }
      else if (space.left >= CARD_W + GAP * 2) { x = s.x - CARD_W - GAP; y = s.y; }
      else if (space.below >= ch + GAP * 2) { x = s.x; y = s.y + s.h + GAP; }
      else if (space.above >= ch + GAP * 2) { x = s.x; y = s.y - ch - GAP; }
      else { x = (vw - CARD_W) / 2; y = vh - ch - GAP * 2; }
      x = Math.max(GAP, Math.min(x, vw - CARD_W - GAP));
      y = Math.max(GAP, Math.min(y, vh - ch - GAP));
      Object.assign(card.style, { left: x + "px", top: y + "px" });
    }
    placeArrow();
  }

  function next() {
    index += 1;
    if (index >= FLOWS[flow].length) finish(false);
    else show();
  }

  function finish(forever) {
    if (!layer || layer.hidden) return;
    layer.hidden = true;
    const cb = onEnd;
    onEnd = null;
    if (cb) cb(forever);
  }

  // ------------------------------------------------ import-passed arrow
  function showArrow(target) {
    hideArrow();
    arrowTarget = target;
    arrowEl = document.createElement("div");
    arrowEl.className = "guide-arrow";
    arrowEl.innerHTML =
      '<span class="mono guide-arrow-label">导入通过 · 点击下一步</span>' +
      '<svg width="24" height="52" viewBox="0 0 24 52" fill="none" stroke="#FFD31A" stroke-width="3" stroke-linecap="square">' +
      '<path d="M12 2v46M2 38l10 10 10-10"/></svg>';
    document.body.append(arrowEl);
    target.classList.add("guide-target");
    // make room above the target so the arrow never covers nearby text
    if (target.parentElement) target.parentElement.classList.add("guide-room");
    placeArrow();
    setTimeout(() => document.addEventListener("click", hideArrow, { once: true, capture: true }), 0);
  }

  function placeArrow() {
    // vertical arrow above the target, pointing down at it
    if (!arrowEl || !arrowTarget) return;
    const r = arrowTarget.getBoundingClientRect();
    const w = arrowEl.offsetWidth, h = arrowEl.offsetHeight;
    // label sits left of the arrow; keep the arrow itself centred on the target
    const svgW = arrowEl.querySelector("svg").getBoundingClientRect().width;
    const x = Math.max(8, Math.min(r.left + r.width / 2 + svgW / 2 - w, window.innerWidth - w - 8));
    const y = Math.max(8, r.top - h - 6);
    Object.assign(arrowEl.style, { left: x + "px", top: y + "px" });
  }

  function hideArrow() {
    if (arrowTarget) {
      arrowTarget.classList.remove("guide-target");
      if (arrowTarget.parentElement) arrowTarget.parentElement.classList.remove("guide-room");
    }
    if (arrowEl) arrowEl.remove();
    arrowEl = null;
    arrowTarget = null;
  }

  return { start, showArrow, hideArrow, active: () => !!layer && !layer.hidden };
})();
