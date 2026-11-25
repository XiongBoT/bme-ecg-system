const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const elements=new Map(),make=()=>({textContent:'',value:'',hidden:false,disabled:false,children:[],listeners:{},append(...v){this.children.push(...v)},replaceChildren(...v){this.children=[...v]},reset(){},showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()},addEventListener(k,fn){this.listeners[k]=fn},setAttribute(){},removeAttribute(){}});
 const el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id)};
 const ctx=vm.createContext({document:{getElementById:el,createElement:make,querySelectorAll:()=>[],body:{dataset:{}},addEventListener(){}},window:{addEventListener(){},location:{pathname:'/devices',search:''},history:{replaceState(){}}},setInterval(){},AbortSignal,URL,URLSearchParams,Blob,setTimeout,console,fetch:async()=>{},confirm:()=>true});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/admin-common.js'),'utf8'),ctx);
 let source=fs.readFileSync(path.join(__dirname,'../web/device-manager.js'),'utf8');source=source.replace(/initializeManager\(\);\s*$/,'');vm.runInContext(source,ctx);
 return {ctx,el,state:vm.runInContext('manager',ctx)};
}
test('closing credential dialog erases the secret from state and text',()=>{
 const h=harness();h.ctx.showCredentials({device_id:'pi',token:'temporary-test-secret'});h.el('device-credentials').close();
 assert.equal(h.state.credentials,null);assert.equal(h.el('credential-value').value,'');
});
test('different signed-in user clears the editor and credentials before response data',async()=>{
 const h=harness();h.state.user={id:'admin-a'};h.ctx.showCredentials({token:'old-private'});
 h.ctx.fetch=async()=>({headers:{get:()=> 'admin-b'},ok:true,json:async()=>({devices:[]})});
 await assert.rejects(h.ctx.managerRequest('/api/admin/devices'),/账号/);
 assert.equal(h.state.credentials,null);assert.equal(h.el('manager-content').hidden,true);
});
test('late body from old account cannot repopulate new account',async()=>{
 const h=harness();let resolve,seen;const wait=new Promise(r=>seen=r);
 h.ctx.fetch=async()=>({headers:{get:()=>null},ok:true,status:200,json:()=>{seen();return new Promise(r=>resolve=r)}});
 const request=h.ctx.managerRequest('/api/admin/devices');await wait;h.state.epoch++;resolve({devices:[{name:'private'}]});
 await assert.rejects(request,/登录状态已改变/);
});
test('initial permission failure replaces the loading message with a useful error',async()=>{
 const h=harness();h.el('manager-notice').textContent='正在检查登录…';
 h.ctx.fetch=async()=>({headers:{get:()=>null},ok:false,status:403,json:async()=>({detail:'需要用户登录'})});
 await h.ctx.initializeManager();assert.doesNotMatch(h.el('manager-notice').textContent,/正在检查/);
});

test('session recheck erases credentials when another page has signed out',async()=>{
 const h=harness();h.state.user={id:'admin-a',is_admin:true};h.ctx.showCredentials({token:'old-private'});
 h.ctx.fetch=async()=>({headers:{get:()=>null},ok:false,status:401,json:async()=>({detail:'需要登录'})});
 assert.equal(await h.ctx.recheckManagerSession(),false);
 assert.equal(h.state.credentials,null);assert.equal(h.el('device-credentials').open,false);
});

test('download rechecks the session before exposing a saved credential',async()=>{
 const h=harness();h.state.user={id:'admin-a',is_admin:true};h.ctx.showCredentials({token:'old-private'});
 h.ctx.fetch=async()=>({headers:{get:()=> 'admin-b'},ok:true,status:200,json:async()=>({user:{id:'admin-b',is_admin:true}})});
 await h.el('download-credentials').onclick();
 assert.equal(h.state.credentials,null);assert.equal(h.el('manager-content').hidden,true);
});

test('a rejected write clears credentials even without an identity header',async()=>{
 const h=harness();h.state.user={id:'admin-a',is_admin:true};h.ctx.showCredentials({token:'old-private'});
 h.ctx.fetch=async()=>({headers:{get:()=>null},ok:false,status:403,json:async()=>({detail:'登录校验已失效'})});
 await assert.rejects(h.ctx.managerRequest('/api/admin/devices','POST',{}));
 assert.equal(h.state.credentials,null);assert.equal(h.el('device-credentials').open,false);
});

test('a late credential response cannot reopen a dialog while the page is hidden',()=>{
 const h=harness();h.ctx.document.hidden=true;h.ctx.showCredentials({token:'late-private'});
 assert.equal(h.state.credentials,null);assert.notEqual(h.el('device-credentials').open,true);
 assert.match(h.el('manager-notice').textContent,/重新/);
});

test('returning to the page does not restore credentials requested before hiding',()=>{
 const h=harness(),version=h.state.credentialEpoch;
 h.ctx.hideManagerCredentials();h.ctx.document.hidden=false;h.ctx.showCredentials({token:'late-private'},version);
 assert.equal(h.state.credentials,null);assert.notEqual(h.el('device-credentials').open,true);
});

