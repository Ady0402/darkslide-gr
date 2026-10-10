"use strict";

const $ = (id) => document.getElementById(id);
const Names = window.DarkslideNames;
const VIS = { x: 1, y: 2, w: 38, h: 36 };
const STAGE_TAG = { test: "实验", open: "", later: "稍后", closed: "不可改" };

const state = {
  status: null,
  template: null,
  firmware: null,
  factory: null,
  project: null,
  changes: {},
  sel: 7,
  undo: [],
  redo: [],
  saveTimer: null,
  knownRows: null,
  revealAsset: null,
  enterSlots: false,
  draftState: "",
};

// ---------------------------------------------------------------- api
async function api(method, path, body, headers) {
  const opts = { method, headers: headers || {} };
  if (body instanceof Blob || body instanceof ArrayBuffer) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || "请求失败（" + res.status + "）");
    err.data = data;
    throw err;
  }
  return data;
}

function toast(msg, bad) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (bad ? " bad" : "");
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { el.hidden = true; }, bad ? 5000 : 2200);
}

function show(view) {
  if (view === "viewRescue" && show.current !== "viewRescue") show.previous = show.current;
  show.current = view;
  for (const id of ["viewStart", "viewWork", "viewDone", "viewRescue", "viewQuit"]) $(id).hidden = id !== view;
  $("cameraChip").hidden = view === "viewStart" || view === "viewQuit";
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children || [])) if (c) node.append(c);
  return node;
}

const slotOf = (no) => state.template.slots.find((s) => s.no === no);
const editable = (slot, what) => slot[what] === "test" || slot[what] === "open";
const assetUrl = (asset) => "/api/projects/" + state.project.id + "/assets/" + asset;
const factoryUrl = (no) => state.factory ? "/api/factory/" + state.project.input_sha256 + "/icons/" + no + ".png" : null;

// ---------------------------------------------------------------- start
function renderModels() {
  const models = [
    { name: "GR III", desc: "28mm · 固件 2.10", tag: "已支持", on: true, lens: 46 },
    { name: "GR IIIx", desc: "40mm", tag: "未支持", lens: 54 },
    { name: "GR IV", desc: "28mm · 新一代", tag: "未支持", lens: 48 },
  ];
  $("models").replaceChildren(...models.map((m) => el("button", {
    class: "model" + (m.on ? " on" : ""), disabled: !m.on, "aria-pressed": m.on ? "true" : "false",
  }, [
    (() => { const st = el("div", { class: "model-stage" }); st.innerHTML = window.DarkslideCamera.svg(m.name, m.name.replace(/\W/g, "")); return st; })(),
    el("div", { class: "model-name" }, [el("b", { text: m.name }), el("span", { class: "mono xsmall " + (m.on ? "" : "dim2"), text: m.tag })]),
    el("div", { class: "dim small", style: "width:100%", text: m.desc }),
  ])));
}

async function importFile(file) {
  const out = $("importResult");
  out.className = "import-result dim small";
  out.textContent = "正在核对 " + file.name + " …";
  $("projectPick").hidden = true;
  try {
    const buf = await file.arrayBuffer();
    const res = await api("POST", "/api/firmware", buf, { "X-Filename": encodeURIComponent(file.name) });
    state.firmware = res;
    if (res.kind === "official") {
      out.className = "import-result small ok";
      out.textContent = "✓ " + res.reason + " · SHA " + res.sha256.slice(0, 8) + "…" + res.sha256.slice(-8);
      renderProjectPick();
      const go = $("projectPick").querySelector(".btn.primary");
      if (go) window.DarkslideGuide.showArrow(go);
    } else if (res.kind === "generated") {
      out.className = "import-result small ok";
      out.textContent = res.reason;
      if (res.project_id) openProject(res.project_id);
    } else {
      out.className = "import-result small bad";
      out.textContent = "✕ " + res.reason;
      const drop = $("drop"); drop.classList.remove("shake"); void drop.offsetWidth; drop.classList.add("shake");
    }
  } catch (e) {
    out.className = "import-result small bad";
    out.textContent = "✕ " + e.message;
  }
}

