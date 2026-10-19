// node tools/i18n_hant.js <opencc-js dist/umd/full.js> <source.json plus extra-en.json keys> tools/i18n/zh-Hant.json
// Dev-time only (opencc-js, MIT/Apache-2.0): draft Simplified -> Traditional (Taiwan phrases) and the per-character map.
// The "strings" it writes are only a draft: tools/i18n/zh-Hant.json holds reviewed Taiwan wording, so merge new drafts by hand.
const [,, lib, src, out] = process.argv;
const OpenCC = require(lib);
const fs = require('fs');
const phrase = OpenCC.Converter({ from: 'cn', to: 'twp' });
const chars = OpenCC.Converter({ from: 'cn', to: 'tw' });
const source = JSON.parse(fs.readFileSync(src, 'utf8'));
const dict = {}, charMap = {};
for (const k of Object.keys(source)) {
  const v = phrase(k);
  if (v !== k) dict[k] = v;
  for (const ch of k) if (/[㐀-鿿]/.test(ch)) { const t = chars(ch); if (t !== ch) charMap[ch] = t; }
}
fs.writeFileSync(out, JSON.stringify({ strings: dict, chars: charMap }, null, 0));
console.log(Object.keys(dict).length, 'strings,', Object.keys(charMap).length, 'chars');
