const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(){
 const nodes=new Map(),el=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:false,textContent:'',disabled:false,reset(){}});return nodes.get(id)};
 const state={epoch:1,user:{id:'admin'}};
 const c=vm.createContext({databaseUI:state,dbEl:el,dbText:(id,v)=>el(id).textContent=v,dbDate:String,dbStatuses:{failed:'未完成'},dbRequest:async()=>({enabled:false,hour:2,minute:0,revision:0,last_run:null})});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/backup-schedule.js'),'utf8'),c);return {c,el,state,ui:c.BackupScheduleUI};
}
test('background schedule refresh preserves dirty values and original revision',async()=>{
 const h=setup();await h.ui.load();h.el('backup-plan-form').oninput();h.el('backup-plan-time').value='03:30';h.el('backup-plan-enabled').checked=true;
 h.c.dbRequest=async()=>({enabled:true,hour:6,minute:0,revision:1,last_run:null});await h.ui.load();assert.equal(h.el('backup-plan-time').value,'03:30');let payload;h.c.dbRequest=async(_p,_m,v)=>{payload=v;throw Error('conflict');};await h.el('backup-plan-form').onsubmit({preventDefault(){}});assert.equal(payload.revision,0);assert.equal(payload.hour,3);assert.match(h.el('backup-plan-feedback').textContent,/conflict/);
});
test('late schedule response after leaving the account is discarded',async()=>{
 const h=setup();let finish;h.c.dbRequest=()=>new Promise(r=>finish=r);const pending=h.ui.load();h.state.epoch++;h.ui.clear();finish({enabled:true,hour:2,minute:0,revision:7});await pending;assert.equal(h.el('backup-plan-state').textContent,'');
});
