const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(module){
  const elements=new Map(),stored=new Map();let seq=0;
  function element(id){
    if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,open:false,checked:false,children:[],dataset:{},listeners:{},
      addEventListener(n,fn){this.listeners[n]=fn;},setAttribute(){},removeAttribute(){},append(...nodes){this.children.push(...nodes);},
      replaceChildren(){this.children=[];this.textContent='';},querySelectorAll(){return [];},reset(){},
      showModal(){this.open=true;},close(){if(this.open){this.open=false;this.listeners.close?.();}}});
    return elements.get(id);
  }
  const document={documentElement:{dataset:{}},hidden:false,querySelectorAll:()=>[],addEventListener(){},
    createElement:tag=>element(tag+ ++seq),createElementNS:(_,tag)=>element(tag+ ++seq)};
  element('login-panel').hidden=true;
  const state={ready:false,epoch:1,user:null},context=vm.createContext({$:element,state,document,window:{},navigator:{},location:{},
    ECGHealth:require('../web/health_core.js'),localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},
    setInterval:()=>1,clearInterval(){},AbortSignal,URLSearchParams,console,confirm:()=>true,notice(){},fetch:async()=>({json:async()=>({health_assistant_version:1})})});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',module),'utf8'),context);
  return {element,state,context,stored};
}
test('application validates confirmation and suppresses double submission',async()=>{
  const h=harness('applications.js');h.element('apply-account').onclick();let calls=0,finish;
  h.element('application-username').value=' Student ';h.element('application-password').value='12345';h.element('application-confirm').value='54321';
  h.context.fetch=()=>{calls++;return new Promise(resolve=>finish=resolve);};
  const submit=()=>h.element('application-form').onsubmit({preventDefault(){}});
  await submit();assert.equal(calls,0);assert.match(h.element('application-feedback').textContent,/不一致/);
  h.element('application-confirm').value='12345';const pending=submit();await submit();assert.equal(calls,1);
  h.element('application-close').onclick();assert.equal(h.element('application-password').value,'');
  h.element('application-feedback').textContent='new form';finish({ok:true,json:async()=>({message:'old private request'})});await pending;
  assert.equal(h.element('application-feedback').textContent,'new form');assert.equal(h.element('username').value,'');
});
test('late pending application list cannot populate a different account',async()=>{
  const h=harness('applications.js');h.state.user={is_admin:true};h.element('admin-dialog').open=true;let finish,headersSeen;
  const body=new Promise(resolve=>finish=resolve),seen=new Promise(resolve=>headersSeen=resolve);
  h.context.api=async()=>({json:()=>{headersSeen();return body;}});
  const pending=h.context.AccountApplications.load();await seen;
  h.state.epoch++;h.state.user={is_admin:false};h.context.AccountApplications.clear();
  finish({applications:[{id:'a',username:'private applicant',created_at:1}]});await pending;
  assert.equal(h.element('application-list').children.length,0);assert.equal(h.element('application-review-feedback').textContent,'');
});
test('late health trends cannot reappear after logout',async()=>{
  const h=harness('health.js');h.state.ready=true;h.state.user={username:'alice'};
  h.context.api=async()=>({json:async()=>({measurements:[]})});await h.context.HealthAssistant.ready();
  let finish,headersSeen;const body=new Promise(resolve=>finish=resolve),seen=new Promise(resolve=>headersSeen=resolve);
  h.context.api=async()=>({json:()=>{headersSeen();return body;}});
  h.element('health-trends-open').onclick();await seen;
  h.state.epoch++;h.state.ready=false;h.context.HealthAssistant.clear();finish({total_records:999,buckets:[]});await Promise.resolve();await Promise.resolve();
  assert.equal(h.element('trend-total').textContent,'—');assert.equal(h.element('health-chart').children.length,0);
});
test('remember username never writes password to web storage',async()=>{
  const h=harness('health.js');h.state.user={id:'alice-id',username:'alice'};
  h.element('remember-account').checked=true;h.element('remember-password').checked=true;
  await h.context.HealthAssistant.loginSuccess({username:'alice',password:'private-test-password'});
  assert.equal(JSON.parse(h.stored.get('ecg-health-account-v1')).username,'alice');
  assert.ok(!JSON.stringify([...h.stored]).includes('private-test-password'));
  h.context.HealthAssistant.forget();assert.equal(h.stored.size,0);
});
