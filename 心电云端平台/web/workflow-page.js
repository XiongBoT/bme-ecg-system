'use strict';
const element=id=>document.getElementById(id),mode=document.body.dataset.page;
let listVersion=0,offset=0,polling=false,preferenceBusy=false,ready=false;
const client=ECGWorkflow.client((...args)=>fetch(...args),message=>{
 listVersion++;ready=false;element('page-content').hidden=true;element('metrics').replaceChildren();
 for(const id of ['task-list','issues'])element(id)?.replaceChildren();
 element('page-account').textContent='';element('page-notice').textContent=message;
 for(const id of ['workflow-admin-nav','operations-link','admin-link'])if(element(id))element(id).hidden=true;
 if(element('preferences-form'))element('preferences-form').reset();
});
const text=(id,value)=>{element(id).textContent=value;};
const node=(tag,value,style)=>{const item=document.createElement(tag);if(value!=null)item.textContent=value;if(style)item.className=style;return item;};
const when=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN'):'尚无记录';
const bytes=value=>value==null?'未知':(value/1024**3).toFixed(2)+' GiB';
function metrics(items){element('metrics').replaceChildren();for(const [label,value,note] of items){const box=node('div',null,'metric');box.append(node('span',label),node('strong',value),node('p',note));element('metrics').append(box);}}
async function action(sid,kind,button){
 const epoch=client.epoch;button.disabled=true;
 try{await client.request('/api/sessions/'+encodeURIComponent(sid)+(kind==='model'?'/analysis-jobs':'/physiology-jobs'),'POST');if(epoch===client.epoch){text('page-notice','后台任务已接受，离开页面后仍会继续。');await refreshPage();}}
 catch(error){if(epoch===client.epoch)text('page-notice',error.message);}
 finally{if(epoch===client.epoch&&button.isConnected)button.disabled=false;}
}
function renderTasks(data){
 const counts=data.counts;metrics([['上传中',counts.uploading||0,'在终端继续或重试上传'],['分析处理中',counts.processing||0,'后台持续运行'],['需要处理',counts.attention||0,'检查原因后重试'],['已有结果',counts.results||0,'包括分析条件不足']]);
 text('tasks-total',data.total+' 条记录');text('page-number',Math.floor(offset/25)+1+' / '+Math.max(1,Math.ceil(data.total/25)));
 element('previous-page').disabled=offset===0;element('next-page').disabled=offset+25>=data.total;
 element('task-list').replaceChildren();
 if(!data.records.length)element('task-list').append(node('p','没有符合条件的记录。','muted'));
 const stages={uploading:'上传中',processing:'处理中',attention:'需要处理',results:'已有结果',ready:'待分析'};
 for(const item of data.records){
  const card=node('article',null,'panel task-card'),head=node('div',null,'toolbar');
  head.append(node('h3',item.name||item.session_id),node('span',stages[item.stage], 'badge'+(item.stage==='attention'?' attention':'')));
  card.append(head,node('p',when(item.created_at)+' · '+(item.sample_count/360).toFixed(1)+' 秒','muted'));
  const steps=node('div',null,'steps');steps.append(node('p',item.complete?'✓ 上传及清单校验完成':'◷ 等待终端继续上传'));
  for(const [kind,label] of [['model','心搏分类'],['physiology','心搏与间期']]){
   const job=item.jobs[kind],automatic=item.automatic.find(x=>x.kind===kind),row=node('div',null,'step');
   let description=ECGWorkflow.status(job?.status||'not_run');
   if(job?.status==='running')description+=' '+job.processed+' / '+job.total+' 点';
   if(!job&&automatic)description=ECGWorkflow.status(automatic.status)+(automatic.message?' · '+automatic.message:'');
   const details=node('div');details.append(node('strong',label),node('p',description,'muted'));
   if(job?.error)details.append(node('p',job.error,'muted'));row.append(details);
   if(item.complete&&(!job||['failed','not_configured','stale'].includes(job.status))){const button=node('button',job?.status==='stale'?'重新分析':job?'重试':'开始','secondary');button.type='button';button.onclick=()=>action(item.session_id,kind,button);row.append(button);}
   steps.append(row);
  }
  const link=node('a','查看波形、报告与复核 →');link.href='/?record='+encodeURIComponent(item.session_id);
  card.append(steps,link);element('task-list').append(card);
 }
}
function renderOperations(data){
 const q=data.queue,d=data.devices;
 metrics([['在线设备',d.online,d.offline+' 离线 · '+d.unknown+' 未上报 · '+d.disabled+' 停用'],['分析队列',(q.queued||0)+(q.running||0),(q.queued||0)+' 等待 · '+(q.running||0)+' 运行'],['未完成上传',data.uploads.pending,data.uploads.stalled+' 条超过 15 分钟无更新'],['磁盘可用',bytes(data.disk.free_bytes),'总容量 '+bytes(data.disk.total_bytes)]]);
 text('issue-count',data.issues.length+' 项');element('issues').replaceChildren();
 if(!data.issues.length)element('issues').append(node('p','当前未发现上述规则范围内的运行问题。'));
 for(const issue of data.issues){const row=node('div',null,'issue '+issue.severity),link=node('a','去处理 →');link.href=issue.href;row.append(node('p',issue.text),link);element('issues').append(row);}
 text('service-status','分类服务：'+({ready:'已就绪',not_configured:'未启用',error:'加载异常'}[data.model_status]||'待确认')+' · QRS/RR：'+(data.physiology_ready?'已就绪':'未就绪'));
 text('queue-status','历史任务：'+(q.complete||0)+' 完成 · '+(q.ineligible||0)+' 条件不足 · '+(q.failed||0)+' 失败（含重试前的任务）');
 text('backup-status','最近成功备份：'+when(data.last_successful_backup));text('disk-status','可用空间 '+bytes(data.disk.free_bytes)+'；仅显示磁盘容量，文件分类占用请打开数据库管理。');
 const schedule=data.backup_schedule;
 text('backup-schedule-status',!schedule?'备份计划状态未提供，请刷新或检查服务版本。':!schedule.enabled?'每日自动备份未启用。':
   '每日北京时间 '+String(schedule.hour).padStart(2,'0')+':'+String(schedule.minute).padStart(2,'0')+' · '+
   ({scheduled:'已安排',blocked:'暂时受阻',waiting:'等待维护队列'}[schedule.state]||'请查看维护任务')+' · 下次计划 '+when(schedule.next_due)+'。全部备份保留，需定期检查容量。');
}
async function refreshPage(){
 if(!client.user)return;
 const version=++listVersion,epoch=client.epoch;
 try{
  const data=await client.request(mode==='tasks'?'/api/workflow/tasks?'+new URLSearchParams({limit:25,offset,stage:element('task-stage').value}):'/api/admin/operations');
  if(epoch!==client.epoch||version!==listVersion)return;
  if(mode==='tasks'&&offset&&offset>=data.total){offset=Math.max(0,Math.ceil(data.total/25)-1)*25;return refreshPage();}
  (mode==='tasks'?renderTasks:renderOperations)(data);text('page-notice','状态更新于 '+when(data.measured_at)+' · 页面可见时每 15 秒刷新');
 }catch(error){if(epoch===client.epoch&&version===listVersion)text('page-notice',error.message+'。当前保留上次读取内容，请刷新重试。');}
}
async function initializePage(){
 client.clear('正在确认登录状态…');const epoch=client.epoch;
 try{
  const me=await client.request('/api/auth/me');if(epoch!==client.epoch)return;
  if(!me.user||(mode==='operations'&&!me.user.is_admin)){client.clear('请返回工作台登录'+(mode==='operations'?'管理员':'本人')+'账号。');return;}
  client.set(me.user,me.csrf_token);const activeEpoch=client.epoch;
  for(const id of ['workflow-admin-nav','operations-link','admin-link'])if(element(id))element(id).hidden=!me.user.is_admin;
  if(mode==='tasks'){
   const pref=await client.request('/api/workflow/preferences');if(activeEpoch!==client.epoch)return;
   element('auto-model').checked=pref.auto_model;element('auto-physiology').checked=pref.auto_physiology;
  }
  text('page-account',me.user.username+' · '+(mode==='tasks'?'仅显示本人记录':'管理员运行视图'));ready=true;element('page-content').hidden=false;await refreshPage();
 }catch(error){if(epoch===client.epoch||client.user)text('page-notice',error.message+'；请返回工作台确认登录后重试。');}
}
element('refresh-page').onclick=()=>client.user&&ready?refreshPage():initializePage();
if(mode==='tasks'){
 element('task-stage').onchange=()=>{offset=0;refreshPage();};
 element('previous-page').onclick=()=>{offset=Math.max(0,offset-25);refreshPage();};element('next-page').onclick=()=>{offset+=25;refreshPage();};
 element('preferences-form').onsubmit=async event=>{
  event.preventDefault();if(preferenceBusy)return;preferenceBusy=true;const epoch=client.epoch;element('save-preferences').disabled=true;
  try{await client.request('/api/workflow/preferences','PUT',{auto_model:element('auto-model').checked,auto_physiology:element('auto-physiology').checked});if(epoch===client.epoch){text('preferences-message','设置已保存，仅用于此后首次上传完成的本人记录。');await refreshPage();}}
  catch(error){if(epoch===client.epoch)text('preferences-message',error.message);}
  finally{preferenceBusy=false;element('save-preferences').disabled=false;}
 };
}
setInterval(async()=>{if(document.hidden||polling||!client.user)return;polling=true;try{await refreshPage();}finally{polling=false;}},15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&client.user)refreshPage();});
initializePage();
