const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const settle=()=>new Promise(setImmediate),A='a'.repeat(64),B='b'.repeat(64);
function harness({build=A,pwa=true,native=false,response,offline=false}={}){
 const ids=new Map(),events={},docEvents={},intervals=new Map(),timeouts=new Map(),calls=[];
 let now=1000000,reloads=0,serial=0;
 function element(tag){return {tag,hidden:false,disabled:false,children:[],textContent:'',
   set id(v){this._id=v;ids.set(v,this);},get id(){return this._id;},
   setAttribute(k,v){this[k]=v;},appendChild(node){this.children.push(node);return node;},
   append(...nodes){this.children.push(...nodes);},addEventListener(n,fn){this[n]=fn;}};}
 if(pwa){const banner=element('div');banner.id='pwa-update';banner.hidden=true;const button=element('button');button.id='pwa-update-button';button.onclick=()=>reloads++;}
 const original=pwa?ids.get('pwa-update-button').onclick:null;
 const document={readyState:'complete',hidden:false,documentElement:{dataset:{nativeApp:native?'android':''}},
  querySelector:()=>build?{content:build}:null,getElementById:id=>ids.get(id)||null,createElement:element,
  body:{prepend(node){this.first=node;}},addEventListener:(n,f)=>docEvents[n]=f};
 const window={addEventListener:(n,f)=>events[n]=f};
 const context=vm.createContext({window,document,navigator:{onLine:!offline},location:{reload(){reloads++;}},
  Date:{now:()=>now},AbortController,TextDecoder,Uint8Array,console,
  setInterval:(f,ms)=>{const id=++serial;intervals.set(id,{f,ms});return id;},clearInterval:id=>intervals.delete(id),
  setTimeout:(f,ms)=>{const id=++serial;timeouts.set(id,{f,ms});return id;},clearTimeout:id=>timeouts.delete(id),
  fetch:async(url,options)=>{calls.push({url,options});return response?response():new Response(JSON.stringify({schema:1,web:{build_id:B}}),{headers:{'Content-Type':'application/json'}});}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/update_notice.js'),'utf8'),context);
 return {ids,events,docEvents,document,context,intervals,timeouts,calls,original,advance(ms){now+=ms;},get reloads(){return reloads;}};
}

test('compares against embedded page build, reuses PWA action and never reloads automatically',async()=>{
 const h=harness();await settle();
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,'/api/updates');
 assert.equal(h.calls[0].options.credentials,'omit');assert.equal(h.calls[0].options.redirect,'error');
 assert.equal(h.calls[0].options.cache,'no-store');assert.ok(h.calls[0].options.signal);
 assert.equal(h.ids.get('pwa-update').hidden,false);assert.equal(h.reloads,0);
 assert.equal(h.ids.get('pwa-update-button').onclick,h.original);
 h.ids.get('pwa-update-button').onclick();assert.equal(h.reloads,1);
});

test('unchanged build does not show a reminder',async()=>{
 const h=harness({response:()=>Response.json({schema:1,web:{build_id:A}})});await settle();
 assert.equal(h.calls.length,1);assert.equal(h.ids.get('pwa-update').hidden,true);assert.equal(h.reloads,0);
});

test('missing embedded identity and APK pages do not guess a baseline',async()=>{
 for(const options of [{build:null},{build:'unbuilt-placeholder'},{native:true}]){
  const h=harness(options);await settle();assert.equal(h.calls.length,0);assert.equal(h.reloads,0);
 }
});

test('management pages get a visible explicit-refresh prompt only after a changed build',async()=>{
 const h=harness({pwa:false});await settle();
 const banner=h.ids.get('web-update-notice'),button=h.ids.get('web-update-refresh');
 assert.ok(banner);assert.match(banner.children[0].textContent,/未保存|尚未提交/);
 assert.equal(h.reloads,0);button.onclick();assert.equal(h.reloads,1);
});

test('invalid schema, redirected, HTML, oversized, HTTP and network failures do not advertise an update',async()=>{
 const responses=[()=>Response.json({schema:2,web:{build_id:B}}),()=>Response.json({schema:1,web:{build_id:'bad'}}),
  ()=>new Response('{}',{status:503,headers:{'Content-Type':'application/json'}}),
  ()=>new Response('<html>login</html>',{headers:{'Content-Type':'text/html'}}),
  ()=>new Response('x'.repeat(17000),{headers:{'Content-Type':'application/json'}}),
  ()=>{throw Error('offline');},()=>({ok:true,redirected:true,headers:new Headers({'Content-Type':'application/json'}),text:async()=>JSON.stringify({schema:1,web:{build_id:B}})})];
 for(const response of responses){const h=harness({response});await settle();assert.equal(h.ids.get('pwa-update').hidden,true);assert.equal(h.reloads,0);}
});

test('checks visible online pages at bounded intervals without duplicate in-flight work',async()=>{
 let finish;const h=harness({response:()=>new Promise(resolve=>finish=resolve)});
 h.docEvents.visibilitychange();h.events.online();assert.equal(h.calls.length,1);
 finish(Response.json({schema:1,web:{build_id:A}}));await settle();
 h.docEvents.visibilitychange();assert.equal(h.calls.length,1);
 h.advance(60001);h.document.hidden=true;h.docEvents.visibilitychange();assert.equal(h.calls.length,1);
 h.document.hidden=false;h.context.navigator.onLine=false;h.events.online();assert.equal(h.calls.length,1);
 h.context.navigator.onLine=true;h.docEvents.visibilitychange();assert.equal(h.calls.length,2);
 finish(Response.json({schema:1,web:{build_id:A}}));await settle();
 const poll=[...h.intervals.values()][0];assert.equal(poll.ms,300000);
 h.advance(300000);poll.f();assert.equal(h.calls.length,3);
});

test('page hide cancels current check and pageshow resumes checking without a reload',async()=>{
 let signal;const h=harness({response:()=>new Promise(()=>{})});
 signal=h.calls[0].options.signal;h.events.pagehide();assert.equal(signal.aborted,true);
 assert.equal(h.intervals.size,0);h.advance(300000);h.events.pageshow();
 assert.equal(h.intervals.size,1);assert.equal(h.reloads,0);
});