function renderProjectPick() {
  // The primary button is always "下一步": continue the latest project for this
  // firmware, or start a new one. Older projects stay listed above it.
  const sha = state.firmware.sha256;
  const projects = (state.status.projects || []).filter((p) => p.input_sha256 === sha);
  const box = $("projectPick");
  const items = projects.map((p) => el("button", { class: "project-item", onclick: () => openProject(p.id) }, [
    el("span", { text: p.title }),
    el("span", { class: "dim xsmall", text: p.changes + " 项改动" }),
  ]));
  items.push(el("button", { class: "btn primary", onclick: () => (projects.length ? openProject(projects[0].id) : newProject()), text: "下一步" }));
  if (projects.length) items.push(el("button", { class: "btn ghost small-btn", onclick: newProject, text: "新建工程" }));
  box.replaceChildren(...items);
  box.hidden = false;
}

async function newProject() {
  try {
    const p = await api("POST", "/api/projects", { title: "未命名", input_sha256: state.firmware.sha256 });
    await loadProject(p);
  } catch (e) { toast(e.message, true); }
}

async function openProject(id) {
  try { await loadProject(await api("GET", "/api/projects/" + id)); } catch (e) { toast(e.message, true); }
}

async function loadProject(p) {
  state.project = p;
  state.changes = JSON.parse(JSON.stringify(p.draft.changes || {}));
  state.undo = [];
  state.redo = [];
  state.enterSlots = true;
  state.knownRows = null;
  state.draftState = p.unsaved ? "草稿未正式保存" : (p.saved_at ? "已保存 " + p.saved_at.slice(11, 16) : "未保存");
  $("projectTitle").value = p.title;
  try { state.factory = await api("GET", "/api/factory/" + p.input_sha256); } catch (e) { state.factory = null; }
  show("viewWork");
  renderAll();
  maybeGuide("work");
}

// ---------------------------------------------------------------- guide
async function setPref(key, value) {
  try { state.status.prefs = await api("POST", "/api/prefs", { key, value }); } catch (e) { /* keep going */ }
}

function maybeGuide(flow) {
  const prefs = (state.status && state.status.prefs) || {};
  if (prefs.guide_off || prefs["guide_" + flow + "_seen"]) return;
  requestAnimationFrame(() => window.DarkslideGuide.start(flow, (forever) => {
    setPref("guide_" + flow + "_seen", true);
    if (forever) setPref("guide_off", true);
  }));
}

// ---------------------------------------------------------------- changes
function snapshot() { return JSON.stringify(state.changes); }

function mutate(fn) {
  state.undo.push(snapshot());
  if (state.undo.length > 200) state.undo.shift();
  state.redo = [];
  fn(state.changes);
  for (const k of Object.keys(state.changes)) if (!Object.keys(state.changes[k]).length) delete state.changes[k];
  scheduleDraft();
  renderAll();
}

function setEdit(no, key, value) {
  mutate((c) => {
    const slot = (c[no] = c[no] || {});
    if (value === undefined) delete slot[key];
    else slot[key] = value;
  });
}

function undo() {
  if (!state.undo.length) return;
  state.redo.push(snapshot());
  state.changes = JSON.parse(state.undo.pop());
  scheduleDraft();
  renderAll();
}

function redo() {
  if (!state.redo.length) return;
  state.undo.push(snapshot());
  state.changes = JSON.parse(state.redo.pop());
  scheduleDraft();
  renderAll();
}

function scheduleDraft() {
  state.draftState = "正在自动保存…";
  renderSaveState();
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(pushDraft, 500);
}

async function pushDraft() {
  try {
    const p = await api("PUT", "/api/projects/" + state.project.id + "/draft", { changes: state.changes });
    state.project = p;
    state.draftState = p.unsaved ? "草稿已自动保存" : "已保存";
  } catch (e) {
    state.draftState = "自动保存失败";
    toast(e.message, true);
  }
  renderSaveState();
}

async function saveProject() {
  clearTimeout(state.saveTimer);
  try {
    await api("PUT", "/api/projects/" + state.project.id + "/draft", { changes: state.changes });
    const p = await api("POST", "/api/projects/" + state.project.id + "/save");
    state.project = p;
    state.draftState = "已保存 " + p.saved_at.slice(11, 16);
    const flash = $("saveState").parentElement;
    flash.classList.remove("flash"); void flash.offsetWidth; flash.classList.add("flash");
    toast("已保存（第 " + p.versions.length + " 版）");
  } catch (e) { toast(e.message, true); }
  renderSaveState();
}

// ---------------------------------------------------------------- render
function renderAll() {
  renderBanner();
  renderSlots();
  renderEditor();
  renderLcd();
  renderChanges();
  renderSaveState();
}

