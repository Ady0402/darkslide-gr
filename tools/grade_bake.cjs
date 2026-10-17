// Bake "film preview LUT + grade" exactly as the page does before fitting:
// DarkslideAdjust.combine(base, grade, camera=true, 33) and film.js cubeText.
// stdin: {"adjust": "<path to web/adjust.js>", "base": "<cube text>", "grades": [{...}, ...]}
// stdout: JSON array of cube texts, one per grade. Development tool (tools/build_grade_limits.py).
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = { window: {}, document: { getElementById: () => null }, Math, Float32Array };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(input.adjust, 'utf8'), ctx);
const A = ctx.window.DarkslideAdjust;
function parseCube(text) {  // film.js parseCube
  const lines = text.split('\n');
  const size = parseInt((lines.find((l) => l.startsWith('LUT_3D_SIZE')) || '').split(/\s+/)[1], 10);
  const data = new Float32Array(size * size * size * 3); let k = 0;
  for (const l of lines) { if (!/^[0-9.\-+]/.test(l.trim())) continue; const v = l.trim().split(/\s+/); data[k++] = +v[0]; data[k++] = +v[1]; data[k++] = +v[2]; }
  return { size, data };
}
function cubeText(lut) {  // film.js cubeText, without title/credit lines (they do not affect the fit)
  const n = Math.round(Math.cbrt(lut.data.length / 3));
  const lines = ['LUT_3D_SIZE ' + n, 'DOMAIN_MIN 0.0 0.0 0.0', 'DOMAIN_MAX 1.0 1.0 1.0'];
  for (let i = 0; i < lut.data.length; i += 3) lines.push(lut.data[i].toFixed(6) + ' ' + lut.data[i + 1].toFixed(6) + ' ' + lut.data[i + 2].toFixed(6));
  return lines.join('\n') + '\n';
}
const base = parseCube(input.base);
process.stdout.write(JSON.stringify(input.grades.map((g) => cubeText(A.combine(base, g, true, 33)))));
