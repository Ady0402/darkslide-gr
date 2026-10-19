// Interface language: 繁體中文 / 简体中文 / English.
// The page is written in Simplified Chinese; this file rewrites what is on screen —
// static markup, text the scripts build later, server messages, tooltips — by
// watching the document. Data comes from i18n-data.js (built by tools/i18n_build.py).
// Lookups: exact string, then a source string with %s/%d/{0} slots as a pattern,
// then known strings as fragments, then (繁體) a per-character map.
(function () {
  "use strict";
  const DATA = window.DarkslideI18nData || { en: {}, hant: { strings: {}, chars: {} } };
  const LANGS = [
    { code: "zh-Hans", label: "简体中文", short: "简" },
    { code: "zh-Hant", label: "繁體中文", short: "繁" },
    { code: "en", label: "English", short: "EN" },
  ];
  const KEY = "darkslide.uiLang";
  const CJK = /[㐀-鿿]/;
  const SLOT = /%(?:\([^)]*\))?[-+ #0]*\d*(?:\.\d+)?[sdifr]|\{\d+\}/g;
  const ATTRS = ["title", "aria-label", "placeholder", "alt"];
  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "NOSCRIPT"]);

  // Until the visitor picks one, the page follows the browser's language.
  function saved() {
    try {
      const value = localStorage.getItem(KEY);
      return LANGS.some((l) => l.code === value) ? value : null;
    } catch (e) { return null; }  // storage blocked: follow the browser
  }

  function fromBrowser() {
    for (const tag of navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ""]) {
      const t = tag.toLowerCase();
      if (/^zh-(tw|hk|mo)\b|hant/.test(t)) return "zh-Hant";
      if (t.startsWith("zh")) return "zh-Hans";
      if (t.startsWith("en")) return "en";
    }
    return "en";
  }

  function initial() { return saved() || fromBrowser(); }

  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  function compile(dict) {
    const exact = new Map(), patterns = [], frags = [];
    for (const [k, v] of Object.entries(dict)) {
      if (!v || v === k) continue;
      exact.set(k, v);
      const slots = k.match(SLOT);
      if (slots) {
        const parts = k.split(SLOT).map(escapeRe);
        if (parts.join("").length < 2) continue;  // a pattern of slots only would match anything
        patterns.push({ re: new RegExp("^" + parts.join("(.+?)") + "$"), slots, value: v });
      } else {
        frags.push(k);  // longest first, so single characters only fill what is left
      }
    }
    patterns.sort((a, b) => b.re.source.length - a.re.source.length);
    frags.sort((a, b) => b.length - a.length);
    const fragRe = frags.length ? new RegExp(frags.map(escapeRe).join("|"), "g") : null;
    return { exact, patterns, fragRe };
  }

  const TABLES = { en: compile(DATA.en || {}), "zh-Hant": compile((DATA.hant || {}).strings || {}) };
  const CHARS = (DATA.hant || {}).chars || {};
  let lang = initial();
  let cache = new Map();

  function fill(value, slots, args) {
    // %-style slots are positional; {n} slots are by index.
    let i = 0;
    return value.replace(SLOT, (s) => {
      const m = /^\{(\d+)\}$/.exec(s);
      const at = m ? slots.indexOf(s) : i++;
      return at >= 0 && at < args.length ? args[at] : s;
    });
  }

  function core(text, t, depth) {
    if (t.exact.has(text)) return t.exact.get(text);
    if (depth < 3) {
      for (const p of t.patterns) {
        const m = p.re.exec(text);
        if (m) return fill(p.value, p.slots, m.slice(1).map((a) => translate(a, depth + 1)));
      }
    }
    let out = t.fragRe ? text.replace(t.fragRe, (f) => t.exact.get(f)) : text;
    if (lang === "en") out = out.replace(/([㐀-鿿])([A-Za-z])/g, "$1 $2").replace(/([A-Za-z.,])([㐀-鿿])/g, "$1 $2");
    return out;
  }

  function translate(text, depth) {
    if (lang === "zh-Hans" || !text || !CJK.test(text)) return text;
    const key = lang + "\u0000" + text;
    if (cache.has(key)) return cache.get(key);
    const lead = text.match(/^\s*/)[0], trail = text.match(/\s*$/)[0];
    const body = text.trim().replace(/\s+/g, " ");
    let out = core(body, TABLES[lang], depth || 0);
    if (lang === "zh-Hant") out = out.replace(/[㐀-鿿]/g, (c) => CHARS[c] || c);
    out = lead + out + trail;
    if (cache.size > 5000) cache = new Map();
    cache.set(key, out);
    return out;
  }

  // --- the document -------------------------------------------------------
  const textOrig = new WeakMap();   // text node -> { orig, shown }
  const attrOrig = new WeakMap();   // element -> { [attr]: { orig, shown } }

  function skipped(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (SKIP.has(e.tagName) || e.isContentEditable || e.getAttribute("translate") === "no") return true;
    }
    return false;
  }

  function doText(node) {
    const now = node.nodeValue;
    let rec = textOrig.get(node);
    if (!rec || now !== rec.shown) {   // new, or the page wrote new text
      if (!CJK.test(now) && !rec) return;
      rec = { orig: now, shown: now };
      textOrig.set(node, rec);
    }
    const want = translate(rec.orig);
    if (want !== now) node.nodeValue = want;
    rec.shown = want;
  }

  function doAttrs(el) {
    let recs = attrOrig.get(el);
    for (const a of ATTRS) {
      const now = el.getAttribute(a);
      if (now === null) continue;
      if (!recs) { recs = {}; attrOrig.set(el, recs); }
      let rec = recs[a];
      if (!rec || now !== rec.shown) {
        if (!CJK.test(now) && !rec) continue;
        rec = recs[a] = { orig: now, shown: now };
      }
      const want = translate(rec.orig);
      if (want !== now) el.setAttribute(a, want);
      rec.shown = want;
    }
  }

  function walk(root) {
    if (root.nodeType === 3) { if (!skipped(root.parentElement)) doText(root); return; }
    if (root.nodeType !== 1 || skipped(root)) return;
    doAttrs(root);
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => n.nodeType === 1 && (SKIP.has(n.tagName) || n.getAttribute("translate") === "no")
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      if (n.nodeType === 3) doText(n); else doAttrs(n);
    }
  }

  let titleOrig = null;
  function applyAll() {
    document.documentElement.lang = lang;
    document.documentElement.dataset.uiLang = lang;
    if (titleOrig === null) titleOrig = document.title;
    document.title = translate(titleOrig);
    walk(document.body);
  }

  const observer = new MutationObserver((list) => {
    for (const m of list) {
      if (m.type === "characterData") { if (!skipped(m.target.parentElement)) doText(m.target); }
      else if (m.type === "attributes") { if (!skipped(m.target)) doAttrs(m.target); }
      else for (const n of m.addedNodes) walk(n);
    }
  });

  // Native dialogs carry text too.
  for (const name of ["alert", "confirm", "prompt"]) {
    const native = window[name].bind(window);
    window[name] = (msg, ...rest) => native(translate(String(msg)), ...rest);
  }

  function setLang(code, remember = true) {
    if (!LANGS.some((l) => l.code === code)) return;
    if (remember) {
      try { localStorage.setItem(KEY, code); } catch (e) { /* not remembered, still applied */ }
    }
    if (code === lang) return;
    lang = code;
    applyAll();
    renderSwitch();
    document.dispatchEvent(new CustomEvent("darkslide:lang", { detail: code }));
  }

  // --- the switch in the header ------------------------------------------
  function renderSwitch() {
    const box = document.getElementById("uiLang");
    if (!box) return;
    for (const b of box.querySelectorAll("button")) {
      const on = b.dataset.lang === lang;
      b.classList.toggle("on", on);
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    }
  }

  function buildSwitch() {
    const top = document.querySelector("header.top");
    if (!top || document.getElementById("uiLang")) return;
    const box = document.createElement("div");
    box.id = "uiLang";
    box.className = "ui-lang";
    box.setAttribute("role", "radiogroup");
    box.setAttribute("aria-label", "Language / 語言 / 语言");
    box.setAttribute("translate", "no");
    for (const l of LANGS) {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.lang = l.code;
      b.setAttribute("role", "radio");
      b.setAttribute("lang", l.code);
      b.title = l.label;
      b.textContent = l.short;
      b.addEventListener("click", () => setLang(l.code));
      box.appendChild(b);
    }
    box.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      const list = [...box.querySelectorAll("button")];
      const next = list[(list.findIndex((b) => b.dataset.lang === lang) + step + list.length) % list.length];
      setLang(next.dataset.lang);
      next.focus();
    });
    const settings = document.getElementById("btnSettings");
    top.insertBefore(box, settings && settings.parentElement === top ? settings : null);
    renderSwitch();
  }

  window.addEventListener("languagechange", () => { if (!saved()) setLang(fromBrowser(), false); });

  window.DarkslideI18n = { t: (s) => translate(s), lang: () => lang, set: setLang };

  function start() {
    buildSwitch();
    applyAll();
    observer.observe(document.body, {
      subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS,
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
