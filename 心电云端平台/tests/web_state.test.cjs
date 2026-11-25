// Isolated DOM/state regression probes; no browser, records or network access.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness() {
  const elements=new Map(); let sequence=0;
  const document={getElementById:element,querySelectorAll:()=>[],listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},
    createElement:tag=>element(tag+'-'+(++sequence)),activeElement:null,documentElement:{dataset:{}}};
  function element(id) {
    if(!elements.has(id)) elements.set(id,{textContent:'',hidden:false,value:'',width:100,dataset:{},attributes:{},children:[],listeners:{},
      addEventListener(name,fn){this.listeners[name]=fn;},showModal(){this.open=true;},
      classList:{add(){},remove(){},toggle(){}},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},
      replaceChildren(){this.children=[];this.textContent='';},reset(){},close(){this.open=false;this.onclose?.();},focus(){document.activeElement=this;},click(){return this.onclick?.() ?? this.listeners.click?.();},
      getBoundingClientRect(){return {width:0}},append(...children){this.children.push(...children);}});
    return elements.get(id);
  }
  const media={narrow:{matches:true,addEventListener(n,fn){this.changed=fn;}},standalone:{matches:false,addEventListener(){}}};
  const window={scrollY:0,scrollTo({top}){this.scrollY=top;},navigator:{standalone:false},addEventListener(){},
    matchMedia:q=>q.includes('max-width')?media.narrow:media.standalone};
  const context=vm.createContext({document,window,requestAnimationFrame:fn=>fn(),location:{href:''},
    sessionStorage:{getItem:()=>'',removeItem(){},setItem(){}},ResizeObserver:class{observe(){}},
    URLSearchParams,AbortSignal,console,confirm:()=>true,fetch:async()=>({ok:false}),setTimeout,clearTimeout,setInterval(){}});
  const root=path.join(__dirname,'..','web');
  vm.runInContext(fs.readFileSync(path.join(root,'experience_core.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'connection.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'desktop_core.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'devices.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'measurement.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'physiology.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),context);
  const source=fs.readFileSync(path.join(root,'workspace.js'),'utf8');
  vm.runInContext(source.slice(0,source.indexOf('initialize();setInterval')),context);
  return {context,element,media,document,state:vm.runInContext('state',context),
    loadMobile(){vm.runInContext(fs.readFileSync(path.join(root,'mobile.js'),'utf8'),context);},
    loadExperience(){vm.runInContext(fs.readFileSync(path.join(root,'experience.js'),'utf8'),context);}};
}
test('merged health workspace preserves task and admin navigation with account permissions',()=>{
  const h=harness();h.context.refresh=()=>{};h.context.location.search='?record=linked-record';
  h.context.enterWorkspace({user:{id:'admin',is_admin:true}});
  for(const id of ['manage-console','manage-operations','task-center','records-tasks'])assert.equal(h.element(id).hidden,false);
  assert.equal(h.state.filters.q,'linked-record');
  h.context.enterWorkspace({user:{id:'ordinary',is_admin:false}});
  assert.equal(h.element('manage-console').hidden,true);assert.equal(h.element('manage-operations').hidden,true);
  assert.equal(h.element('task-center').hidden,false);
  const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
  for(const id of ['manage-console','manage-operations','task-center','records-tasks','app-preferences','health-measure-open','apply-account'])assert.equal(html.split('id="'+id+'"').length-1,1);
});
test('switching account clears text, device status, forms and pagination before fetch',()=>{
  const h=harness();h.state.user={id:'alice'};
  for(const id of ['record-name','record-note','record-id','model-message','device-signal','session-count']) h.element(id).textContent='Alice private';
  h.context.clearAccount();
  for(const id of ['record-name','record-note','record-id','model-message']) assert.equal(h.element(id).textContent,'');
  assert.equal(h.element('content').hidden,true);assert.equal(h.element('session-count').textContent,'0');
  assert.equal(h.element('records-page').textContent,'1 / 1');
  assert.equal(h.element('qrs-count').textContent,'—');assert.equal(h.element('physiology-analyze').disabled,true);
  assert.ok(!h.element('device-signal').textContent.includes('Alice'));assert.equal(h.state.user,null);
});
test('late 401 body cannot log out a newer account',async()=>{
  const h=harness();h.state.auth=true;h.state.user={id:'alice'};
  let resolveBody,headersSeen;
  const body=new Promise(resolve=>resolveBody=resolve), seen=new Promise(resolve=>headersSeen=resolve);
  h.context.fetch=async()=>({ok:false,status:401,json:()=>{headersSeen();return body;}});
  const request=h.context.api('/api/sessions');await seen;
  h.state.epoch++;h.state.user={id:'bob'};resolveBody({detail:'expired'});
  await assert.rejects(request,/登录状态已改变/);assert.equal(h.state.user.id,'bob');
});
test('late filtered list cannot replace a newer filter result',async()=>{
  const h=harness();h.state.ready=true;let resolveList;
  h.context.api=async url=>({json:async()=>url.startsWith('/api/sessions')?new Promise(resolve=>resolveList=resolve):null});
  const pending=h.context.refresh();await Promise.resolve();await Promise.resolve();
  h.state.listEpoch++;h.state.sessions=[{session_id:'new-selection'}];resolveList({sessions:[{session_id:'old'}],total:1});
  await pending;assert.equal(h.state.sessions[0].session_id,'new-selection');
});
test('persistent task progress uses the server task field',()=>{
  const h=harness();h.state.selected='sid';
  h.context.renderAnalysis({session_id:'sid',analysis_status:'running',model_status:'ready',task:{stage:'计算中',processed:12,total:100}});
  assert.match(h.element('model-message').textContent,/12 \/ 100/);
  assert.equal(h.element('analyze').disabled,true);
});
test('another tab changing the account clears the previous workspace',async()=>{
  const h=harness();h.state.auth=true;h.state.user={id:'alice'};h.element('record-note').textContent='alice private';
  h.context.fetch=async()=>({ok:true,headers:{get:()=> 'bob'}});
  await assert.rejects(h.context.api('/api/sessions'),/登录账号已改变/);
  assert.equal(h.state.user,null);assert.equal(h.element('record-note').textContent,'');
  assert.equal(h.element('workspace-shell').hidden,true);
});