function renderBanner() {
  const t = state.template;
  $("templateBanner").hidden = !!t.reviewed;
  $("templateBanner").textContent = t.review_note || "";
  $("templateState").textContent = t.reviewed ? t.id : "草稿 · 未复核";
}

function slotIcon(slot, cls) {
  const edit = state.changes[slot.no];
  const box = el("span", { class: cls, "aria-hidden": "true" });
  if (edit && edit.icon) box.append(el("img", { src: assetUrl(edit.icon.asset), alt: "" }));
  else if (factoryUrl(slot.no)) { box.classList.add("img"); box.append(el("img", { src: factoryUrl(slot.no), alt: "" })); }
  else box.textContent = slot.abbr;
  return box;
}

function renderSlots() {
  // Design A: editable slots are solid cards; locked ones recede (grey, faded icon, lock).
  setTimeout(() => { state.enterSlots = false; }, 0);
  $("slots").replaceChildren(...state.template.slots.map((s) => {
    const locked = !editable(s, "icon") && !editable(s, "rename");
    const changed = !!state.changes[s.no];
    const what = editable(s, "rename") ? "图标和预设名可改" : editable(s, "icon") ? "仅图标可改" : "暂不开放";
    return el("button", {
      class: "slot" + (s.no === state.sel ? " on" : "") + (locked ? " locked" : " open") + (state.enterSlots ? " enter" : ""),
      style: state.enterSlots ? "animation-delay:" + (s.no - 1) * 20 + "ms" : null,
      role: "option", "aria-selected": s.no === state.sel ? "true" : "false",
      "aria-disabled": locked ? "true" : "false", title: s.name + " · " + what,
      onclick: () => { if (locked) return; state.sel = s.no; renderAll(); },
    }, [
      el("span", { class: "top-line" }, [
        el("span", { class: "mono", text: String(s.no).padStart(2, "0") }),
        changed ? el("span", { class: "dot" }) : locked ? el("span", { class: "lock", "aria-label": "暂不开放" }) : null,
      ]),
      el("span", { class: "name-line" }, [slotIcon(s, "abbr"), el("span", { text: s.name })]),
    ]);
  }));
}

function renderLcd() {
  const slots = state.template.slots;
  const i = slots.findIndex((s) => s.no === state.sel);
  const start = Math.max(0, Math.min(i - 1, slots.length - 4));
  $("lcdCount").textContent = String(state.sel).padStart(2, "0") + "/" + slots.length;
  $("lcdRows").replaceChildren(...slots.slice(start, start + 4).map((s) => {
    const edit = state.changes[s.no] || {};
    return el("div", { class: "lcd-row" + (s.no === state.sel ? " on" : "") }, [
      slotIcon(s, "lcd-icon"),
      el("span", { text: edit.name !== undefined ? edit.name : s.name }),
    ]);
  }));
  requestAnimationFrame(() => {
    const on = $("lcdRows").querySelector(".lcd-row.on");
    const bar = $("lcdBar");
    if (!on) { bar.style.opacity = "0"; return; }
    bar.style.opacity = "1";
    bar.style.transform = "translateY(" + on.offsetTop + "px)";
    bar.style.height = on.offsetHeight + "px";
  });
}

