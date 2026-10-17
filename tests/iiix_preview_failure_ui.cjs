// Run real preview/render code with failed installation, original preview and explicit retry.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const cube='LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n';
const rid='user_lut_photo_'+'a'.repeat(32),edit={film:rid},requests=[],messages=[],nodes={};
let fail=true,blobs=0;
const node=id=>nodes[id]||(nodes[id]={style:{},children:[],classList:{toggle(){}},replaceChildren(){},showModal(){this.open=true;},close(){this.open=false;}});
const ctx={Float32Array,URL:{createObjectURL:()=> 'blob:'+ ++blobs,revokeObjectURL(){}},
 ImageData:class{constructor(w,h){this.width=w;this.height=h;this.data=new Uint8ClampedArray(w*h*4);}},
 document:{getElementById:node,createElement:()=>({getContext:()=>({putImageData(){}}),toBlob:cb=>cb({})})},
 window:{DarkslideAdjust:{isEmpty:x=>!x||!Object.keys(x).length,lutOnly:()=>false,combine:b=>b}},
 fetch:async url=>{requests.push(url);return {ok:!(fail&&url.endsWith('/install.cube')),json:async()=>({error:'胶片矩阵超出原厂数值边界'}),text:async()=>cube};}};
ctx.setTimeout=ctx.setTimeout||setTimeout;ctx.clearTimeout=ctx.clearTimeout||clearTimeout; // film.js debounces its write-range check
vm.createContext(ctx);
const source=fs.readFileSync('app/web/film.js','utf8');
vm.runInContext(source.replace('  window.DarkslideFilm =',`  window.probe={film,configure(a,h,t){api=a;hooks=h;toast=t;sourceImage=async()=>({img:{width:1,height:1,data:new Uint8ClampedArray([10,20,30,255])}});}};
  window.DarkslideFilm =`),ctx);
const f=ctx.window.DarkslideFilm,p=ctx.window.probe;
const api=async(method,url)=>url.endsWith('fitting-setup')?{state:'ready'}:url.endsWith('film-catalog')?{films:[],writer:{available:false}}:url.endsWith('film-luts')?{luts:[],capabilities:{camera_fit:true,photo_recipe_read:true}}:url.endsWith('photo-recipes')?{recipes:[{id:rid,photo_snapshot:{original_id:'ektar100'}}]}:{films:{}};
p.configure(api,{scene:()=> 'scene',mine:()=>null,rerender(){},invalidateCheck(){}},m=>messages.push(m));
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 await f.load('P');
 assert.equal(f.previewUrl(edit,true,8),null);await tick();
 assert.equal(f.previewUrl(edit,true,8),null);await tick();
 assert.equal(requests.length,1);assert.ok(requests[0].endsWith('/install.cube'));
 assert.equal(blobs,0);assert.match(f.previewError(8,edit),/矩阵/);assert.match(messages[0],/相机预览不可用/);
 f.renderOutput({no:8},edit);assert.equal(node('fitBadge').textContent,'预览不可用');assert.match(node('fitNote').textContent,/矩阵/);
 // Real app rendering must label the fallback source as original, never camera approximation.
 Object.assign(ctx,{$:node,state:{feature:'ic',sel:8,view:'camera',changes:{8:edit}},samples:{mine:true},focusedIndex:()=>0,refocus(){},el:()=>({}),slotOf:()=>({no:8,name:'slot'}),sceneBackground:()=> 'original',toast:m=>messages.push(m)});
 const app=fs.readFileSync('app/web/app.js','utf8');
 vm.runInContext(app.slice(app.indexOf('const VIEW_NOTES ='),app.indexOf('// Factory defaults of')),ctx);
 node('zoomDialog').open=true;ctx.renderSamples();assert.equal(node('zoomDialog').open,false);assert.match(node('viewNote').textContent,/当前显示原图/);assert.equal(node('sampleAfterTag').textContent,'原图 · 相机预览不可用');
 ctx.openZoom();assert.notEqual(node('zoomDialog').open,true);
 // Original preview is still explicitly available in the after view.
 f.previewUrl(edit,false,8);await tick();assert.ok(f.previewUrl(edit,false,8).startsWith('blob:'));
 assert.ok(requests.at(-1).endsWith('/camera.cube'));assert.equal(f.previewUrl(edit,true,8),null);
 // Retrying a failure must preserve the failure; retry success must clear it and allow install preview.
 await f.fitNow({no:8,name:'slot'},edit);assert.match(f.previewError(8,edit),/矩阵/);
 fail=false;await f.fitNow({no:8,name:'slot'},edit);assert.equal(f.previewError(8,edit),null);
 f.previewUrl(edit,true,8);await tick();assert.ok(f.previewUrl(edit,true,8).startsWith('blob:'));
 ctx.renderSamples();assert.equal(node('sampleAfterTag').textContent,'相机近似');
 // Project switching cannot carry failure state to a different project.
 await f.load('Q');assert.equal(f.previewError(8,edit),null);
 console.log('PASS: failed install never falls back; reason/labels/zoom, original preview, retry, project isolation');
})().catch(e=>{console.error(e);process.exitCode=1});
