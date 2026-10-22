"use strict";
// Deterministic JPEG decoder (pure JS, integer arithmetic only).
// Why: browsers decode the same JPEG to slightly different pixels (libjpeg-turbo vs
// macOS ImageIO), which made generated firmware differ per platform. Every step here
// (Huffman, IDCT, upsampling, colour conversion) is defined by JS integer math, so the
// RGBA output is identical in every browser on every CPU.
// Supports: baseline / extended sequential (SOF0/1) and progressive (SOF2) Huffman, 8-bit,
// grayscale or 3-component (YCbCr, or RGB when Adobe transform=0), any sampling factors
// with integer ratios, restart intervals, 8/16-bit DQT. Throws on anything else
// (arithmetic, lossless, hierarchical, 12-bit, CMYK/YCCK) so the caller can fall back.
// EXIF orientation is reported but NOT applied.
// IDCT: 8x8 integer "islow"-style Loeffler-Ligtenberg-Moschytz with 13-bit constants.
// Upsampling: 2x axes use a centered triangle filter (3/4 near + 1/4 far, integer, edges
// clamped); other integer ratios replicate. Colour: JFIF full range, 16-bit fixed point.
(function (root) {
  const ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
  ];
  // IDCT constants: round(x * 2^13).
  const F_0_298 = 2446, F_0_390 = 3196, F_0_541 = 4433, F_0_765 = 6270, F_0_899 = 7373;
  const F_1_175 = 9633, F_1_501 = 12299, F_1_847 = 15137, F_1_961 = 16069;
  const F_2_053 = 16819, F_2_562 = 20995, F_3_072 = 25172;
  // Larger pictures go to the browser: a 4:4:4 picture this size already needs ~1 GB here.
  const MAX_PIXELS = 64 * 1000 * 1000;

  function fail(msg) { throw new Error("JPEG decode: " + msg); }

  // Canonical Huffman table with a 9-bit fast lookup and a slow path for longer codes.
  function buildHuff(counts, vals) {
    const fast = new Uint16Array(512);
    const maxcode = new Int32Array(18), mincode = new Int32Array(18), valptr = new Int32Array(18);
    let code = 0, k = 0;
    for (let l = 1; l <= 16; l++) {
      valptr[l] = k;
      mincode[l] = code;
      const n = counts[l - 1];
      if (code + n > (1 << l)) fail("bad Huffman table");
      if (l <= 9) {
        for (let i = 0; i < n; i++) {
          const lo = (code + i) << (9 - l), cnt = 1 << (9 - l);
          for (let j = 0; j < cnt; j++) fast[lo + j] = (l << 8) | vals[k + i];
        }
      }
      code += n;
      k += n;
      maxcode[l] = n ? code - 1 : -1;
      code <<= 1;
    }
    return { fast, maxcode, mincode, valptr, vals };
  }

  function parseExifOrientation(d, p, end) {
    // p points at "Exif\0\0"; the TIFF header follows.
    const t = p + 6;
    if (end - t < 8) return 1;
    const le = d[t] === 0x49 && d[t + 1] === 0x49;
    if (!le && !(d[t] === 0x4d && d[t + 1] === 0x4d)) return 1;
    const u16 = (o) => le ? d[o] | (d[o + 1] << 8) : (d[o] << 8) | d[o + 1];
    const u32 = (o) => (le ? (d[o] | (d[o + 1] << 8) | (d[o + 2] << 16) | (d[o + 3] << 24))
      : ((d[o] << 24) | (d[o + 1] << 16) | (d[o + 2] << 8) | d[o + 3])) >>> 0;
    if (u16(t + 2) !== 42) return 1;
    const ifd = t + u32(t + 4);
    if (ifd + 2 > end) return 1;
    const n = u16(ifd);
    for (let i = 0; i < n; i++) {
      const e = ifd + 2 + i * 12;
      if (e + 12 > end) return 1;
      if (u16(e) === 0x0112) {
        const v = u16(e + 8);
        return v >= 1 && v <= 8 ? v : 1;
      }
    }
    return 1;
  }

  function decode(bytes) {
    if (!(bytes instanceof Uint8Array)) fail("input must be a Uint8Array");
    const data = bytes, len = data.length;
    if (len < 4 || data[0] !== 0xff || data[1] !== 0xd8) fail("not a JPEG");

    const qts = [null, null, null, null];
    const dcTbls = [null, null, null, null], acTbls = [null, null, null, null];
    let frame = null, restartInterval = 0, orientation = 1, adobeTransform = -1, sawScan = false;
    let pos = 2;

    // ---- entropy decoder state ----
    let bitBuf = 0, bitCnt = 0, hitMarker = false, eobrun = 0;

    function readByte() {
      if (hitMarker) return 0;
      if (pos >= len) fail("truncated data");
      const b = data[pos];
      if (b !== 0xff) { pos++; return b; }
      let p = pos + 1;
      while (p < len && data[p] === 0xff) p++; // fill bytes
      if (p >= len) fail("truncated data");
      if (data[p] === 0) { pos = p + 1; return 0xff; } // stuffed byte
      pos = p - 1; // leave pos on the 0xFF of the marker
      hitMarker = true;
      return 0;
    }
    function fill() {
      while (bitCnt <= 24) { bitBuf = (bitBuf << 8) | readByte(); bitCnt += 8; }
    }
    function receive(n) {
      if (n === 0) return 0;
      if (bitCnt < n) fill();
      bitCnt -= n;
      return (bitBuf >>> bitCnt) & ((1 << n) - 1);
    }
    function bit() {
      if (bitCnt < 1) fill();
      bitCnt--;
      return (bitBuf >>> bitCnt) & 1;
    }
    function huff(t) {
      if (bitCnt < 16) fill();
      const look = t.fast[(bitBuf >>> (bitCnt - 9)) & 511];
      if (look) { bitCnt -= look >> 8; return look & 255; }
      const peek = (bitBuf >>> (bitCnt - 16)) & 0xffff;
      for (let l = 10; l <= 16; l++) {
        const code = peek >> (16 - l);
        if (code <= t.maxcode[l]) {
          bitCnt -= l;
          return t.vals[t.valptr[l] + code - t.mincode[l]];
        }
      }
      return fail("bad Huffman code");
    }
    function extend(v, s) { return v < (1 << (s - 1)) ? v - (1 << s) + 1 : v; }

    // ---- per-scan block decoders (coefficients stay quantized, natural order) ----
    let ss = 0, se = 63, ah = 0, al = 0, dcT = null, acT = null;

    function blockBaseline(c, o) {
      const cf = c.coefs;
      const t = huff(dcT);
      if (t > 15) fail("bad DC category");
      c.pred += t ? extend(receive(t), t) : 0;
      cf[o] = c.pred;
      for (let k = 1; k < 64;) {
        const rs = huff(acT), s = rs & 15, r = rs >> 4;
        if (s === 0) { if (r < 15) break; k += 16; continue; }
        k += r;
        if (k > 63) break;
        cf[o + ZIGZAG[k]] = extend(receive(s), s);
        k++;
      }
    }
    function blockDCFirst(c, o) {
      const t = huff(dcT);
      if (t > 15) fail("bad DC category");
      c.pred += t ? extend(receive(t), t) : 0;
      c.coefs[o] = c.pred * (1 << al);
    }
    function blockDCRefine(c, o) {
      if (bit()) c.coefs[o] |= 1 << al;
    }
    function blockACFirst(c, o) {
      if (eobrun > 0) { eobrun--; return; }
      const cf = c.coefs;
      for (let k = ss; k <= se;) {
        const rs = huff(acT), s = rs & 15, r = rs >> 4;
        if (s === 0) {
          if (r < 15) { eobrun = (1 << r) - 1; if (r) eobrun += receive(r); break; }
          k += 16;
          continue;
        }
        k += r;
        if (k > 63) break;
        cf[o + ZIGZAG[k]] = extend(receive(s), s) * (1 << al);
        k++;
      }
    }
    function blockACRefine(c, o) {
      const cf = c.coefs;
      const p1 = 1 << al, m1 = -p1;
      let k = ss;
      if (eobrun === 0) {
        for (; k <= se; k++) {
          const rs = huff(acT);
          let s = rs & 15, r = rs >> 4;
          if (s !== 0) {
            if (s !== 1) fail("bad refine symbol");
            s = bit() ? p1 : m1;
          } else if (r !== 15) {
            eobrun = 1 << r;
            if (r) eobrun += receive(r);
            break;
          }
          // Skip r zero-history coefficients, refining non-zero ones on the way.
          do {
            const idx = o + ZIGZAG[k], v = cf[idx];
            if (v !== 0) {
              if (bit() && (v & p1) === 0) cf[idx] = v >= 0 ? v + p1 : v + m1;
            } else if (--r < 0) break;
            k++;
          } while (k <= se);
          if (s !== 0 && k <= se) cf[o + ZIGZAG[k]] = s;
        }
      }
      if (eobrun > 0) {
        for (; k <= se; k++) {
          const idx = o + ZIGZAG[k], v = cf[idx];
          if (v !== 0 && bit() && (v & p1) === 0) cf[idx] = v >= 0 ? v + p1 : v + m1;
        }
        eobrun--;
      }
    }

    function readSOF(p, end, marker) {
      if (frame) fail("multiple frames");
      if (end - p < 6) fail("short SOF");
      if (data[p] !== 8) fail("unsupported precision " + data[p]);
      const h = (data[p + 1] << 8) | data[p + 2], w = (data[p + 3] << 8) | data[p + 4];
      const n = data[p + 5];
      if (!w || !h) fail("bad dimensions");
      if (w * h > MAX_PIXELS) fail("image too large");
      if (n !== 1 && n !== 3) fail("unsupported component count " + n);
      if (end - p < 6 + n * 3) fail("short SOF");
      const comps = [];
      let hmax = 1, vmax = 1;
      for (let i = 0; i < n; i++) {
        const q = p + 6 + i * 3;
        const hs = data[q + 1] >> 4, vs = data[q + 1] & 15;
        if (hs < 1 || hs > 4 || vs < 1 || vs > 4) fail("bad sampling factors");
        comps.push({ id: data[q], h: hs, v: vs, tq: data[q + 2] & 3, q: null, pred: 0, dcTbl: 0, acTbl: 0 });
        if (hs > hmax) hmax = hs;
        if (vs > vmax) vmax = vs;
      }
      // A single-component image is never interleaved, so its sampling factors are irrelevant.
      if (n === 1) { comps[0].h = 1; comps[0].v = 1; hmax = 1; vmax = 1; }
      for (const c of comps) {
        if (hmax % c.h || vmax % c.v) fail("non-integer subsampling ratio");
      }
      const mcusX = Math.ceil(w / (8 * hmax)), mcusY = Math.ceil(h / (8 * vmax));
      for (const c of comps) {
        c.bpl = mcusX * c.h; // blocks per line, padded to whole MCUs
        c.bpc = mcusY * c.v;
        c.cw = Math.ceil(w * c.h / hmax); // real component size in samples
        c.ch = Math.ceil(h * c.v / vmax);
        c.coefs = new Int16Array(c.bpl * c.bpc * 64);
      }
      frame = { w, h, comps, hmax, vmax, mcusX, mcusY, progressive: marker === 0xc2 };
    }

    function decodeScan(sc, ri) {
      const prog = frame.progressive;
      const single = sc.length === 1;
      const bw = single ? Math.ceil(sc[0].cw / 8) : 0;
      const total = single ? bw * Math.ceil(sc[0].ch / 8) : frame.mcusX * frame.mcusY;
      let fn;
      if (!prog) fn = blockBaseline;
      else if (ss === 0) fn = ah === 0 ? blockDCFirst : blockDCRefine;
      else fn = ah === 0 ? blockACFirst : blockACRefine;

      bitBuf = 0; bitCnt = 0; hitMarker = false; eobrun = 0;
      for (const c of sc) c.pred = 0;

      for (let m = 0; m < total; m++) {
        if (ri && m > 0 && m % ri === 0) {
          // Restart: drop remaining bits, find RSTn, reset predictors.
          bitBuf = 0; bitCnt = 0; hitMarker = false; eobrun = 0;
          while (pos + 1 < len && !(data[pos] === 0xff && data[pos + 1] >= 0xd0 && data[pos + 1] <= 0xd7)) {
            if (data[pos] === 0xff && data[pos + 1] !== 0 && data[pos + 1] !== 0xff) fail("missing restart marker");
            pos++;
          }
          if (pos + 1 >= len) fail("truncated data");
          pos += 2;
          for (const c of sc) c.pred = 0;
        }
        if (single) {
          const c = sc[0];
          dcT = dcTbls[c.dcTbl]; acT = acTbls[c.acTbl];
          fn(c, (((m / bw) | 0) * c.bpl + (m % bw)) * 64);
        } else {
          const mx = m % frame.mcusX, my = (m / frame.mcusX) | 0;
          for (let i = 0; i < sc.length; i++) {
            const c = sc[i];
            dcT = dcTbls[c.dcTbl]; acT = acTbls[c.acTbl];
            for (let v = 0; v < c.v; v++) {
              for (let h = 0; h < c.h; h++) {
                fn(c, ((my * c.v + v) * c.bpl + mx * c.h + h) * 64);
              }
            }
          }
        }
      }
      // Advance to the next real marker after the entropy-coded data.
      while (pos + 1 < len && !(data[pos] === 0xff && data[pos + 1] !== 0 && data[pos + 1] !== 0xff &&
        !(data[pos + 1] >= 0xd0 && data[pos + 1] <= 0xd7))) pos++;
      if (pos + 1 >= len) fail("truncated data");
    }

    // ---- marker loop ----
    for (;;) {
      if (pos >= len) fail("missing EOI");
      if (data[pos] !== 0xff) { pos++; continue; }
      while (pos < len && data[pos] === 0xff) pos++;
      if (pos >= len) fail("missing EOI");
      const marker = data[pos++];
      if (marker === 0 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd8)) continue;
      if (marker === 0xd9) break;
      if (pos + 2 > len) fail("truncated segment");
      const segLen = (data[pos] << 8) | data[pos + 1];
      const p = pos + 2, end = pos + segLen;
      if (segLen < 2 || end > len) fail("bad segment length");
      pos = end;

      if (marker === 0xc0 || marker === 0xc1 || marker === 0xc2) {
        readSOF(p, end, marker);
      } else if (marker === 0xc4) {
        let q = p;
        while (q < end) {
          const tc = data[q] >> 4, th = data[q] & 15;
          if (tc > 1 || th > 3 || q + 17 > end) fail("bad DHT");
          const counts = data.subarray(q + 1, q + 17);
          let n = 0;
          for (let i = 0; i < 16; i++) n += counts[i];
          if (n > 256 || q + 17 + n > end) fail("bad DHT");
          (tc ? acTbls : dcTbls)[th] = buildHuff(counts, data.subarray(q + 17, q + 17 + n));
          q += 17 + n;
        }
      } else if (marker === 0xdb) {
        let q = p;
        while (q < end) {
          const pq = data[q] >> 4, tq = data[q] & 15;
          if (pq > 1 || tq > 3) fail("bad DQT");
          const sz = pq ? 128 : 64;
          if (q + 1 + sz > end) fail("bad DQT");
          const t = new Uint16Array(64);
          for (let i = 0; i < 64; i++) {
            t[ZIGZAG[i]] = pq ? (data[q + 1 + i * 2] << 8) | data[q + 2 + i * 2] : data[q + 1 + i];
          }
          qts[tq] = t;
          q += 1 + sz;
        }
      } else if (marker === 0xdd) {
        if (end - p < 2) fail("bad DRI");
        restartInterval = (data[p] << 8) | data[p + 1];
      } else if (marker === 0xda) {
        if (!frame) fail("SOS before SOF");
        const ns = data[p];
        if (ns < 1 || ns > frame.comps.length || end - p < 1 + ns * 2 + 3) fail("bad SOS");
        const sc = [];
        for (let i = 0; i < ns; i++) {
          const c = frame.comps.find((x) => x.id === data[p + 1 + i * 2]);
          if (!c || sc.indexOf(c) >= 0) fail("bad scan component");
          c.dcTbl = data[p + 2 + i * 2] >> 4;
          c.acTbl = data[p + 2 + i * 2] & 15;
          if (c.dcTbl > 3 || c.acTbl > 3) fail("bad table selector");
          if (!c.q) {
            if (!qts[c.tq]) fail("missing quantization table");
            c.q = qts[c.tq]; // latched at first use, like libjpeg
          }
          sc.push(c);
        }
        const q = p + 1 + ns * 2;
        if (frame.progressive) {
          ss = data[q]; se = data[q + 1]; ah = data[q + 2] >> 4; al = data[q + 2] & 15;
          if (ss > se || se > 63 || al > 13 || ah > 13) fail("bad progressive params");
          if (ss === 0 ? se !== 0 : ns !== 1) fail("bad progressive scan");
          if (ah !== 0 && ah !== al + 1) fail("bad refinement");
        } else {
          ss = 0; se = 63; ah = 0; al = 0;
        }
        const needDC = !frame.progressive || (ss === 0 && ah === 0);
        const needAC = !frame.progressive || ss > 0;
        for (const c of sc) {
          if (needDC && !dcTbls[c.dcTbl]) fail("missing DC table");
          if (needAC && !acTbls[c.acTbl]) fail("missing AC table");
        }
        decodeScan(sc, restartInterval);
        sawScan = true;
      } else if (marker === 0xe1) {
        if (end - p >= 14 && data[p] === 0x45 && data[p + 1] === 0x78 && data[p + 2] === 0x69 &&
          data[p + 3] === 0x66 && data[p + 4] === 0 && data[p + 5] === 0) {
          orientation = parseExifOrientation(data, p, end);
        }
      } else if (marker === 0xee) {
        if (end - p >= 12 && data[p] === 0x41 && data[p + 1] === 0x64 && data[p + 2] === 0x6f &&
          data[p + 3] === 0x62 && data[p + 4] === 0x65) adobeTransform = data[p + 11];
      } else if ((marker >= 0xc3 && marker <= 0xcf) || marker === 0xdc || marker === 0xde || marker === 0xdf) {
        fail("unsupported JPEG type (marker 0x" + marker.toString(16) + ")");
      }
      // APPn, COM and anything else: skipped.
    }
    if (!frame || !sawScan) fail("no image data");

    const { w, h, comps, hmax, vmax } = frame;
    const planes = [];
    const ws = new Int32Array(64);
    for (const c of comps) {
      const stride = c.bpl * 8;
      const plane = new Uint8Array(stride * c.bpc * 8);
      for (let by = 0; by < c.bpc; by++) {
        for (let bx = 0; bx < c.bpl; bx++) {
          idctBlock(c.coefs, (by * c.bpl + bx) * 64, c.q, ws, plane, by * 8 * stride + bx * 8, stride);
        }
      }
      c.coefs = null;
      const rh = hmax / c.h, rv = vmax / c.v;
      if (rh === 1 && rv === 1) planes.push({ d: plane, s: stride });
      else planes.push({ d: upsample(plane, stride, c.cw, c.ch, rh, rv, w, h), s: w });
    }
    const out = new Uint8ClampedArray(w * h * 4);
    const P0 = planes[0];
    if (comps.length === 1) {
      for (let y = 0, o = 0; y < h; y++) {
        for (let x = 0, i = y * P0.s; x < w; x++, i++, o += 4) {
          const v = P0.d[i];
          out[o] = v; out[o + 1] = v; out[o + 2] = v; out[o + 3] = 255;
        }
      }
    } else {
      const rgb = adobeTransform === 0 ||
        (comps[0].id === 0x52 && comps[1].id === 0x47 && comps[2].id === 0x42);
      const P1 = planes[1], P2 = planes[2];
      for (let y = 0, o = 0; y < h; y++) {
        let i0 = y * P0.s, i1 = y * P1.s, i2 = y * P2.s;
        for (let x = 0; x < w; x++, o += 4) {
          const Y = P0.d[i0++], cb = P1.d[i1++] - 128, cr = P2.d[i2++] - 128;
          let r, g, b;
          if (rgb) { r = Y; g = cb + 128; b = cr + 128; } else {
            r = Y + ((91881 * cr + 32768) >> 16);
            g = Y + ((-22554 * cb - 46802 * cr + 32768) >> 16);
            b = Y + ((116130 * cb + 32768) >> 16);
          }
          out[o] = r < 0 ? 0 : r > 255 ? 255 : r;
          out[o + 1] = g < 0 ? 0 : g > 255 ? 255 : g;
          out[o + 2] = b < 0 ? 0 : b > 255 ? 255 : b;
          out[o + 3] = 255;
        }
      }
    }
    return { w, h, data: out, orientation };
  }

  // Dequantize + 8x8 inverse DCT of one block into `plane` (clamped, +128 level shift).
  function idctBlock(cf, o, q, ws, plane, po, stride) {
    // Pass 1: columns, output scaled by 2^2.
    for (let c = 0; c < 8; c++) {
      const i0 = cf[o + c] * q[c], i1 = cf[o + 8 + c] * q[8 + c], i2 = cf[o + 16 + c] * q[16 + c];
      const i3 = cf[o + 24 + c] * q[24 + c], i4 = cf[o + 32 + c] * q[32 + c], i5 = cf[o + 40 + c] * q[40 + c];
      const i6 = cf[o + 48 + c] * q[48 + c], i7 = cf[o + 56 + c] * q[56 + c];
      if ((i1 | i2 | i3 | i4 | i5 | i6 | i7) === 0) {
        const dc = i0 << 2;
        ws[c] = dc; ws[8 + c] = dc; ws[16 + c] = dc; ws[24 + c] = dc;
        ws[32 + c] = dc; ws[40 + c] = dc; ws[48 + c] = dc; ws[56 + c] = dc;
        continue;
      }
      let z1 = (i2 + i6) * F_0_541;
      const t2 = z1 - i6 * F_1_847, t3 = z1 + i2 * F_0_765;
      const t0 = (i0 + i4) << 13, t1 = (i0 - i4) << 13;
      const t10 = t0 + t3, t13 = t0 - t3, t11 = t1 + t2, t12 = t1 - t2;
      let a0 = i7, a1 = i5, a2 = i3, a3 = i1;
      z1 = a0 + a3;
      let z2 = a1 + a2, z3 = a0 + a2, z4 = a1 + a3;
      const z5 = (z3 + z4) * F_1_175;
      a0 *= F_0_298; a1 *= F_2_053; a2 *= F_3_072; a3 *= F_1_501;
      z1 *= -F_0_899; z2 *= -F_2_562; z3 = z3 * -F_1_961 + z5; z4 = z4 * -F_0_390 + z5;
      a0 += z1 + z3; a1 += z2 + z4; a2 += z2 + z3; a3 += z1 + z4;
      ws[c] = (t10 + a3 + 1024) >> 11; ws[56 + c] = (t10 - a3 + 1024) >> 11;
      ws[8 + c] = (t11 + a2 + 1024) >> 11; ws[48 + c] = (t11 - a2 + 1024) >> 11;
      ws[16 + c] = (t12 + a1 + 1024) >> 11; ws[40 + c] = (t12 - a1 + 1024) >> 11;
      ws[24 + c] = (t13 + a0 + 1024) >> 11; ws[32 + c] = (t13 - a0 + 1024) >> 11;
    }
    // Pass 2: rows. Descale 2^18 = 13 constant bits + 2 pass-1 bits + 3 for the 8x8 gain.
    const R = 131072 + (128 << 18); // rounding + level shift
    for (let r = 0; r < 8; r++) {
      const w = r * 8, d = po + r * stride;
      let z1 = (ws[w + 2] + ws[w + 6]) * F_0_541;
      const t2 = z1 - ws[w + 6] * F_1_847, t3 = z1 + ws[w + 2] * F_0_765;
      const t0 = (ws[w] + ws[w + 4]) << 13, t1 = (ws[w] - ws[w + 4]) << 13;
      const t10 = t0 + t3, t13 = t0 - t3, t11 = t1 + t2, t12 = t1 - t2;
      let a0 = ws[w + 7], a1 = ws[w + 5], a2 = ws[w + 3], a3 = ws[w + 1];
      z1 = a0 + a3;
      let z2 = a1 + a2, z3 = a0 + a2, z4 = a1 + a3;
      const z5 = (z3 + z4) * F_1_175;
      a0 *= F_0_298; a1 *= F_2_053; a2 *= F_3_072; a3 *= F_1_501;
      z1 *= -F_0_899; z2 *= -F_2_562; z3 = z3 * -F_1_961 + z5; z4 = z4 * -F_0_390 + z5;
      a0 += z1 + z3; a1 += z2 + z4; a2 += z2 + z3; a3 += z1 + z4;
      let v;
      v = (t10 + a3 + R) >> 18; plane[d] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t10 - a3 + R) >> 18; plane[d + 7] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t11 + a2 + R) >> 18; plane[d + 1] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t11 - a2 + R) >> 18; plane[d + 6] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t12 + a1 + R) >> 18; plane[d + 2] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t12 - a1 + R) >> 18; plane[d + 5] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t13 + a0 + R) >> 18; plane[d + 3] = v < 0 ? 0 : v > 255 ? 255 : v;
      v = (t13 - a0 + R) >> 18; plane[d + 4] = v < 0 ? 0 : v > 255 ? 255 : v;
    }
  }

  // Expand a subsampled plane to w*h. Ratio 2 on an axis: centered triangle (3 near + 1 far);
  // other ratios: replicate. Vertical first (scale 4), then horizontal (scale 4), one rounding.
  function upsample(plane, stride, cw, ch, rh, rv, w, h) {
    const out = new Uint8Array(w * h);
    const tv = new Int32Array(cw);
    for (let y = 0; y < h; y++) {
      let sh = 0;
      if (rv === 2) {
        const sy = y >> 1;
        const far = (y & 1) ? (sy + 1 < ch ? sy + 1 : ch - 1) : (sy > 0 ? sy - 1 : 0);
        const a = sy * stride, b = far * stride;
        for (let x = 0; x < cw; x++) tv[x] = 3 * plane[a + x] + plane[b + x];
        sh = 2;
      } else {
        const a = ((y / rv) | 0) * stride;
        for (let x = 0; x < cw; x++) tv[x] = plane[a + x];
      }
      const o = y * w;
      if (rh === 2) {
        sh += 2;
        const rnd = 1 << (sh - 1);
        for (let x = 0; x < w; x++) {
          const i = x >> 1;
          const nb = (x & 1) ? (i + 1 < cw ? i + 1 : cw - 1) : (i > 0 ? i - 1 : 0);
          out[o + x] = (3 * tv[i] + tv[nb] + rnd) >> sh;
        }
      } else {
        const rnd = sh ? 1 << (sh - 1) : 0;
        for (let x = 0; x < w; x++) {
          out[o + x] = (tv[rh === 1 ? x : (x / rh) | 0] + rnd) >> sh;
        }
      }
    }
    return out;
  }

  root.DarkslideJpegDecode = { decode };
})(typeof window !== "undefined" ? window : globalThis);
