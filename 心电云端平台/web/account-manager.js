'use strict';
const accountTools=window.AdminUI;
const accountUI={session:null,offset:0,limit:20,total:0,load:0,detail:0,unassigned:0,selected:null,passwordTarget:null,busy:false};
function clearAccountSecrets(){for(const id of ['account-new-password','account-new-confirm','account-password-value','account-password-confirm'])accountTools.el(id).value='';accountUI.passwordTarget=null;}
accountUI.session=new accountTools.Session(message=>{
 accountUI.load++;accountUI.detail++;accountUI.unassigned++;accountUI.selected=null;accountUI.busy=false;
 accountTools.el('accounts-content').hidden=true;accountTools.el('account-detail-content').hidden=true;
 for(const id of ['accounts-list','account-detail','account-devices','account-unassigned'])accountTools.el(id).replaceChildren();
 for(const id of ['accounts-identity','accounts-success','accounts-error','account-detail-title'])accountTools.text(id,'');
 clearAccountSecrets();accountTools.el('account-password-dialog').close();accountTools.text('accounts-notice',message);
});
function accountQuery(){return {q:accountTools.el('accounts-query').value.trim(),status:accountTools.el('accounts-status').value||'all',role:accountTools.el('accounts-role').value||'all',offset:accountUI.offset,selected:accountUI.selected?.id};}
function saveAccountQuery(){window.history.replaceState(null,'',accountTools.link('/admin/accounts',accountQuery()));}
function accountBusy(value){accountUI.busy=value;for(const id of ['account-create-submit','account-toggle','account-revoke','account-reset','account-password-submit','accounts-refresh','account-unassigned-load'])accountTools.el(id).disabled=value;}
async function loadAccounts(){
 const version=++accountUI.load,epoch=accountUI.session.epoch;accountTools.text('accounts-list-note','正在读取…');
 try{
  const data=await accountUI.session.request(accountTools.link('/api/admin/console/accounts',{...accountQuery(),selected:null,limit:accountUI.limit}));
  if(version!==accountUI.load||epoch!==accountUI.session.epoch)return;
  if(accountUI.offset&&accountUI.offset>=data.total){accountUI.offset=Math.max(0,Math.floor((data.total-1)/accountUI.limit)*accountUI.limit);return loadAccounts();}
  accountUI.total=data.total;accountTools.el('accounts-list').replaceChildren();accountTools.text('accounts-count',data.total+' 个');
  for(const user of data.accounts){
   const row=accountTools.node('div','','admin-item'),body=accountTools.node('div',''),button=accountTools.node('button','查看详情','button secondary');button.type='button';
   body.append(accountTools.node('strong',user.username),accountTools.node('p',(user.is_admin?'管理员':'普通账号')+' · '+(user.active?'可登录':'已停用')),accountTools.node('p',user.device_count+' 台关联设备 · '+user.record_count+' 条有效记录'));
   button.onclick=()=>{if(!accountUI.busy&&epoch===accountUI.session.epoch)return selectAccount(user.id);};row.append(body,button);accountTools.el('accounts-list').append(row);
  }
  accountTools.text('accounts-list-note',data.total?'读取于 '+new Date().toLocaleString():'没有符合条件的账号。');
  accountTools.text('accounts-page',(Math.floor(accountUI.offset/accountUI.limit)+1)+' / '+Math.max(1,Math.ceil(data.total/accountUI.limit)));
  accountTools.el('accounts-prev').disabled=accountUI.offset===0;accountTools.el('accounts-next').disabled=accountUI.offset+accountUI.limit>=data.total;saveAccountQuery();
 }catch(error){if(version===accountUI.load&&epoch===accountUI.session.epoch){accountTools.text('accounts-error',error.message+'；可刷新重试。');accountTools.text('accounts-list-note','读取未完成，已有列表可能已过期。');}}
}
async function selectAccount(uid){
 const version=++accountUI.detail,epoch=accountUI.session.epoch;accountUI.selected=null;accountTools.el('account-detail-content').hidden=true;accountTools.text('account-detail-notice','正在读取账号详情…');
 try{
  const data=await accountUI.session.request('/api/admin/console/accounts/'+encodeURIComponent(uid));
  if(version!==accountUI.detail||epoch!==accountUI.session.epoch)return;
  const user=data.account;accountUI.selected=user;accountTools.text('account-detail-title',user.username);accountTools.text('account-detail-notice','');accountTools.el('account-detail').replaceChildren();
  for(const [name,value] of [['账号状态',user.active?'可登录':'已停用'],['角色',user.is_admin?'管理员':'普通账号'],['创建时间',accountTools.date(user.created_at)],['最近登录',accountTools.date(user.last_login_at)],['有效登录',String(user.active_sessions??0)],['有效记录',String(user.record_count)]])accountTools.el('account-detail').append(accountTools.node('dt',name),accountTools.node('dd',value));
  for(const id of ['account-toggle','account-revoke','account-reset'])accountTools.el(id).hidden=user.is_admin;
  accountTools.el('account-toggle').textContent=user.active?'停用账号':'恢复账号';accountTools.el('account-records-link').href=accountTools.link('/database',{owner_id:uid});accountTools.el('account-grants-link').href=accountTools.link('/devices',{account:uid});
  accountTools.el('account-detail-content').hidden=false;accountTools.el('account-devices').replaceChildren(accountTools.node('p','正在读取设备…','admin-hint'));saveAccountQuery();
  if(window.matchMedia?.('(max-width:1100px)').matches)accountTools.el('account-detail-title').scrollIntoView({block:'start'});
  try{
   const devices=await accountUI.session.request(accountTools.link('/api/admin/console/devices',{account_id:uid,grant:'granted',limit:5}));
   if(version!==accountUI.detail||epoch!==accountUI.session.epoch)return;
   accountTools.el('account-devices').replaceChildren();
   for(const device of devices.devices){const row=accountTools.node('div','','admin-item'),a=accountTools.node('a',device.name),note=accountTools.node('p',(device.legacy_shared?'旧版共享':'单独授权')+' · '+(device.active?'已启用':'已停用'));a.href=accountTools.link('/devices',{account:uid,selected:device.device_id});const body=accountTools.node('div','');body.append(a,note);row.append(body);accountTools.el('account-devices').append(row);}
   if(!devices.total)accountTools.el('account-devices').append(accountTools.node('p','尚无关联设备，可点击下方管理授权。','admin-hint'));
   if(devices.total>5)accountTools.el('account-devices').append(accountTools.node('p','显示前 5 台，共 '+devices.total+' 台；点击管理授权查看全部。','admin-hint'));
  }catch(error){if(version===accountUI.detail&&epoch===accountUI.session.epoch)accountTools.el('account-devices').replaceChildren(accountTools.node('p','设备读取失败：'+error.message,'form-error'));}
 }catch(error){if(version===accountUI.detail&&epoch===accountUI.session.epoch)accountTools.text('account-detail-notice',error.message+'；可重新选择账号。');}
}
async function accountMutation(action,message,onSuccess){
 if(accountUI.busy||!accountUI.session.user)return;const epoch=accountUI.session.epoch;accountBusy(true);accountTools.text('accounts-error','');accountTools.text('accounts-success','');
 try{
  const result=await action();if(epoch!==accountUI.session.epoch)return;
  accountTools.text('accounts-success',typeof message==='function'?message(result):message);if(onSuccess)await onSuccess(result);
  if(epoch!==accountUI.session.epoch)return;await loadAccounts();
  if(epoch===accountUI.session.epoch&&accountUI.selected)await selectAccount(accountUI.selected.id);
 }catch(error){if(epoch===accountUI.session.epoch)accountTools.text('accounts-error',error.message);}
 finally{if(epoch===accountUI.session.epoch)accountBusy(false);}
}
accountTools.el('account-create-form').onsubmit=async event=>{
 event.preventDefault();if(accountUI.busy)return;const name=accountTools.el('account-new-name').value.trim().toLowerCase(),password=accountTools.el('account-new-password').value;
 let error='';if(!/^[a-z0-9][a-z0-9_-]{2,31}$/.test(name))error='账号须为 3–32 位字母、数字、横线或下划线';else if(Array.from(password).length<5||Array.from(password).length>128)error='密码须为 5–128 个字符';else if(password!==accountTools.el('account-new-confirm').value)error='两次密码不一致';
 accountTools.text('account-create-error',error);if(error)return;
 await accountMutation(()=>accountUI.session.request('/api/admin/users','POST',{username:name,password}),'账号已创建。请在账号详情的“管理设备授权”中继续配置采集设备。',async result=>{clearAccountSecrets();accountTools.el('account-new-name').value='';await selectAccount(result.id);});
};
accountTools.el('account-toggle').onclick=()=>{const u=accountUI.selected;if(!u||u.is_admin||!confirm((u.active?'停用':'恢复')+'账号“'+u.username+'”？'+(u.active?'将撤销其已有登录。':'')+'记录和设备授权保留。'))return;return accountMutation(()=>accountUI.session.request('/api/admin/users/'+encodeURIComponent(u.id),'PATCH',{active:!u.active}),'账号状态已更新。');};
accountTools.el('account-revoke').onclick=()=>{const u=accountUI.selected;if(!u||u.is_admin||!confirm('撤销“'+u.username+'”已有登录？该账号仍可用原密码重新登录。'))return;return accountMutation(()=>accountUI.session.request('/api/admin/users/'+encodeURIComponent(u.id)+'/revoke-sessions','POST',{}),'已有登录已撤销。');};
accountTools.el('account-reset').onclick=()=>{const u=accountUI.selected;if(!u||u.is_admin)return;accountUI.passwordTarget={id:u.id,username:u.username};accountTools.text('account-password-title','重置 '+u.username+' 的密码');accountTools.text('account-password-error','');accountTools.el('account-password-dialog').showModal();};
accountTools.el('account-password-dialog').addEventListener('close',()=>{accountUI.passwordTarget=null;accountTools.el('account-password-value').value='';accountTools.el('account-password-confirm').value='';});
accountTools.el('account-password-cancel').onclick=()=>accountTools.el('account-password-dialog').close();
accountTools.el('account-password-form').onsubmit=async event=>{
 event.preventDefault();const target=accountUI.passwordTarget,password=accountTools.el('account-password-value').value;if(!target||accountUI.busy)return;
 if(Array.from(password).length<5||Array.from(password).length>128||password!==accountTools.el('account-password-confirm').value){accountTools.text('account-password-error','请输入 5–128 个字符的新密码，并确保两次输入一致。');return;}
 await accountMutation(()=>accountUI.session.request('/api/admin/users/'+encodeURIComponent(target.id)+'/password','POST',{new_password:password}),'密码已重置，原有登录已失效。',()=>accountTools.el('account-password-dialog').close());
 if(accountTools.el('account-password-dialog').open)accountTools.text('account-password-error',accountTools.el('accounts-error').textContent);
};
async function loadUnassignedAccounts(){
 const version=++accountUI.unassigned,epoch=accountUI.session.epoch;accountTools.text('account-unassigned-notice','正在读取…');
 try{
  const [data,users]=await Promise.all([accountUI.session.request('/api/admin/database/records?owner_id=unassigned&limit=100'),accountUI.session.request('/api/admin/users')]);
  if(version!==accountUI.unassigned||epoch!==accountUI.session.epoch)return;accountTools.el('account-unassigned').replaceChildren();
  for(const record of data.records){
   const row=accountTools.node('div','','admin-item'),name=accountTools.node('strong',record.session_id),select=accountTools.node('select',''),button=accountTools.node('button','确认分配','button secondary');select.setAttribute('aria-label','记录 '+record.session_id+' 的所属账号');const empty=accountTools.node('option','选择所属账号');empty.value='';select.append(empty);
   for(const user of users.users.filter(u=>u.active)){const o=accountTools.node('option',user.username);o.value=user.id;select.append(o);}button.type='button';button.onclick=async()=>{if(!select.value||accountUI.busy||epoch!==accountUI.session.epoch)return;const uid=select.value;if(!confirm('将记录“'+record.session_id+'”分配给所选账号？确认后不能在此更改归属。'))return;await accountMutation(()=>accountUI.session.request('/api/admin/sessions/'+encodeURIComponent(record.session_id)+'/assign','POST',{owner_id:uid}),'记录已分配。');if(epoch===accountUI.session.epoch)await loadUnassignedAccounts();};const actions=accountTools.node('div','','admin-actions');actions.append(select,button);row.append(name,actions);accountTools.el('account-unassigned').append(row);
  }
  accountTools.text('account-unassigned-notice',data.records.length?'本次显示 '+data.records.length+' / '+data.total+' 条；仅在确认归属后分配。':'没有待分配记录。');
 }catch(error){if(version===accountUI.unassigned&&epoch===accountUI.session.epoch)accountTools.text('account-unassigned-notice',error.message+'；可重试读取。');}
}
accountTools.el('account-unassigned-load').onclick=loadUnassignedAccounts;
accountTools.el('accounts-filters').onsubmit=event=>{event.preventDefault();accountUI.offset=0;accountTools.text('accounts-error','');loadAccounts();};
accountTools.el('accounts-prev').onclick=()=>{accountUI.offset=Math.max(0,accountUI.offset-accountUI.limit);loadAccounts();};accountTools.el('accounts-next').onclick=()=>{accountUI.offset+=accountUI.limit;loadAccounts();};
accountTools.el('accounts-refresh').onclick=async()=>{if(!accountUI.session.user)return initializeAccounts();accountTools.text('accounts-error','');await loadAccounts();if(accountUI.selected)await selectAccount(accountUI.selected.id);};
async function initializeAccounts(){
 try{
  await accountUI.session.identify();const p=new URLSearchParams(window.location.search);accountTools.el('accounts-query').value=(p.get('q')||'').slice(0,32);
  accountTools.el('accounts-status').value=['active','disabled'].includes(p.get('status'))?p.get('status'):'all';accountTools.el('accounts-role').value=['admin','user'].includes(p.get('role'))?p.get('role'):'all';accountUI.offset=Math.max(0,Math.min(1000000,Math.floor(Number(p.get('offset'))||0)));
  accountTools.text('accounts-identity',accountUI.session.user.username+' · 管理员');accountTools.text('accounts-notice','');accountTools.el('accounts-content').hidden=false;
  if(p.get('create')==='1')accountTools.el('account-create').open=true;await loadAccounts();if(p.get('selected')&&accountUI.session.user)await selectAccount(p.get('selected'));
 }catch(error){if(accountUI.session.user)accountUI.session.clear(error.message);else accountTools.text('accounts-notice',error.message+'；请返回工作台确认登录。');}
}
accountUI.session.watch();
initializeAccounts();
