const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('app/web/app.js','utf8');
const nodes={},get=id=>nodes[id]||(nodes[id]={textContent:'',children:[],value:'',append(v){this.children.push(v)},replaceChildren(...v){this.children=v}});
let resolve,last;
const ctx={state:{firmware:{sha256:"fixture"},project:{id:'p_A',template_id:'gr3-2.10-reviewed-1'},template:{model:'GR III'},changes:{}},$:get,document:{createElement(){return {textContent:''}}},window:{DarkslideFilm:{nameOf:x=>x}},api:(...args)=>{last=args;return new Promise(r=>resolve=r)},toast:()=>{},el:(tag,attrs)=>attrs};
vm.createContext(ctx);
vm.runInContext(code.slice(code.indexOf('let filmPrepareEpoch ='),code.indexOf('// ---------------------------------------------------------------- generate')),ctx);
vm.runInContext(code.slice(code.indexOf('async function newProject()'),code.indexOf('async function openProject(')),ctx);
vm.runInContext(code.slice(code.indexOf('function renderProjectBody()'),code.indexOf('// ---------------------------------------------------------------- guide')),ctx);
ctx.camBlocked=()=>false;ctx.camModel=()=>['GR III HDF'];ctx.loadProject=p=>ctx.loaded=p;
vm.runInContext('const SERIES=[{short:"GR III",models:[["GR III"],["GR III HDF"]]}]',ctx);
const response=()=>({project_id:'p_A',request_id:last[2].request_id,production_approved:false,full_image_created:false,decoded_growth_bytes:0,slots:[],data_verified:true,shared_reference_verified:true,coverage_verified:true,note:'fixture',body:{status:'protected_windows_unchanged',compatibility_approved:false,device_tested:false,summary:'55 windows'}});
(async()=>{
 let pending=ctx.newProject();assert.equal(last[2].camera_variant,'GR III HDF');resolve({id:'new'});await pending;
 ctx.renderProjectBody();assert.equal(get('projectBody').value,'');
 get('projectBody').value='GR III HDF';pending=get('projectBody').onchange();assert.equal(last[2].camera_variant,'GR III HDF');resolve({target_body:'GR III HDF',camera_variant:'GR III HDF'});await pending;assert.equal(ctx.state.project.target_body,'GR III HDF');
 pending=ctx.prepareFilms();resolve(response());await pending;assert.match(get('filmPrepareStatus').textContent,/离线数据核对通过/);
 for(const body of [{status:'review_required',summary:'需要专项复核'},undefined,{status:'unknown'}]){
   pending=ctx.prepareFilms();resolve({...response(),body});await pending;assert.match(get('filmPrepareStatus').textContent,/核对未通过/);assert.doesNotMatch(get('filmPrepareStatus').textContent,/离线数据核对通过/);
 }
 pending=ctx.prepareFilms();const r=response();ctx.invalidateFilmPrepare();resolve(r);await pending;assert.doesNotMatch(get('filmPrepareStatus').textContent,/离线数据核对通过/);
 console.log('PASS actual UI: homepage selection payload, old project explicit choice, protected failure/missing/unknown, stale response');
})().catch(e=>{console.error(e);process.exitCode=1});