function renderEditor() {
  const s = slotOf(state.sel);
  const edit = state.changes[s.no] || {};
  $("slotMeta").textContent = String(s.no).padStart(2, "0") + " · MODE " + s.mode + " · ICON " + s.icon_id + " · STR " + s.string_id;
  $("slotTitle").textContent = s.name;
  if (factoryUrl(s.no)) $("iconFactory").replaceChildren(el("img", { src: factoryUrl(s.no), alt: s.name + " 原厂图标" }));
  else $("iconFactory").textContent = s.abbr;
  const iconNew = $("iconNew");
  if (edit.icon) {
    iconNew.className = "icon-new has";
    const reveal = state.revealAsset === edit.icon.asset;
    iconNew.replaceChildren(el("img", { class: reveal ? "reveal" : null, src: assetUrl(edit.icon.asset), alt: s.name + " 新图标" }));
    if (reveal) state.revealAsset = null;
  } else {
    iconNew.className = "icon-new";
    iconNew.replaceChildren(el("span", { text: "未修改" }));
  }
  const iconOpen = editable(s, "icon");
  $("iconField").classList.toggle("locked", !iconOpen);
  for (const id of ["btnUpload", "btnFactoryStyle", "btnIconReset"]) $(id).disabled = !iconOpen;
  $("btnIconReset").disabled = !iconOpen || !edit.icon;
  $("iconHint").textContent = iconOpen
    ? "PNG / JPG / WebP，裁成 38×36 可见区，四周透明边按原厂规则保留"
    : "这个预设的图标" + (s.icon === "closed" ? "不开放编辑" : "稍后开放");

  const nameOpen = editable(s, "rename");
  const limit = s.factory_en.length;
  const input = $("nameInput");
  $("nameField").classList.toggle("locked", !nameOpen);
  input.disabled = !nameOpen;
  input.placeholder = s.factory_en;
  const value = edit.name !== undefined ? edit.name : s.factory_en;
  if (document.activeElement !== input) input.value = value;
  $("btnNameReset").disabled = !nameOpen || edit.name === undefined;
  const checks = nameOpen ? Names.check(value, limit) : [];
  const ok = checks.every((c) => c.ok);
  $("nameBox").classList.toggle("bad", nameOpen && !ok);
  $("nameCount").textContent = nameOpen ? value.length + " / " + limit : "";
  const items = checks.map((c) => el("li", { class: c.ok ? "" : "bad" }, [el("span", { class: "mk", text: c.ok ? "✓" : "✕" }), el("span", { text: c.message })]));
  if (nameOpen) {
    items.push(el("li", { class: "info" }, [el("span", { class: "mk", text: "i" }), el("span", { text: "原厂英文名 " + s.factory_en + "；英文和简体中文菜单显示新预设名，其他 19 种语言保持原厂" })]));
  } else {
    items.push(el("li", { class: "info" }, [el("span", { class: "mk", text: "i" }), el("span", { text: "这个预设的预设名" + (s.rename === "closed" ? "暂不开放" : "稍后开放") + (s.note ? "：" + s.note : "") })]));
  }
  $("nameChecks").replaceChildren(...items);
}

function renderChanges() {
  const rows = [];
  for (const s of state.template.slots) {
    const edit = state.changes[s.no];
    if (!edit) continue;
    if (edit.icon) {
      rows.push(el("div", { class: "change", "data-key": s.no + "i" }, [
        el("span", { class: "thumb" }, el("img", { src: assetUrl(edit.icon.asset), alt: "" })),
        el("span", { class: "txt" }, [el("span", { text: s.name + " 图标" }), el("span", { text: edit.icon.style === "factory" ? "→ 原厂风格 · " + (edit.icon.text || "") : "→ 自定义图片" })]),
        el("button", { "aria-label": "撤销 " + s.name + " 图标改动", text: "×", onclick: (e) => leaveThen(e, () => setEdit(s.no, "icon", undefined)) }),
      ]));
    }
    if (edit.name !== undefined) {
      const ok = Names.ok(edit.name, s.factory_en.length);
      rows.push(el("div", { class: "change", "data-key": s.no + "n" }, [
        el("span", { class: "thumb", text: "Aa" }),
        el("span", { class: "txt" }, [el("span", { text: s.name + " 预设名" + (ok ? "" : " · 未通过检查") }), el("span", { text: "→ " + edit.name })]),
        el("button", { "aria-label": "撤销 " + s.name + " 预设名改动", text: "×", onclick: (e) => leaveThen(e, () => setEdit(s.no, "name", undefined)) }),
      ]));
    }
  }
  const known = state.knownRows;
  for (const r of rows) if (known && !known.has(r.dataset.key)) r.classList.add("enter");
  state.knownRows = new Set(rows.map((r) => r.dataset.key));
  const n = rows.length;
  $("changeCount").textContent = "CHANGES · " + n;
  $("changeSlots").textContent = n ? Object.keys(state.changes).length + " 个预设" : "";
  $("changeList").replaceChildren(...(rows.length ? rows : [el("div", { class: "empty", text: "还没有改动。选一个预设，换图标或改预设名。" })]));
}

function leaveThen(e, fn) {
  const row = e.currentTarget.closest(".change");
  if (!row || matchMedia("(prefers-reduced-motion: reduce)").matches) { fn(); return; }
  row.classList.add("leave");
  setTimeout(fn, 180);
}

function renderSaveState() {
  $("saveState").textContent = state.draftState;
  const n = (state.status.builds || []).filter((b) => state.project && b.project_id === state.project.id).length;
  $("buildCount").textContent = n;
}