test('password confirmation mismatch never sends a request',async()=>{
  const h=harness();let called=false;
  h.context.jsonRequest=async()=>{called=true;};
  h.element('replacement-password').value='new-password-A';h.element('confirm-password').value='new-password-B';
  await h.element('password-form').onsubmit({preventDefault(){}});
  assert.equal(called,false);assert.match(h.element('password-error').textContent,/不一致/);
});
test('late password-change response does not log out a newer account',async()=>{
  const h=harness();h.state.user={id:'alice'};let finish;
  h.context.jsonRequest=()=>new Promise(resolve=>finish=resolve);
  h.element('replacement-password').value=h.element('confirm-password').value='new-password-A';
  const pending=h.element('password-form').onsubmit({preventDefault(){}});
  h.state.epoch++;h.state.user={id:'bob'};finish({ok:true});await pending;
  assert.equal(h.state.user.id,'bob');
});

function adminHarness(users=[],records=[]) {
  const h=harness();h.state.user={id:'admin',is_admin:true};
  h.context.api=async url=>({json:async()=>url.endsWith('/users')?{users}:{sessions:records}});
  return h;
}
function allText(node) {return node.textContent+' '+node.children.map(allText).join(' ');}
function userButton(h,label) {
  const flatten=node=>[node,...node.children.flatMap(flatten)];
  return flatten(h.element('user-list')).find(node=>node.textContent===label);
}
test('admin list filters by name status and role with bounded pages and honest unknown dates',async()=>{
  const users=Array.from({length:23},(_,i)=>({id:String(i),username:'user'+String(i).padStart(2,'0'),active:i!==1,is_admin:i===0,active_sessions:2}));
  const h=adminHarness(users);await h.element('admin').onclick();
  assert.equal(h.element('user-list').children.length,10);
  assert.match(h.element('admin-page').textContent,/1 \/ 3/);
  assert.match(allText(h.element('user-list')),/未记录/);
  assert.match(allText(h.element('user-list')),/有效登录/);
  h.element('admin-next').onclick();assert.match(h.element('admin-page').textContent,/2 \/ 3/);
  h.element('admin-query').value=' USER01 ';h.element('admin-query').oninput();
  assert.equal(h.element('user-list').children.length,1);
  h.element('admin-status-filter').value='active';h.element('admin-status-filter').onchange();
  assert.match(allText(h.element('user-list')),/没有符合/);
  h.element('admin-query').value='';h.element('admin-status-filter').value='all';h.element('admin-role-filter').value='admin';
  h.element('admin-role-filter').onchange();assert.equal(h.element('user-list').children.length,1);
  assert.equal(userButton(h,'停用'),undefined);assert.equal(userButton(h,'撤销登录'),undefined);
});
test('creating an account validates before sending and blocks duplicate submits',async()=>{
  const h=adminHarness();await h.element('admin').onclick();let calls=0,finish,body;
  h.context.jsonRequest=async()=>{calls++;return {username:'unexpected'};};
  const submit=()=>h.element('new-user-form').onsubmit({preventDefault(){}});
  h.element('new-username').value='bad name';h.element('new-password').value=h.element('new-password-confirm').value='Initial-test-9182!';
  await submit();assert.equal(calls,0);assert.match(h.element('new-user-error').textContent,/账号/);
  h.element('new-username').value=' New-User ';h.element('new-password-confirm').value='different';
  await submit();assert.equal(calls,0);assert.match(h.element('new-user-error').textContent,/不一致/);
  h.element('new-password-confirm').value='Initial-test-9182!';
  h.context.jsonRequest=(_,__,payload)=>{calls++;body=payload;return new Promise(resolve=>finish=resolve);};
  const pending=submit();await submit();assert.equal(calls,1);assert.equal(body.username,'new-user');
  assert.equal(h.element('new-user-submit').disabled,true);
  finish({username:'new-user'});await pending;
  assert.equal(h.element('new-password').value,'');assert.equal(h.element('new-password-confirm').value,'');
  assert.match(h.element('admin-success').textContent,/new-user/);
});
test('a failed unassigned-record request still leaves account management usable',async()=>{
  const h=adminHarness([{id:'a',username:'alice',active:true}]);
  h.context.api=async url=>{if(!url.endsWith('/users'))throw new Error('records offline');return {json:async()=>({users:[{id:'a',username:'alice',active:true}]})};};
  await h.element('admin').onclick();assert.match(allText(h.element('user-list')),/alice/);
  assert.match(h.element('unassigned-error').textContent,/records offline/);
  assert.equal(h.element('new-user-submit').disabled,false);
});
test('late management loads cannot overwrite a newer refresh or a new account',async()=>{
  const h=adminHarness();await h.element('admin').onclick();let finish;
  h.context.api=async url=>({json:()=>url.endsWith('/users')?new Promise(resolve=>finish=resolve):Promise.resolve({sessions:[]})});
  const old=h.context.loadAdmin();await Promise.resolve();await Promise.resolve();
  h.context.api=async url=>({json:async()=>url.endsWith('/users')?{users:[{id:'b',username:'newest',active:true}]}:{sessions:[]}});
  await h.context.loadAdmin();finish({users:[{id:'a',username:'outdated',active:true}]});await old;
  assert.match(allText(h.element('user-list')),/newest/);assert.doesNotMatch(allText(h.element('user-list')),/outdated/);
  h.context.api=async url=>({json:()=>url.endsWith('/users')?new Promise(resolve=>finish=resolve):Promise.resolve({sessions:[]})});
  const stale=h.context.loadAdmin();await Promise.resolve();await Promise.resolve();h.context.clearAccount();
  h.state.user={id:'bob'};finish({users:[{id:'a',username:'private-admin-data'}]});await stale;
  assert.equal(allText(h.element('user-list')).trim(),'');
});
test('closing and reopening admin clears secrets and ignores previous creation response',async()=>{
  const h=adminHarness();await h.element('admin').onclick();let finish;
  h.context.jsonRequest=()=>new Promise(resolve=>finish=resolve);
  h.element('new-username').value='alice';h.element('new-password').value=h.element('new-password-confirm').value='Initial-test-9182!';
  const old=h.element('new-user-form').onsubmit({preventDefault(){}});
  h.element('admin-dialog').close();assert.equal(h.element('new-password').value,'');
  await h.element('admin').onclick();h.element('new-username').value='next-user';
  finish({username:'alice'});await old;
  assert.equal(h.element('new-username').value,'next-user');assert.equal(h.element('admin-success').textContent,'');
  assert.equal(h.element('new-user-submit').disabled,false);
});
test('revoke login requires explicit confirmation and sends once without disabling the account',async()=>{
  const h=adminHarness([{id:'a',username:'alice',active:true,active_sessions:2}]);await h.element('admin').onclick();
  let calls=0,finish,request;h.context.confirm=()=>false;h.context.jsonRequest=(...args)=>{calls++;request=args;return new Promise(resolve=>finish=resolve);};
  await userButton(h,'撤销登录').onclick();assert.equal(calls,0);
  h.context.confirm=message=>{assert.match(message,/alice/);assert.match(message,/重新登录/);return true;};
  const button=userButton(h,'撤销登录'),pending=button.onclick();await button.onclick();assert.equal(calls,1);
  assert.equal(request[0],'/api/admin/users/a/revoke-sessions');assert.equal(request[1],'POST');
  finish({revoked_sessions:2});await pending;assert.match(h.element('admin-success').textContent,/2/);
});
test('successful creation remains reported when reloading the list fails and retry recovers',async()=>{
  const h=adminHarness();await h.element('admin').onclick();
  h.context.jsonRequest=async()=>({username:'alice'});h.context.api=async()=>{throw new Error('refresh unavailable');};
  h.element('new-username').value='alice';h.element('new-password').value=h.element('new-password-confirm').value='Initial-test-9182!';
  await h.element('new-user-form').onsubmit({preventDefault(){}});
  assert.match(h.element('admin-success').textContent,/已创建/);assert.match(h.element('admin-error').textContent,/refresh unavailable/);
  h.context.api=async url=>({json:async()=>url.endsWith('/users')?{users:[{id:'a',username:'alice',active:true}]}:{sessions:[]}});
  await h.element('admin-refresh').onclick();assert.match(allText(h.element('user-list')),/alice/);assert.equal(h.element('admin-error').textContent,'');
});
test('password reset refreshes effective login counts and reports success separately',async()=>{
  const h=adminHarness([{id:'a',username:'alice',active:true,active_sessions:2}]);await h.element('admin').onclick();
  userButton(h,'重置密码').onclick();let calls=0,finish;
  h.context.jsonRequest=()=>{calls++;return new Promise(resolve=>finish=resolve);};
  h.element('replacement-password').value=h.element('confirm-password').value='Replacement-9182!';
  const pending=h.element('password-form').onsubmit({preventDefault(){}});
  const duplicate=h.element('password-form').onsubmit({preventDefault(){}});
  assert.equal(calls,1);
  h.context.api=async url=>({json:async()=>url.endsWith('/users')?{users:[{id:'a',username:'alice',active:true,active_sessions:0}]}:{sessions:[]}});
  finish({active:true});await pending;await duplicate;
  assert.match(h.element('admin-success').textContent,/重置 alice/);assert.match(allText(h.element('user-list')),/有效登录：0/);
  assert.equal(h.element('replacement-password').value,'');
});
test('closing the password editor clears secrets and successful self change still signs out',async()=>{
  const h=harness();h.state.user={id:'a'};h.context.openPasswordEditor();let finish;
  h.context.jsonRequest=()=>new Promise(resolve=>finish=resolve);
  h.element('replacement-password').value=h.element('confirm-password').value='Replacement-9182!';
  const pending=h.element('password-form').onsubmit({preventDefault(){}});
  h.element('password-dialog').close();assert.equal(h.element('replacement-password').value,'');
  h.context.openPasswordEditor();h.element('replacement-password').value='new draft';
  finish({ok:true});await pending;
  // Password change succeeded: old account is cleared, even if the editor was reopened.
  assert.equal(h.state.user,null);assert.equal(h.element('replacement-password').value,'');
});
test('a mutation completed after reopening refreshes current state without replacing a new draft',async()=>{
  const h=adminHarness([{id:'a',username:'alice',active:true}]);await h.element('admin').onclick();let finish;
  h.context.jsonRequest=()=>new Promise(resolve=>finish=resolve);
  const old=userButton(h,'停用').onclick();h.element('admin-dialog').close();await h.element('admin').onclick();
  assert.match(allText(h.element('user-list')),/可登录/);h.element('new-username').value='next-draft';
  h.context.api=async url=>({json:async()=>url.endsWith('/users')?{users:[{id:'a',username:'alice',active:false}]}:{sessions:[]}});
  finish({active:false});await old;
  assert.match(allText(h.element('user-list')),/已停用/);assert.equal(h.element('new-username').value,'next-draft');
  assert.equal(h.element('admin-success').textContent,'');
});
test('account filtering keeps a selected unassigned recipient and does not invent an empty success on failure',async()=>{
  const h=adminHarness([{id:'a',username:'alice',active:true}],[{session_id:'old-record'}]);await h.element('admin').onclick();
  const assignment=h.element('unassigned-list').children[0],select=assignment.children[1];select.value='a';
  h.element('admin-query').value='a';h.element('admin-query').oninput();
  assert.equal(h.element('unassigned-list').children[0],assignment);assert.equal(select.value,'a');
  h.context.api=async url=>{if(!url.endsWith('/users'))throw new Error('records failed');return {json:async()=>({users:[]})};};
  await h.context.loadAdmin();h.element('admin-query').oninput();
  assert.equal(allText(h.element('unassigned-list')).trim(),'');assert.match(h.element('unassigned-error').textContent,/records failed/);
});

