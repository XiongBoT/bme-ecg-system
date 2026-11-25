const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const W=require('../web/workflow_core.js');
function harness(){
 const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,reset(){}});return elements.get(id);}
 const state={auth:true,user:{id:'a'},epoch:1,selected:'s',ready:true};
 const result={session_id:'s',status:'pending',note:'',revision:0,context:'context',basis:{analyses:{model:{digest:'d',status:'not_run'},physiology:{digest:'p',status:'not_run'}}}};
 state.analysis={session_id:'s',source_digest:'d',analysis_status:'not_run'};state.physiology={session_id:'s',source_digest:'p',analysis_status:'not_run'};
 const ctx=vm.createContext({$:el,state,ECGWorkflow:W,text:(id,value)=>el(id).textContent=value,date:String,experience(){},api:async()=>({json:async()=>result}),console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/review.js'),'utf8'),ctx);
 return {ctx,el,state,result,review:ctx.RecordReview};
}
test('late review for another selection cannot populate the new record',async()=>{
 const h=harness();let resolve;h.ctx.api=async()=>({json:()=>new Promise(r=>resolve=r)});
 const request=h.review.load();await new Promise(r=>setImmediate(r));h.state.selected='other';h.review.clear();resolve({...h.result,note:'private old note'});await request;
 assert.equal(h.el('review-panel').hidden,true);assert.doesNotMatch(h.el('review-note').value,/private/);
});
test('same account logout while JSON arrives clears review and report association',async()=>{
 const h=harness();await h.review.load();h.state.epoch++;h.state.user=null;h.review.clear();
 assert.match(h.review.reportRows()[0][1],/未同步/);assert.equal(h.el('review-save').disabled,true);
});
test('report shows a stale review separately from algorithm results',async()=>{
 const h=harness();h.result.stale=true;h.result.status='viewed';h.result.note='noise';await h.review.load();
 const rows=h.review.reportRows();assert.match(rows[0][1],/已过期/);assert.equal(rows[1][1],'noise');
 h.state.analysis.source_digest='changed';assert.match(h.review.reportRows()[0][1],/未同步/);
});
test('mismatched displayed results cannot be marked reviewed',async()=>{
 const h=harness();await h.review.load();h.state.physiology=null;let sent=false;h.ctx.api=async()=>{sent=true;};
 await h.el('review-form').onsubmit({preventDefault(){}});assert.equal(sent,false);assert.match(h.el('review-feedback').textContent,/不一致/);
});
test('save blocks refresh until it finishes and restores controls on failure',async()=>{
 const h=harness();await h.review.load();h.el('review-status').value='viewed';let reject;
 h.ctx.api=()=>new Promise((_,r)=>reject=r);const request=h.el('review-form').onsubmit({preventDefault(){}});
 assert.equal(h.el('review-refresh').disabled,true);assert.equal(h.el('review-note').disabled,true);
 reject(new Error('conflict'));await request;assert.equal(h.el('review-refresh').disabled,false);assert.match(h.el('review-feedback').textContent,/conflict/);
});
