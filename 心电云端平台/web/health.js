'use strict';
var HealthAssistant=(()=>{
  const core=ECGHealth, native=document.documentElement.dataset.nativeApp==='android';
  const settingsKey='ecg-health-preferences-v1', accountKey='ecg-health-account-v1';
  let prefs=core.preferences(), period='month', trend=null, revision=0, pendingCredentials=null;
  let tasks=[], taskBusy=false, startBusy=false, requestKey=null, autoReport=null, support=false, timer=null, lastRefresh=0;
  try{prefs=core.preferences(JSON.parse(localStorage.getItem(settingsKey)||'{}'));}catch(_){}
  const setText=(id,value)=>{$(id).textContent=value;};
  const save=(key,value)=>{try{if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,JSON.stringify(value));return true;}catch(_){return false;}};
  const current=(epoch)=>state.ready&&epoch===state.epoch;
  function apply(){document.documentElement.dataset.healthText=prefs.textSize;document.documentElement.dataset.healthContrast=prefs.contrast;}
  function loginShown(){
    try{const remembered=JSON.parse(localStorage.getItem(accountKey)||'null');if(remembered?.username){$('username').value=remembered.username;$('remember-account').checked=true;}}catch(_){}
    if(native)location.href='ecg-credentials://load';
  }
  function restoreLogin(value){
    if(state.ready||$('login-panel').hidden||!value||typeof value.username!=='string'||typeof value.password!=='string')return;
    $('username').value=value.username;$('password').value=value.password;$('remember-account').checked=true;$('remember-password').checked=true;
    setText('remember-feedback','已填入此手机安全保存的账号，请点击登录。');
  }
  async function loginSuccess(values){
    save(accountKey,$('remember-account').checked?{username:state.user?.username||values.username}:null);
    if(!$('remember-password').checked){pendingCredentials=null;if(native)location.href='ecg-credentials://clear';return;}
    if(native){pendingCredentials={username:state.user.username,password:values.password,userId:state.user.id};location.href='ecg-credentials://save';}
    else if(window.PasswordCredential&&navigator.credentials?.store){
      try{await navigator.credentials.store(new PasswordCredential({id:values.username,password:values.password}));}
      catch(_){notice('登录成功；密码未保存，可使用浏览器的密码管理器。');}
    }else notice('登录成功；请在浏览器密码管理器中保存密码，此浏览器不支持应用主动保存。');
  }
  function consumeCredentials(){const value=pendingCredentials;pendingCredentials=null;return value;}
  function forget(){save(accountKey,null);pendingCredentials=null;$('username').value='';$('password').value='';$('remember-account').checked=false;$('remember-password').checked=false;if(native)location.href='ecg-credentials://clear';setText('preferences-feedback',native?'已请求清除此手机保存的账号密码。':'已清除记住的账号；浏览器保存的密码请在浏览器密码管理器删除。');}
  function clear(){revision++;trend=null;tasks=[];taskBusy=false;startBusy=false;requestKey=null;autoReport=null;support=false;pendingCredentials=null;clearInterval(timer);timer=null;$('health-chart').replaceChildren();$('trend-table-body').replaceChildren();$('measurement-tasks').replaceChildren();$('measurement-device').replaceChildren();for(const id of ['trend-total','trend-duration'])setText(id,'—');}
  async function ready(){
    const epoch=state.epoch;
    try{const response=await fetch('/health',{cache:'no-store'});const health=await response.json();if(!current(epoch))return;support=health.health_assistant_version>=1;}
    catch(_){if(!current(epoch))return;support=false;}
    $('measurement-start').disabled=!support;
    setText('health-capability',support?'选择时长，连接设备，完成一次有记录的测量。':'新版趋势与手机发起测量需要更新云端和采集终端。历史记录仍可查看。');
    if(support)loadTasks();
    timer=setInterval(()=>{if(!current(epoch)||document.hidden)return;if($('measurement-dialog').open)loadTasks();if(Date.now()-lastRefresh>prefs.refreshSeconds*1000){lastRefresh=Date.now();if($('trends-dialog').open)loadTrends();}},3000);
  }
  async function loadTrends(){
    const epoch=state.epoch,ticket=++revision,anchor=$('trend-anchor').value;
    if(!support){setText('trends-feedback','服务器尚未提供趋势统计接口，请更新云端后使用。');return;}
    if(!/^\d{4}-\d{2}-\d{2}$/.test(anchor)){setText('trends-feedback','请选择有效日期。');return;}
    setText('trends-feedback','正在读取趋势…');
    try{
      const offset=-new Date(anchor+'T12:00:00').getTimezoneOffset();
      const payload=await(await api('/api/records/trends?'+new URLSearchParams({period,anchor,utc_offset_minutes:offset}))).json();
      if(!current(epoch)||ticket!==revision)return;trend=payload;paintTrend();
      setText('trends-feedback',payload.note+' 时区 UTC'+(offset>=0?'+':'')+(offset/60)+'。');
    }catch(e){if(current(epoch)&&ticket===revision){trend=null;$('health-chart').replaceChildren();$('trend-table-body').replaceChildren();setText('trend-total','—');setText('trend-duration','—');setText('trends-feedback','统计未读取成功：'+e.message);}}
  }
  function svg(tag,attributes={},label){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attributes))node.setAttribute(k,String(v));if(label!==undefined)node.textContent=label;return node;}
  function paintTrend(){
    if(!trend)return;const metric=$('trend-metric').value,values=core.series(trend.buckets,metric),chart=$('health-chart'),width=Math.max(280,chart.clientWidth||620),points=core.points(values,width);chart.replaceChildren();chart.setAttribute('viewBox','0 0 '+width+' 195');
    setText('trend-total',String(trend.total_records));setText('trend-duration',(trend.total_duration_s/60).toFixed(1)+' 分钟');
    const label=metric==='hr'?'平均心率（次/分）':metric==='duration'?'记录时长（分钟）':'测量次数';
    chart.setAttribute('aria-label',label+'趋势；精确数值见下方数据表');chart.append(svg('title',{},label),svg('line',{x1:30,y1:165,x2:width-10,y2:165,stroke:'#b9cec2'}));
    const max=Math.max(1,...values.filter(Number.isFinite));chart.append(svg('text',{x:4,y:22,fill:'#577064','font-size':12},Number(max.toFixed(1))));
    let segment=[];const flush=()=>{if(segment.length>1)chart.append(svg('polyline',{points:segment.join(' '),fill:'none',stroke:'#087f71','stroke-width':2.5}));segment=[];};
    points.forEach((p,i)=>{
      if(!p){flush();return;}
      if(metric==='hr'){segment.push(p.x+','+p.y);chart.append(svg('circle',{cx:p.x,cy:p.y,r:3,fill:'#087f71'}));}
      else {const barWidth=Math.min(18,(width-50)/points.length*.65);chart.append(svg('rect',{x:p.x-barWidth/2,y:p.y,width:barWidth,height:Math.max(0,165-p.y),rx:3,fill:'#299782'}));}
      if(i===0||i===points.length-1||i%Math.ceil(points.length/6)===0)chart.append(svg('text',{x:p.x,y:185,'text-anchor':'middle',fill:'#577064','font-size':11},trend.buckets[i].label));
    });flush();
    if(metric==='hr'&&!values.some(Number.isFinite))chart.append(svg('text',{x:width/2,y:94,'text-anchor':'middle',fill:'#577064','font-size':15},'暂无可信心率数据'));
    const body=$('trend-table-body');body.replaceChildren();for(const b of trend.buckets){const tr=document.createElement('tr');for(const value of [b.label,b.records,(b.duration_s/60).toFixed(1),b.hr_mean??'暂无']){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}body.append(tr);}
  }
  async function openMeasurement(){
    $('measurement-dialog').showModal();$('measurement-duration').value=String(prefs.duration);$('measurement-confirm').checked=false;setText('measurement-feedback','正在读取设备…');
    const epoch=state.epoch;const select=$('measurement-device');select.replaceChildren();
    try{const payload=await(await api('/api/devices')).json();if(!current(epoch))return;for(const d of payload.devices||[]){const opt=document.createElement('option');opt.value=d.device_id;opt.textContent=(d.name||d.device_id)+' · '+(d.connection==='online'&&d.remote_ready?'可测量':'未就绪');opt.disabled=!(d.active&&d.connection==='online'&&d.remote_ready);select.append(opt);}const available=Array.from(select.options).find(o=>!o.disabled);select.value=available?.value||'';setText('measurement-feedback',available?'请确认电极贴好并选择测量时长。':'暂无就绪终端。请更新并启动树莓派程序，选择真实采集串口。');}
    catch(e){if(current(epoch))setText('measurement-feedback','设备读取失败：'+e.message);}
    if(current(epoch))loadTasks();
  }
  async function startMeasurement(event){
    event.preventDefault();if(startBusy)return;if(!$('measurement-confirm').checked||!$('measurement-device').value){setText('measurement-feedback','请先选择可用设备并确认测量准备。');return;}
    const epoch=state.epoch;startBusy=true;$('measurement-start').disabled=true;
    requestKey=requestKey||crypto.randomUUID();
    try{const task=await jsonRequest('/api/measurements','POST',{device_id:$('measurement-device').value,duration_s:Number($('measurement-duration').value),request_key:requestKey});if(!current(epoch))return;autoReport=task.id;requestKey=null;setText('measurement-feedback','请求已发送，等待终端确认。测量计时由终端执行。');await loadTasks();}
    catch(e){if(current(epoch))setText('measurement-feedback','发起测量未确认：'+e.message+'。重试会沿用同一请求，避免重复采集。');}
    finally{if(current(epoch)){startBusy=false;$('measurement-start').disabled=!support;}}
  }
  async function loadTasks(){
    if(taskBusy||!support||!state.ready)return;const epoch=state.epoch;taskBusy=true;
    try{const payload=await(await api('/api/measurements')).json();if(!current(epoch))return;tasks=payload.measurements;paintTasks();const completed=tasks.find(t=>t.id===autoReport&&t.status==='completed');if(completed&&$('measurement-dialog').open){autoReport=null;openTaskReport(completed);}}
    catch(e){if(current(epoch)&&$('measurement-dialog').open)setText('measurement-feedback','测量状态暂未更新：'+e.message+'；已开始的采集仍由终端计时。');}
    finally{if(current(epoch))taskBusy=false;}
  }
  function paintTasks(){
    const parent=$('measurement-tasks');parent.replaceChildren();const names={queued:'等待终端',accepted:'准备采集',recording:'正在测量',uploading:'上传并生成报告',completed:'报告已就绪',failed:'需要检查',expired:'请求已过期'};
    for(const task of tasks){const card=document.createElement('article');card.className='measurement-task';const title=document.createElement('h3');title.textContent=task.duration_s/60+' 分钟 · '+(names[task.status]||task.status);const message=document.createElement('p');message.textContent=task.message;card.append(title,message);if(task.status==='recording'){const bar=document.createElement('progress');bar.removeAttribute('value');bar.setAttribute('aria-label','终端正在按选定时长采集');card.append(bar);}if(task.status==='completed'&&task.session_id){const button=document.createElement('button');button.className='button secondary';button.textContent='查看测量报告';button.onclick=()=>openTaskReport(task);card.append(button);}parent.append(card);}
  }
  async function openTaskReport(task){
    const epoch=state.epoch;setText('measurement-feedback','正在准备报告…');
    try{
      // Each task type is independently deduplicated by the server; failures stay visible in the report.
      await Promise.allSettled(['analysis-jobs','physiology-jobs'].map(kind=>api('/api/sessions/'+encodeURIComponent(task.session_id)+'/'+kind,{method:'POST'})));
      if(!current(epoch))return;selectSession(task.session_id);renderList();MobileUI.show('results',{load:false});
      await Promise.all([loadWave(),loadAnalysis()]);if(!current(epoch)||state.selected!==task.session_id)return;
      if(state.wave?.session?.session_id!==task.session_id)throw new Error('记录未读取成功，请重试');
      $('measurement-dialog').close();UserExperience.openReport();
    }catch(e){if(current(epoch))setText('measurement-feedback','报告暂未打开：'+e.message);}
  }
  function openPreferences(){for(const [key,id]of Object.entries({textSize:'preference-text',contrast:'preference-contrast',refreshSeconds:'preference-refresh',duration:'preference-duration'}))$(id).value=String(prefs[key]);setText('preferences-feedback','设置仅保存在此设备，不影响账号和云端记录。');$('preferences-dialog').showModal();}
  $('health-trends-open').onclick=()=>{$('trends-dialog').showModal();loadTrends();};$('health-measure-open').onclick=openMeasurement;$('app-preferences').onclick=openPreferences;
  for(const name of ['trends','measurement','preferences'])$(name+'-close').onclick=()=>$(name+'-dialog').close();
  for(const button of document.querySelectorAll('[data-trend-period]'))button.onclick=()=>{period=button.dataset.trendPeriod;for(const b of document.querySelectorAll('[data-trend-period]'))b.setAttribute('aria-pressed',String(b===button));loadTrends();};
  $('trend-anchor').value=core.day();$('trend-anchor').onchange=loadTrends;$('trend-metric').onchange=paintTrend;$('trends-refresh').onclick=loadTrends;
  $('measurement-form').onsubmit=startMeasurement;$('measurement-reload').onclick=openMeasurement;
  for(const id of ['measurement-device','measurement-duration'])$(id).onchange=()=>{requestKey=null;};
  $('preferences-form').onsubmit=event=>{event.preventDefault();prefs=core.preferences({textSize:$('preference-text').value,contrast:$('preference-contrast').value,refreshSeconds:$('preference-refresh').value,duration:$('preference-duration').value});apply();setText('preferences-feedback',save(settingsKey,prefs)?'设置已保存。':'设置已应用，但此设备不允许保存，下次打开将恢复默认。');};
  $('forget-login').onclick=forget;
  $('remember-password').onchange=()=>{if($('remember-password').checked)$('remember-account').checked=true;};
  $('remember-account').onchange=()=>{if(!$('remember-account').checked){$('remember-password').checked=false;save(accountKey,null);if(native)location.href='ecg-credentials://clear';}};
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.ready&&support)loadTasks();});
  apply();if(!$('login-panel').hidden)loginShown();if(state.ready)ready();
  return {clear,ready,loginShown,loginSuccess,restoreLogin,consumeCredentials,forget,openPreferences};
})();
