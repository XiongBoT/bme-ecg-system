'use strict';
function clearAccount() {
  clearAdmin();
  clearPasswordEditor();
  if(typeof resetDesktop==='function')resetDesktop();
  clearDevices();
  renderMeasurement(null);
  physiologyUI?.clear();
  state.epoch++; state.listEpoch++; state.generation++; state.analysisGeneration++;
  state.ready=false; state.user=null; state.csrf=''; state.sessions=[]; state.selected=null;
  state.wave=null; state.analysis=null; state.analyzing=null; state.views.clear(); state.page=0;
  state.busy=false; state.total=0; state.filters={}; state.analysisKey=''; state.tableKey=''; state.listKey='';
  detailFeedback(); $('detail-retry').disabled=false;
  text('filter-error',''); $('filter-error').hidden=true;
  if (typeof MobileUI !== 'undefined') MobileUI.reset();
  state.beatFilter='all';state.amplitude=1;
  $('sessions').replaceChildren(); $('beats-body').replaceChildren(); $('content').hidden=true;
  text('session-count','0'); text('records-page','1 / 1'); $('records-prev').disabled=true; $('records-next').disabled=true;
  $('model-result').hidden=true; $('user-list').replaceChildren(); $('unassigned-list').replaceChildren();
  for(const id of ['record-name','record-note','record-id','source','provenance-kind','samples','chunks','duration','valid',
    'device','capture-time','first-upload','received','source-status','provenance-note','clock-note','wave-origin',
    'model-name','model-message','beat-count','class-N','class-S','class-V','model-time','eligible-count',
    'skipped-count','quality-reasons','position-label','selected-beat','account-name','model-status','upload-status','beats-total','beats-page']) text(id,'');
  $('input-summary').hidden=true; $('beats-panel').hidden=true; $('marker-legend').hidden=true;
  $('skip-reasons').replaceChildren(); $('chart').width=$('chart').width;
  $('record-form').reset(); $('new-user-form').reset(); $('password-form').reset(); renderDevice(null); notice('');
  $('filters').reset(); experience('clear'); for(const dialog of document.querySelectorAll('dialog[open]')) dialog.close();
  draw();
}
function showLogin(message='') {
  clearAccount(); $('workspace-shell').hidden=true; $('login-panel').hidden=false;
  $('password').value=''; text('login-error',message);
  $('login-submit').disabled=false;
}
function enterWorkspace(payload) {
  clearAccount(); state.user=payload?.user || null; state.csrf=payload?.csrf_token || ''; state.ready=true;
  $('login-panel').hidden=true; $('workspace-shell').hidden=false; $('password').value='';
  $('settings').hidden=state.auth; $('logout').hidden=!state.auth; $('admin').hidden=!state.user?.is_admin;
  $('change-password').hidden=!state.auth;
  $('manage-devices').hidden=!state.user?.is_admin;
  $('manage-database').hidden=!state.user?.is_admin;
  $('manage-operations').hidden=!state.user?.is_admin;
  $('task-center').hidden=$('records-tasks').hidden=!state.user;
  const linkedRecord=new URLSearchParams(globalThis.location?.search || '').get('record');
  if(linkedRecord && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(linkedRecord)){state.filters.q=linkedRecord;$('query').value=linkedRecord;}
  text('account-name',state.user ? state.user.username+' · 我的记录' : '本机工作台');
  $('login-submit').disabled=false;connectionStatus();
  refresh();
}
function renderDevice(d) {
  const connection={online:'终端在线',offline:'终端离线',disabled:'设备已停用',unknown:'尚未收到设备状态'};
  const modes={standby:'待机',acquiring:'采集中',saving:'保存中',error:'设备需要检查',other_user:'终端在线'};
  text('device-state',d?.connection==='online' ? modes[d.state] || '终端在线' : connection[d?.connection] || '设备状态暂不可用');
  text('device-signal',d?.connection==='online' && d.state!=='other_user'
    ? d.signal_text || (d.state==='standby'?'可在树莓派屏幕上手动开始采集':'等待信号状态')
    : '历史记录可继续查看；当前信号状态不显示');
  text('device-seen',d?.last_seen ? '最近心跳 '+date(d.last_seen*1000) : '未收到心跳不代表设备已断电');
}
async function jsonRequest(path,method,body) {
  const epoch=state.epoch;
  const response=await (await api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  if(epoch!==state.epoch)throw new Error('登录状态已改变');
  return response;
}
$('login-form').onsubmit=async event=>{
  event.preventDefault(); const epoch=state.epoch; $('login-submit').disabled=true; text('login-error','');
  try {enterWorkspace(await jsonRequest('/api/auth/login','POST',{username:$('username').value,password:$('password').value}));}
  catch(e) {if(epoch===state.epoch)text('login-error',e.message);}
  finally {if(epoch===state.epoch)$('login-submit').disabled=false;}
};
$('logout').onclick=async()=>{
  try {await api('/api/auth/logout',{method:'POST'}); showLogin();}
  catch(e) {notice('退出未完成：'+e.message);}
};
function reloadList() {state.listEpoch++; state.busy=false; state.generation++; state.analysisGeneration++; refresh();}
$('filters').onsubmit=event=>{
  event.preventDefault(); const params={trashed:$('trash-filter').value};
  text('filter-error',''); $('filter-error').hidden=true;
  if ($('date-from').value && $('date-to').value && $('date-from').value > $('date-to').value) {
    text('filter-error','开始日期不能晚于结束日期。'); $('filter-error').hidden=false; return;
  }
  if($('query').value.trim()) params.q=$('query').value.trim();
  if($('filter-source').value) params.source=$('filter-source').value;
  if($('filter-device').value) params.device_id=$('filter-device').value;
  if($('date-from').value) params.started_from=new Date($('date-from').value+'T00:00:00').toISOString();
  if($('date-to').value) {const d=new Date($('date-to').value+'T00:00:00');d.setDate(d.getDate()+1);params.started_before=d.toISOString();}
  state.filters=params; state.page=0;
  if (typeof MobileUI !== 'undefined') MobileUI.filtersChanged();
  reloadList();
};
$('reset-filters').onclick=()=>{
  $('filters').reset();state.filters={};state.page=0; text('filter-error','');$('filter-error').hidden=true;
  if (typeof MobileUI !== 'undefined') MobileUI.filtersChanged();
  reloadList();
};
$('records-prev').onclick=()=>{state.page=Math.max(0,state.page-1);reloadList();};
$('records-next').onclick=()=>{state.page++;reloadList();};
let editSession=null;
$('edit-record').onclick=()=>{
  const s=state.wave?.session;if(!s || s.session_id!==state.selected)return;
  editSession=s.session_id;$('edit-name').value=s.name || '';$('edit-note').value=s.note || '';
  text('edit-error','');$('record-editor').showModal();
};
$('record-form').onsubmit=async event=>{
  event.preventDefault();const epoch=state.epoch;
  try {
    await jsonRequest('/api/sessions/'+encodeURIComponent(editSession)+'/details','PATCH',{name:$('edit-name').value,note:$('edit-note').value});
    if(epoch!==state.epoch)return;$('record-editor').close();reloadList();
  } catch(e) {if(epoch===state.epoch)text('edit-error',e.message);}
};
$('trash-record').onclick=async()=>{
  const s=state.wave?.session,epoch=state.epoch;if(!s || s.session_id!==state.selected)return;
  if(!s.trashed_at && !confirm('将此记录移入回收站？原始数据保留，可随时恢复。'))return;
  try {await api('/api/sessions/'+encodeURIComponent(s.session_id)+(s.trashed_at?'/restore':'/trash'),{method:'POST'});if(epoch===state.epoch)reloadList();}
  catch(e) {if(epoch===state.epoch)notice(e.message);}
};
const adminView={users:[],records:[],generation:0,load:0,page:0,busy:false,loading:false,loaded:false,userButtons:[],recordButtons:[]};
function clearNewUser() {
  $('new-user-form').reset();
  for(const id of ['new-username','new-password','new-password-confirm'])$(id).value='';
  text('new-user-error','');
}
function clearAdmin() {
  adminView.generation++;adminView.load++;adminView.users=[];adminView.records=[];
  adminView.page=0;adminView.busy=false;adminView.loading=false;adminView.loaded=false;adminView.userButtons=[];adminView.recordButtons=[];
  clearNewUser();$('admin-query').value='';$('admin-status-filter').value='all';$('admin-role-filter').value='all';
  for(const id of ['admin-error','admin-success','admin-summary','admin-page','admin-loading','unassigned-error'])text(id,'');
  $('user-list').replaceChildren();$('unassigned-list').replaceChildren();setAdminBusy(false);
}
function adminCurrent(epoch,generation) {
  return epoch===state.epoch && generation===adminView.generation && !!state.user?.is_admin && $('admin-dialog').open;
}
function setAdminBusy(busy) {
  adminView.busy=busy;
  $('new-user-submit').disabled=busy;$('admin-refresh').disabled=busy || adminView.loading;
  for(const button of [...adminView.userButtons,...adminView.recordButtons])button.disabled=busy || adminView.loading;
}
function renderAdminUsers() {
  const all=adminView.users,query=$('admin-query').value.trim().toLowerCase();
  const status=$('admin-status-filter').value,role=$('admin-role-filter').value;
  const users=all.filter(u=>u.username.includes(query) && (status==='active'?u.active:status==='disabled'?!u.active:true)
    && (role==='admin'?u.is_admin:role==='user'?!u.is_admin:true));
  const pages=Math.max(1,Math.ceil(users.length/10));adminView.page=Math.min(adminView.page,pages-1);
  const list=$('user-list');list.replaceChildren();adminView.userButtons=[];
  text('admin-summary',adminView.loaded?'共 '+all.length+' 个账号 · 可登录 '+all.filter(u=>u.active).length+' · 已停用 '+all.filter(u=>!u.active).length:'');
  text('admin-page',adminView.loaded?(adminView.page+1)+' / '+pages+' · 筛选 '+users.length+' 个':'—');
  $('admin-prev').disabled=!adminView.loaded || adminView.page===0;
  $('admin-next').disabled=!adminView.loaded || adminView.page>=pages-1;
  if(!adminView.loaded)return;
  if(!users.length){list.textContent='没有符合条件的账号';return;}
  const epoch=state.epoch,generation=adminView.generation;
  for(const u of users.slice(adminView.page*10,adminView.page*10+10)) {
    const row=document.createElement('article');row.className='user-row';
    const info=document.createElement('div');info.className='user-info';
    const name=document.createElement('strong');name.textContent=u.username;
    const badge=document.createElement('span');badge.className='pill '+(u.active?'':'neutral');
    badge.textContent=(u.is_admin?'管理员':'普通账号')+' · '+(u.active?'可登录':'已停用');
    const meta=document.createElement('p');meta.className='user-meta';
    meta.textContent='创建：'+(u.created_at?date(u.created_at*1000):'未记录')+'\n最近登录：'+(u.last_login_at?date(u.last_login_at*1000):'未记录')
      +'\n有效登录：'+(Number.isInteger(u.active_sessions)?u.active_sessions:'未提供');
    info.append(name,badge,meta);row.append(info);
    if(!u.is_admin) {
      const actions=document.createElement('div');actions.className='user-actions';
      const button=(label,handler)=>{
        const node=document.createElement('button');node.type='button';node.className='button secondary';node.textContent=label;
        node.setAttribute('aria-label',label+' '+u.username);node.disabled=adminView.busy || adminView.loading;
        node.onclick=()=>{if(adminCurrent(epoch,generation) && !adminView.busy && !adminView.loading)return handler();};
        actions.append(node);adminView.userButtons.push(node);
      };
      button('重置密码',()=>openPasswordEditor(u));
      button('撤销登录',()=>{
        if(!confirm('撤销 '+u.username+' 的所有已有登录？该账号可用原密码重新登录，记录和设备授权保留。'))return;
        return adminMutation(()=>jsonRequest('/api/admin/users/'+encodeURIComponent(u.id)+'/revoke-sessions','POST',{}),
          result=>'已撤销 '+u.username+' 的 '+result.revoked_sessions+' 个有效登录。');
      });
      button(u.active?'停用':'恢复',()=>{
        if(!confirm((u.active?'停用 '+u.username+' 后将撤销已有登录，并停止该账号登录及作为采集接收人。':'恢复 '+u.username+' 后允许重新登录。')+'已有记录和归属保留。'))return;
        return adminMutation(()=>jsonRequest('/api/admin/users/'+encodeURIComponent(u.id),'PATCH',{active:!u.active}),
          ()=>'已'+(u.active?'停用':'恢复')+' '+u.username+'。');
      });
      row.append(actions);
    }
    list.append(row);
  }
}
function renderUnassigned() {
  const container=$('unassigned-list');container.replaceChildren();adminView.recordButtons=[];
  if(!adminView.records.length){container.textContent='没有待分配记录';return;}
  const epoch=state.epoch,generation=adminView.generation;
  for(const s of adminView.records) {
    const row=document.createElement('div');row.className='assign-row';
    const label=document.createElement('p');label.textContent=(s.name || s.session_id)+' · '+date(s.started_utc);
    const select=document.createElement('select');select.setAttribute('aria-label','选择记录所属账号');
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='选择所属账号';select.append(placeholder);
    for(const u of adminView.users.filter(u=>u.active)) {const option=document.createElement('option');option.value=u.id;option.textContent=u.username;select.append(option);}
    const button=document.createElement('button');button.className='button secondary';button.textContent='确认分配';
    button.onclick=async()=>{
      if(!select.value || !adminCurrent(epoch,generation) || adminView.busy || adminView.loading)return;
      if(!confirm('将该记录归属给 '+select.selectedOptions[0].textContent+'？分配后无法在此更改。'))return;
      await adminMutation(()=>jsonRequest('/api/admin/sessions/'+encodeURIComponent(s.session_id)+'/assign','POST',{owner_id:select.value}),()=> '记录已分配。');
      if(adminCurrent(epoch,generation))reloadList();
    };
    adminView.recordButtons.push(button);button.disabled=adminView.busy || adminView.loading;
    row.append(label,select,button);container.append(row);
  }
}
async function loadAdmin() {
  const epoch=state.epoch,generation=adminView.generation,load=++adminView.load;
  if(!adminCurrent(epoch,generation))return;
  adminView.loading=true;setAdminBusy(adminView.busy);text('admin-loading','正在更新账号与待分配记录…');
  const [users,records]=await Promise.allSettled([api('/api/admin/users').then(r=>r.json()),api('/api/admin/unassigned-sessions').then(r=>r.json())]);
  if(!adminCurrent(epoch,generation) || load!==adminView.load)return;
  adminView.loading=false;adminView.loaded=users.status==='fulfilled';
  adminView.users=adminView.loaded?users.value.users:[];
  adminView.records=records.status==='fulfilled'?records.value.sessions:[];
  text('admin-loading','');text('admin-error',adminView.loaded?'':'账号列表更新失败：'+users.reason.message+'；可点击刷新重试。');
  text('unassigned-error',records.status==='fulfilled'?'':'待分配记录更新失败：'+records.reason.message+'；可点击刷新重试。');
  renderAdminUsers();
  if(adminView.loaded && records.status==='fulfilled')renderUnassigned();else {adminView.recordButtons=[];$('unassigned-list').replaceChildren();}
  setAdminBusy(adminView.busy);
}
async function adminMutation(action,message,onSuccess=null,errorId='admin-error') {
  const epoch=state.epoch,generation=adminView.generation;
  if(!adminCurrent(epoch,generation) || adminView.busy)return;
  setAdminBusy(true);text(errorId,'');text('admin-success','');
  try {
    const result=await action();
    if(!adminCurrent(epoch,generation)) {
      // The mutation still committed after this window closed. Refresh the
      // current view for the same login, without replacing its draft or notices.
      if(epoch===state.epoch && state.user?.is_admin && $('admin-dialog').open)await loadAdmin();
      return;
    }
    onSuccess?.(result);text('admin-success',message(result));await loadAdmin();
  } catch(e){if(adminCurrent(epoch,generation))text(errorId,e.message);}
  finally {if(adminCurrent(epoch,generation))setAdminBusy(false);}
}
$('admin').onclick=async()=>{clearAdmin();$('admin-dialog').showModal();await loadAdmin();};
$('admin-dialog').onclose=()=>{if(!$('admin-dialog').open)clearAdmin();};
$('admin-refresh').onclick=()=>{if(!adminView.busy)return loadAdmin();};
function filterAdmin(){adminView.page=0;renderAdminUsers();}
$('admin-query').oninput=filterAdmin;
$('admin-status-filter').onchange=filterAdmin;$('admin-role-filter').onchange=filterAdmin;
$('admin-prev').onclick=()=>{adminView.page=Math.max(0,adminView.page-1);renderAdminUsers();};
$('admin-next').onclick=()=>{adminView.page++;renderAdminUsers();};
$('new-user-form').onsubmit=async event=>{
  event.preventDefault();if(adminView.busy)return;
  const username=$('new-username').value.trim().toLowerCase(),password=$('new-password').value;
  if(!/^[a-z0-9][a-z0-9_-]{2,31}$/.test(username)){text('new-user-error','账号须为 3–32 位字母、数字、横线或下划线，并以字母或数字开头。');return;}
  if(Array.from(password).length<10 || Array.from(password).length>128){text('new-user-error','密码须为 10–128 个字符。');return;}
  if(password!==$('new-password-confirm').value){text('new-user-error','两次初始密码不一致。');return;}
  await adminMutation(()=>jsonRequest('/api/admin/users','POST',{username,password}),
    result=>'已创建普通账号 '+result.username+'。请通过可信渠道交付初始密码；设备采集权限请在设备管理中设置。',clearNewUser,'new-user-error');
};
let initializeGeneration=0;
async function initialize() {
  const generation=++initializeGeneration,epoch=state.epoch;
  $('login-submit').disabled=true;
  try {
    const config=await (await api('/api/auth/config')).json();if(generation!==initializeGeneration||epoch!==state.epoch)return;state.auth=config.enabled;
    if(state.auth) {
      state.token='';sessionStorage.removeItem('ecg-token');
      try {const payload=await (await api('/api/auth/me')).json();if(generation===initializeGeneration&&epoch===state.epoch)enterWorkspace(payload);}
      catch(e){if(generation!==initializeGeneration||epoch!==state.epoch)return;if(e.status===401){showLogin();connectionStatus();}else throw e;}
    } else enterWorkspace();
  } catch(e) {
    if(generation!==initializeGeneration||epoch!==state.epoch)return;
    showLogin('服务暂时无法连接，请点击上方“重新连接”。');$('login-submit').disabled=true;
    connectionStatus(e.connection || connectionProblem(e));
  }
}
let passwordTarget=null,passwordGeneration=0;
function clearPasswordEditor() {
  passwordGeneration++;passwordTarget=null;$('password-form').reset();
  for(const id of ['current-password','replacement-password','confirm-password'])$(id).value='';
  text('password-error','');$('password-submit').disabled=false;
}
function openPasswordEditor(user=null) {
  clearPasswordEditor();
  passwordTarget=user;
  text('password-title',user?'重置 '+user.username+' 的密码':'修改我的密码');
  $('current-password-field').hidden=!!user;$('current-password').required=!user;
  $('password-dialog').showModal();
}
$('password-dialog').onclose=()=>{if(!$('password-dialog').open)clearPasswordEditor();};
$('change-password').onclick=()=>openPasswordEditor();
$('password-form').onsubmit=async event=>{
  event.preventDefault();if($('password-submit').disabled)return;
  const epoch=state.epoch,target=passwordTarget,generation=passwordGeneration;
  if($('replacement-password').value!==$('confirm-password').value){text('password-error','两次新密码不一致');return;}
  const payload={new_password:$('replacement-password').value};
  if(!target)payload.current_password=$('current-password').value;
  $('password-submit').disabled=true;
  try {
    if(target) {
      await adminMutation(()=>jsonRequest('/api/admin/users/'+encodeURIComponent(target.id)+'/password','POST',payload),
        ()=>'已重置 '+target.username+' 的密码，其原有登录已撤销。',
        ()=>{if(generation===passwordGeneration){$('password-dialog').close();clearPasswordEditor();}},'password-error');
      return;
    }
    await jsonRequest('/api/auth/password','POST',payload);
    if(epoch!==state.epoch)return;
    showLogin('密码已修改，请用新密码重新登录。');
  } catch(e) {if(epoch===state.epoch && generation===passwordGeneration)text('password-error',e.message);}
  finally {if(epoch===state.epoch && generation===passwordGeneration)$('password-submit').disabled=false;}
};
initialize();setInterval(()=>{if(!document.hidden)refresh();},3000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
