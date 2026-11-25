const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const file=path.join(__dirname,'../web/database-manager.js');assert.ok(fs.existsSync(file),'database manager UI missing');
 const elements=new Map(),make=()=>({textContent:'',value:'',hidden:false,disabled:false,children:[],listeners:{},append(...v){this.children.push(...v)},replaceChildren(...v){this.children=[...v]},reset(){},addEventListener(k,fn){this.listeners[k]=fn},setAttribute(){}});
 const el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id)};
 const ctx=vm.createContext({document:{getElementById:el,createElement:make,hidden:false,addEventListener(){}},window:{addEventListener(){},location:{search:'',hash:''},history:{replaceState(){}}},setInterval(){},AbortSignal,URLSearchParams,Date,console,fetch:async()=>{},confirm:()=>true});
 vm.runInContext(fs.readFileSync(file,'utf8').replace(/initializeDatabase\(\);\s*$/,''),ctx);
 return {ctx,el,state:vm.runInContext('databaseUI',ctx)};
}
test('database identity change clears metadata immediately',async()=>{
 const h=harness();h.state.user={id:'one'};
 h.ctx.fetch=async()=>({headers:{get:()=> 'two'},status:200,ok:true,json:async()=>({counts:{sessions:2}})});
 await assert.rejects(h.ctx.dbRequest('/api/admin/database'),/账号/);
 assert.equal(h.state.user,null);assert.equal(h.el('database-content').hidden,true);
});
test('late body cannot restore data after logout',async()=>{
 const h=harness();h.state.user={id:'one'};let resolve,started;
 const ready=new Promise(r=>started=r);
 h.ctx.fetch=async()=>({headers:{get:()=> 'one'},ok:true,status:200,json:()=>{started();return new Promise(r=>resolve=r)}});
 const pending=h.ctx.dbRequest('/api/admin/database');await ready;h.ctx.clearDatabase('signed out');resolve({private:true});
 await assert.rejects(pending,/登录状态/);assert.equal(h.state.user,null);
});
test('permission error hides every management section',async()=>{
 const h=harness();h.state.user={id:'one'};
 h.ctx.fetch=async()=>({headers:{get:()=>null},ok:false,status:403,json:async()=>({detail:'需要管理员账号'})});
 await assert.rejects(h.ctx.dbRequest('/api/admin/database'));assert.equal(h.el('database-content').hidden,true);
});

test('database restores encoded cross-page filters and cloud registration day',()=>{
 const h=harness();h.ctx.window.location.search='?device_id=lab-one&owner_id=alice&registered_day=2026-11-25&state=uploading&offset=25';
 h.ctx.restoreDatabaseFilters();const p=h.ctx.recordParams();assert.equal(p.get('device_id'),'lab-one');assert.equal(p.get('owner_id'),'alice');assert.equal(p.get('registered_day'),'2026-11-25');assert.equal(p.get('state'),'uploading');assert.equal(p.get('offset'),'25');
});
test('older filter response cannot replace the latest record list',async()=>{
 const h=harness();h.state.user={id:'one'};h.el('db-state').value='active';let resolve,calls=0;
 h.ctx.fetch=async()=>({headers:{get:()=> 'one'},ok:true,status:200,json:()=>++calls===1?new Promise(r=>resolve=r):Promise.resolve({records:[],total:0})});
 const older=h.ctx.loadDatabaseRecords();await new Promise(r=>setImmediate(r));
 await h.ctx.loadDatabaseRecords();resolve({records:[{session_id:'old',name:'old',complete:1}],total:99});await older;
 assert.equal(h.state.total,0);assert.doesNotMatch(h.el('db-page').textContent,/99/);
});
test('task feedback labels detected damage without saying all data is healthy',()=>{
 const h=harness();h.ctx.renderMaintenance([{job_id:'j',kind:'check',status:'complete',stage:'检查完成',result:{ok:false,issue_count:2,issues:['损坏块'],scope:'raw'}}]);
 assert.match(h.el('db-jobs').children.map(c=>c.textContent).join(' '),/2|损坏/);
});
test('same-turn revocation prevents stale overview rendering and followup reads',async()=>{
 const h=harness();h.state.user={id:'one'};let good,bad,calls=0;
 h.ctx.fetch=async path=>{calls++;if(calls>2)throw new Error('unexpected followup');return {headers:{get:()=> 'one'},ok:path!=='/api/auth/me',status:path==='/api/auth/me'?401:200,json:()=>new Promise(r=>{if(path==='/api/auth/me')bad=r;else good=r;})};};
 const refresh=h.ctx.refreshDatabase(),revoked=h.ctx.dbRequest('/api/auth/me').catch(()=>{});
 await new Promise(r=>setImmediate(r));
 good({counts:{sessions:7},uploading:0,trashed:0,database_bytes:{main:1},disk:{free_bytes:2,total_bytes:3},storage_scan:null});bad({detail:'expired'});
 await Promise.all([refresh,revoked]);assert.equal(h.state.user,null);assert.equal(h.el('db-count').textContent,'');assert.equal(calls,2);
});
