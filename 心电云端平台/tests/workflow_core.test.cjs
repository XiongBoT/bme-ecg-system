const test=require('node:test'),assert=require('node:assert/strict');
const W=require('../web/workflow_core.js');
const response=(body,user='a',status=200)=>({ok:status<400,status,headers:{get:()=>user},json:async()=>body});

test('account change discards the response and clears the page',async()=>{
 let cleared=0;const c=W.client(async()=>response({private:'other'},'b'),()=>cleared++);c.set({id:'a'},'csrf');
 await assert.rejects(c.request('/api/workflow/tasks'),/账号/);assert.equal(cleared,1);assert.equal(c.user,null);
});
test('response that finishes parsing after logout is discarded',async()=>{
 let release;const c=W.client(async()=>({...response(null),json:()=>new Promise(r=>release=r)}),()=>{});c.set({id:'a'},'csrf');
 const request=c.request('/api/workflow/tasks');await Promise.resolve();c.clear();release({private:'old'});
 await assert.rejects(request,/状态/);
});
test('403 invalidates privilege and never exposes previous content',async()=>{
 let cleared=0;const c=W.client(async()=>response({detail:'forbidden'},'a',403),()=>cleared++);c.set({id:'a'},'csrf');
 await assert.rejects(c.request('/api/admin/operations'));assert.equal(cleared,1);
});
test('writes carry CSRF and JSON and do not persist data',async()=>{
 let options;const c=W.client(async(p,o)=>{options=o;return response({ok:true});},()=>{});c.set({id:'a'},'abc');
 await c.request('/api/workflow/preferences','PUT',{auto_model:true});
 assert.equal(options.headers['X-CSRF-Token'],'abc');assert.equal(JSON.parse(options.body).auto_model,true);assert.equal(options.cache,'no-store');
});
test('review cannot attach to a previous result or another record',()=>{
 const analysis={session_id:'s',source_digest:'d',analyzed_at:'t',analysis_status:'complete',task:{job_id:'j',status:'complete'}};
 const review={session_id:'s',basis:{analyses:{model:{digest:'d',analyzed_at:'t',status:'complete',job:{job_id:'j',status:'complete'}},physiology:{digest:'p',status:'not_run',analyzed_at:null,job:null}}}};
 const phys={session_id:'s',source_digest:'p',analysis_status:'not_run'};
 assert.equal(W.reviewMatches(review,'s',analysis,phys),true);
 assert.equal(W.reviewMatches(review,'other',analysis,phys),false);
 assert.equal(W.reviewMatches(review,'s',{...analysis,task:{job_id:'new',status:'complete'}},phys),false);
 assert.equal(W.reviewMatches(review,'s',{...analysis,analyzed_at:'new'},phys),false);
 assert.equal(W.reviewMatches(review,'s',analysis,null),false);
});
test('ineligible is described as insufficient evidence, not normal',()=>{
 assert.match(W.status('ineligible'),/条件不足/);assert.doesNotMatch(W.status('ineligible'),/正常/);
 assert.match(W.status('not_run'),/未开始/);
});