test('initial connection failure can be retried without leaving login disabled',async()=>{
  const h=harness();h.context.fetch=async()=>{throw new TypeError('Failed to fetch');};
  await h.context.initialize();assert.equal(h.element('login-submit').disabled,true);
  h.context.fetch=async url=>({ok:true,json:async()=>url.endsWith('/config')?{enabled:true}:{user:{id:'alice',username:'alice'},csrf_token:'test'},headers:{get:()=>null}});
  h.context.refresh=async()=>{};
  await h.context.initialize();assert.equal(h.element('login-submit').disabled,false);
  assert.equal(h.state.user.id,'alice');assert.equal(h.element('workspace-shell').hidden,false);
});

test('a failed authentication probe is not presented as an ordinary signed-out session',async()=>{
  const h=harness();h.context.fetch=async url=>{
    if(url.endsWith('/config'))return {ok:true,json:async()=>({enabled:true})};
    throw new TypeError('Failed to fetch');
  };
  await h.context.initialize();assert.match(h.element('login-error').textContent,/连接|网络|服务/);
  assert.equal(h.element('login-submit').disabled,true);
});

test('late login failure cannot overwrite a newer account login panel',async()=>{
  const h=harness();let reject;
  h.context.jsonRequest=()=>new Promise((_,r)=>reject=r);
  const pending=h.element('login-form').onsubmit({preventDefault(){}});
  h.state.epoch++;h.element('login-error').textContent='new account message';
  reject(new Error('old failure'));await pending;
  assert.equal(h.element('login-error').textContent,'new account message');
});

