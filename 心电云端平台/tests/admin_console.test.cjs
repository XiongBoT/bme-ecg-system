const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const elements=new Map(),node=()=>({textContent:'',hidden:false,children:[],attributes:{},append(...v){this.children.push(...v)},replaceChildren(...v){this.children=v},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},classList:{add(){}},addEventListener(){}});
 const el=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id)};
 const context=vm.createContext({document:{getElementById:el,createElement:node,createElementNS:node,querySelector:()=>null,body:{dataset:{}},hidden:false,addEventListener(){}},window:{location:{pathname:'/admin',search:''},addEventListener(){},history:{replaceState(){}}},URLSearchParams,AbortSignal,setInterval(){},console,fetch:async()=>{}});
 const file=path.join(__dirname,'../web/admin-common.js');assert.ok(fs.existsSync(file),'shared admin session missing');
 vm.runInContext(fs.readFileSync(file,'utf8'),context);
 return {context,ui:context.window.AdminUI,el};
}
test('admin session rejects a different account before reading the body',async()=>{
 const h=harness();let cleared=0,read=false;const session=new h.ui.Session(()=>cleared++);session.user={id:'a'};
 h.context.fetch=async()=>({headers:{get:()=> 'b'},status:200,ok:true,json:async()=>{read=true;return {secret:true}}});
 await assert.rejects(session.request('/api/admin/console/overview'),/账号/);assert.equal(read,false);assert.equal(cleared,1);assert.equal(session.user,null);
});
test('late JSON after invalidation cannot restore an admin result',async()=>{
 const h=harness();const session=new h.ui.Session(()=>{});session.user={id:'a'};let resolve,started;const ready=new Promise(r=>started=r);
 h.context.fetch=async()=>({headers:{get:()=> 'a'},status:200,ok:true,json:()=>{started();return new Promise(r=>resolve=r)}});
 const pending=session.request('/api/admin/console/overview');await ready;session.clear('退出');resolve({private:true});
 await assert.rejects(pending,/登录状态/);assert.equal(session.user,null);
});
test('permission failure clears state even when identity header is absent',async()=>{
 const h=harness();let cleared=0;const session=new h.ui.Session(()=>cleared++);session.user={id:'a'};session.csrf='old';
 h.context.fetch=async()=>({headers:{get:()=>null},status:403,ok:false,json:async()=>({detail:'禁止'})});
 await assert.rejects(session.request('/api/admin/console/accounts'));assert.equal(cleared,1);assert.equal(session.csrf,'');
});
test('session initialization refuses ordinary users and never marks them ready',async()=>{
 const h=harness();const session=new h.ui.Session(()=>{});
 h.context.fetch=async()=>({headers:{get:()=> 'u'},status:200,ok:true,json:async()=>({user:{id:'u',is_admin:false},csrf_token:'secret'})});
 await assert.rejects(session.identify(),/管理员/);assert.equal(session.user,null);
});
test('query links encode identifiers without allowing a new destination',()=>{
 const h=harness();const href=h.ui.link('/database',{device_id:'x&owner_id=other',q:'<script>'});
 const url=new URL(href,'https://example.test');assert.equal(url.pathname,'/database');assert.equal(url.searchParams.get('device_id'),'x&owner_id=other');assert.equal(url.searchParams.get('owner_id'),null);
});