// ---------------------------------------------------------------- name
function onNameInput() {
  const s = slotOf(state.sel);
  const v = $("nameInput").value;
  const current = (state.changes[s.no] || {}).name;
  if (v === s.factory_en) { if (current !== undefined) setEdit(s.no, "name", undefined); else renderEditor(); return; }
  if (v === current) return;
  // collapse consecutive keystrokes into one undo step
  const last = state.undo[state.undo.length - 1];
  const typing = onNameInput.lastSlot === s.no && Date.now() - (onNameInput.lastAt || 0) < 1200;
  if (typing && last) {
    state.changes[s.no] = Object.assign({}, state.changes[s.no], { name: v });
    scheduleDraft();
    renderSlots(); renderEditor(); renderLcd(); renderChanges();
  } else {
    setEdit(s.no, "name", v);
  }
  onNameInput.lastSlot = s.no;
  onNameInput.lastAt = Date.now();
}

// ---------------------------------------------------------------- icons
async function uploadPng(canvas, kind) {
  const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
  return api("POST", "/api/projects/" + state.project.id + "/assets?kind=" + kind, blob);
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片打不开"));
    img.src = url;
  });
}

const crop = { img: null, scale: 1, base: 1, ox: 0, oy: 0, drag: null };

function cropClamp() {
  const c = $("cropCanvas");
  const w = crop.img.naturalWidth * crop.scale, h = crop.img.naturalHeight * crop.scale;
  crop.ox = Math.min(0, Math.max(c.width - w, crop.ox));
  crop.oy = Math.min(0, Math.max(c.height - h, crop.oy));
}

function cropRect() {
  const c = $("cropCanvas");
  return { sx: -crop.ox / crop.scale, sy: -crop.oy / crop.scale, sw: c.width / crop.scale, sh: c.height / crop.scale };
}

function drawIcon(target, r) {
  // stepped downscale for a cleaner 38×36 result
  const mid = document.createElement("canvas");
  mid.width = VIS.w * 4; mid.height = VIS.h * 4;
  const m = mid.getContext("2d");
  m.imageSmoothingQuality = "high";
  m.drawImage(crop.img, r.sx, r.sy, r.sw, r.sh, 0, 0, mid.width, mid.height);
  const t = target.getContext("2d");
  t.clearRect(0, 0, 40, 40);
  // the visible area must be fully opaque (factory contract: alpha 255 inside, 0 outside)
  t.fillStyle = "#000000";
  t.fillRect(VIS.x, VIS.y, VIS.w, VIS.h);
  t.imageSmoothingQuality = "high";
  t.drawImage(mid, 0, 0, mid.width, mid.height, VIS.x, VIS.y, VIS.w, VIS.h);
}

function cropRender() {
  const c = $("cropCanvas"), g = c.getContext("2d");
  g.clearRect(0, 0, c.width, c.height);
  g.imageSmoothingQuality = "high";
  g.drawImage(crop.img, crop.ox, crop.oy, crop.img.naturalWidth * crop.scale, crop.img.naturalHeight * crop.scale);
  const p1 = $("cropPreview1");
  drawIcon(p1, cropRect());
  const p4 = $("cropPreview4").getContext("2d");
  p4.imageSmoothingEnabled = false;
  p4.clearRect(0, 0, 160, 160);
  p4.drawImage(p1, 0, 0, 160, 160);
}

async function startCrop(file) {
  try { crop.img = await loadImage(file); } catch (e) { toast(e.message, true); return; }
  const c = $("cropCanvas");
  crop.base = Math.max(c.width / crop.img.naturalWidth, c.height / crop.img.naturalHeight);
  crop.scale = crop.base;
  $("cropZoom").value = "1";
  crop.ox = (c.width - crop.img.naturalWidth * crop.scale) / 2;
  crop.oy = (c.height - crop.img.naturalHeight * crop.scale) / 2;
  cropRender();
  $("cropDialog").showModal();
}

function zoomTo(z, cx, cy) {
  const c = $("cropCanvas");
  cx = cx === undefined ? c.width / 2 : cx;
  cy = cy === undefined ? c.height / 2 : cy;
  const next = crop.base * Math.min(8, Math.max(1, z));
  crop.ox = cx - (cx - crop.ox) * (next / crop.scale);
  crop.oy = cy - (cy - crop.oy) * (next / crop.scale);
  crop.scale = next;
  $("cropZoom").value = String(next / crop.base);
  cropClamp();
  cropRender();
}