test('invalid date range retains prior results and makes no request',()=>{
  const h=harness();let reloaded=0;h.context.reloadList=()=>reloaded++;
  h.state.filters={q:'previous'};h.state.page=2;
  h.element('date-from').value='2026-11-23';h.element('date-to').value='2026-11-01';
  h.element('filters').onsubmit({preventDefault(){}});
  assert.equal(reloaded,0);assert.equal(h.state.filters.q,'previous');assert.equal(h.state.page,2);
  assert.equal(h.element('filter-error').hidden,false);
});
test('accepted mobile filter collapses the form without clearing the selected condition',()=>{
  const h=harness();h.loadMobile();let reloads=0;h.context.reloadList=()=>reloads++;
  h.element('query').value='  resting  ';h.element('trash-filter').value='false';h.element('filter-panel').open=true;
  h.element('filters').onsubmit({preventDefault(){}});
  assert.equal(h.state.filters.q,'resting');assert.equal(h.element('filter-panel').open,false);
  assert.match(h.element('filter-summary').textContent,/1/);assert.equal(reloads,1);
});
test('polling mobile records does not fetch waves or navigate to results',async()=>{
  const h=harness();h.loadMobile();h.state.ready=true;let details=0;
  h.context.loadWave=h.context.loadAnalysis=async()=>details++;
  h.context.api=async url=>({json:async()=>url.startsWith('/api/sessions')?{total:1,sessions:[{session_id:'first'}]}:{devices:[]}});
  await h.context.refresh();
  assert.equal(h.state.selected,'first');assert.equal(details,0);
  assert.equal(h.element('workspace-shell').dataset.mobileView,'records');assert.equal(h.element('nav-records').attributes['aria-current'],'page');
  h.element('sessions').children[0].onclick();
  assert.equal(h.element('workspace-shell').dataset.mobileView,'results');assert.equal(details,2);
});
test('account view skips detail polling; returning to results refreshes and preserves record selection',()=>{
  const h=harness();h.loadMobile();h.state.ready=true;h.state.selected='one';let details=0;
  h.context.loadWave=h.context.loadAnalysis=()=>details++;
  h.element('nav-account').onclick();assert.equal(h.context.MobileUI.needsDetail(),false);
  h.context.MobileUI.openResult();assert.equal(h.state.selected,'one');assert.equal(details,2);
  assert.equal(h.element('nav-records').attributes['aria-current'],'page');
  assert.equal(h.document.activeElement,h.element('results-heading'));
});
test('empty selection cannot open results and disappearance returns mobile to records',()=>{
  const h=harness();h.loadMobile();h.context.MobileUI.openResult();
  assert.equal(h.element('workspace-shell').dataset.mobileView,'records');
  h.state.selected='one';h.context.MobileUI.openResult();h.context.selectSession(null);
  assert.equal(h.element('workspace-shell').dataset.mobileView,'records');assert.equal(h.context.MobileUI.openResult(),false);
});
test('account cleanup removes mobile errors and navigation from the previous account',()=>{
  const h=harness();h.loadMobile();h.element('nav-account').onclick();h.context.detailFeedback('private error',true);
  h.element('filter-error').textContent='old error';h.context.clearAccount();
  assert.equal(h.element('workspace-shell').dataset.mobileView,'records');
  assert.equal(h.element('detail-message').textContent,'');assert.equal(h.element('detail-feedback').hidden,true);
  assert.equal(h.element('filter-error').textContent,'');assert.equal(h.context.MobileUI.openResult(),false);
});
test('identical list updates retain the actual button and keyboard focus',()=>{
  const h=harness();h.state.sessions=[{session_id:'one',name:'A'}];h.state.total=1;
  h.context.renderList();const button=h.element('sessions').children[0];button.focus();
  h.context.renderList();assert.equal(h.element('sessions').children[0],button);assert.equal(h.document.activeElement,button);
  h.state.sessions[0].name='B';h.context.renderList();
  assert.notEqual(h.element('sessions').children[0],button);assert.equal(h.document.activeElement,h.element('sessions').children[0]);
});
test('failed wave provides retry and selecting another record resets the disabled retry button',async()=>{
  const h=harness();h.state.selected='one';h.context.api=async()=>{throw Error('unreachable');};
  await h.context.loadWave();assert.equal(h.element('detail-retry').hidden,false);assert.match(h.element('detail-message').textContent,/重试/);
  h.element('detail-retry').disabled=true;h.context.selectSession('two');assert.equal(h.element('detail-retry').disabled,false);
});
test('late wave error cannot replace a newer selection loading message',async()=>{
  const h=harness();let fail;h.state.selected='one';h.context.api=()=>new Promise((resolve,reject)=>fail=reject);
  const request=h.context.loadWave();h.context.selectSession('two');fail(Error('old error'));await request;
  assert.equal(h.element('detail-retry').hidden,true);assert.doesNotMatch(h.element('detail-message').textContent,/old error/);
});
test('desktop resize restores detail refresh and opens the filter form',()=>{
  const h=harness();h.loadMobile();h.state.ready=true;h.state.selected='one';let details=0;
  h.context.loadWave=h.context.loadAnalysis=()=>details++;
  h.media.narrow.matches=false;h.media.narrow.changed();
  assert.equal(h.context.MobileUI.needsDetail(),true);assert.equal(details,2);assert.equal(h.element('filter-panel').open,true);
});
test('Android export passes only record and user identity to the system save flow',async()=>{
  const h=harness();h.document.documentElement.dataset.nativeApp='android';h.state.selected='session_1';h.state.user={id:'a'.repeat(32)};
  let called=false;h.context.api=()=>{called=true;};await h.element('download').onclick();
  assert.equal(called,false);assert.equal(h.context.location.href,'ecg-export://download/session_1?user='+'a'.repeat(32));
});

