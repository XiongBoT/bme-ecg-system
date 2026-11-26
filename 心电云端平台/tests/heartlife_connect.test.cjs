const test=require('node:test'),assert=require('node:assert/strict');
const {safeUrl,createController}=require('../web/heartlife_core.js');
const user={id:'alice',username:'alice'};
function response(data,status=200,owner='alice'){
  return {ok:status>=200&&status<300,status,headers:new Headers(owner?{'X-ECG-User':owner}:{}),json:async()=>data};
}
function harness(){
  let state;const calls=[],routes=new Map([
    ['/api/auth/config',()=>response({enabled:true,heartlife_url:'https://example.test/heartlife/'})],
    ['/api/auth/me',()=>response({user,csrf_token:'csrf-alice'})],
    ['/api/heartlife/link',()=>response({enabled:true,heartlife_url:'https://example.test/heartlife/',linked:false,expires_at:null})],
    ['/api/auth/logout',()=>response({ok:true})],
  ]);
  const controller=createController(async(path,options)=>{calls.push({path,...options});return routes.get(path)(options);},value=>state=value);
  return {controller,calls,routes,get state(){return state;}};
}
test('configured HeartLife entry accepts only fixed HTTPS destinations',()=>{
  assert.equal(safeUrl('https://example.test/heartlife/'),'https://example.test/heartlife/');
  for(const value of [null,'','http://example.test/','javascript:alert(1)','//example.test/','https://user:secret@example.test/','https://example.test/?token=secret','https://example.test/#secret'])assert.equal(safeUrl(value),null);
});
test('default-disabled setup does not solicit login or generate a code',async()=>{
  const h=harness();h.routes.set('/api/auth/config',()=>response({enabled:false}));
  await h.controller.load();await h.controller.generate(true);
  assert.equal(h.state.phase,'disabled');assert.equal(h.calls.length,1);assert.equal(h.state.user,null);
});
test('existing user may still revoke a link after integration is disabled',async()=>{
  const h=harness();h.routes.set('/api/auth/config',()=>response({enabled:true,heartlife_url:null}));
  h.routes.set('/api/heartlife/link',options=>response(options.method==='DELETE'?{revoked:true}:{enabled:false,heartlife_url:null,linked:true,expires_at:100}));
  await h.controller.load();assert.equal(h.state.phase,'disabled');assert.equal(h.state.linked,true);
  await h.controller.revoke();assert.equal(h.state.linked,false);
});
test('code requires consent, sends CSRF, and does not duplicate pending mutation',async()=>{
  const h=harness();await h.controller.load();let finish;
  h.routes.set('/api/heartlife/link-code',()=>new Promise(resolve=>finish=resolve));
  await h.controller.generate(false);assert.match(h.state.message,/确认/);
  assert.equal(h.calls.filter(call=>call.path.endsWith('link-code')).length,0);
  const pending=h.controller.generate(true);await h.controller.generate(true);
  const mutations=h.calls.filter(call=>call.path.endsWith('link-code'));assert.equal(mutations.length,1);
  assert.equal(mutations[0].headers['X-CSRF-Token'],'csrf-alice');assert.equal(mutations[0].credentials,'same-origin');assert.equal(mutations[0].redirect,'error');
  finish(response({code:'one-time-code',expires_at:100}));await pending;
  assert.equal(h.state.code,'one-time-code');h.controller.expire(101);assert.equal(h.state.code,'');assert.match(h.state.message,/过期/);
});
test('late code response cannot reappear after logout or account switch',async()=>{
  const h=harness();await h.controller.load();let finish;
  h.routes.set('/api/heartlife/link-code',()=>new Promise(resolve=>finish=resolve));
  const pending=h.controller.generate(true);
  h.routes.set('/api/auth/me',()=>response({detail:'请先登录'},401));await h.controller.logout();
  finish(response({code:'private-old-code',expires_at:9999999999}));await pending;
  assert.equal(h.state.phase,'login');assert.equal(h.state.user,null);assert.equal(h.state.code,'');
});
test('mismatched owner header invalidates identity before showing private code',async()=>{
  const h=harness();await h.controller.load();
  h.routes.set('/api/heartlife/link-code',()=>response({code:'bob-code',expires_at:9999999999},200,'bob'));
  await h.controller.generate(true);assert.equal(h.state.phase,'login');assert.equal(h.state.user,null);assert.equal(h.state.code,'');
});
test('revoke failure retains linked status and never reports success',async()=>{
  const h=harness();h.routes.set('/api/heartlife/link',options=>options.method==='DELETE'?response({detail:'服务暂时不可用'},503):response({enabled:true,linked:true,expires_at:100,heartlife_url:'https://example.test/'}));
  await h.controller.load();await h.controller.revoke();assert.equal(h.state.linked,true);assert.match(h.state.message,/不可用/);
  h.routes.set('/api/heartlife/link',()=>response({revoked:true}));await h.controller.revoke();assert.equal(h.state.linked,false);assert.match(h.state.message,/已撤销/);
});
test('page hide clears secrets and ignores prior request completion',async()=>{
  const h=harness();await h.controller.load();let finish;
  h.routes.set('/api/heartlife/link-code',()=>new Promise(resolve=>finish=resolve));
  const pending=h.controller.generate(true);h.controller.clear();
  finish(response({code:'hidden-secret',expires_at:9999999999}));await pending;
  assert.equal(h.state.user,null);assert.equal(h.state.code,'');assert.equal(h.state.url,null);
});
