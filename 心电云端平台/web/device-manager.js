'use strict';
const el=id=>document.getElementById(id);
const manager={epoch:0,credentialEpoch:0,user:null,csrf:'',devices:[],users:[],selected:null,credentials:null,busy:false};
function clearCredentials(){manager.credentials=null;el('credential-value').value='';}
function clearManager(message){
 manager.epoch++;manager.user=null;manager.csrf='';manager.devices=[];manager.users=[];manager.selected=null;
 clearCredentials();el('device-credentials').close();el('manager-content').hidden=true;el('managed-devices').replaceChildren();el('device-users').replaceChildren();el('device-form').reset();el('manager-account').textContent='';el('manager-notice').textContent=message;
}
async function managerRequest(path,method='GET',payload){
 const epoch=manager.epoch;
 const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000),
  headers:{'Content-Type':'application/json','X-CSRF-Token':manager.csrf},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
 if(epoch!==manager.epoch)throw new Error('登录状态已改变');
 const uid=response.headers.get('X-ECG-User');
 if(manager.user && uid && uid!==manager.user.id){clearManager('其他页面已切换账号，请返回工作台重新登录。');throw new Error('账号已改变');}
 const body=await response.json();
 if(epoch!==manager.epoch)throw new Error('登录状态已改变');
 if(response.status===401){clearManager('请先返回工作台登录管理员账号。');throw new Error('需要登录');}
 if(response.status===403 && manager.user){clearManager('登录校验或管理权限已失效，请返回工作台重新登录。');throw new Error('需要重新登录');}
 if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'请求失败（'+response.status+'）');
 return body;
}
function drawDeviceEditor(d=null){
 clearCredentials();manager.selected=d;
 el('device-editor-title').textContent=d?'配置设备':'添加设备';el('device-id').value=d?.device_id || '';el('device-id').disabled=!!d;
 el('device-name').value=d?.name || '';el('legacy-device-note').hidden=!d?.legacy_shared;
 el('save-device').textContent=d?'保存设备配置':'创建并获取凭据';el('toggle-device').hidden=el('rotate-device').hidden=!d;
 el('toggle-device').textContent=d?.active?'停用设备':'恢复设备';el('rotate-device').disabled=d?.active===false;
 el('device-form-error').textContent='';const users=el('device-users');users.replaceChildren();
 for(const u of manager.users){
  const label=document.createElement('label'),checkbox=document.createElement('input'),caption=document.createElement('span');
  checkbox.type='checkbox';checkbox.value=u.id;checkbox.name='device-user';checkbox.disabled=!u.active;
  checkbox.checked=!!u.active && (!!d?.legacy_shared || !!d?.user_ids?.includes(u.id));
  caption.textContent=u.username+(!u.active?'（已停用，当前不可授权）':'');label.append(checkbox,caption);users.append(label);
 }
 drawDeviceList();
}
function drawDeviceList(){
 const parent=el('managed-devices');parent.replaceChildren();
 for(const d of manager.devices){
  const button=document.createElement('button');button.type='button';button.className='managed-device'+(manager.selected?.device_id===d.device_id?' active':'');
  const name=document.createElement('strong'),detail=document.createElement('span');name.textContent=d.name;
  detail.textContent=d.device_id+' · '+(d.active?'已启用':'已停用')+' · '+(d.legacy_shared?'旧版共享选人':d.user_ids.length+' 个授权账号');
  const facts=document.createElement('dl');facts.className='device-facts';
  const info=d.device_info||{};
  for(const [label,value]of [['连接状态',({online:'在线',offline:'离线',unknown:'尚未接入',disabled:'已停用'})[d.connection]||'未知'],['最近上报',d.last_seen?new Date(d.last_seen*1000).toLocaleString():'未收到'],['接入时间',d.created_at?new Date(d.created_at*1000).toLocaleString():'未记录'],['硬件型号',info.model||'未提供'],['系统',info.platform||'未提供'],['终端版本',info.app_version||'未提供'],['串口',info.serial_port||'未选择'],['采样率',info.sample_rate_hz?info.sample_rate_hz+' Hz':'未提供'],['剩余空间',Number.isFinite(d.free_bytes)?(d.free_bytes/1073741824).toFixed(2)+' GB':'未提供'],['记录数量',d.record_count??'未知'],['手机发起测量',d.remote_ready?'已就绪':'未就绪']]){const pair=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=String(value);pair.append(dt,dd);facts.append(pair);}
  button.append(name,detail,facts);button.onclick=()=>{if(!manager.busy)drawDeviceEditor(d);};parent.append(button);
 }
}
async function reloadDevices(prefer){
 const epoch=manager.epoch;
 const [devices,users]=await Promise.all([managerRequest('/api/admin/devices'),managerRequest('/api/admin/users')]);
 if(epoch!==manager.epoch)return;
 manager.devices=devices.devices;manager.users=users.users;
 const selected=prefer===undefined?manager.selected?.device_id:prefer;
 drawDeviceEditor(manager.devices.find(d=>d.device_id===selected) || null);
}
function showCredentials(value,version=manager.credentialEpoch){
 if(document.hidden || version!==manager.credentialEpoch){clearCredentials();el('manager-notice').textContent='页面离开期间收到的凭据未展示；请重新更新设备凭据并保存。';return;}
 manager.credentials=value;el('credential-value').value=JSON.stringify(value,null,2);el('device-credentials').showModal();
}
async function performDeviceAction(action){
 if(manager.busy)return;
 manager.busy=true;el('save-device').disabled=true;const epoch=manager.epoch;el('device-form-error').textContent='';
 try{await action(epoch);}catch(e){if(epoch===manager.epoch)el('device-form-error').textContent=e.message;}
 finally{manager.busy=false;el('save-device').disabled=false;}
}
el('device-form').onsubmit=event=>{
 event.preventDefault();const selected=manager.selected,credentialEpoch=manager.credentialEpoch;
 const payload={name:el('device-name').value,user_ids:Array.from(document.querySelectorAll('input[name="device-user"]:checked')).map(x=>x.value)};
 if(!selected)payload.device_id=el('device-id').value.trim();
 performDeviceAction(async epoch=>{
  const result=await managerRequest('/api/admin/devices'+(selected?'/'+encodeURIComponent(selected.device_id):''),selected?'PATCH':'POST',payload);
  if(epoch!==manager.epoch)return;
  const did=selected?.device_id || result.device.device_id;
  try {await reloadDevices(did);} finally {if(epoch===manager.epoch && result.credentials)showCredentials(result.credentials,credentialEpoch);}
  if(epoch!==manager.epoch)return;
  if(result.credentials && !manager.credentials)return;
  el('manager-notice').textContent=selected?'设备配置已保存。':'设备已创建，请保存并安装本台设备的凭据。';
 });
};
el('new-device').onclick=()=>{if(!manager.busy)drawDeviceEditor();};
el('reload-devices').onclick=()=>performDeviceAction(()=>reloadDevices());
el('toggle-device').onclick=()=>{
 const d=manager.selected;if(!d || !confirm((d.active?'停用':'恢复')+'设备“'+d.name+'”？已有记录和归属保留。'))return;
 performDeviceAction(async epoch=>{await managerRequest('/api/admin/devices/'+encodeURIComponent(d.device_id),'PATCH',{active:!d.active});if(epoch===manager.epoch)await reloadDevices(d.device_id);});
};
el('rotate-device').onclick=()=>{
 const d=manager.selected;if(!d || !confirm('更新“'+d.name+'”的设备凭据？旧凭据将立即失效，需重新安装新凭据。'))return;
 const credentialEpoch=manager.credentialEpoch;
 performDeviceAction(async epoch=>{const result=await managerRequest('/api/admin/devices/'+encodeURIComponent(d.device_id)+'/credentials','POST');if(epoch===manager.epoch)showCredentials(result.credentials,credentialEpoch);});
};
el('close-credentials').onclick=()=>el('device-credentials').close();
el('device-credentials').addEventListener('close',clearCredentials);
el('device-credentials').addEventListener('cancel',clearCredentials);
el('download-credentials').onclick=async()=>{
 if(!manager.credentials || !await recheckManagerSession() || !manager.credentials)return;
 const url=URL.createObjectURL(new Blob([JSON.stringify(manager.credentials,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download=manager.credentials.device_id+'-credentials.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
async function initializeManager(){
 const epoch=manager.epoch;
 try{
  const current=await managerRequest('/api/auth/me');
  if(!current.user.is_admin){clearManager('设备配置需要管理员账号。请返回工作台查看自己的记录。');return;}
  manager.user=current.user;manager.csrf=current.csrf_token;el('manager-account').textContent=current.user.username+' · 设备管理';
  await reloadDevices();if(epoch!==manager.epoch)return;
  el('manager-content').hidden=false;el('manager-notice').textContent='';
 }catch(e){if(epoch===manager.epoch)el('manager-notice').textContent=e.message+'。请返回工作台以管理员身份登录。';}
}
async function recheckManagerSession(){
 if(!manager.user)return false;
 const epoch=manager.epoch;
 try{
  const current=await managerRequest('/api/auth/me');
  if(epoch!==manager.epoch)return false;
  if(current.user.id!==manager.user.id || !current.user.is_admin){clearManager('登录权限已改变，请返回工作台重新登录。');return false;}
  manager.csrf=current.csrf_token;return true;
 }catch(e){if(epoch===manager.epoch)clearManager('无法确认当前登录状态，请返回工作台重新登录。');return false;}
}
function hideManagerCredentials(){manager.credentialEpoch++;clearCredentials();el('device-credentials').close();}
document.addEventListener('visibilitychange',()=>{if(document.hidden)hideManagerCredentials();else recheckManagerSession();});
window.addEventListener('pagehide',hideManagerCredentials);
window.addEventListener('focus',()=>recheckManagerSession());
setInterval(()=>{if(!document.hidden)recheckManagerSession();},3000);
initializeManager();
