const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const elements=new Map();const make=()=>({textContent:'',value:'all',hidden:false,disabled:false,children:[],append(...v){this.children.push(...v);},replaceChildren(...v){this.children=[...v];},reset(){},isConnected:true});
 const el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id);};
 const ctx=vm.createContext({ECGWorkflow:require('../web/workflow_core.js'),document:{getElementById:el,body:{dataset:{page:'tasks'}},createElement:make,addEventListener(){},hidden:false},fetch:async()=>{},AbortSignal,URLSearchParams,Date,setInterval(){},console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workflow-page.js'),'utf8').replace(/initializePage\(\);\s*$/,''),ctx);
 return {ctx,el};
}
const response=body=>({ok:true,status:200,headers:{get:()=> 'owner'},json:async()=>body});
test('refresh recovers after preferences temporarily fail during initialization',async()=>{
 const h=harness();let fail=true;
 h.ctx.fetch=async path=>{if(path==='/api/auth/me')return response({user:{id:'owner',username:'owner'},csrf_token:'t'});if(path==='/api/workflow/preferences'){if(fail)throw new Error('offline');return response({auto_model:false,auto_physiology:true});}return response({counts:{},records:[],total:0,measured_at:1});};
 await h.ctx.initializePage();assert.equal(h.el('page-content').hidden,true);fail=false;
 await h.el('refresh-page').onclick();assert.equal(h.el('page-content').hidden,false);assert.equal(h.el('auto-physiology').checked,true);
});
test('older filtered task result cannot overwrite the current list',async()=>{
 const h=harness();vm.runInContext("client.set({id:'owner'},'t')",h.ctx);let resolve,count=0;
 h.ctx.fetch=async()=>response(++count===1?await new Promise(r=>resolve=r):{counts:{},records:[],total:0,measured_at:1});
 const older=h.ctx.refreshPage();await new Promise(r=>setImmediate(r));await h.ctx.refreshPage();resolve({counts:{},records:[],total:99,measured_at:1});await older;
 assert.equal(h.el('tasks-total').textContent,'0 条记录');
});