test('older device search cannot overwrite a newer filter result',async()=>{
 const h=harness();h.state.user={id:'admin'};let release,calls=0;
 h.ctx.managerRequest=async url=>url==='/api/admin/users'?{users:[]}:++calls===1?new Promise(r=>release=r):{devices:[],total:0,account:null};
 const old=h.ctx.reloadDevices(null);await h.ctx.reloadDevices(null);release({devices:[{device_id:'old',name:'old',user_ids:[]}],total:99,account:null});await old;
 assert.equal(h.state.total,0);assert.equal(h.state.devices.length,0);
});

test('account context grant changes only the chosen account and device',async()=>{
 const h=harness();h.state.user={id:'admin'};h.state.account={id:'alice',username:'alice',active:true};h.state.accountId='alice';let call;
 h.ctx.managerRequest=async(path,method,payload)=>{call={path,method,payload};return {};};h.ctx.reloadDevices=async()=>{};
 await h.ctx.changeDeviceGrant({device_id:'pi-one',name:'终端',granted:false,active:true,legacy_shared:false});
 assert.equal(call.path,'/api/admin/console/accounts/alice/devices/pi-one');assert.equal(call.method,'PUT');assert.equal(call.payload.granted,true);
});

test('device detail late response cannot overwrite another selected device',async()=>{
 const h=harness();h.state.user={id:'admin'};h.state.users=[];let release;
 h.ctx.managerRequest=async url=>url.endsWith('/old')?new Promise(r=>release=r):{device:{device_id:'new',name:'新终端',active:true,user_ids:[]},recent_records:[]};
 const old=h.ctx.loadManagedDevice('old');await h.ctx.loadManagedDevice('new');release({device:{device_id:'old',name:'旧终端',active:true,user_ids:[]},recent_records:[]});await old;
 assert.equal(h.state.selected.device_id,'new');assert.equal(h.el('device-name').value,'新终端');
});

test('two submitted device searches use the latest query and matching URL',async()=>{
 const h=harness();h.state.user={id:'admin'};let release,requested=[],saved='';
 h.ctx.window.history.replaceState=(a,b,url)=>saved=url;
 h.ctx.managerRequest=async url=>{if(url==='/api/admin/users')return {users:[]};const q=new URL(url,'https://example.test').searchParams.get('q');requested.push(q);return q==='first'?new Promise(r=>release=r):{devices:[],total:0,account:null};};
 h.el('device-query').value='first';const old=h.el('device-search').onsubmit({preventDefault(){}});
 h.el('device-query').value='second';await h.el('device-search').onsubmit({preventDefault(){}});
 assert.deepEqual(requested,['first','second']);release({devices:[],total:2,account:null});await old;
 assert.equal(h.state.total,0);assert.equal(new URL(saved,'https://example.test').searchParams.get('q'),'second');
});

test('renaming a device omits unchanged grants including disabled users',async()=>{
 const h=harness();h.state.user={id:'admin'};h.state.users=[{id:'alice',active:false}];
 h.ctx.drawDeviceEditor({device_id:'pi-one',name:'旧名',user_ids:['alice'],active:true});
 h.ctx.document.querySelectorAll=()=>[{value:'alice'}];h.el('device-name').value='新名';let payload;
 h.ctx.managerRequest=async(p,m,v)=>{payload=v;return {};};h.ctx.reloadDevices=async()=>{};
 await h.el('device-form').onsubmit({preventDefault(){}});
 assert.equal(payload.name,'新名');assert.equal(payload.user_ids,undefined);
 assert.equal(h.el('device-users').children[0].children[0].checked,true);
});

test('grant success stays visible when selected device refresh fails',async()=>{
 const h=harness();h.state.user={id:'admin'};h.state.account={id:'alice',username:'alice',active:true};h.state.selected={device_id:'pi-one'};
 h.ctx.managerRequest=async(p,m)=>{if(m==='PUT')return {};throw Error('详情断网');};h.ctx.reloadDevices=()=>h.ctx.loadManagedDevice('pi-one');
 await h.ctx.changeDeviceGrant({device_id:'pi-one',name:'终端',granted:false,active:true});
 assert.match(h.el('manager-success').textContent,/授权已更新/);assert.match(h.el('manager-notice').textContent,/断网/);
});

test('legacy device name edit preserves sharing until explicit conversion',async()=>{
 const h=harness();h.state.user={id:'admin'};h.state.users=[{id:'alice',active:true}];
 h.ctx.drawDeviceEditor({device_id:'legacy',name:'共享终端',user_ids:[],legacy_shared:true,active:true});
 h.ctx.document.querySelectorAll=()=>[{value:'alice'}];let payload;
 h.ctx.managerRequest=async(p,m,v)=>{payload=v;return {};};h.ctx.reloadDevices=async()=>{};
 await h.el('device-form').onsubmit({preventDefault(){}});assert.equal(payload.user_ids,undefined);
 h.el('convert-legacy-device').checked=true;await h.el('device-form').onsubmit({preventDefault(){}});
 assert.deepEqual(Array.from(payload.user_ids),['alice']);assert.deepEqual(Array.from(payload.expected_user_ids),[]);assert.equal(payload.expected_legacy_shared,true);
});