async function applyCrop() {
  const s = slotOf(state.sel);
  const btn = $("cropApply");
  btn.disabled = true;
  try {
    const src = document.createElement("canvas");
    const k = Math.min(1, 1600 / Math.max(crop.img.naturalWidth, crop.img.naturalHeight));
    src.width = Math.round(crop.img.naturalWidth * k);
    src.height = Math.round(crop.img.naturalHeight * k);
    src.getContext("2d").drawImage(crop.img, 0, 0, src.width, src.height);
    const source = await uploadPng(src, "source");
    const icon = await uploadPng($("cropPreview1"), "icon");
    const r = cropRect();
    state.revealAsset = icon.asset;
    setEdit(s.no, "icon", {
      asset: icon.asset, source: source.asset, style: "image",
      crop: { sx: r.sx * k, sy: r.sy * k, sw: r.sw * k, sh: r.sh * k },
    });
    $("cropDialog").close();
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

function drawFactory(canvas, text) {
  const g = canvas.getContext("2d");
  g.clearRect(0, 0, 40, 40);
  g.fillStyle = "#808080";
  g.fillRect(VIS.x, VIS.y, VIS.w, VIS.h);
  g.fillStyle = "#353536";
  g.fillRect(VIS.x + 1, VIS.y + 1, VIS.w - 2, VIS.h - 2);
  g.fillStyle = "#FFFFFF";
  g.textAlign = "center";
  g.textBaseline = "middle";
  let size = 18;
  do {
    g.font = "bold " + size + "px 'Helvetica Neue', Helvetica, Arial, sans-serif";
    size -= 1;
  } while (size > 7 && g.measureText(text).width > VIS.w - 6);
  g.fillText(text, 20, VIS.y + VIS.h / 2 + 1);
}

function factoryRender() {
  const text = $("factoryText").value;
  drawFactory($("factoryPreview1"), text);
  const p4 = $("factoryPreview4").getContext("2d");
  p4.imageSmoothingEnabled = false;
  p4.clearRect(0, 0, 160, 160);
  p4.drawImage($("factoryPreview1"), 0, 0, 160, 160);
}

async function applyFactory() {
  const s = slotOf(state.sel);
  const text = $("factoryText").value.trim();
  if (!text || !/^[\x20-\x7e]{1,5}$/.test(text)) { toast("请输入 1–5 个英文字母、数字或符号", true); return; }
  try {
    const icon = await uploadPng($("factoryPreview1"), "icon");
    state.revealAsset = icon.asset;
    setEdit(s.no, "icon", { asset: icon.asset, style: "factory", text });
    $("factoryDialog").close();
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- generate
async function generate() {
  const bad = state.template.slots.filter((s) => {
    const e = state.changes[s.no];
    return e && e.name !== undefined && !Names.ok(e.name, s.factory_en.length);
  });
  if (bad.length) { toast(bad.map((s) => s.name).join("、") + " 的预设名没有通过检查", true); return; }
  if (!Object.keys(state.changes).length) { toast("还没有改动", true); return; }
  if (!(state.status.prefs || {}).preflight_seen) { $("preflightDialog").showModal(); return; }
  await saveProject();
  if (state.project.unsaved) return;
  showPending();
  try {
    const manifest = await api("POST", "/api/projects/" + state.project.id + "/generate");
    state.status.builds = (state.status.builds || []).concat([{ build_id: manifest.build_id, project_id: manifest.project_id,
      output_sha256: manifest.output_sha256, created_at: manifest.created_at }]);
    showResult(true, manifest);
  } catch (e) {
    showResult(false, { error: e.message, checks: (e.data && e.data.checks) || [] });
  }
}

function showPending() {
  $("doneTag").textContent = "WORKING";
  $("doneTitle").textContent = "正在生成并核对…";
  $("doneText").textContent = "从官方原件重新生成，然后用另一套代码拆开读回、逐项核对。大约需要十几秒。";
  $("doneTable").replaceChildren();
  $("doneChecks").replaceChildren();
  $("doneDownloads").hidden = true;
  show("viewDone");
}

function showResult(ok, data) {
  $("doneTag").textContent = ok ? "DONE" : "NOT YET";
  $("doneTitle").textContent = ok ? "固件已生成" : "还不能生成";
  $("doneText").textContent = ok ? "全部核对通过。下面是这次生成的明细。" : data.error;
  const rows = ok
    ? [["工程", data.project_title], ["改动", data.summary.map((x) => x.preset + " " + x.what + " → " + x.value).join("；")],
       ["版本", "2.10（不变）"], ["SHA-256", data.output_sha256], ["验证", "离线核对通过 · 未实机"]]
    : [["工程", state.project.title], ["模板", state.template.reviewed ? state.template.id : "草稿 · 未复核"]];
  $("doneTable").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { class: k === "SHA-256" ? "mono sha" : "", text: v })]));
  $("doneChecks").replaceChildren(...(data.checks || []).map((c) => el("li", { class: c.ok ? "" : "bad" }, [
    el("span", { class: "mk", text: c.ok ? "✓" : "✕" }), el("span", { text: c.title + (c.detail ? "（" + c.detail + "）" : "") })])));
  const dl = $("doneDownloads");
  dl.hidden = !ok;
  if (ok) {
    $("dlFirmware").href = "/api/builds/" + data.build_id + "/firmware";
    $("dlManifest").href = "/api/builds/" + data.build_id + "/manifest";
  }
  show("viewDone");
}

