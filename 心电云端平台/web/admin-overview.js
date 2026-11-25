'use strict';
const overviewUI=window.AdminUI;
let overviewLoad=0;
const overviewSession=new overviewUI.Session(message=>{
 overviewLoad++;overviewUI.el('console-content').hidden=true;overviewUI.text('console-account','');overviewUI.text('console-notice',message);overviewUI.text('console-updated','');
 for(const id of ['console-stats','console-todos','console-problems','console-storage'])overviewUI.el(id).replaceChildren();
});
function overviewCard(label,value,note,href){
 const a=overviewUI.node('a','','admin-stat');a.href=href;a.append(overviewUI.node('span',label),overviewUI.node('strong',String(value)),overviewUI.node('small',note));overviewUI.el('console-stats').append(a);
}
function overviewRow(container,title,note,href){
 const row=overviewUI.node('div','','admin-item'),body=overviewUI.node('div',''),a=overviewUI.node('a','查看');body.append(overviewUI.node('strong',title),overviewUI.node('p',note));a.href=href;row.append(body,a);overviewUI.el(container).append(row);
}
function renderConsole(data){
 for(const id of ['console-stats','console-todos','console-problems','console-storage'])overviewUI.el(id).replaceChildren();
 const devices=data.devices,records=data.records,total=Object.values(devices).reduce((a,b)=>a+b,0);
 overviewCard('在线采集设备',devices.online||0,'共 '+total+' 台 · 心跳 35 秒内','/devices?connection=online');
 overviewCard('今日上传登记',records.today_registered,data.day.date+' · 北京时间',overviewUI.link('/database',{registered_day:data.day.date}));
 overviewCard('待分配记录',records.unassigned,'有效记录中尚无所属账号','/database?owner_id=unassigned');
 overviewCard('分析失败待查',data.analysis.failed||0,'另有 '+((data.analysis.queued||0)+(data.analysis.running||0))+' 项分析进行中','#analysis-problems');
 const offline=devices.offline||0,unknown=devices.unknown||0;
 if(offline)overviewRow('console-todos',offline+' 台设备未近期上报','不等于设备已停用；可检查最近连接和上传。','/devices?connection=offline');
 if(unknown)overviewRow('console-todos',unknown+' 台设备尚未上报','完成凭据安装后，确认终端连接情况。','/devices?connection=unknown');
 if(records.uploading)overviewRow('console-todos',records.uploading+' 条记录上传未完成','可能仍在正常上传，需结合最近活动判断。','/database?state=uploading');
 if(records.unassigned)overviewRow('console-todos',records.unassigned+' 条记录等待分配','确认记录归属后，通过账号管理的历史记录入口处理。','/admin/accounts#unassigned-section');
 if(!offline&&!unknown&&!records.uploading&&!records.unassigned)overviewUI.el('console-todos').append(overviewUI.node('p','当前没有上述待办。','admin-empty'));
 for(const job of data.analysis_problems)overviewRow('console-problems',job.session_id,(job.kind==='physiology'?'QRS / RR':'分类分析')+' · '+overviewUI.date(job.updated),overviewUI.link('/database',{q:job.session_id}));
 if(!data.analysis_problems.length)overviewUI.el('console-problems').append(overviewUI.node('p','最近任务中没有分析失败项。','admin-empty'));
 for(const [name,value] of [['磁盘剩余',overviewUI.bytes(data.disk.free_bytes)],['磁盘总量',overviewUI.bytes(data.disk.total_bytes)],['有效记录',records.active+' 条'],['可登录账号',data.accounts.active+' / '+data.accounts.total],['最近成功备份',data.latest_backup?overviewUI.date(data.latest_backup.updated):'尚无成功备份'],['维护任务',(data.maintenance.running||0)+' 项处理中 · '+(data.maintenance.queued||0)+' 项等待']])overviewUI.el('console-storage').append(overviewUI.node('dt',name),overviewUI.node('dd',value));
 overviewUI.text('console-updated','读取于 '+overviewUI.date(data.measured_at)+' · 设备在线仅表示近期上报');
}
async function refreshConsole(){
 const version=++overviewLoad;overviewUI.el('console-refresh').disabled=true;
 try{
  if(!overviewSession.user)await overviewSession.identify();
  if(version!==overviewLoad)return;
  overviewUI.text('console-account',overviewSession.user.username+' · 管理员');
  const data=await overviewSession.request('/api/admin/console/overview');if(version!==overviewLoad)return;
  renderConsole(data);overviewUI.el('console-content').hidden=false;overviewUI.text('console-notice','');
 }catch(error){if(version===overviewLoad)overviewUI.text('console-notice',error.message+'；可刷新重试。已有数据以读取时间为准。');}
 finally{overviewUI.el('console-refresh').disabled=false;}
}
overviewUI.el('console-refresh').onclick=refreshConsole;overviewSession.watch();refreshConsole();
