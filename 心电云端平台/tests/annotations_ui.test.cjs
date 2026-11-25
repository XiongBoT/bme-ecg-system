const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(){
 const elements=new Map(),make=()=>({value:'',checked:false,hidden:false,disabled:false,textContent:'',children:[],reset(){},focus(){},scrollIntoView(){},append(...x){this.children.push(...x)},replaceChildren(...x){this.children=[...x]}}),el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id)};
 const state={epoch:1,user:{id:'owner'},auth:true,selected:'mine',wave:{session:{session_id:'mine',upload_status:'complete',first_sample_id:0,last_sample_id:3599},start_sample:0,end_sample:3599}};
 const c=vm.createContext({state,$:el,text:(id,v)=>el(id).textContent=v,document:{createElement:make},crypto:{randomUUID:()=> '12345678-1234-1234-1234-123456789abc'},URLSearchParams,console,loadWave(){},api:async()=>({json:async()=>({annotations:[],total:0})})});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/annotations.js'),'utf8'),c);return {c,el,state,ui:c.RecordAnnotations};
}
const flush=()=>new Promise(r=>setImmediate(r));
test('annotation response cannot repopulate another account or record',async()=>{
 const h=setup();let finish;h.c.api=async()=>({json:()=>new Promise(r=>finish=r)});const pending=h.ui.load();await flush();h.state.epoch++;h.ui.clear();finish({annotations:[{note:'private'}],total:1});await pending;assert.equal(h.el('annotation-panel').hidden,true);assert.equal(h.el('annotation-list').children.length,0);
});
test('window range uses saved bounds and failed retry keeps annotation identifier',async()=>{
 const h=setup();h.ui.useWindow();assert.equal(h.el('annotation-start').value,'0.000');assert.equal(h.el('annotation-end').value,'9.997');h.el('annotation-kind').value='note';let requests=[];
 h.c.api=async(url,opts)=>{if(opts){requests.push({url,body:JSON.parse(opts.body)});throw Error('network');}return {json:async()=>({annotations:[],total:0})};};
 h.el('annotation-form').onsubmit({preventDefault(){}});await flush();h.el('annotation-form').onsubmit({preventDefault(){}});await flush();assert.equal(requests.length,2);assert.equal(requests[0].url,requests[1].url);assert.equal(requests[0].body.end_sample,3599);
});
test('invalid annotation interval sends no mutation',()=>{
 const h=setup();let called=false;h.c.api=async()=>{called=true;};h.el('annotation-start').value='10';h.el('annotation-end').value='1';h.el('annotation-form').onsubmit({preventDefault(){}});assert.equal(called,false);assert.match(h.el('annotation-feedback').textContent,/起止时间/);
});
