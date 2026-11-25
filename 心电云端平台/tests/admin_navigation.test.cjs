const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');

function node(tag='div'){
 return {tagName:tag.toUpperCase(),textContent:'',hidden:false,value:'all',children:[],attributes:{},disabled:false,isConnected:true,
  append(...children){this.children.push(...children);},replaceChildren(...children){this.children=[...children];},
  setAttribute(key,value){this.attributes[key]=value;},removeAttribute(key){delete this.attributes[key];},reset(){}};
}
function descendants(parent){return parent.children.flatMap(child=>[child,...descendants(child)]);}
function admin(section='overview',hash=''){
 const navigation=node('nav'),events={};
 const context=vm.createContext({document:{getElementById:id=>id==='admin-navigation'?navigation:null,createElement:node,createElementNS:(_,tag)=>node(tag),body:{dataset:{adminSection:section}}},window:{location:{hash},addEventListener:(type,callback)=>{events[type]=callback;}},URLSearchParams,AbortSignal});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/admin-common.js'),'utf8'),context);
 const links=()=>descendants(navigation).filter(item=>item.tagName==='A');
 return {links,current:()=>links().filter(item=>item.attributes['aria-current']),hash(value){context.window.location.hash=value;events.hashchange();}};
}

test('management navigation keeps daily destinations reachable beside administrative destinations',()=>{
 const h=admin();
 for(const href of ['/','/tasks','/admin','/operations','/admin/accounts','/devices','/database','/database#db-maintenance-section','/database#db-activity-section']){
  assert.equal(h.links().filter(link=>link.href===href).length,1,href+' should have one navigation destination');
 }
 assert.deepEqual(h.current().map(link=>link.href),['/admin']);
});

test('management sections identify only the current page',()=>{
 for(const [section,href] of [['overview','/admin'],['accounts','/admin/accounts'],['devices','/devices'],['records','/database']]){
  const h=admin(section);
  assert.deepEqual(h.current().map(link=>[link.href,link.attributes['aria-current']]),[[href,'page']]);
 }
});

test('database hash navigation follows maintenance, activity, and return to records',()=>{
 const h=admin('records','#db-maintenance-section');
 assert.deepEqual(h.current().map(link=>[link.href,link.attributes['aria-current']]),[['/database#db-maintenance-section','location']]);
 h.hash('#db-activity-section');
 assert.deepEqual(h.current().map(link=>[link.href,link.attributes['aria-current']]),[['/database#db-activity-section','location']]);
 for(const hash of ['#db-records-section','#unrecognized','']){
  h.hash(hash);assert.deepEqual(h.current().map(link=>link.href),['/database']);
 }
});

test('database hashes do not select unrelated sections on another management page',()=>{
 const h=admin('accounts','#db-maintenance-section');
 h.hash('#db-activity-section');
 assert.deepEqual(h.current().map(link=>link.href),['/admin/accounts']);
});

function workflow(mode='tasks'){
 const elements=new Map();
 const html=fs.readFileSync(path.join(__dirname,'../web/'+mode+'.html'),'utf8');
 for(const match of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
  const item=node(match[1]);item.hidden=/\bhidden\b/.test(match[2]);elements.set(match[3],item);
 }
 const context=vm.createContext({ECGWorkflow:require('../web/workflow_core.js'),document:{getElementById:id=>elements.get(id)||null,createElement:node,body:{dataset:{page:mode}},addEventListener(){},hidden:false},fetch:async()=>{},AbortSignal,URLSearchParams,Date,setInterval(){},console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workflow-page.js'),'utf8').replace(/initializePage\(\);\s*$/,''),context);
 return {context,el:id=>elements.get(id),clear:()=>vm.runInContext("client.clear('登录已失效')",context)};
}
function response(body,status=200){return {ok:status<400,status,headers:{get:()=> 'owner'},json:async()=>body};}
function signIn(h,isAdmin){
 h.context.fetch=async url=>{
  if(url==='/api/auth/me')return response({user:{id:'owner',username:'owner',is_admin:isAdmin},csrf_token:'token'});
  if(url==='/api/workflow/preferences')return response({auto_model:false,auto_physiology:false});
  if(url.startsWith('/api/workflow/tasks?'))return response({counts:{},records:[],total:0,measured_at:1});
  if(url==='/api/admin/operations')return response({queue:{queued:0,running:0,complete:0,ineligible:0,failed:0},devices:{online:0,offline:0,unknown:0,disabled:0},uploads:{pending:0,stalled:0},disk:{free_bytes:2048,total_bytes:4096},issues:[],model_status:'not_configured',physiology_ready:true,last_successful_backup:null,measured_at:1});
  throw new Error('Unexpected request: '+url);
 };
 return h.context.initializePage();
}

test('task navigation reveals administrative destinations only for an administrator',async()=>{
 for(const isAdmin of [false,true]){
  const h=workflow();await signIn(h,isAdmin);
  assert.ok(h.el('admin-link'),'management entry exists in the task navigation');
  assert.equal(h.el('admin-link').hidden,!isAdmin);
  assert.equal(h.el('operations-link').hidden,!isAdmin);
  assert.equal(h.el('workflow-admin-nav').hidden,!isAdmin);
  assert.equal(h.el('page-content').hidden,false);
 }
});

test('task navigation removes administrative destinations when the session is invalidated',async()=>{
 const h=workflow();await signIn(h,true);
 h.context.fetch=async()=>response({detail:'Forbidden'},403);
 await h.context.refreshPage();
 assert.equal(h.el('operations-link').hidden,true);
 assert.ok(h.el('admin-link'),'management entry exists in the task navigation');
 assert.equal(h.el('admin-link').hidden,true);
 assert.equal(h.el('workflow-admin-nav').hidden,true);
 assert.equal(h.el('page-content').hidden,true);
});

test('ordinary accounts cannot open operation content or its administrative navigation',async()=>{
 const h=workflow('operations');await signIn(h,false);
 assert.equal(h.el('page-content').hidden,true);
 assert.ok(h.el('admin-link'),'management entry exists in the operation navigation');
 assert.equal(h.el('admin-link').hidden,true);
 assert.equal(h.el('operations-link').hidden,true);
 assert.equal(h.el('workflow-admin-nav').hidden,true);
});

test('operation navigation stays available for an administrator until the session ends',async()=>{
 const h=workflow('operations');await signIn(h,true);
 assert.equal(h.el('page-content').hidden,false);
 for(const id of ['workflow-admin-nav','operations-link','admin-link'])assert.equal(h.el(id).hidden,false);
 h.clear();
 for(const id of ['workflow-admin-nav','operations-link','admin-link'])assert.equal(h.el(id).hidden,true);
 assert.equal(h.el('page-content').hidden,true);
});