test('result chapter navigation moves focus as well as the visible scroll position',()=>{
  const h=harness();let click,scrolled=false,prevented=false;
  h.document.querySelectorAll=selector=>selector==='.result-shortcuts a'?[{
    hash:'#physiology-panel',addEventListener(event,handler){if(event==='click')click=handler;}
  }]:[];
  const target=h.element('physiology-panel');target.scrollIntoView=()=>scrolled=true;
  h.loadMobile();click({preventDefault(){prevented=true;}});
  assert.equal(h.document.activeElement,target);assert.equal(target.attributes.tabindex,'-1');
  assert.equal(scrolled,true);assert.equal(prevented,true);
  target.hidden=true;scrolled=false;prevented=false;
  click({preventDefault(){prevented=true;}});
  assert.equal(scrolled,false);assert.equal(prevented,false);
});

test('phone canvas uses readable colors while retaining identical signal coordinates',()=>{
  const h=harness(),paths=[],colors=[];
  const canvas=h.element('chart');canvas.getBoundingClientRect=()=>({width:350,height:240});
  const c=new Proxy({}, {get(target,key){
    if(key==='moveTo'||key==='lineTo')return (...args)=>paths.push([key,...args]);
    return target[key] || (()=>{});
  },set(target,key,value){target[key]=value;if(key==='strokeStyle')colors.push(value);return true;}});
  canvas.getContext=()=>c;h.state.selected='one';
  h.state.wave={session:{session_id:'one'},start_sample:0,end_sample:720,points:[[0,1800],[360,2300],[720,1900]]};
  h.context.draw();const phone=JSON.stringify(paths);assert.ok(colors.includes('#087f71'));
  paths.length=colors.length=0;h.media.narrow.matches=false;h.context.draw();
  assert.ok(colors.includes('#5ce2af'));assert.equal(JSON.stringify(paths),phone);
  assert.equal(h.state.wave.points[1][1],2300);
});

