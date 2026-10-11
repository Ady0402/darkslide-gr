"use strict";
// Baseline JPEG encoder for the shutdown image.
// Output matches the camera's own shutdown JPEGs: baseline (SOF0), 3 components,
// Y 2x2 + Cb/Cr 1x1 (4:2:0), JFIF APP0 only, two DQT, four DHT, no restart markers,
// no EXIF/ICC. Standard (Annex K) quantization and Huffman tables.
(function (root) {
  const ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
  ];
  const STD_LUMA = [
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
  ];
  const STD_CHROMA = [
    17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
  ];
  // Annex K Huffman specs: counts for lengths 1..16, then symbols.
  const DC_LUMA = [[0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0], [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]];
  const DC_CHROMA = [[0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0], [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]];
  const AC_LUMA = [[0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d], [
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
    0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
    0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
    0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
    0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
    0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
    0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
    0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
    0xf9, 0xfa,
  ]];
  const AC_CHROMA = [[0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77], [
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
    0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
    0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
    0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
    0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
    0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
    0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
    0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
    0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
    0xf9, 0xfa,
  ]];

  function buildCodes(spec) {
    const [counts, symbols] = spec;
    const codes = new Array(256);
    let code = 0, k = 0;
    for (let len = 1; len <= 16; len++) {
      for (let i = 0; i < counts[len - 1]; i++) codes[symbols[k++]] = [code++, len];
      code <<= 1;
    }
    return codes;
  }
  const CODES = {
    dcL: buildCodes(DC_LUMA), acL: buildCodes(AC_LUMA),
    dcC: buildCodes(DC_CHROMA), acC: buildCodes(AC_CHROMA),
  };

  function scaleTable(base, quality) {
    const q = Math.min(100, Math.max(1, Math.round(quality)));
    const s = q < 50 ? 5000 / q : 200 - q * 2;
    return base.map((v) => Math.min(255, Math.max(1, Math.floor((v * s + 50) / 100))));
  }

  // separable float DCT-II with orthonormal scaling (matches JPEG's 1/4 C(u)C(v) form)
  const COS = new Float64Array(64);
  for (let x = 0; x < 8; x++) for (let u = 0; u < 8; u++) {
    COS[x * 8 + u] = Math.cos(((2 * x + 1) * u * Math.PI) / 16) * (u === 0 ? Math.SQRT1_2 : 1) / 2;
  }
  const tmp = new Float64Array(64);
  function fdct(block, out) {
    for (let y = 0; y < 8; y++) for (let u = 0; u < 8; u++) {
      let s = 0;
      for (let x = 0; x < 8; x++) s += block[y * 8 + x] * COS[x * 8 + u];
      tmp[y * 8 + u] = s;
    }
    for (let u = 0; u < 8; u++) for (let v = 0; v < 8; v++) {
      let s = 0;
      for (let y = 0; y < 8; y++) s += tmp[y * 8 + u] * COS[y * 8 + v];
      out[v * 8 + u] = s;
    }
  }

  class BitWriter {
    constructor() { this.bytes = []; this.acc = 0; this.n = 0; }
    put(code, len) {
      for (let i = len - 1; i >= 0; i--) {
        this.acc = (this.acc << 1) | ((code >> i) & 1);
        if (++this.n === 8) { this.byte(this.acc); this.acc = 0; this.n = 0; }
      }
    }
    byte(b) { this.bytes.push(b); if (b === 0xff) this.bytes.push(0); }
    flush() { while (this.n !== 0) this.put(1, 1); }
  }

  function magnitude(v) {
    let a = v < 0 ? -v : v, n = 0;
    while (a) { n++; a >>= 1; }
    return n;
  }

  function encodeBlock(bw, coef, q, prevDc, dcCodes, acCodes) {
    const zz = new Int32Array(64);
    for (let i = 0; i < 64; i++) zz[i] = Math.round(coef[ZIGZAG[i]] / q[ZIGZAG[i]]);
    const diff = zz[0] - prevDc;
    const dn = magnitude(diff);
    bw.put(...dcCodes[dn]);
    if (dn) bw.put(diff < 0 ? diff + (1 << dn) - 1 : diff, dn);
    let run = 0;
    for (let i = 1; i < 64; i++) {
      const v = zz[i];
      if (v === 0) { run++; continue; }
      while (run > 15) { bw.put(...acCodes[0xf0]); run -= 16; }
      const n = magnitude(v);
      bw.put(...acCodes[(run << 4) | n]);
      bw.put(v < 0 ? v + (1 << n) - 1 : v, n);
      run = 0;
    }
    if (run) bw.put(...acCodes[0x00]);
    return zz[0];
  }

  function segment(marker, payload) {
    const len = payload.length + 2;
    return [0xff, marker, len >> 8, len & 0xff, ...payload];
  }

  // rgba: Uint8ClampedArray (width*height*4). Returns Uint8Array.
  function encode(rgba, width, height, quality) {
    const qL = scaleTable(STD_LUMA, quality), qC = scaleTable(STD_CHROMA, quality);
    const head = [0xff, 0xd8];
    head.push(...segment(0xe0, [0x4a, 0x46, 0x49, 0x46, 0x00, 1, 1, 0, 0, 1, 0, 1, 0, 0]));
    head.push(...segment(0xdb, [0x00, ...ZIGZAG.map((i) => qL[i])]));
    head.push(...segment(0xdb, [0x01, ...ZIGZAG.map((i) => qC[i])]));
    head.push(...segment(0xc0, [8, height >> 8, height & 0xff, width >> 8, width & 0xff, 3,
      1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]));
    for (const [cls, spec] of [[0x00, DC_LUMA], [0x10, AC_LUMA], [0x01, DC_CHROMA], [0x11, AC_CHROMA]]) {
      head.push(...segment(0xc4, [cls, ...spec[0], ...spec[1]]));
    }
    head.push(...segment(0xda, [3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0]));

    const W = width, H = height;
    const Y = new Float64Array(W * H), Cb = new Float64Array(W * H), Cr = new Float64Array(W * H);
    for (let i = 0, p = 0; i < W * H; i++, p += 4) {
      const r = rgba[p], g = rgba[p + 1], b = rgba[p + 2];
      Y[i] = 0.299 * r + 0.587 * g + 0.114 * b - 128;
      Cb[i] = -0.168736 * r - 0.331264 * g + 0.5 * b;
      Cr[i] = 0.5 * r - 0.418688 * g - 0.081312 * b;
    }
    const at = (plane, x, y) => plane[Math.min(H - 1, y) * W + Math.min(W - 1, x)];
    const bw = new BitWriter();
    const block = new Float64Array(64), coef = new Float64Array(64);
    let dcY = 0, dcCb = 0, dcCr = 0;
    for (let my = 0; my < H; my += 16) {
      for (let mx = 0; mx < W; mx += 16) {
        for (const [ox, oy] of [[0, 0], [8, 0], [0, 8], [8, 8]]) {
          for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) block[y * 8 + x] = at(Y, mx + ox + x, my + oy + y);
          fdct(block, coef);
          dcY = encodeBlock(bw, coef, qL, dcY, CODES.dcL, CODES.acL);
        }
        for (const [plane, which] of [[Cb, 0], [Cr, 1]]) {
          for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
            const sx = mx + x * 2, sy = my + y * 2;
            block[y * 8 + x] = (at(plane, sx, sy) + at(plane, sx + 1, sy) + at(plane, sx, sy + 1) + at(plane, sx + 1, sy + 1)) / 4;
          }
          fdct(block, coef);
          if (which === 0) dcCb = encodeBlock(bw, coef, qC, dcCb, CODES.dcC, CODES.acC);
          else dcCr = encodeBlock(bw, coef, qC, dcCr, CODES.dcC, CODES.acC);
        }
      }
    }
    bw.flush();
    const out = new Uint8Array(head.length + bw.bytes.length + 2);
    out.set(head, 0);
    out.set(bw.bytes, head.length);
    out[out.length - 2] = 0xff; out[out.length - 1] = 0xd9;
    return out;
  }

  // Highest quality (1..max) whose file fits the budget; null if even quality 1 is too big.
  function fit(rgba, width, height, budget, max) {
    let lo = 1, hi = max || 95, best = null;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const data = encode(rgba, width, height, mid);
      if (data.length <= budget) { best = { quality: mid, data }; lo = mid + 1; } else hi = mid - 1;
    }
    return best;
  }

  const api = { encode, fit };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DarkslideJpeg = api;
})(typeof window !== "undefined" ? window : this);
