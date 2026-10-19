"use strict";
// 配方卡: one picture (and the same words as text) of how a look was made — the film and the
// adjustments. Drawn in this tab only.
(function () {
  const $ = (id) => document.getElementById(id);
  const W = 1080, H = 2000, PAD = 72;
  // Card colours; the user picks one under the card (remembered in this browser), 深色 by default.
  const THEMES = {
    dark:  { bg: "#1C1C1B", panel: "#262624", text: "#EDEDEA", soft: "#B9B8B2", dim: "#85847E", line: "#3A3936", box: "#353536" },
    paper: { bg: "#F3F0E8", panel: "#E4E0D6", text: "#1C1C1B", soft: "#4A4945", dim: "#8A877F", line: "#D6D2C8", box: "#D6D2C8" },
    white: { bg: "#FFFFFF", panel: "#EEEEEE", text: "#111111", soft: "#444444", dim: "#8C8C8C", line: "#E2E2E2", box: "#E2E2E2" },
    stone: { bg: "#E6E4DF", panel: "#D6D3CC", text: "#1E1E1C", soft: "#4A4844", dim: "#7E7B74", line: "#CCC9C2", box: "#CCC9C2" },
    cream: { bg: "#F1E9D8", panel: "#E2D8C4", text: "#2A241C", soft: "#54493A", dim: "#8C806C", line: "#DDD2BD", box: "#DDD2BD" },
  };
  const THEME_NAMES = { dark: "深色", paper: "米白", white: "纯白", stone: "石灰", cream: "奶油" };
  const THEME_KEY = "darkslide.recipeTheme";
  // Camera line under the title: plain text only (never the RICOH logo artwork); the user picks
  // whether to name the maker and whether to add the model suffix (remembered in this browser).
  const MODEL = "GR III";
  const MARKS = { model: MODEL, ricoh: "RICOH GR", ricohModel: "RICOH " + MODEL };
  const MARK_KEY = "darkslide.recipeMark";
  function savedMark() { try { const m = localStorage.getItem(MARK_KEY); return MARKS[m] ? m : "model"; } catch (e) { return "model"; } }
  let C = THEMES.dark, last = null, drawing = 0;
  function savedTheme() { try { const t = localStorage.getItem(THEME_KEY); return THEMES[t] ? t : "dark"; } catch (e) { return "dark"; } }
  const FONT = '"PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif';
  let card = null, toast = null;

  // Everything the card says, as plain lines (also what 「复制文字」 copies).
  function content(slot, edit) {
    const F = window.DarkslideFilm, info = F.filmInfo(edit.film);
    const adj = window.DarkslideAdjust.describe(edit.grade);
    const writable = F.SLOTS.includes(slot.no);
    const name = edit.name !== undefined ? edit.name : slot.name;
    const rows = [];
    adj.forEach((a, i) => rows.push([i ? "" : "调整", a.text + (a.lutOnly ? "（仅预览/导出）" : "")]));
    const notes = [];
    if (adj.some((a) => a.lutOnly) && writable) notes.push("标「仅预览/导出」的调整相机做不到，写进相机时会去掉。");
    // The card is titled by the look (the film), not by the preset slot it happens to sit in.
    return { title: info ? info.name : name, sub: MARKS[savedMark()], rows, notes };
  }

  function text(c) {
    const lines = ["DARKSLIDE GR", c.title + "（" + c.sub + "）", ""];
    for (const [k, v] of c.rows) lines.push((k ? k + "：" : "　　") + v);
    if (c.notes.length) lines.push("", ...c.notes);
    return lines.join("\n");
  }

  // Wrap `s` to `width` px; returns the lines.
  function wrap(g, s, width) {
    const out = [];
    let line = "";
    for (const ch of s) {
      if (g.measureText(line + ch).width > width && line) { out.push(line); line = ch.trim() ? ch : ""; }
      else line += ch;
    }
    if (line) out.push(line);
    return out;
  }

  async function draw(slot, edit, iconSrc, theme) {
    C = THEMES[theme] || THEMES.dark;
    const c = content(slot, edit);
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    const g = cv.getContext("2d");
    g.fillStyle = C.bg; g.fillRect(0, 0, W, H);
    g.textBaseline = "alphabetic";
    // brand line
    g.fillStyle = C.text; g.fillRect(PAD, PAD - 18, 18, 18);
    g.font = "600 22px " + FONT; g.letterSpacing = "6px";
    g.fillText("DARKSLIDE GR", PAD + 32, PAD);
    g.letterSpacing = "0px";
    // preset title with its icon
    let y = PAD + 64;
    const icon = iconSrc ? await new Promise((ok) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => ok(null); im.src = iconSrc; }) : null;
    // a 40×40 camera icon is enlarged pixel-sharp; a larger original is scaled down smoothly, in its
    // own proportions and with nothing behind it (no grey edge around it)
    if (icon) {
      const k = 80 / Math.max(icon.naturalWidth, icon.naturalHeight), iw = icon.naturalWidth * k, ih = icon.naturalHeight * k;
      g.imageSmoothingEnabled = icon.naturalWidth > 80; g.imageSmoothingQuality = "high";
      g.drawImage(icon, PAD + (80 - iw) / 2, y + (80 - ih) / 2, iw, ih);
      g.imageSmoothingEnabled = true;
    } else { g.fillStyle = C.box; g.fillRect(PAD, y, 80, 80); g.fillStyle = C.text; g.font = "600 22px " + FONT; g.textAlign = "center"; g.fillText(slot.abbr || "", PAD + 40, y + 48); g.textAlign = "left"; }
    // long film or LUT names shrink to fit the line
    let size = 52;
    g.font = "700 " + size + "px " + FONT;
    while (size > 28 && g.measureText(c.title).width > W - PAD * 2 - 108) g.font = "700 " + (size -= 2) + "px " + FONT;
    g.fillStyle = C.text; g.fillText(c.title, PAD + 108, y + 50);
    g.fillStyle = C.dim; g.font = "24px " + FONT; g.fillText(c.sub, PAD + 108, y + 84);
    // picture
    y += 120;
    // the whole photo in its own proportions, never cropped: a landscape one spans the width, a
    // portrait one is at most 5:4 of the width tall and centred, so the rows below still fit
    const pw = W - 2 * PAD;
    const pic = await window.DarkslideFilm.gradedCanvas(edit);
    let ph = Math.round(pw * 2 / 3);
    if (pic) {
      let dw = pw, dh = pw * pic.height / pic.width;
      if (dh > pw * 5 / 4) { dh = pw * 5 / 4; dw = dh * pic.width / pic.height; }
      dw = Math.round(dw); ph = Math.round(dh);
      g.drawImage(pic, 0, 0, pic.width, pic.height, PAD + Math.round((pw - dw) / 2), y, dw, ph);
    } else { g.fillStyle = C.panel; g.fillRect(PAD, y, pw, ph); }
    y += ph + 56;
    // rows
    const keyW = 140, valW = pw - keyW;
    for (const [k, v] of c.rows) {
      g.font = "26px " + FONT;
      const lines = wrap(g, v, valW);
      if (y + lines.length * 38 > H - 300) break;
      if (k) { g.fillStyle = C.line; g.fillRect(PAD, y - 34, pw, 1); g.fillStyle = C.dim; g.fillText(k, PAD, y); }
      g.fillStyle = k ? C.text : C.soft;
      lines.forEach((l, i) => g.fillText(l, PAD + keyW, y + i * 38));
      y += lines.length * 38 + (k ? 18 : 10);
    }
    // notes right under the rows (attribution lives in the app, the .cube and the docs); the card is as tall as its content
    g.font = "18px " + FONT;
    const foot = c.notes;
    const lines = foot.flatMap((s) => wrap(g, s, pw));
    let fy = y + 14;
    if (lines.length) { g.fillStyle = C.line; g.fillRect(PAD, fy - 34, pw, 1); }
    g.fillStyle = C.dim;
    lines.forEach((l, i) => g.fillText(l, PAD, fy + i * 28));
    const height = Math.min(H, lines.length ? fy + (lines.length - 1) * 28 + PAD : y - 56 + PAD);
    const out = document.createElement("canvas");
    out.width = W; out.height = height;
    out.getContext("2d").drawImage(cv, 0, 0);
    return { canvas: out, content: c };
  }

  function renderMarks() {
    const current = savedMark();
    $("recipeMarks").replaceChildren(...Object.keys(MARKS).map((m) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "recipe-theme"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", m === current ? "true" : "false");
      b.textContent = MARKS[m];
      b.addEventListener("click", () => {
        try { localStorage.setItem(MARK_KEY, m); } catch (e) { /* not remembered */ }
        if (last) open(last.slot, last.edit, last.iconSrc);
      });
      return b;
    }));
  }

  function renderThemes(current) {
    $("recipeThemes").replaceChildren(...Object.keys(THEMES).map((t) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "recipe-theme"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", t === current ? "true" : "false");
      const sw = document.createElement("i"); sw.style.background = THEMES[t].bg;
      b.append(sw, THEME_NAMES[t]);
      b.addEventListener("click", () => {
        try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* not remembered */ }
        if (last) open(last.slot, last.edit, last.iconSrc, t);
      });
      return b;
    }));
  }

  async function open(slot, edit, iconSrc, theme) {
    try {
      theme = THEMES[theme] ? theme : savedTheme();
      last = { slot, edit, iconSrc };
      renderThemes(theme);
      renderMarks();
      if (!$("recipeDialog").open) { $("recipeShow").replaceChildren(); $("recipeDialog").showModal(); }
      const mine = ++drawing;  // quick clicks: only the newest drawing is shown
      const made = await draw(slot, edit, iconSrc, theme);
      if (mine !== drawing) return;
      card = made;
      const img = new Image();
      img.src = card.canvas.toDataURL("image/png");
      img.alt = "配方卡：" + card.content.title;
      $("recipeShow").replaceChildren(img);
    } catch (e) { toast(e.message, true); }
  }

  function save() {
    if (!card) return;
    card.canvas.toBlob((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = ("配方卡_" + card.content.title).replace(/[\\/:*?"<>|\x00-\x1f]/g, "_") + ".png";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }, "image/png");
  }

  async function copy() {
    if (!card) return;
    try { await navigator.clipboard.writeText(text(card.content)); toast("配方文字已复制"); }
    catch (e) { toast("复制失败：" + e.message, true); }
  }

  function wire(toastFn) {
    toast = toastFn;
    $("recipeSave").addEventListener("click", save);
    $("recipeCopy").addEventListener("click", copy);
    $("recipeClose").addEventListener("click", () => $("recipeDialog").close());
  }

  window.DarkslideRecipe = { wire, open, text: (slot, edit) => text(content(slot, edit)) };
})();
