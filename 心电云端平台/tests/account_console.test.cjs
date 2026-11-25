const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const elements=new Map(),make=()=>({textContent:'',value:'',hidden:false,disabled:false,open:false,children:[],listeners:{},append(...v){this.children.push(...v)},replaceChildren(...v){this.children=[...v]},reset(){},showModal(){this.open=true},close(){this.open=false;this.listeners.close?.()},addEventListener(k,fn){this.listeners[k]=fn},setAttribute(){},removeAttribute(){},classList:{add(){}}});
 const el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id)};
 const context=vm.createContext({document:{getElementById:el,createElement:make,querySelector:()=>null,querySelectorAll:()=>[],body:{dataset:{}},hidden:false,addEventListener(){}},window:{location:{pathname:'/admin/accounts',search:''},addEventListener(){},history:{replaceState(){}}},setInterval(){},URLSearchParams,AbortSignal,console,fetch:async()=>{},confirm:()=>true});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/admin-common.js'),'utf8'),context);
 const file=path.join(__dirname,'../web/account-manager.js');assert.ok(fs.existsSync(file),'dedicated account page missing');
 vm.runInContext(fs.readFileSync(file,'utf8').replace(/initializeAccounts\(\);\s*$/,''),context);
 const state=vm.runInContext('accountUI',context);state.session.user={id:'admin',is_admin:true};
 return {context,el,state};
}
test('older account search cannot replace newer results',async()=>{
 const h=harness();let release,calls=0;h.state.session.request=async()=>++calls===1?new Promise(r=>release=r):({accounts:[],total:0});
 const old=h.context.loadAccounts();await h.context.loadAccounts();release({accounts:[{id:'old',username:'old'}],total:99});await old;
 assert.equal(h.state.total,0);assert.doesNotMatch(h.el('accounts-page').textContent,/99/);
});
test('account detail response cannot replace a later selection',async()=>{
 const h=harness();let release;h.state.session.request=async url=>url.endsWith('/old')?new Promise(r=>release=r):url.includes('/devices?')?{devices:[],total:0}:{account:{id:'new',username:'new',active:true,record_count:1,device_count:0}};
 const old=h.context.selectAccount('old');await h.context.selectAccount('new');release({account:{id:'old',username:'old'}});await old;
 assert.equal(h.state.selected.id,'new');assert.equal(h.el('account-detail-title').textContent,'new');
});
test('creating account validates password confirmation before any request',async()=>{
 const h=harness();let calls=0;h.state.session.request=async()=>{calls++;};h.el('account-new-name').value='new-user';h.el('account-new-password').value='Example-test-812!';h.el('account-new-confirm').value='different';
 await h.el('account-create-form').onsubmit({preventDefault(){}});assert.equal(calls,0);assert.match(h.el('account-create-error').textContent,/一致/);
});
test('successful change remains visible if list refresh fails',async()=>{
 const h=harness();h.state.session.request=async()=>{throw new Error('断网')};
 await h.context.accountMutation(async()=>({ok:true}),'操作成功');assert.match(h.el('accounts-success').textContent,/操作成功/);assert.match(h.el('accounts-error').textContent,/断网/);
});
test('permission clearing removes details, passwords and selection',()=>{
 const h=harness();h.state.selected={id:'private'};h.el('account-new-password').value='secret';h.el('account-password-value').value='secret';h.state.session.clear('已退出');
 assert.equal(h.state.selected,null);assert.equal(h.el('account-new-password').value,'');assert.equal(h.el('account-password-value').value,'');assert.equal(h.el('accounts-content').hidden,true);
});