// ---------------------------------------------------------------- wire up
function wire() {
  const drop = $("drop");
  $("fileInput").addEventListener("change", (e) => e.target.files[0] && importFile(e.target.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer.files[0]) importFile(e.dataTransfer.files[0]);
  });
  $("cameraChip").addEventListener("click", () => { show("viewStart"); });
  $("nameInput").addEventListener("input", onNameInput);
  $("btnNameReset").addEventListener("click", () => setEdit(state.sel, "name", undefined));
  $("btnUpload").addEventListener("click", () => $("imageInput").click());
  $("imageInput").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) startCrop(f); });
  $("btnIconReset").addEventListener("click", () => setEdit(state.sel, "icon", undefined));
  $("btnFactoryStyle").addEventListener("click", () => {
    const s = slotOf(state.sel);
    const e = (state.changes[s.no] || {}).icon;
    $("factoryText").value = e && e.style === "factory" ? e.text : s.abbr;
    factoryRender();
    $("factoryDialog").showModal();
  });
  $("factoryText").addEventListener("input", factoryRender);
  $("factoryCancel").addEventListener("click", () => $("factoryDialog").close());
  $("factoryApply").addEventListener("click", applyFactory);

  const cc = $("cropCanvas");
  cc.addEventListener("pointerdown", (e) => { crop.drag = { x: e.clientX, y: e.clientY, ox: crop.ox, oy: crop.oy }; cc.setPointerCapture(e.pointerId); });
  cc.addEventListener("pointermove", (e) => {
    if (!crop.drag) return;
    const k = cc.width / cc.getBoundingClientRect().width;
    crop.ox = crop.drag.ox + (e.clientX - crop.drag.x) * k;
    crop.oy = crop.drag.oy + (e.clientY - crop.drag.y) * k;
    cropClamp(); cropRender();
  });
  cc.addEventListener("pointerup", () => { crop.drag = null; });
  cc.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = cc.getBoundingClientRect(), k = cc.width / rect.width;
    zoomTo((crop.scale / crop.base) * (e.deltaY < 0 ? 1.08 : 1 / 1.08), (e.clientX - rect.left) * k, (e.clientY - rect.top) * k);
  }, { passive: false });
  $("cropZoom").addEventListener("input", (e) => zoomTo(parseFloat(e.target.value)));
  $("cropCancel").addEventListener("click", () => $("cropDialog").close());
  $("cropApply").addEventListener("click", applyCrop);

  $("btnSave").addEventListener("click", saveProject);
  $("btnGenerate").addEventListener("click", generate);
  $("preflightCancel").addEventListener("click", () => $("preflightDialog").close());
  $("preflightOk").addEventListener("click", async () => {
    $("preflightDialog").close();
    try { state.status.prefs = await api("POST", "/api/prefs", { key: "preflight_seen", value: true }); } catch (e) { toast(e.message, true); return; }
    generate();
  });
  $("btnBack").addEventListener("click", () => show("viewWork"));
  $("projectTitle").addEventListener("change", async (e) => {
    try { state.project = await api("PATCH", "/api/projects/" + state.project.id, { title: e.target.value }); } catch (err) { toast(err.message, true); }
  });
  for (const id of ["rescueLink", "rescueLink2"]) {
    $(id).addEventListener("click", (e) => { e.preventDefault(); show("viewRescue"); window.scrollTo(0, 0); });
  }
  $("rescueBack").addEventListener("click", () => show(show.previous || "viewStart"));
  const rd = $("rescueDrop");
  $("rescueInput").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) checkRescue(f); });
  rd.addEventListener("dragover", (e) => { e.preventDefault(); rd.classList.add("over"); });
  rd.addEventListener("dragleave", () => rd.classList.remove("over"));
  rd.addEventListener("drop", (e) => { e.preventDefault(); rd.classList.remove("over"); if (e.dataTransfer.files[0]) checkRescue(e.dataTransfer.files[0]); });
  $("btnSettings").addEventListener("click", () => {
    $("appVersion").textContent = "v" + state.status.version;
    $("dataRoot").textContent = state.status.data_root;
    $("settingsDialog").showModal();
  });
  $("settingsClose").addEventListener("click", () => $("settingsDialog").close());
  $("btnOpenRescue").addEventListener("click", () => { $("settingsDialog").close(); show("viewRescue"); window.scrollTo(0, 0); });
  $("btnGuideReset").addEventListener("click", async () => {
    for (const k of ["guide_off", "guide_start_seen", "guide_work_seen"]) await setPref(k, false);
    $("settingsDialog").close();
    toast("指引已重新打开");
    maybeGuide($("viewWork").hidden ? "start" : "work");
  });
  $("btnQuit").addEventListener("click", quitApp);
  $("btnBuilds").addEventListener("click", openBuilds);
  $("buildsClose").addEventListener("click", () => $("buildsDialog").close());

  document.addEventListener("keydown", (e) => {
    if ($("viewWork").hidden) return;
    const mod = e.metaKey || e.ctrlKey;
    if (!mod) return;
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
    if (e.key.toLowerCase() === "s") { e.preventDefault(); saveProject(); }
    else if (e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  });
  window.addEventListener("beforeunload", () => { if (state.project) pushDraft(); });
}