test('device tab remains reachable without a measurement and preserves the selected record',()=>{
  const h=harness();h.loadMobile();h.state.selected=null;
  h.element('nav-devices').onclick();assert.equal(h.element('workspace-shell').dataset.mobileView,'devices');
  assert.equal(h.document.activeElement,h.element('devices-heading'));assert.equal(h.context.MobileUI.needsDetail(),false);
  h.state.selected='one';h.element('nav-records').onclick();assert.equal(h.state.selected,'one');
});
test('first-use guide opens for a new account, not for empty search results',()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.total=0;h.state.sessions=[];
  h.context.UserExperience.listUpdated();assert.equal(h.element('first-steps').open,true);
  h.context.clearAccount();h.state.filters={q:'no match'};
  h.context.UserExperience.listUpdated();assert.equal(h.element('first-steps').open,false);
});
test('quick dates keep existing search/device filters and reset pagination',()=>{
  const h=harness();h.loadMobile();h.loadExperience();let reloaded=0;h.context.reloadList=()=>reloaded++;
  h.element('query').value='rest';h.element('filter-device').value='device-1';h.element('trash-filter').value='false';h.state.page=4;
  h.context.UserExperience.quickRange(7);
  assert.equal(h.state.filters.q,'rest');assert.equal(h.state.filters.device_id,'device-1');assert.equal(h.state.page,0);
  assert.ok(h.state.filters.started_from);assert.ok(h.state.filters.started_before);assert.equal(reloaded,1);
});
test('refresh failure retains timestamps but marks previously read content as stale',()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.context.UserExperience.listUpdated();h.context.UserExperience.detailUpdated();
  const before=h.element('records-updated').textContent.replace('列表更新于 ','');
  h.context.UserExperience.listFailed();h.context.UserExperience.detailFailed();
  assert.ok(h.element('records-updated').textContent.includes(before));assert.match(h.element('result-updated').textContent,/上次读取/);
  h.context.clearAccount();assert.doesNotMatch(h.element('records-updated').textContent,/更新失败/);
});
test('a report captures the selected window, and account switching destroys the snapshot',()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.selected='one';h.state.user={id:'alice',username:'Alice'};
  h.state.wave={session:{session_id:'one',name:'Private note',source:'serial',sample_count:1800,source_status:'complete',upload_status:'complete'},points:[[0,1]],start_sample:360,end_sample:720};
  const create=h.document.createElement;let background;
  h.document.createElement=tag=>{const e=create(tag);if(tag==='canvas'){
    const context={fillRect(){background=this.fillStyle;},drawImage(){}};e.getContext=()=>context;e.toDataURL=()=> 'data:image/png;base64,AAAA';
  }return e;};
  h.context.UserExperience.openReport();const report=h.context.UserExperience.printDocument();
  assert.ok(report.includes('Private note'));assert.match(report,/1.0–2.0 秒/);assert.match(report,/完整原始数据请导出 CSV/);
  assert.ok(report.includes('data:image/png;base64,AAAA'));assert.equal(background,'#fbfdfc');
  h.context.clearAccount();assert.equal(h.context.UserExperience.printDocument(),null);assert.equal(h.element('report-rows').children.length,0);assert.equal(h.element('report-name').textContent,'');
});
test('changing record invalidates a report before any replacement data is loaded',()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.selected='one';
  h.state.wave={session:{session_id:'one'},points:[]};h.context.UserExperience.openReport();
  h.context.selectSession('two');assert.equal(h.context.UserExperience.printDocument(),null);assert.equal(h.element('report-dialog').open,false);
});
test('device page does not expose another users current acquisition signal',()=>{
  const h=harness();h.loadMobile();h.loadExperience();
  h.context.renderDevices({devices:[{device_id:'one',connection:'online',state:'other_user',signal_text:'Other private state'}]});
  const card=h.element('device-list').children[0];assert.ok(!card.children.some(c=>c.textContent.includes('Other private state')));
  h.context.clearAccount();assert.equal(h.element('device-list').children.length,0);
});
test('password visibility resets when account/login state is cleared',()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.element('password').type='password';
  h.element('toggle-password').click();assert.equal(h.element('password').type,'text');
  h.context.clearAccount();assert.equal(h.element('password').type,'password');assert.equal(h.element('toggle-password').attributes['aria-pressed'],'false');
});
test('a failed analysis refresh cannot retain a completed result in summary or report',async()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.selected='one';h.state.analysis={session_id:'one',analysis_status:'complete'};
  h.context.api=async()=>{throw new Error('offline');};await h.context.loadAnalysis();
  assert.equal(h.state.analysis.analysis_status,'unavailable');assert.equal(h.element('model-result').hidden,true);assert.equal(h.element('analyze').disabled,true);
});
test('pull to refresh requires the top of records, a vertical gesture, and release',async()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.ready=true;let count=0;h.context.refresh=async()=>count++;
  const target={closest:()=>null},start={touches:[{clientX:10,clientY:20}],target};
  h.document.listeners.touchstart(start);h.document.listeners.touchmove({touches:[{clientX:10,clientY:115}]});h.document.listeners.touchend();
  await Promise.resolve();assert.equal(count,1);
  h.context.window.scrollY=50;h.document.listeners.touchstart(start);h.document.listeners.touchmove({touches:[{clientX:10,clientY:115}]});h.document.listeners.touchend();
  assert.equal(count,1);
});
test('latest-record shortcut reloads the first page rather than opening an old page head',async()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.page=2;h.state.sessions=[{session_id:'old-page'}];
  h.context.loadWave=h.context.loadAnalysis=()=>{};
  h.context.refresh=async()=>{assert.equal(h.state.page,0);h.state.sessions=[{session_id:'latest'}];};
  await h.element('latest-record').click();assert.equal(h.state.selected,'latest');
  assert.equal(h.element('workspace-shell').dataset.mobileView,'results');
});
test('device polling preserves the focused record button',()=>{
  const h=harness();h.loadMobile();h.loadExperience();const payload={devices:[{device_id:'device-1',connection:'online',state:'standby'}]};
  h.context.renderDevices(payload);h.element('device-list').children[0].children[4].focus();
  h.context.renderDevices(payload);assert.equal(h.document.activeElement.dataset.deviceId,'device-1');
  assert.equal(h.document.activeElement,h.element('device-list').children[0].children[4]);
});
test('pull during automatic refresh does not duplicate requests or leave a release prompt stuck',async()=>{
  const h=harness();h.loadMobile();h.loadExperience();h.state.ready=true;h.state.busy={};let calls=0;h.context.refresh=()=>calls++;
  await h.context.UserExperience.refreshManually();assert.equal(calls,0);assert.match(h.element('pull-feedback').textContent,/同步/);
  h.context.UserExperience.listUpdated();assert.equal(h.element('pull-feedback').textContent,'');
});
