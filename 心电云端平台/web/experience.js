'use strict';
// User-facing navigation, status and report snapshots. No records are persisted here.
var UserExperience = (() => {
  let listTime=null,detailTime=null,listStale=false,detailStale=false,guideInitialized=false;
  let snapshot=null,manualBusy=false,pull=null;
  const stamp=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'尚未成功读取';
  const session=()=>state.wave?.session?.session_id===state.selected?state.wave.session:null;
  const on=(id,event,handler)=>$(id).addEventListener(event,handler);
  function renderTimes(){
    text('records-updated',(listStale?'更新失败，保留上次列表 · ':'列表更新于 ')+stamp(listTime));
    text('result-updated',(detailStale?'更新失败，显示上次读取结果 · ':'波形与记录更新于 ')+stamp(detailTime));
  }
  function renderSummary(){
    const s=session(),summary=ECGExperience.describe(s,state.analysis,state.physiology);
    text('process-title',summary.title);text('process-next',summary.next);
    $('record-progress').dataset.tone=summary.tone;
    text('classification-progress',summary.classification || '正在读取');
    text('physiology-progress',summary.physiology || '正在读取');
    $('preview-report').disabled=!s;
  }
  function listUpdated(){
    listTime=Date.now();listStale=false;renderTimes();
    if(!manualBusy)text('pull-feedback','');
    $('latest-record').disabled=!state.sessions.length;
    if(!guideInitialized){$('first-steps').open=state.total===0 && !Object.keys(state.filters).length;guideInitialized=true;}
    renderSummary();
  }
  function detailUpdated(){detailTime=Date.now();detailStale=false;renderTimes();renderSummary();}
  function listFailed(){listStale=true;renderTimes();if(!manualBusy)text('pull-feedback','刷新未完成，可点击刷新重试。');}
  function detailFailed(){detailStale=true;renderTimes();renderSummary();}
  function clearReport(){
    snapshot=null;$('report-dialog').close();$('report-rows').replaceChildren();
    $('report-wave').removeAttribute('src');$('report-wave').hidden=true;
    for(const id of ['report-name','report-range','report-note','report-feedback'])text(id,'');
    $('report-print').disabled=true;
  }
  function selectionChanged(){
    detailTime=null;detailStale=false;clearReport();renderTimes();renderSummary();
    $('record-details').open=!window.matchMedia('(max-width: 720px)').matches;
  }
  function clear(){
    listTime=detailTime=null;listStale=detailStale=false;guideInitialized=false;manualBusy=false;pull=null;
    clearReport();$('device-list').replaceChildren();$('latest-record').disabled=true;
    $('first-steps').open=false;$('password').type='password';
    $('refresh').disabled=$('refresh-devices').disabled=false;text('devices-feedback','正在读取设备状态…');
    $('toggle-password').setAttribute('aria-pressed','false');text('toggle-password','显示');
    text('pull-feedback','');renderTimes();renderSummary();
    for(const id of ['quick-today','quick-week'])$(id).setAttribute('aria-pressed','false');
  }
  function renderDevices(payload){
    const focused=document.activeElement?.dataset?.deviceId;
    const parent=$('device-list');parent.replaceChildren();
    if(!payload){text('devices-feedback','设备状态读取失败，请重试。已有历史记录仍可查看。');return;}
    const devices=payload.devices || [];
    text('devices-feedback',devices.length?'最近刷新：'+stamp(Date.now()):'暂无可查看的设备，请联系分配账号的管理员确认设备授权。');
    for(const d of devices){
      const card=document.createElement('article');card.className='panel device-entry';
      const title=document.createElement('h2');title.textContent=d.name || d.device_id;
      const connection=document.createElement('p');connection.className='device-connection';
      const connectionNames={online:'终端在线',offline:'终端离线',disabled:'设备已停用',unknown:'状态待确认'};
      const modeNames={standby:'待机，可在设备端开始测量',acquiring:'采集中',saving:'正在保存',error:'设备需要检查',other_user:'终端在线'};
      connection.textContent=d.connection==='online'?(modeNames[d.state] || '终端在线'):(connectionNames[d.connection] || '状态待确认');
      const signal=document.createElement('p');
      signal.textContent=d.connection==='online' && d.state!=='other_user'?(d.signal_text || '请在设备屏幕查看采集状态'):'当前采集信息不显示，历史记录仍可查看。';
      const seen=document.createElement('p');seen.className='muted';seen.textContent=d.last_seen?'最近上报：'+stamp(d.last_seen*1000):'尚未收到上报，不代表设备已断电。';
      const records=document.createElement('button');records.type='button';records.className='button secondary';records.textContent='查看该设备记录';
      records.dataset.deviceId=d.device_id;
      records.onclick=()=>{
        $('filters').reset();state.filters={device_id:d.device_id};state.page=0;
        $('filter-device').value=d.device_id;MobileUI.filtersChanged();MobileUI.show('records',{load:false});reloadList();
        for(const id of ['quick-today','quick-week'])$(id).setAttribute('aria-pressed','false');
      };
      card.append(title,connection,signal,seen,records);parent.append(card);
      if(focused===d.device_id)records.focus({preventScroll:true});
    }
  }
  async function refreshManually(){
    if(manualBusy || state.busy || !state.ready){text('pull-feedback',state.busy?'正在同步，请稍候…':'');return;}
    const epoch=state.epoch;manualBusy=true;text('pull-feedback','正在刷新…');
    $('refresh').disabled=$('refresh-devices').disabled=true;
    try {await refresh();}
    finally {if(epoch===state.epoch){manualBusy=false;$('refresh').disabled=$('refresh-devices').disabled=false;text('pull-feedback',listStale?'刷新未完成，可点击刷新重试。':'已刷新');}}
  }
  function quickRange(days){
    const range=ECGExperience.dateRange(days);
    $('date-from').value=range.from;$('date-to').value=range.to;
    $('filters').onsubmit({preventDefault(){}});
    $('quick-today').setAttribute('aria-pressed',String(days===1));$('quick-week').setAttribute('aria-pressed',String(days===7));
  }
  async function openLatest(){
    if(state.page!==0){
      const epoch=state.epoch;state.page=0;state.listEpoch++;state.busy=false;
      const ticket=state.listEpoch;await refresh();
      if(epoch!==state.epoch || ticket!==state.listEpoch || listStale)return;
    }
    const record=state.sessions[0];if(!record)return;
    selectSession(record.session_id);renderList();
    if(!MobileUI.openResult()){loadWave();loadAnalysis();}
  }
  function help(){ $('help-dialog').showModal(); }
  function openReport(){
    const s=session();if(!s)return;
    const summary=ECGExperience.describe(s,state.analysis,state.physiology);
    const wave=state.wave,rows=[
      ['记录名称',s.name || '未命名记录'],['记录编号',s.session_id],['账号',state.user?.username || '本机工作台'],
      ['采集时间（设备记录）',date(s.started_utc)],['来源',sources[s.source] || '来源未知'],['设备',s.device_id || '未提供'],
      ['记录状态',summary.title],['测量时长',ECGExperience.duration(s.sample_count)],
      ['心率 · 终端统计',$('measurement-heart').textContent],['有效信号 · 终端统计',$('measurement-quality').textContent],
      ['心搏分类 · 终端保存',$('measurement-class').textContent],['心搏分类 · 云端',summary.classification],
      ['心搏与间期分析 · 云端',summary.physiology],['记录备注',s.note || '无']
    ];
    if(state.analysis?.session_id===s.session_id && state.analysis.analysis_status==='complete'){
      rows.push(['云端分类数量','N '+$('class-N').textContent+' / S '+$('class-S').textContent+' / V '+$('class-V').textContent],
        ['分类版本',$('model-name').textContent],['分类结果时间',$('model-time').textContent]);
    }
    if(state.physiology?.session_id===s.session_id && ['complete','ineligible'].includes(state.physiology.analysis_status)){
      rows.push(['平均心搏间期 · 云端',$('rr-mean').textContent],['间期换算心率 · 云端',$('rr-heart-rate').textContent],
        ['有效信号覆盖 · 云端',$('qrs-quality').textContent],['心搏与间期分析版本',$('physiology-version').textContent],['HRV',$('hrv-message').textContent]);
    }
    let image='';
    try{
      if(wave.points?.some(p=>p[1]!==null)){
        const source=$('chart'),copy=document.createElement('canvas');copy.width=source.width;copy.height=source.height;
        const context=copy.getContext('2d');
        context.fillStyle=window.matchMedia('(max-width: 720px)').matches?'#fbfdfc':'#0c2026';
        context.fillRect(0,0,copy.width,copy.height);context.drawImage(source,0,0);
        image=copy.toDataURL('image/png');
      }
    }catch(_){}
    const range='仅显示当前窗口：采样时间 '+((wave.start_sample || 0)/360).toFixed(1)+'–'+((wave.end_sample || 0)/360).toFixed(1)+' 秒；横轴跨中断不代表连续时钟时间。完整原始数据请导出 CSV。';
    const note='报告生成于 '+stamp(Date.now())+'。'+$('result-updated').textContent+'。'+$('clock-note').textContent;
    snapshot={epoch:state.epoch,sid:s.session_id,user:state.user?.id,title:s.name || '未命名记录',rows,image,range,note};
    text('report-name',snapshot.title);text('report-range',range);text('report-note',note);text('report-feedback','');
    const body=$('report-rows');body.replaceChildren();
    for(const [label,value] of rows){const row=document.createElement('tr'),head=document.createElement('th'),cell=document.createElement('td');head.textContent=label;head.setAttribute('scope','row');cell.textContent=value;row.append(head,cell);body.append(row);}
    $('report-wave').hidden=!image;if(image)$('report-wave').src=image;else $('report-wave').removeAttribute('src');
    $('report-print').disabled=false;$('report-dialog').showModal();
  }
  function printDocument(){
    if(!snapshot || snapshot.epoch!==state.epoch || snapshot.sid!==state.selected || snapshot.user!==state.user?.id || !$('report-dialog').open)return null;
    return ECGExperience.reportHTML(snapshot);
  }
  function printReport(){
    if(!printDocument())return;
    if(document.documentElement.dataset.nativeApp==='android'){location.href='ecg-report://print';return;}
    if(typeof window.print==='function')window.print();
    else text('report-feedback','此浏览器暂不支持打印，请在系统浏览器打开后使用“打印/存储 PDF”。');
  }
  on('quick-today','click',()=>quickRange(1));on('quick-week','click',()=>quickRange(7));on('latest-record','click',openLatest);
  $('refresh').onclick=refreshManually;on('refresh-devices','click',refreshManually);
  on('open-devices','click',()=>MobileUI.show('devices'));
  on('my-help','click',help);on('login-help','click',help);on('device-help','click',help);
  on('help-close','click',()=>$('help-dialog').close());
  on('toggle-password','click',()=>{const show=$('password').type==='password';$('password').type=show?'text':'password';$('toggle-password').setAttribute('aria-pressed',String(show));text('toggle-password',show?'隐藏':'显示');});
  on('preview-report','click',openReport);on('report-print','click',printReport);on('report-close','click',clearReport);
  on('report-dialog','close',()=>{snapshot=null;$('report-rows').replaceChildren();$('report-wave').removeAttribute('src');});
  on('record-details','toggle',()=>requestAnimationFrame(draw));
  on('filters','submit',()=>{for(const id of ['quick-today','quick-week'])$(id).setAttribute('aria-pressed','false');});
  on('reset-filters','click',()=>{for(const id of ['quick-today','quick-week'])$(id).setAttribute('aria-pressed','false');});
  // A pull only starts at the top of the records page, outside inputs/buttons.
  document.addEventListener('touchstart',event=>{
    pull=null;
    if(!state.ready || !window.matchMedia('(max-width: 720px)').matches || event.touches.length!==1 || window.scrollY>0 || $('workspace-shell').dataset.mobileView!=='records' || event.target.closest('button,a,input,select,textarea,summary,dialog'))return;
    pull={x:event.touches[0].clientX,y:event.touches[0].clientY,ready:false};
  },{passive:true});
  document.addEventListener('touchmove',event=>{
    if(!pull || event.touches.length!==1){pull=null;return;}
    const dx=event.touches[0].clientX-pull.x,dy=event.touches[0].clientY-pull.y;
    if(Math.abs(dx)>40 || dy<0){pull=null;text('pull-feedback','');return;}
    pull.ready=dy>=80;text('pull-feedback',pull.ready?'松开刷新':'下拉刷新');
  },{passive:true});
  document.addEventListener('touchend',()=>{const ready=pull?.ready;pull=null;if(ready)refreshManually();else text('pull-feedback','');},{passive:true});
  document.addEventListener('touchcancel',()=>{pull=null;text('pull-feedback','');},{passive:true});
  text('app-version',document.documentElement.dataset.nativeApp==='android'?'Android 1.1.0':'网页版 · 界面 1.1.0');
  $('record-details').open=!window.matchMedia('(max-width: 720px)').matches;
  renderTimes();renderSummary();
  return {clear,selectionChanged,listUpdated,listFailed,detailUpdated,detailFailed,renderSummary,renderDevices,printDocument,openReport,refreshManually,quickRange};
})();