async function quitApp() {
  const btn = $("btnQuit");
  btn.disabled = true;
  try {
    if (state.project) {
      clearTimeout(state.saveTimer);
      await api("PUT", "/api/projects/" + state.project.id + "/draft", { changes: state.changes });
    }
    await api("POST", "/api/quit");
  } catch (e) {
    btn.disabled = false;
    toast("退出失败：" + e.message, true);
    return;
  }
  state.project = null; // stop the beforeunload draft push
  $("settingsDialog").close();
  window.DarkslideGuide.hideArrow();
  $("cameraChip").hidden = true;
  $("btnSettings").hidden = true;
  show("viewQuit");
}

async function checkRescue(file) {
  const out = $("rescueResult");
  out.className = "import-result small dim";
  out.textContent = "正在核对 " + file.name + " …";
  try {
    const buf = await file.arrayBuffer();
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", buf))).map((b) => b.toString(16).padStart(2, "0")).join("");
    const official = state.template.official_inputs[0];
    if (digest === official.sha256 && file.name === official.filename) {
      out.className = "import-result small ok";
      out.textContent = "✓ 是官方 GR III 2.10 原件，可以做救机卡。SHA " + digest.slice(0, 8) + "…" + digest.slice(-8);
    } else if (digest === official.sha256) {
      out.className = "import-result small bad";
      out.textContent = "✕ 内容是官方原件，但文件名必须是 fwdc239b.bin，相机才认得";
    } else {
      out.className = "import-result small bad";
      out.textContent = "✕ 不是官方 GR III 2.10 原件，不能当救机卡用";
    }
  } catch (e) {
    out.className = "import-result small bad";
    out.textContent = "✕ " + e.message;
  }
}

function openBuilds() {
  const mine = (state.status.builds || []).filter((b) => b.project_id === state.project.id).slice().reverse();
  $("buildList").replaceChildren(...(mine.length ? mine.map((b) => el("div", { class: "build-row" }, [
    el("div", { class: "txt" }, [el("span", { text: b.created_at.slice(0, 16).replace("T", " ") }), el("span", { class: "mono xsmall dim", text: "SHA " + b.output_sha256.slice(0, 8) + "…" + b.output_sha256.slice(-8) })]),
    el("a", { class: "btn", href: "/api/builds/" + b.build_id + "/firmware", download: "fwdc239b.bin", text: "固件" }),
    el("a", { class: "btn ghost", href: "/api/builds/" + b.build_id + "/manifest", text: "清单" }),
  ])) : [el("div", { class: "empty", text: "这个工程还没有生成过。" })]));
  $("buildsDialog").showModal();
}

async function init() {
  wire();
  renderModels();
  try {
    state.status = await api("GET", "/api/status");
    state.template = state.status.template;
    maybeGuide("start");
  } catch (e) {
    $("importResult").textContent = "✕ 本地服务没有响应：" + e.message;
  }
}

init();
