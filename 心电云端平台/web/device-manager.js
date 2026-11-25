'use strict';
const el=id=>document.getElementById(id);
const manager={epoch:0,credentialEpoch:0,user:null,csrf:'',devices:[],users:[],selected:null,credentials:null,busy:false,listVersion:0,detailVersion:0,offset:0,limit:10,total:0,accountId:'',account:null};
const deviceTools=window.AdminUI;
const deviceConnections={online:'近期在线',offline:'未近期上报',unknown:'尚未上报',disabled:'已停用'};
const deviceStates={standby:'待机',acquiring:'正在采集',saving:'正在保存',error:'终端报告异常',unknown:'当前状态未知'};
function clearCredentials(){manager.credentials=null;el('credential-value').value='';}
function clearManager(message){
 manager.epoch++;manager.user=null;manager.csrf='';manager.devices=[];manager.users=[];manager.selected=null;
 manager.listVersion++;manager.detailVersion++;manager.account=null;manager.total=0;manager.appliedQuery=null;el('manager-success').textContent='';
 for(const id of ['device-runtime','device-recent-records','device-account-context'])el(id).replaceChildren();
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
 clearCredentials();manager.selected=d;manager.editorUserIds=[];el('convert-legacy-device').checked=false;
 el('device-editor-title').textContent=d?'配置设备':'添加设备';el('device-id').value=d?.device_id || '';el('device-id').disabled=!!d;
 el('device-name').value=d?.name || '';el('legacy-device-note').hidden=!d?.legacy_shared;
 el('save-device').textContent=d?'保存设备配置':'创建并获取凭据';el('toggle-device').hidden=el('rotate-device').hidden=!d;
 el('toggle-device').textContent=d?.active?'停用设备':'恢复设备';el('rotate-device').disabled=d?.active===false;
 el('device-form-error').textContent='';const users=el('device-users');users.replaceChildren();
 el('device-form').hidden=false;el('device-user-query').value='';el('device-runtime').hidden=!d;el('device-runtime').replaceChildren();el('device-recent-records').replaceChildren();
 if(d){
  el('device-runtime').append(deviceTools.node('strong',(deviceConnections[d.connection]||'状态未知')+' · '+(deviceStates[d.state]||'当前状态未知')),
   deviceTools.node('p','配置：'+(d.active?'已启用':'已停用')+' · 最近上报 '+deviceTools.date(d.last_seen)),deviceTools.node('p','最近上传活动 '+deviceTools.date(d.last_upload_at)));
  const link=deviceTools.node('a','查看此设备的记录信息');link.href=deviceTools.link('/database',{device_id:d.device_id});el('device-runtime').append(link);
 }
 for(const u of manager.users){
  const label=document.createElement('label'),checkbox=document.createElement('input'),caption=document.createElement('span');
  checkbox.type='checkbox';checkbox.value=u.id;checkbox.name='device-user';checkbox.disabled=!u.active;
  checkbox.checked=!!d?.user_ids?.includes(u.id) || (!!u.active && (!!d?.legacy_shared || (!d&&u.id===manager.accountId)));
  if(checkbox.checked)manager.editorUserIds.push(u.id);
  caption.textContent=u.username+(!u.active?'（已停用，当前不可授权）':'');label.append(checkbox,caption);users.append(label);
 }
 drawDeviceList();
}
function drawDeviceList(){
 const parent=el('managed-devices');parent.replaceChildren();
 for(const d of manager.devices){
  const button=document.createElement('button');button.type='button';button.className='managed-device'+(manager.selected?.device_id===d.device_id?' active':'');
  const name=document.createElement('strong'),detail=document.createElement('span');name.textContent=d.name;
  detail.textContent=d.device_id+' · '+(d.active?'已启用':'已停用')+' · '+(deviceConnections[d.connection]||'状态未知')+'\n'+(d.legacy_shared?'旧版共享选人':d.explicit_grants+' 个授权账号')+' · '+d.record_count+' 条记录';
  button.append(name,detail);button.onclick=()=>{if(!manager.busy)return loadManagedDevice(d.device_id);};parent.append(button);
  if(manager.account){const action=deviceTools.node('button',d.legacy_shared?'旧版共享，需在配置中转换':d.granted?'取消此账号授权':'授权给此账号','button secondary');action.type='button';action.disabled=manager.busy||d.legacy_shared||(!d.granted&&(!d.active||!manager.account.active));action.onclick=()=>changeDeviceGrant(d);parent.append(action);}
 }
 if(!manager.devices.length)parent.append(deviceTools.node('p','没有符合条件的设备。','admin-empty'));
 el('device-page').textContent=(Math.floor(manager.offset/manager.limit)+1)+' / '+Math.max(1,Math.ceil(manager.total/manager.limit))+' · '+manager.total+' 台';el('device-prev').disabled=manager.offset===0;el('device-next').disabled=manager.offset+manager.limit>=manager.total;
}
function saveDeviceQuery(){window.history.replaceState(null,'',deviceTools.link('/devices',{...manager.appliedQuery,account:manager.accountId,offset:manager.offset,selected:manager.selected?.device_id}));}
async function loadManagedDevice(did){
 const epoch=manager.epoch,version=++manager.detailVersion;manager.selected=null;clearCredentials();el('device-form').hidden=true;el('device-runtime').hidden=true;el('device-recent-records').replaceChildren();el('device-editor-title').textContent='正在读取设备…';
 try{
  const result=await managerRequest('/api/admin/console/devices/'+encodeURIComponent(did));if(epoch!==manager.epoch||version!==manager.detailVersion)return;
  drawDeviceEditor(result.device);saveDeviceQuery();
  if(result.recent_records?.length){el('device-recent-records').append(deviceTools.node('h3','最近登记记录'));for(const record of result.recent_records){const row=deviceTools.node('div','','admin-item'),body=deviceTools.node('div',''),a=deviceTools.node('a',record.name||record.session_id);a.href=deviceTools.link('/database',{device_id:did,q:record.session_id});body.append(a,deviceTools.node('p',(record.complete?'上传完成':'上传中')+' · '+deviceTools.date(record.created_at)));row.append(body);el('device-recent-records').append(row);}}
 }catch(error){if(epoch===manager.epoch&&version===manager.detailVersion){el('device-editor-title').textContent='设备详情未读取';el('device-form-error').textContent=error.message;el('manager-notice').textContent=error.message+'；可重新选择设备。';}}
}
async function reloadDevices(prefer){
 const epoch=manager.epoch,version=++manager.listVersion;el('device-list-note').textContent='正在读取…';
 const selected=prefer===undefined?manager.selected?.device_id:prefer;
 const query={q:el('device-query').value,connection:el('device-connection').value||'all',grant:manager.accountId?(el('device-grant').value||'all'):'all'};
 const [devices,users]=await Promise.all([managerRequest(deviceTools.link('/api/admin/console/devices',{...query,account_id:manager.accountId,limit:manager.limit,offset:manager.offset})),managerRequest('/api/admin/users')]);
 if(epoch!==manager.epoch||version!==manager.listVersion)return;
 manager.devices=devices.devices;manager.users=users.users;manager.total=devices.total;manager.account=devices.account;manager.appliedQuery=query;
 if(manager.offset&&manager.offset>=manager.total){manager.offset=Math.max(0,Math.floor((manager.total-1)/manager.limit)*manager.limit);return reloadDevices(selected);}
 el('device-account-context').hidden=!manager.account;el('device-grant-filter').hidden=!manager.account;el('device-account-context').replaceChildren();
 if(manager.account){el('device-account-context').append(deviceTools.node('p','正在配置账号 '+manager.account.username+' 的设备授权'+(manager.account.active?'':'（已停用）')));const a=deviceTools.node('a','返回账号详情');a.href=deviceTools.link('/admin/accounts',{selected:manager.accountId});el('device-account-context').append(a);}
 drawDeviceList();el('device-list-note').textContent='读取于 '+new Date().toLocaleString()+' · 在线表示 35 秒内收到心跳';
 if(selected)await loadManagedDevice(selected);else drawDeviceEditor(null);if(epoch===manager.epoch&&version===manager.listVersion)saveDeviceQuery();
}
async function changeDeviceGrant(device){
 if(!manager.account||manager.busy||device.legacy_shared)return;const account=manager.account;
 if(!confirm((device.granted?'取消':'添加')+'账号“'+account.username+'”在设备“'+device.name+'”的授权？已有记录和其他账号授权保留。'))return;
 await performDeviceAction(async epoch=>{await managerRequest('/api/admin/console/accounts/'+encodeURIComponent(account.id)+'/devices/'+encodeURIComponent(device.device_id),'PUT',{granted:!device.granted});if(epoch!==manager.epoch)return;el('manager-success').textContent='该账号的设备授权已更新。';await reloadDevices(manager.selected?.device_id);});
}
function showCredentials(value,version=manager.credentialEpoch){
 if(document.hidden || version!==manager.credentialEpoch){clearCredentials();el('manager-notice').textContent='页面离开期间收到的凭据未展示；请重新更新设备凭据并保存。';return;}
 manager.credentials=value;el('credential-value').value=JSON.stringify(value,null,2);el('device-credentials').showModal();
}
async function performDeviceAction(action){
 if(manager.busy)return;
 manager.busy=true;el('save-device').disabled=true;const epoch=manager.epoch;el('device-form-error').textContent='';
 try{await action(epoch);}catch(e){if(epoch===manager.epoch)el('device-form-error').textContent=e.message;}
 finally{manager.busy=false;el('save-device').disabled=false;if(epoch===manager.epoch&&manager.user)drawDeviceList();}
}
el('device-form').onsubmit=event=>{
 event.preventDefault();const selected=manager.selected,credentialEpoch=manager.credentialEpoch;
 const payload={name:el('device-name').value,user_ids:Array.from(document.querySelectorAll('input[name="device-user"]:checked')).map(x=>x.value)};
 if(!selected)payload.device_id=el('device-id').value.trim();
 else {
  const changed=JSON.stringify([...payload.user_ids].sort())!==JSON.stringify([...(manager.editorUserIds||[])].sort());
  if(selected.legacy_shared&&!el('convert-legacy-device').checked){if(changed){el('device-form-error').textContent='请勾选确认转换为单独授权后再保存名单。';return;}delete payload.user_ids;}
  else if(!changed&&!selected.legacy_shared)delete payload.user_ids;
  if(payload.user_ids){payload.expected_user_ids=selected.user_ids||[];payload.expected_legacy_shared=!!selected.legacy_shared;}
 }
 return performDeviceAction(async epoch=>{
  const result=await managerRequest('/api/admin/devices'+(selected?'/'+encodeURIComponent(selected.device_id):''),selected?'PATCH':'POST',payload);
  if(epoch!==manager.epoch)return;
  el('manager-success').textContent=selected?'设备配置已保存。':'设备已创建，请保存并安装本台设备的凭据。';
  const did=selected?.device_id || result.device.device_id;
  try {await reloadDevices(did);} finally {if(epoch===manager.epoch && result.credentials)showCredentials(result.credentials,credentialEpoch);}
  if(epoch!==manager.epoch)return;
  if(result.credentials && !manager.credentials)return;
 });
};
el('new-device').onclick=()=>{if(!manager.busy){manager.detailVersion++;drawDeviceEditor();saveDeviceQuery();}};
el('reload-devices').onclick=()=>performDeviceAction(()=>reloadDevices());
el('device-search').onsubmit=async event=>{event.preventDefault();if(manager.busy){el('manager-notice').textContent='设备变更正在保存，请完成后重新查询。';return;}manager.offset=0;const epoch=manager.epoch;try{await reloadDevices();}catch(error){if(epoch===manager.epoch)el('device-list-note').textContent='查询未完成：'+error.message+'；已有列表可能已过期。';}};
el('device-prev').onclick=()=>{if(manager.busy)return;manager.offset=Math.max(0,manager.offset-manager.limit);performDeviceAction(()=>reloadDevices());};
el('device-next').onclick=()=>{if(manager.busy)return;manager.offset+=manager.limit;performDeviceAction(()=>reloadDevices());};
el('device-user-query').oninput=()=>{const query=el('device-user-query').value.toLowerCase();for(const label of el('device-users').children)label.hidden=!label.textContent.toLowerCase().includes(query);};
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
  const params=new URLSearchParams(window.location.search);manager.accountId=(params.get('account')||'').slice(0,96);el('device-query').value=(params.get('q')||'').slice(0,100);el('device-connection').value=['online','offline','unknown','disabled'].includes(params.get('connection'))?params.get('connection'):'all';el('device-grant').value=['granted','ungranted'].includes(params.get('grant'))?params.get('grant'):'all';manager.offset=Math.max(0,Math.min(1000000,Number(params.get('offset'))||0));
  await reloadDevices(params.get('new')==='1'?null:params.get('selected'));if(epoch!==manager.epoch)return;
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
