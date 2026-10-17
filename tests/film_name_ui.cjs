// Picking a built-in film renames the preset (user, 2026-10-17), with the page's real code:
// presetName() from film.js and setFilm()/syncFilmName() from app.js. Also: no browser confirm()/prompt()
// anywhere, because some embedded browsers answer them "no" without showing anything.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const film=fs.readFileSync('app/web/film.js','utf8'),app=fs.readFileSync('app/web/app.js','utf8'),names=fs.readFileSync('app/web/names.js','utf8');
const between=(s,a,b)=>{const i=s.indexOf(a),j=s.indexOf(b,i);if(i<0||j<0)throw new Error('marker missing: '+(i<0?a:b));return s.slice(i,j);};
const films=[['portra400','Portra 400'],['gold200','Gold 200'],['ektar100','Ektar 100'],['pro400h','Pro 400H'],['ultramax400','UltraMax 400'],
 ['xtra400_portraendura','X-Tra 400'],['5207','5207'],['5219','5219'],['portra160','Portra 160'],['portra800','Portra 800'],
 ['portra800push1','Portra 800 推1'],['portra800push2','Portra 800 推2'],['c200','C200'],['5203','5203'],['5213','5213'],['verita200d','Verita 200D'],
 ['newfilm','Some New Film 推3']].map(([id,name])=>({id,name}));
const ctx={window:{},film:{catalog:{films}}};
vm.createContext(ctx);
vm.runInContext(names,ctx);
vm.runInContext(between(film,'  const PRESET_NAMES = {','  // The name plate of a built-in film as a full square picture'),ctx);
const P=(id,max)=>vm.runInContext('presetName('+JSON.stringify(id)+','+max+')',ctx);
// Every built-in film gets a camera-legal name in every film preset (8, 12, 13 and 16 characters).
for(const f of films.filter((x)=>x.id!=='newfilm'))for(const max of [8,12,13,16]){const n=P(f.id,max);assert.ok(n&&ctx.window.DarkslideNames.ok(n,max),f.id+' @'+max+' -> '+n);}
assert.equal(P('portra400',8),'Port 400');assert.equal(P('portra400',12),'Portra 400');
assert.equal(P('ultramax400',8),'UltraMax');assert.equal(P('ultramax400',12),'UltraMax 400');
assert.equal(P('portra800push1',12),'Portra 800+1');assert.equal(P('portra800push1',8),'P800+1');
assert.equal(P('verita200d',8),'Verita');assert.equal(P('newfilm',16),'Some New Film 3');assert.equal(P('newfilm',8),null,'a future film that does not fit leaves the name alone');
assert.equal(P('user_lut_0123456789ab',12),null);
// setFilm: the name follows the film, a typed name included; leaving the film restores the factory name.
const slots={8:{no:8,rename:'open',name_max:null,factory_en:'Bleach Bypass'},9:{no:9,rename:'open',name_max:8,factory_en:'Retro'},
 10:{no:10,rename:'open',name_max:12,factory_en:'HDR Tone'},2:{no:2,rename:'closed',factory_en:'Vivid'}};
const a={state:{changes:{}},slotOf:(no)=>slots[no],syncFilmIcon(){},window:{DarkslideFilm:{presetName:P}}};
a.editable=(s,w)=>s[w]==='test'||s[w]==='open';a.nameMax=(s)=>s.name_max||s.factory_en.length;
a.mutate=(fn)=>{fn(a.state.changes);for(const k of Object.keys(a.state.changes))if(!Object.keys(a.state.changes[k]).length)delete a.state.changes[k];};
vm.createContext(a);
vm.runInContext(between(app,'function setEdit(no, key, value) {','\n}\n')+'\n}',a);
vm.runInContext(between(app,'function setFilm(no, id) {','// Choosing a built-in film puts its icon on the preset'),a);
const name=(no)=>(a.state.changes[no]||{}).name, set=(no,id)=>vm.runInContext('setFilm('+no+','+JSON.stringify(id)+')',a);
a.state.changes={9:{name:'Lior'}};set(9,'portra400');assert.equal(name(9),'Port 400');
set(9,'gold200');assert.equal(name(9),'Gold 200');
set(8,'pro400h');assert.equal(name(8),'Pro 400H');
set(9,undefined);assert.equal(name(9),undefined,'leaving a built-in film drops its name');
a.state.changes[10]={name:'Mine'};set(10,'user_lut_0123456789ab');assert.equal(name(10),'Mine','the user LUT keeps a typed name');
set(10,'c200');assert.equal(name(10),'C200');set(10,'user_lut_0123456789ab');assert.equal(name(10),undefined);
set(2,'gold200');assert.equal(name(2),undefined,'a preset whose name cannot change is left alone');
// No browser dialogs left in the page.
for(const [f,s] of [['app.js',app],['film.js',film]])assert.ok(!/window\.(confirm|prompt)\(/.test(s),f+' still uses the browser confirm()/prompt()');
assert.ok(/id="askDialog"/.test(fs.readFileSync('app/web/index.html','utf8')));
console.log('PASS film names: every built-in film fits every film preset; name follows the film, factory name back on leaving it; no browser confirm()/prompt()');
