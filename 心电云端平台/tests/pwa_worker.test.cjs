const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function harness(){
 const handlers={},stored=new Map(),deleted=[];
 const cache={put:async(k,v)=>stored.set(typeof k==='string'?k:k.url,v),match:async k=>stored.get(k)?.clone()};
 const ctx=vm.createContext({URL,Request,Response,Promise,console,
  self:{location:{origin:'https://ecg.example'},addEventListener:(n,fn)=>handlers[n]=fn,
   clients:{claim:async()=>{}},skipWaiting:async()=>{ctx.skipped=true;}},
  caches:{open:async()=>cache,keys:async()=>['ecg-app-old','unrelated-app'],delete:async k=>deleted.push(k)},
  fetch:async()=>new Response('public fixture')});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/sw.js'),'utf8'),ctx);
 const event=async(n,extra={})=>{let promise;handlers[n]({...extra,waitUntil:p=>promise=p});await promise;};
 const fetchEvent=req=>{let response;handlers.fetch({request:req,respondWith:p=>response=p});return response;};
 return {ctx,stored,deleted,event,fetchEvent};
}
test('installation stores only a public offline page and declared icons',async()=>{
 const h=harness();await h.event('install');assert.ok(h.stored.has('/assets/offline.html'));
 for(const k of h.stored.keys())assert.ok(k==='/assets/offline.html'||k.startsWith('/assets/icons/'),k);
});
test('API, downloads, POST and other origins bypass the worker completely',()=>{
 const h=harness();
 for(const [url,method,mode] of [
 ['https://ecg.example/api/sessions','GET','cors'],['https://ecg.example/api/sessions/x/export','GET','navigate'],
 ['https://ecg.example/api/auth/login','POST','cors'],['https://other.example/','GET','navigate'],
 ['https://ecg.example/assets/app.js','GET','cors']]){
  assert.equal(h.fetchEvent({url,method,mode}),undefined);
 }
});
test('offline root navigation serves generic fallback without caching authenticated HTML',async()=>{
 const h=harness();await h.event('install');
 h.ctx.fetch=async()=>{throw new Error('offline');};
 const r=await h.fetchEvent({url:'https://ecg.example/',method:'GET',mode:'navigate'});
 assert.equal(await r.text(),'public fixture');assert.equal(h.stored.has('/'),false);
 h.ctx.fetch=async()=>new Response('private page');
 assert.equal(await (await h.fetchEvent({url:'https://ecg.example/',method:'GET',mode:'navigate'})).text(),'private page');
 assert.equal(h.stored.has('/'),false);
});
test('device management navigation uses the same anonymous offline fallback',async()=>{
 const h=harness();await h.event('install');h.ctx.fetch=async()=>{throw Error('offline');};
 const r=await h.fetchEvent({url:'https://ecg.example/devices',method:'GET',mode:'navigate'});
 assert.ok(r);assert.equal(await r.text(),'public fixture');assert.equal(h.stored.has('/devices'),false);
});
test('API errors are never replaced with an offline HTML success',async()=>{
 const h=harness();h.ctx.fetch=async()=>new Response('no access',{status:401});
 const r=await h.fetchEvent({url:'https://ecg.example/',method:'GET',mode:'navigate'});
 assert.equal(r.status,401);
});

test('admin navigation has an anonymous fallback and never caches management pages',async()=>{
 const h=harness();await h.event('install');h.ctx.fetch=async()=>{throw Error('offline');};
 for(const path of ['/admin','/admin/accounts?selected=demo','/database?owner_id=demo']){
  const r=await h.fetchEvent({url:'https://ecg.example'+path,method:'GET',mode:'navigate'});
  assert.ok(r);assert.equal(await r.text(),'public fixture');assert.equal(h.stored.has(path),false);
 }
 assert.equal(h.fetchEvent({url:'https://ecg.example/api/admin/console/overview',method:'GET',mode:'navigate'}),undefined);
});
test('missing fallback and server outage are reported without inventing a successful page',async()=>{
 const h=harness();h.ctx.fetch=async()=>new Response('down',{status:503});
 const r=await h.fetchEvent({url:'https://ecg.example/',method:'GET',mode:'navigate'});
 assert.equal(r.status,503);assert.match(await r.text(),/暂时无法连接/);
 assert.equal(h.stored.size,0);
});
test('activation removes only obsolete ECG caches; update is explicitly requested',async()=>{
 const h=harness();await h.event('activate');assert.deepEqual(h.deleted,['ecg-app-old']);
 assert.equal(h.ctx.skipped,undefined);await h.event('message',{data:{type:'unrelated'}});assert.equal(h.ctx.skipped,undefined);
 await h.event('message',{data:{type:'ECG_ACTIVATE_UPDATE'}});assert.equal(h.ctx.skipped,true);
});
