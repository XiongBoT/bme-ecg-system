'use strict';
const dbEl=id=>document.getElementById(id);
const databaseUI={epoch:0,listVersion:0,user:null,csrf:'',offset:0,limit:25,total:0,busy:false,polling:false,lastJobs:''};
const dbKinds={scan:'统计占用',check:'完整性检查',backup:'服务器备份',cleanup:'清理中断临时文件',trash:'移入回收站',restore:'恢复记录',grant:'添加账号设备授权',revoke_grant:'取消账号设备授权'};
const dbStatuses={queued:'等待处理',running:'正在处理',complete:'已完成',failed:'未完成',interrupted:'已中断'};
const dbText=(id,value)=>{dbEl(id).textContent=value;};
const dbDate=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString():'--';
function dbBytes(value){if(value==null || !Number.isFinite(value))return '未知';if(value<1024)return value+' B';const units=['KiB','MiB','GiB','TiB'];let i=-1;do{value/=1024;i++;}while(value>=1024&&i<units.length-1);return value.toFixed(value<10?1:0)+' '+units[i];}
function clearDatabase(message){
 if(typeof BackupScheduleUI!=='undefined')BackupScheduleUI.clear();
 databaseUI.epoch++;databaseUI.listVersion++;databaseUI.user=null;databaseUI.csrf='';databaseUI.total=0;databaseUI.offset=0;databaseUI.lastJobs='';databaseUI.busy=false;
 dbEl('database-content').hidden=true;dbText('db-account','');dbText('db-notice',message);
 for(const id of ['db-records','db-jobs','db-backups','db-activity','db-tables'])dbEl(id).replaceChildren();
 for(const id of ['db-count','db-count-note','db-raw','db-raw-note','db-size','db-free','db-free-note','db-scan-detail','db-total','db-record-notice'])dbText(id,'');
 dbEl('db-filters').reset();dbEl('db-owner').replaceChildren();dbEl('db-device').replaceChildren();
 dbEl('db-registered-day').value='';
}
async function dbRequest(path,method='GET',payload){
 const epoch=databaseUI.epoch;
 const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json','X-CSRF-Token':databaseUI.csrf},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
 if(epoch!==databaseUI.epoch)throw new Error('登录状态已改变');
 const user=response.headers.get('X-ECG-User');
 if(databaseUI.user&&user&&user!==databaseUI.user.id){clearDatabase('其他页面已切换账号，请返回工作台重新登录。');throw new Error('账号已改变');}
 const body=await response.json();
 if(epoch!==databaseUI.epoch)throw new Error('登录状态已改变');
 if(response.status===401||response.status===403){clearDatabase('管理权限或登录已失效，请返回工作台登录管理员账号。');throw new Error('需要管理员登录');}
 if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'请求未完成（'+response.status+'）');
 return body;
}
function renderOverview(data){
 dbText('db-count',(data.counts.sessions||0).toLocaleString());dbText('db-count-note',data.uploading+' 条上传中 · '+data.trashed+' 条在回收站');
 const sizes=Object.values(data.database_bytes);dbText('db-size',sizes.some(x=>x==null)?'未知':dbBytes(sizes.reduce((a,b)=>a+b,0)));
 dbText('db-free',dbBytes(data.disk.free_bytes));dbText('db-free-note','磁盘总空间 '+dbBytes(data.disk.total_bytes));
 const scan=data.storage_scan;dbText('db-raw',scan?dbBytes(scan.bytes.raw):'未统计');dbText('db-raw-note',scan?(scan.complete?'统计于 ':'部分路径未统计 · ')+dbDate(scan.measured_at):'点击“统计占用”后查看');
 dbText('db-scan-detail',scan?['原始数据 '+dbBytes(scan.bytes.raw),'分析缓存 '+dbBytes(scan.bytes.analysis),'备份 '+dbBytes(scan.bytes.backups),'临时文件 '+dbBytes(scan.bytes.temporary||0),'其他 '+dbBytes(scan.bytes.other),'时间 '+dbDate(scan.measured_at),...scan.issues].join(' · '):'尚未扫描文件占用。统计不会修改记录。');
 dbEl('db-tables').replaceChildren();for(const [name,count] of Object.entries(data.counts)){const row=document.createElement('div');row.textContent=name+' · '+count+' 行';dbEl('db-tables').append(row);}
}
function recordParams(){
 const p=new URLSearchParams({limit:String(databaseUI.limit),offset:String(databaseUI.offset),state:dbEl('db-state').value||'active'});
 for(const [key,id] of [['q','db-query'],['owner_id','db-owner'],['device_id','db-device']])if(dbEl(id).value)p.set(key,dbEl(id).value);
 if(dbEl('db-registered-day').value)p.set('registered_day',dbEl('db-registered-day').value);
 const start=dbEl('db-from').value,end=dbEl('db-before').value;
 if(start&&end&&start>end)throw new Error('开始日期不能晚于结束日期');
 if(start)p.set('started_from',new Date(start+'T00:00:00').toISOString());
 if(end){const value=new Date(end+'T00:00:00');value.setDate(value.getDate()+1);p.set('started_before',value.toISOString());}
 return p;
}
function restoreDatabaseFilters(){
 const p=new URLSearchParams(window.location.search);
 for(const [key,id] of [['q','db-query'],['owner_id','db-owner'],['device_id','db-device'],['registered_day','db-registered-day'],['from','db-from'],['before','db-before']]){
  const value=p.get(key)||'';
  if(value&&['db-owner','db-device'].includes(id)&&dbEl(id).options&&!Array.from(dbEl(id).options).some(o=>o.value===value))option(id,value,'指定编号：'+value);
  dbEl(id).value=value.slice(0,100);
 }
 dbEl('db-state').value=['active','complete','uploading','trashed'].includes(p.get('state'))?p.get('state'):'active';
 databaseUI.offset=Math.max(0,Math.min(1000000,Math.floor(Number(p.get('offset'))||0)));
}
function rememberDatabaseFilters(){
 const p=new URLSearchParams({state:dbEl('db-state').value||'active',offset:String(databaseUI.offset)});
 for(const [key,id] of [['q','db-query'],['owner_id','db-owner'],['device_id','db-device'],['registered_day','db-registered-day'],['from','db-from'],['before','db-before']])if(dbEl(id).value)p.set(key,dbEl(id).value);
 window.history.replaceState(null,'','/database?'+p+(window.location.hash||''));
}
async function loadDatabaseRecords(){
 const version=++databaseUI.listVersion,epoch=databaseUI.epoch;
 dbText('db-record-notice','正在查询…');
 try{
  const data=await dbRequest('/api/admin/database/records?'+recordParams());
  if(version!==databaseUI.listVersion||epoch!==databaseUI.epoch)return;
  if(databaseUI.offset&&databaseUI.offset>=data.total){databaseUI.offset=data.total?Math.floor((data.total-1)/databaseUI.limit)*databaseUI.limit:0;return loadDatabaseRecords();}
  databaseUI.total=data.total;dbText('db-total',data.total+' 条');dbText('db-record-notice',data.total?'':'没有符合条件的记录。');dbEl('db-records').replaceChildren();
  for(const item of data.records){
   const row=document.createElement('article'),main=document.createElement('div'),name=document.createElement('strong'),id=document.createElement('p'),meta=document.createElement('div'),detail=document.createElement('p'),button=document.createElement('button');
   row.className='db-record';name.textContent=item.name||item.session_id;id.textContent=item.session_id;main.append(name,id);meta.className='db-record-meta';
   detail.textContent=(item.username||'未分配')+' · '+(item.device_id||'未知设备')+' · '+dbDate(item.started_utc)+'\n'+item.sample_count.toLocaleString()+' 点 · '+(item.trashed_at?'回收站':item.complete?'上传完成':'上传中');meta.append(detail);
   if(item.device_id){const link=document.createElement('a');link.href='/devices?'+new URLSearchParams({selected:item.device_id});link.textContent='查看设备';meta.append(link);}
   if(item.owner_id){const link=document.createElement('a');link.href='/admin/accounts?'+new URLSearchParams({selected:item.owner_id});link.textContent=' · 查看账号';meta.append(link);}
   button.type='button';button.className='button secondary';button.textContent=item.trashed_at?'恢复记录':'移入回收站';button.disabled=!item.complete&&!item.trashed_at;
   button.onclick=()=>changeDatabaseRecord(item,button);row.append(main,meta,button);dbEl('db-records').append(row);
  }
  dbText('db-page',(Math.floor(databaseUI.offset/databaseUI.limit)+1)+' / '+Math.max(1,Math.ceil(data.total/databaseUI.limit)));
  dbEl('db-prev').disabled=databaseUI.offset===0;dbEl('db-next').disabled=databaseUI.offset+databaseUI.limit>=data.total;
  rememberDatabaseFilters();
 }catch(error){if(epoch===databaseUI.epoch&&version===databaseUI.listVersion)dbText('db-record-notice',error.message+'；可重新筛选或刷新。');}
}
async function changeDatabaseRecord(item,button){
 if(!confirm(item.trashed_at?'恢复这条记录？':'将这条记录移入回收站？原始数据保留，用户暂时不能查看。'))return;
 const epoch=databaseUI.epoch;button.disabled=true;
 try{await dbRequest('/api/admin/database/records/'+encodeURIComponent(item.session_id)+(item.trashed_at?'/restore':'/trash'),'POST');await refreshDatabase();}
 catch(error){if(epoch===databaseUI.epoch)dbText('db-notice',error.message);}
 finally{if(epoch===databaseUI.epoch)button.disabled=false;}
}
function renderMaintenance(jobs){
 dbEl('db-jobs').replaceChildren();databaseUI.busy=jobs.some(j=>['queued','running'].includes(j.status));
 for(const id of ['db-scan','db-check','db-backup'])dbEl(id).disabled=databaseUI.busy;
 for(const job of jobs.slice(0,5)){
  const row=document.createElement('div'),result=job.result||{};row.className='db-job'+(job.status==='failed'||job.status==='interrupted'||result.ok===false?' problem':'');
  const pieces=[(dbKinds[job.kind]||job.kind)+' · '+(dbStatuses[job.status]||job.status)+' · '+dbDate(job.created),job.stage];
  if(job.total)pieces.push(job.processed+' / '+job.total+' 块');if(job.error)pieces.push(job.error);
  if(job.kind==='check'&&job.status==='complete')pieces.push('已核对 '+result.chunks_checked+' 块，发现 '+result.issue_count+' 项问题',...(result.issues||[]),result.issues_truncated?'仅显示前 50 项，请在服务器进一步核对。':'',result.scope||'');
  if(job.kind==='backup'&&job.status==='complete')pieces.push(result.filename+' · '+dbBytes(result.bytes),'已保存到服务器 · '+result.sessions+' 条记录 / '+result.chunks+' 块');
  row.textContent=pieces.filter(Boolean).join('\n');dbEl('db-jobs').append(row);
 }
 if(!jobs.length)dbText('db-jobs','尚无维护任务。可先统计存储占用，或检查现有数据。');
}
async function loadMaintenance(){
 if(typeof BackupScheduleUI!=='undefined')await BackupScheduleUI.load();
 const epoch=databaseUI.epoch;const [tasks,backups,activity]=await Promise.all([dbRequest('/api/admin/database/jobs'),dbRequest('/api/admin/database/backups'),dbRequest('/api/admin/database/activity')]);
 if(epoch!==databaseUI.epoch)return;renderMaintenance(tasks.jobs);
 dbEl('db-backups').replaceChildren();for(const item of backups.backups){const row=document.createElement('div');row.className='db-backup';row.textContent=dbDate(item.created)+' · '+dbBytes(item.bytes)+' · '+item.sessions+' 条记录\n'+item.filename+'\nSHA256 '+item.sha256;dbEl('db-backups').append(row);}if(!backups.backups.length)dbText('db-backups','暂无已完成备份。');
 dbEl('db-activity').replaceChildren();for(const event of activity.events){const row=document.createElement('div');row.className='db-event';row.textContent=dbDate(event.created)+' · '+(dbKinds[event.action]||event.action)+' · '+(dbStatuses[event.status]||event.status)+'\n对象 '+event.target+' · 管理员 '+event.actor_id+(event.detail?'\n'+event.detail:'');dbEl('db-activity').append(row);}if(!activity.events.length)dbText('db-activity','暂无管理操作。');
 const signature=tasks.jobs.map(j=>j.job_id+':'+j.status).join(',');if(signature!==databaseUI.lastJobs){databaseUI.lastJobs=signature;const overview=await dbRequest('/api/admin/database');if(epoch!==databaseUI.epoch)return;renderOverview(overview);}
}
async function startMaintenance(kind){
 if(kind==='backup'&&!confirm('创建服务器备份？将保存数据库与对应原始波形，并占用额外磁盘空间。'))return;
 const epoch=databaseUI.epoch;
 try{for(const id of ['db-scan','db-check','db-backup'])dbEl(id).disabled=true;await dbRequest('/api/admin/database/jobs','POST',{kind});dbText('db-notice','任务已接受，后台处理将继续。');await loadMaintenance();}
 catch(error){if(epoch===databaseUI.epoch){dbText('db-notice',error.message);for(const id of ['db-scan','db-check','db-backup'])dbEl(id).disabled=false;}}
}
async function refreshDatabase(){
 if(!databaseUI.user)return initializeDatabase();
 const epoch=databaseUI.epoch;try{const data=await dbRequest('/api/admin/database');if(epoch!==databaseUI.epoch)return;renderOverview(data);await Promise.all([loadDatabaseRecords(),loadMaintenance()]);if(epoch===databaseUI.epoch)dbText('db-notice','概览已更新；文件占用以最近一次统计时间为准。');}catch(error){if(epoch===databaseUI.epoch)dbText('db-notice',error.message);}
}
function option(id,value,caption){const item=document.createElement('option');item.value=value;item.textContent=caption;dbEl(id).append(item);}
async function initializeDatabase(){
 clearDatabase('正在检查管理员权限…');const epoch=databaseUI.epoch;
 try{const me=await dbRequest('/api/auth/me');if(epoch!==databaseUI.epoch)return;if(!me.user?.is_admin){clearDatabase('请返回工作台登录管理员账号。');return;}databaseUI.user=me.user;databaseUI.csrf=me.csrf_token;
  const [users,devices]=await Promise.all([dbRequest('/api/admin/users'),dbRequest('/api/admin/devices')]);if(epoch!==databaseUI.epoch)return;
  option('db-owner','','全部用户');option('db-owner','unassigned','尚未分配');for(const user of users.users)option('db-owner',user.id,user.username+(user.active?'':'（停用）'));
  option('db-device','','全部设备');for(const device of devices.devices)option('db-device',device.device_id,device.name||device.device_id);
  restoreDatabaseFilters();
  dbText('db-account',me.user.username+' · 管理员');dbEl('database-content').hidden=false;await refreshDatabase();
 }catch(error){if(epoch===databaseUI.epoch)clearDatabase(error.message+'；请返回工作台确认登录状态。');}
}
dbEl('db-refresh').onclick=refreshDatabase;
dbEl('db-filters').addEventListener('submit',event=>{event.preventDefault();databaseUI.offset=0;loadDatabaseRecords();});
dbEl('db-registered-day').onchange=()=>{databaseUI.offset=0;loadDatabaseRecords();};
dbEl('db-clear-filters').onclick=()=>{dbEl('db-filters').reset();dbEl('db-registered-day').value='';databaseUI.offset=0;loadDatabaseRecords();};
dbEl('db-prev').onclick=()=>{databaseUI.offset=Math.max(0,databaseUI.offset-databaseUI.limit);loadDatabaseRecords();};
dbEl('db-next').onclick=()=>{databaseUI.offset+=databaseUI.limit;loadDatabaseRecords();};
for(const kind of ['scan','check','backup'])dbEl('db-'+kind).onclick=()=>startMaintenance(kind);
async function pollDatabase(){if(document.hidden||!databaseUI.user||databaseUI.polling)return;databaseUI.polling=true;const epoch=databaseUI.epoch;try{await dbRequest('/api/auth/me');await loadMaintenance();}catch(error){if(epoch===databaseUI.epoch)dbText('db-notice',error.message+'；连接恢复后可刷新。');}finally{databaseUI.polling=false;}}
setInterval(pollDatabase,3000);window.addEventListener('focus',()=>databaseUI.user?pollDatabase():initializeDatabase());window.addEventListener('pagehide',()=>clearDatabase('已离开管理页面，请刷新后继续。'));
initializeDatabase();
