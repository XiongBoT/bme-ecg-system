'use strict';
var BackupScheduleUI=(()=>{
 let current=null,version=0,dirty=false,busy=false;
 function lock(value){for(const id of ['backup-plan-enabled','backup-plan-time','backup-plan-save','backup-plan-refresh'])dbEl(id).disabled=value;}
 function clear(){version++;current=null;dirty=busy=false;lock(false);dbEl('backup-plan-form').reset();dbText('backup-plan-state','');dbText('backup-plan-feedback','');}
 function render(value){
  if(!dirty)current=value;
  if(!dirty){dbEl('backup-plan-enabled').checked=value.enabled;dbEl('backup-plan-time').value=String(value.hour).padStart(2,'0')+':'+String(value.minute).padStart(2,'0');}
  const last=value.last_run;
  dbText('backup-plan-state',(value.enabled?'下次计划：'+new Date(value.next_due*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）':'计划已关闭')+(value.message?' · '+value.message:'')+(last?'\n最近计划任务：'+(dbStatuses[last.status]||last.status)+' · '+dbDate(last.updated)+(last.error?' · '+last.error:''):'\n尚未执行计划备份。'));
 }
 async function load(){
  if(busy||!databaseUI.user)return;
  const epoch=databaseUI.epoch,stamp=++version;
  try{const result=await dbRequest('/api/admin/database/backup-schedule');if(epoch===databaseUI.epoch&&stamp===version)render(result);}
  catch(error){if(epoch===databaseUI.epoch&&stamp===version)dbText('backup-plan-feedback',error.message+'；可刷新重试。');}
 }
 dbEl('backup-plan-form').oninput=()=>{dirty=true;};
 dbEl('backup-plan-refresh').onclick=()=>{dirty=false;load();};
 dbEl('backup-plan-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!current||!databaseUI.user)return;
  const match=/^(\d{2}):(\d{2})$/.exec(dbEl('backup-plan-time').value);if(!match){dbText('backup-plan-feedback','请选择每天执行时间。');return;}
  const epoch=databaseUI.epoch,stamp=++version;busy=true;lock(true);
  try{const result=await dbRequest('/api/admin/database/backup-schedule','PUT',{enabled:dbEl('backup-plan-enabled').checked,hour:Number(match[1]),minute:Number(match[2]),revision:current.revision});if(epoch!==databaseUI.epoch||stamp!==version)return;dirty=false;render(result);dbText('backup-plan-feedback','计划已保存。关闭计划只停止后续触发，已接受的维护任务会继续。');}
  catch(error){if(epoch===databaseUI.epoch&&stamp===version)dbText('backup-plan-feedback',error.message+'；请刷新计划后重试。');}
  finally{if(epoch===databaseUI.epoch&&stamp===version){busy=false;lock(false);}}
 };
 return {clear,load};
})();
