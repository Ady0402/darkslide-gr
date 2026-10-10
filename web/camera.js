"use strict";
// Front-view line illustrations of the supported/planned cameras.
// Drawn from the general proportions only: no logos, no brand marks.

window.DarkslideCamera = (function () {
  const SPECS = {
    "GR III":  { lens: 1.0,  barrel: 0,  grip: 46, dial: 40 },
    "GR IIIx": { lens: 1.12, barrel: 6,  grip: 46, dial: 40 },
    "GR IV":   { lens: 1.0,  barrel: 0,  grip: 50, dial: 44, flat: true },
  };

  function svg(model, uid) {
    const s = SPECS[model] || SPECS["GR III"];
    const id = (k) => k + "-" + uid;
    const cx = 160, cy = 92;
    const r = (v) => (v * s.lens).toFixed(1);
    const knurl = Array.from({ length: 9 }, (_, i) =>
      '<line x1="' + (s.dial + 4 + i * 3.6) + '" y1="23" x2="' + (s.dial + 4 + i * 3.6) + '" y2="33" />').join("");
    return (
      '<svg viewBox="0 0 280 168" width="100%" height="100%" role="img" aria-label="' + model + ' 正面示意图" xmlns="http://www.w3.org/2000/svg">' +
      "<defs>" +
      '<linearGradient id="' + id("body") + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#4A4945"/><stop offset="0.12" stop-color="#3A3936"/><stop offset="1" stop-color="#2B2A28"/></linearGradient>' +
      '<linearGradient id="' + id("top") + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#5A5955"/><stop offset="1" stop-color="#3C3B38"/></linearGradient>' +
      '<radialGradient id="' + id("glass") + '" cx="0.42" cy="0.38" r="0.7">' +
      '<stop offset="0" stop-color="#3B4E7A"/><stop offset="0.45" stop-color="#18213A"/><stop offset="1" stop-color="#07090F"/></radialGradient>' +
      '<radialGradient id="' + id("ring") + '" cx="0.5" cy="0.35" r="0.7">' +
      '<stop offset="0" stop-color="#55544F"/><stop offset="1" stop-color="#2A2927"/></radialGradient>' +
      '<pattern id="' + id("grip") + '" width="4" height="4" patternUnits="userSpaceOnUse">' +
      '<rect width="4" height="4" fill="#2E2D2B"/><circle cx="2" cy="2" r="0.8" fill="#3E3D3A"/></pattern>' +
      "</defs>" +
      // shadow
      '<ellipse cx="140" cy="158" rx="112" ry="5" fill="#000" opacity="0.35"/>' +
      // top controls (seen from the front: shutter and dial on the grip side)
      '<g stroke="#6A6964" stroke-width="1" fill="url(#' + id("top") + ')">' +
      '<rect x="' + s.dial + '" y="21" width="36" height="14" rx="3"/>' +
      '<rect x="92" y="27" width="22" height="7" rx="3"/>' +
      '<rect x="96" y="24" width="14" height="5" rx="2.5" fill="#5F5E5A"/>' +
      '<rect x="124" y="29" width="12" height="5" rx="2"/>' +
      "</g>" +
      '<g stroke="#2E2D2B" stroke-width="0.8" opacity="0.8">' + knurl + "</g>" +
      // body
      '<rect x="18" y="32" width="244" height="120" rx="' + (s.flat ? 12 : 16) + '" fill="url(#' + id("body") + ')" stroke="#5F5E5A" stroke-width="1"/>' +
      '<path d="M34 33.5 H246" stroke="#6E6D68" stroke-width="1" opacity="0.6"/>' +
      // grip
      '<rect x="20" y="40" width="' + s.grip + '" height="106" rx="12" fill="url(#' + id("grip") + ')" stroke="#4A4945" stroke-width="1"/>' +
      // strap lugs
      '<rect x="12" y="62" width="7" height="14" rx="2" fill="#3A3936" stroke="#55544F" stroke-width="0.8"/>' +
      '<rect x="261" y="62" width="7" height="14" rx="2" fill="#3A3936" stroke="#55544F" stroke-width="0.8"/>' +
      // AF assist lamp
      '<circle cx="236" cy="56" r="4.5" fill="#1E1D1B" stroke="#55544F" stroke-width="1"/>' +
      '<circle cx="234.8" cy="54.8" r="1.4" fill="#6A6964" opacity="0.7"/>' +
      // lens: cap ring, barrel, rings, glass
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r(46) + '" fill="#252422" stroke="#55544F" stroke-width="1"/>' +
      (s.barrel ? '<circle cx="' + cx + '" cy="' + cy + '" r="' + r(43) + '" fill="none" stroke="#6A6964" stroke-width="' + s.barrel / 2 + '" opacity="0.6"/>' : "") +
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r(39) + '" fill="url(#' + id("ring") + ')" stroke="#6A6964" stroke-width="1"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r(30) + '" fill="#141413" stroke="#4A4945" stroke-width="1.2"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r(26) + '" fill="none" stroke="#2E2D2B" stroke-width="2" stroke-dasharray="1.2 2.2"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="' + r(20) + '" fill="url(#' + id("glass") + ')" stroke="#0A0A0A" stroke-width="1.5"/>' +
      '<ellipse cx="' + (cx - 7 * s.lens).toFixed(1) + '" cy="' + (cy - 8 * s.lens).toFixed(1) + '" rx="' + r(6) + '" ry="' + r(3.4) + '" fill="#FFFFFF" opacity="0.22" transform="rotate(-30 ' + (cx - 7) + " " + (cy - 8) + ')"/>' +
      '<circle cx="' + (cx + 8 * s.lens).toFixed(1) + '" cy="' + (cy + 9 * s.lens).toFixed(1) + '" r="' + r(2) + '" fill="#7C8FC0" opacity="0.25"/>' +
      "</svg>"
    );
  }

  return { svg };
})();
