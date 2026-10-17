const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app/web/film.js','utf8');
const nodes={},get=id=>nodes[id]||(nodes[id]={style:{},textContent:'',disabled:false,hidden:false});
const rid='user_lut_photo_'+'a'.repeat(32),recipe={id:rid,photo_snapshot:{original_id:'gold200'}};
let pendingFetch,selected=[];
const hooks={scene:()=> 'scene',mine:()=>null,rerender(){},invalidateCheck(){},slotNo:()=>8,setFilm:(...args)=>selected.push(args)};
const api=async(method,url)=>url.endsWith('film-catalog')?{films:[],writer:{available:false}}:url.endsWith('film-luts')?{luts:[],capabilities:{camera_fit:true,photo_recipe_read:true}}:url.endsWith('photo-recipes')?{recipes:[recipe]}:{films:{}};
const ctx={document:{getElementById:get},window:{DarkslideAdjust:{isEmpty:x=>!x||!Object.keys(x).length,lutOnly:()=>false}},Float32Array,fetch:()=>new Promise(r=>pendingFetch=r)};
ctx.setTimeout=ctx.setTimeout||setTimeout;ctx.clearTimeout=ctx.clearTimeout||clearTimeout; // film.js debounces its write-range check
vm.createContext(ctx);
vm.runInContext(source.replace('  window.DarkslideFilm =','  window.testFilm={film,cubeOf,cubeAt,importRecipe,configure(a,h){api=a;hooks=h;toast=()=>{};}};\n  window.DarkslideFilm ='),ctx);
const t=ctx.window.testFilm,f=ctx.window.DarkslideFilm;
const cube='LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n';
(async()=>{
 t.configure(api,hooks);await f.load('A');
 assert.equal(f.nameOf(rid),'照片配方 · gold200');
 assert.equal(f.filmInfo(rid).detail,'照片中保存的完整配方');
 f.renderOutput({no:8},{film:rid});assert.equal(get('btnFit').textContent,'核对预览');assert.equal(get('btnExportCube').textContent,'导出配方包');assert.equal(get('fitBadge').textContent,'已恢复');
 const old=t.cubeOf(rid);await f.load('B');pendingFetch({ok:true,text:async()=>cube});await assert.rejects(old,/工程已切换/);assert.equal(Object.keys(t.film.cubes).length,0);
 const current=t.cubeOf(rid);pendingFetch({ok:true,text:async()=>cube});await current;assert.ok(Object.keys(t.film.cubes)[0].includes('/B/'));
 let release,entered;const ready=new Promise(r=>entered=r);
 t.configure(async(method,url)=>{
   if(method==='POST')return recipe;
   if(url==='/api/projects/B/photo-recipes'){entered();return new Promise(r=>release=r);}
   return api(method,url);
 },hooks);
 const importing=t.importRecipe({files:[{size:8,arrayBuffer:async()=>new ArrayBuffer(8)}]});await ready;
 await f.load('C');const cRecipes=t.film.recipes;release({recipes:[{id:'stale'}]});await importing;
 assert.strictEqual(t.film.recipes,cRecipes);assert.equal(selected.length,0);
 f.previewUrl({film:rid},true,8);await f.load('D');pendingFetch({ok:true,text:async()=>cube});await new Promise(r=>setImmediate(r));assert.equal(Object.keys(t.film.graded).length,0);assert.equal(Object.keys(t.film.camFail).length,0);
 t.film.capabilities.candidate_generation=true;assert.equal(f.candidateReady(),true);assert.match(f.fitState({no:8},{film:'gold200'}).note,/离线候选/);
 console.log('PASS IIIx UI: recipe labels/export, project-bound preview cache, stale fetch/import isolation');
})().catch(e=>{console.error(e);process.exitCode=1});
