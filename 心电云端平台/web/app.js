'use strict';
const $ = id => document.getElementById(id);
const state = {
  sessions: [], selected: null, follow: true, busy: false, wave: null,
  token: sessionStorage.getItem('ecg-token') || '', generation: 0, analysisGeneration: 0,
  analyzing: null, analysis: null, analysisKey: '', tableKey: '', views: new Map(), cloud: false,
  auth: false, ready: false, user: null, csrf: '', epoch: 0, listEpoch: 0, page: 0, total: 0, filters: {}, listKey: '',
  beatFilter:'all', amplitude:1, physiology:null
};
const PAGE_SIZE = 10;
const physiologyUI = typeof ECGPhysiology === 'undefined' ? null : ECGPhysiology.create({element:$, context:()=>state, request:(...args)=>api(...args), onChange:result=>{state.physiology=result;experience('renderSummary');}});
const sources = {demo: '本地合成', serial: '串口采集', replay: '文件回放', unknown: '来源未知'};
const kinds = {live: '本次采集', historical: '历史转存', unknown: '上传来源待确认'};
const classColors = {N:'#77e7c2', S:'#ffd27c', V:'#ff93b4'};
const skipLabels = {source_not_real:'本地合成或来源不符合要求',board_simulated:'板端模拟',mode_unknown:'采集模式未知',invalid_adc:'无效或饱和 ADC'};
const text = (id, value) => $(id).textContent = value;
const count = value => Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—';
function date(value) {
  if (!value) return '尚无记录';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '时间格式未知' : d.toLocaleString('zh-CN', {hour12:false});
}
function view() {
  if (!state.views.has(state.selected)) state.views.set(state.selected, {page:0, selected:null});
  return state.views.get(state.selected);
}
function beatKey(beat) { return String(beat.segment_id) + ':' + String(beat.sample_id); }
function currentBeats() {
  return state.analysis?.session_id === state.selected && state.analysis.analysis_status === 'complete'
    ? state.analysis.model_result?.beats || [] : [];
}
function experience(action,...args){if(typeof UserExperience!=='undefined')return UserExperience[action]?.(...args);}
function notice(value) { text('notice', value); $('notice').hidden = !value; }
function connectionStatus(problem=null) {
  const banner=$('connection-banner');if(!banner)return;
  banner.hidden=!problem;
  text('connection-title',problem?.title || '服务已连接');text('connection-message',problem?.message || '');
  text('service',problem?'● '+problem.title:'● 服务已连接');
  $('service').classList.toggle('off',!!problem);
}
function connectionProblem(error,status=0){
  return ECGConnection.describeFailure(error,status,typeof navigator==='undefined'||navigator.onLine!==false);
}
function detailFeedback(message = '', retry = false) {
  text('detail-message', message); $('detail-feedback').hidden = !message;
  $('detail-retry').hidden = !retry;
}
async function api(path, options = {}) {
  const epoch=state.epoch;
  const {timeoutMs = 7000, ...requestOptions} = options;
  const headers=state.auth ? {'X-CSRF-Token':state.csrf} : {'X-API-Key':state.token};
  let response;
  try {response = await fetch(path, {...requestOptions, cache:'no-store', credentials:'same-origin', headers:{...headers, ...options.headers}, signal:AbortSignal.timeout(timeoutMs)});}
  catch(cause){
    if(epoch!==state.epoch)throw new Error('登录状态已改变');
    const problem=connectionProblem(cause);connectionStatus(problem);
    const error=new Error(problem.message);error.connection=problem;throw error;
  }
  if(epoch!==state.epoch) throw new Error('登录状态已改变');
  const respondingUser=response.headers?.get('X-ECG-User');
  if(state.auth && state.user && respondingUser && respondingUser!==state.user.id) {
    showLogin('其他页面已切换账号，请重新确认登录');
    throw new Error('登录账号已改变');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if(epoch!==state.epoch) throw new Error('登录状态已改变');
    if(response.status===401 && state.auth && !path.endsWith('/login') && !path.endsWith('/me')) showLogin('登录已过期，请重新登录');
    const problem=response.status>=500?connectionProblem(null,response.status):null;
    if(problem)connectionStatus(problem);
    const error=new Error(problem?.message || (typeof body.detail === 'string' ? body.detail : '请求失败 (' + response.status + ')'));
    error.status=response.status;error.connection=problem;throw error;
  }
  return response;
}
function uploadLabel(s) {
  if (s.upload_status === 'complete') return '上传完成';
  return !s.received_at || Date.now()-Date.parse(s.received_at)>15000 ? '等待上传' : '正在接收';
}
function selectSession(sid) {
  if (sid === state.selected) return;
  state.selected = sid; state.follow = true; state.generation++; state.analysisGeneration++;
  state.wave = null; state.analysis = null; state.analysisKey = ''; state.tableKey = '';
  physiologyUI?.clear();
  $('content').hidden=true; $('chart').width=$('chart').width;
  $('detail-retry').disabled=false;
  detailFeedback(sid ? '正在读取测量结果…' : '');
  if (typeof MobileUI !== 'undefined') MobileUI.selectionChanged();
  experience('selectionChanged');
  renderAnalysis({session_id:sid, analysis_status:'loading', message:'正在读取此记录的模型状态'});
  draw();
}
function renderList() {
  const key = JSON.stringify([state.selected, state.total, state.filters, state.sessions, state.sessions.map(uploadLabel)]);
  if (key === state.listKey) return;
  state.listKey = key;
  const focused = document.activeElement?.dataset?.sessionId;
  const parent = $('sessions'); parent.replaceChildren(); text('session-count', state.total);
  if (!state.sessions.length) {
    const p=document.createElement('p'); p.className='empty-hint';
    const filtered = Object.entries(state.filters).some(([k,v]) => v && !(k === 'trashed' && v === 'false'));
    p.textContent = filtered ? '没有符合条件的记录。可展开“搜索与筛选”，重置条件后再试。' : '还没有测量记录。在树莓派选择本人账号，完成测量后点击“上传并分析”，再刷新这里。';
    parent.append(p); return;
  }
  let previousDay='';
  for (const s of state.sessions) {
    const button=document.createElement('button'); button.className='session'+(s.session_id===state.selected?' active':'');
    button.dataset.sessionId = s.session_id;
    const day=typeof ECGExperience!=='undefined'?ECGExperience.localDay(s.first_uploaded_at || s.received_at):'';
    if(day && day!==previousDay){const heading=document.createElement('h3');heading.className='session-day mobile-only';heading.textContent=day+' · 上传登记';parent.append(heading);previousDay=day;}
    button.setAttribute('aria-pressed', String(s.session_id===state.selected));
    const title=document.createElement('span'); title.className='session-title'; title.textContent=s.name || sources[s.source] || '来源未知';
    const tag=document.createElement('span'); tag.className='session-kind'; tag.textContent=kinds[s.provenance?.kind] || kinds.unknown;
    const sub=document.createElement('span'); sub.className='session-sub'; sub.textContent='采集 ' + date(s.started_utc);
    const data=document.createElement('span'); data.className='session-data';
    const n=document.createElement('span'); n.textContent=Number.isFinite(s.sample_count)?(s.sample_count/360).toFixed(1)+' 秒':'时长未知';
    const status=document.createElement('span'); status.className='session-status'; status.textContent=uploadLabel(s)+(s.source_status==='complete'?'':' · 采集状态待核对');
    data.append(n,status); button.append(title,tag,sub,data);
    button.onclick=()=>{
      selectSession(s.session_id);renderList();
      if (typeof MobileUI === 'undefined' || !MobileUI.openResult()) {loadWave();loadAnalysis();}
    };
    parent.append(button);
    if (focused === s.session_id) button.focus({preventScroll:true});
  }
}
async function refresh() {
  if(!state.ready || state.busy) return;
  const epoch=state.epoch, listEpoch=state.listEpoch, busy={}; state.busy=busy;
  try {
    const params=new URLSearchParams({...state.filters, limit:20, offset:state.page*20});
    const [result,device]=await Promise.all([
      api('/api/sessions?'+params).then(r=>r.json()),
      api('/api/devices').then(r=>r.json()).catch(()=>null)
    ]);
    if(epoch!==state.epoch || listEpoch!==state.listEpoch) return;
    state.total=result.total; state.sessions=result.sessions;
    if(state.page && !result.sessions.length) {state.page=Math.max(0,Math.ceil(result.total/20)-1); state.busy=false; return refresh();}
    text('records-page',(state.page+1)+' / '+Math.max(1,Math.ceil(result.total/20)));
    $('records-prev').disabled=!state.page; $('records-next').disabled=(state.page+1)*20>=result.total;
    renderDevices(device);
    if(!state.sessions.some(s=>s.session_id===state.selected)) selectSession(state.sessions[0]?.session_id || null);
    renderList(); experience('listUpdated'); $('empty').hidden=!!state.selected; $('content').hidden=!state.selected || state.wave?.session?.session_id!==state.selected;
    connectionStatus(); notice('');
    if(state.selected && (typeof MobileUI === 'undefined' || MobileUI.needsDetail())) await Promise.all([loadWave(),loadAnalysis()]);
  } catch(error) {
    if(epoch!==state.epoch || listEpoch!==state.listEpoch) return;
    text('service','● 连接中断'); $('service').classList.add('off');
    notice(error.message + '。已显示的数据保留，请检查服务或访问设置。');
    experience('listFailed');
  } finally {if(state.busy===busy) state.busy=false;}
}
function renderProvenance(s) {
  const p=s.provenance || {};
  text('provenance-kind',kinds[p.kind] || kinds.unknown);
  $('provenance-kind').className='pill '+(p.kind==='live'?'':'neutral');
  text('capture-time',date(s.started_utc)); $('capture-time').title=s.started_utc || '';
  text('first-upload-label',state.cloud?'云端上传登记':'服务上传登记');
  text('last-upload-label',state.cloud?'云端最后收块':'服务最后收块');
  text('first-upload',date(s.first_uploaded_at));
  text('received',date(s.last_uploaded_at ?? s.received_at));
  const origin=p.origin_device ? '来源设备：' + p.origin_device + '。' : '';
  text('provenance-note',origin + (p.note || '')); $('provenance-note').hidden=!origin&&!p.note;
  let message='设备时钟尚未核准；采集日期保留原始记录。';
  const ref=p.clock_reference==='cloud'?'云端':p.clock_reference==='computer'?'电脑':'参考时钟';
  if(p.clock_status==='ok') message='本次时钟检查与'+ref+'相差不超过 5 秒；采集日期保留原始记录。';
  if(p.clock_status==='offset' && Number.isFinite(p.clock_offset_seconds)) {
    const offset=p.clock_offset_seconds;
    message='设备时钟较'+ref+(offset>=0?'快 ':'慢 ')+Math.abs(offset).toLocaleString('zh-CN',{maximumFractionDigits:1})+' 秒；显示原始采集日期，未改写旧记录。';
  }
  if(p.clock_checked_at) message+=' 检查时间：'+date(p.clock_checked_at)+'。';
  text('clock-note',message); $('clock-note').classList.toggle('clock-ok',p.clock_status==='ok');
}
function renderInputSummary(result) {
  const summary=result.input_summary;
  $('input-summary').hidden=!summary;
  if(!summary) return;
  text('eligible-count',count(summary.eligible_samples));
  text('skipped-count',count(summary.skipped_samples));
  const list=$('skip-reasons'); list.replaceChildren();
  for(const [reason,n] of Object.entries(summary.skipped_reasons || {})) {
    if(!n) continue;
    const li=document.createElement('li'); li.textContent=(skipLabels[reason] || reason)+'：'+count(n)+' 点'; list.append(li);
  }
  const rejectionCounts=result.model_result?.quality_rejection_counts || summary.quality_rejection_counts || {};
  const reasons=Object.entries(rejectionCounts).filter(([,n])=>n>0).map(([reason,n])=>reason+'（'+count(n)+' 搏）');
  const quality=result.analysis_status==='ineligible'
    ? '未生成可分类心搏：'+(result.message || '有效信号或上下文不足')
    : reasons.length ? '心搏质量拒绝：'+reasons.join('；') : '';
  text('quality-reasons',quality); $('quality-reasons').hidden=!quality;
}
function renderAnalysis(result) {
  if(result.session_id && result.session_id!==state.selected) return;
  state.analysis=result;experience('renderSummary');
  const labels={loading:'读取中',not_configured:'未接入模型',not_run:'可开始分析',queued:'排队中',running:'分析中',complete:'复算完成',ineligible:'无可分类片段',failed:'分析失败',stale:'需要重新分析'};
  const status=result.analysis_status || 'not_configured';
  text('model-status',labels[status] || '模型状态未知');
  $('model-status').className='pill'+(['complete','not_run'].includes(status)?'':' neutral');
  text('model-name',result.model_name ? result.model_name+' · '+(result.model_version || 'N / S / V') : status==='loading'?'正在读取模型状态':'此阶段只验证数据链路');
  const job=result.task;
  text('model-message',job && ['queued','running'].includes(status)
    ? job.stage+(job.total?' · 已处理 '+count(job.processed)+' / '+count(job.total)+' 点':'')+'。关闭网页后任务仍会继续。'
    : result.message || '分类结果与模型复核暂为空');
  const data=status==='complete'?result.model_result:null;
  $('model-result').hidden=!data;
  if(data) {
    text('beat-count',count(data.beat_count)+' 个心搏');
    for(const key of ['N','S','V']) text('class-'+key,count(data.counts?.[key] ?? 0));
    text('model-time','分析时间：'+date(result.analyzed_at));
  }
  const enabled=result.model_status==='ready';
  $('analyze').hidden=!enabled;
  $('analyze').disabled=!!state.analyzing || ['queued','running'].includes(status) || !!state.wave?.session?.trashed_at;
  text('analyze',state.analyzing===state.selected?'正在复算…':status==='complete'?'重新核对':'开始云端分析');
  $('model-note').hidden=!enabled;
  const key=[state.selected,status,result.source_digest,result.analyzed_at,data?.beat_count].join('|');
  if(key!==state.analysisKey) {
    state.analysisKey=key;
    renderInputSummary(result);
    renderBeats();
    draw();
  }
}
function renderBeats() {
  const all=currentBeats(), beats=ECGDesktop.filteredBeats(all,state.beatFilter), v=view(), pages=Math.max(1,Math.ceil(beats.length/PAGE_SIZE));
  v.page=Math.min(v.page,pages-1);
  if(v.selected && !beats.some(b=>beatKey(b)===v.selected)) v.selected=null;
  $('beats-panel').hidden=!all.length; $('marker-legend').hidden=!all.length;
  $('beats-empty').hidden=!all.length || !!beats.length;
  $('beat-previous').disabled=!beats.length;$('beat-next').disabled=!beats.length;
  if(!all.length) {
    $('beats-body').replaceChildren(); state.tableKey=''; return;
  }
  text('beats-total',count(beats.length)+' / '+count(all.length)+' 搏');
  text('beats-page','第 '+(v.page+1)+' / '+pages+' 页');
  $('beats-prev').disabled=v.page===0; $('beats-next').disabled=v.page>=pages-1;
  const selected=beats.find(b=>beatKey(b)===v.selected);
  text('selected-beat',selected?'已选 '+(selected.sample_id/360).toFixed(3)+' s · '+selected.label:'选择时间可查看对应波形');
  const tableKey=[state.analysisKey,state.beatFilter,v.page,v.selected].join('|');
  if(state.tableKey===tableKey) return;
  state.tableKey=tableKey;
  const body=$('beats-body'); body.replaceChildren();
  for(const beat of beats.slice(v.page*PAGE_SIZE,(v.page+1)*PAGE_SIZE)) {
    const row=document.createElement('tr'), selected=beatKey(beat)===v.selected;
    row.classList.toggle('selected',selected);
    const timeCell=document.createElement('td'), button=document.createElement('button');
    button.className='beat-jump'; button.textContent=(beat.sample_id/360).toFixed(3)+' s';
    button.title='定位采样点 '+beat.sample_id+'，连续段 '+beat.segment_id;
    button.setAttribute('aria-pressed',String(selected));
    button.setAttribute('aria-label',button.textContent+'，'+beat.label+' 类，定位到波形');
    timeCell.append(button); row.append(timeCell);
    const labelCell=document.createElement('td'), badge=document.createElement('span');
    badge.className='beat-label beat-'+(['N','S','V'].includes(beat.label)?beat.label:'unknown'); badge.textContent=beat.label;
    labelCell.append(badge); row.append(labelCell);
    for(const label of ['N','S','V']) {
      const cell=document.createElement('td'), value=beat.scores?.[label];
      cell.textContent=Number.isFinite(value)?value.toFixed(4):'—'; row.append(cell);
    }
    const review=document.createElement('td'); review.textContent=beat.requires_review?'需复核':'未标记';
    review.className=beat.requires_review?'review-needed':'review-neutral'; row.append(review);
    row.onclick=()=>selectBeat(beat);
    body.append(row);
  }
}
async function selectBeat(beat) {
  view().selected=beatKey(beat); state.follow=false;
  const session=state.wave?.session || state.sessions.find(s=>s.session_id===state.selected);
  if(!session) return;
  const first=session.first_sample_id ?? 0, last=session.last_sample_id ?? beat.sample_id;
  const width=Number($('window').value)*360;
  const end=Math.min(last,Math.max(Math.min(last,first+width-1),beat.sample_id+Math.floor(width/2)));
  $('position').min=first; $('position').max=last; $('position').value=end;
  renderBeats(); await loadWave();
  $('wave-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function loadAnalysis() {
  const physiologyLoad=physiologyUI?.load();
  const sid=state.selected;
  if(!sid || state.analyzing===sid)return physiologyLoad;
  const generation=++state.analysisGeneration;
  try {
    const result=await (await api('/api/sessions/'+encodeURIComponent(sid)+'/analysis')).json();
    if(sid===state.selected && generation===state.analysisGeneration)renderAnalysis(result);
  } catch(error) {if(sid===state.selected && generation===state.analysisGeneration){
    state.analysis={session_id:sid,analysis_status:'unavailable'};state.analysisKey='';renderBeats();draw();
    $('model-result').hidden=true;$('input-summary').hidden=true;$('analyze').disabled=true;
    text('model-status','暂时无法读取');text('model-message','模型状态读取失败：'+error.message);experience('renderSummary');
  }}
  finally {await physiologyLoad;}
}
async function loadWave() {
  const sid=state.selected; if(!sid) return;
  const generation=++state.generation;
  const params=new URLSearchParams({seconds:$('window').value});
  if(!state.follow) params.set('end_sample',$('position').value);
  try {
    const wave=await (await api('/api/sessions/'+encodeURIComponent(sid)+'/waveform?'+params)).json();
    if(sid!==state.selected || generation!==state.generation) return;
    state.wave=wave; const s=wave.session; $('content').hidden=false; detailFeedback();
    text('record-name',s.name || '采集会话');text('record-note',s.note || '');text('record-id',s.session_id);text('source',sources[s.source] || '来源未知');
    text('trash-record',s.trashed_at?'恢复记录':'移入回收站');
    $('source').className='pill'+(s.source==='demo'?' warning':'');
    text('samples',count(s.sample_count));text('chunks',count(s.chunk_count)+' 个数据块已保存');
    text('duration',(s.sample_count/360).toFixed(1)+' s');
    text('valid',s.sample_count?(s.valid_count/s.sample_count*100).toFixed(1)+'%':'—');
    text('device',s.device_id);renderProvenance(s);renderMeasurement(s);physiologyUI?.updateAvailability();
    text('source-status',({recording:'采集中',complete:'正常结束',incomplete:'未完整结束',recovered_incomplete:'中断后恢复',failed:'源记录异常',error:'源记录异常'})[s.source_status] || s.source_status);
    text('download',s.upload_status==='complete'?'下载完整 CSV':'下载已接收 CSV');
    text('upload-status',uploadLabel(s));$('upload-status').className='pill'+(uploadLabel(s)==='等待上传'?' warning':'');
    const modes=new Set(wave.points.map(p=>p[4]));
    let origin=sources[s.source];
    if(s.source==='serial') origin=modes.size===1&&modes.has(0)?'实采模式':modes.size===1&&modes.has(1)?'板端模拟':'串口 / 混合或未知模式';
    text('wave-origin',origin);
    $('position').max=s.last_sample_id??0;$('position').min=s.first_sample_id??0;
    if(state.follow) $('position').value=s.last_sample_id??0;
    text('position-label',((wave.end_sample??0)/360).toFixed(1)+' s');
    $('follow').classList.toggle('active',state.follow);$('follow').setAttribute('aria-pressed',String(state.follow));
    text('follow',state.follow?'跟随最新':'查看历史');
    const hasValid=wave.points.some(p=>p[1]!==null);
    text('chart-empty',wave.points.length?'当前窗口均为无效采样，数据已保存':'该范围暂无数据');
    $('chart-empty').hidden=hasValid;draw();experience('detailUpdated');
    if(typeof RecordAnnotations!=='undefined')RecordAnnotations.updated();
  } catch(error) {
    if(sid===state.selected && generation===state.generation) {
      experience('detailFailed');
      detailFeedback((state.wave ? '更新失败，以下保留上次读取的结果。' : '测量结果暂时无法读取。') + '请检查网络后重试。' + error.message, true);
    }
  }
}
function visibleMarkers(points, start, end) {
  const rows=new Map(points.filter(p=>p[1]!==null).map(p=>[p[0],p]));
  return currentBeats().filter(b=>b.sample_id>=start && b.sample_id<=end && rows.get(b.sample_id)?.[2]===b.segment_id)
    .map(beat=>({beat,point:rows.get(beat.sample_id)}));
}
function draw() {
  const canvas=$('chart'), rect=canvas.getBoundingClientRect(); if(!rect.width) return;
  const ratio=window.devicePixelRatio||1;canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);
  const c=canvas.getContext('2d');c.scale(ratio,ratio);
  // Match the phone's light surface without changing signal values or desktop colors.
  const light=window.matchMedia('(max-width: 720px)').matches;
  const palette=light
    ? {grid:'#cbdedb',minor:'#e6efed',label:'#516c70',wave:'#087f71',selection:'#254a54',edge:'#ffffff',N:'#087565',S:'#9a6500',V:'#b43463'}
    : {grid:'#234048',minor:'#17343c',label:'#7a9c9e',wave:'#5ce2af',selection:'#ffffff',edge:'#0c2026',...classColors};
  const w=rect.width,h=rect.height,left=43,right=13,top=22,bottom=26,pw=w-left-right,ph=h-top-bottom;
  c.clearRect(0,0,w,h);c.font=(light?'11':'9')+'px "Segoe UI",sans-serif';
  const wave=state.wave, points=wave?.session?.session_id===state.selected?wave.points:[], values=points.filter(p=>p[1]!==null).map(p=>p[1]);
  let lo=values.length?Math.min(...values):0,hi=values.length?Math.max(...values):4095;
  const spread=Math.max(hi-lo,200);lo=Math.max(0,lo-spread*.2);hi=Math.min(4095,hi+spread*.2);
  const center=(lo+hi)/2,range=(hi-lo)/state.amplitude;lo=center-range/2;hi=center+range/2;
  const end=wave?.end_sample??3599,start=wave?.start_sample??0,span=Math.max(end-start,360);
  for(let y=0;y<=4;y++) {
    const py=top+ph*y/4;c.strokeStyle=palette.grid;c.lineWidth=.6;c.beginPath();c.moveTo(left,py);c.lineTo(w-right,py);c.stroke();
    c.fillStyle=palette.label;c.textAlign='right';c.fillText(String(Math.round(hi-(hi-lo)*y/4)),left-9,py+3);
  }
  for(let x=0;x<=10;x++) {
    const px=left+pw*x/10;c.strokeStyle=x%2?palette.minor:palette.grid;c.beginPath();c.moveTo(px,top);c.lineTo(px,top+ph);c.stroke();
    if(x%2===0){c.fillStyle=palette.label;c.textAlign='center';c.fillText(((start+span*x/10)/360).toFixed(1)+'s',px,h-7);}
  }
  c.save();c.beginPath();c.rect(left,top,pw,ph);c.clip();c.strokeStyle=palette.wave;c.lineWidth=light?1.6:1.35;c.lineJoin='round';c.beginPath();let connected=false;
  for(const p of points) {
    if(p[1]===null){connected=false;continue;}
    const x=left+(p[0]-start)/span*pw,y=top+(hi-p[1])/(hi-lo)*ph;
    if(!connected||p[5])c.moveTo(x,y);else c.lineTo(x,y);connected=true;
  }
  c.stroke();
  const markers=visibleMarkers(points,start,end);
  text('marker-count','当前窗口 '+markers.length+' 个模型 R 点');
  if($('show-markers').checked) {
    const selected=view().selected; let lastLabelX=-100;
    for(const {beat,point} of markers) {
      const x=left+(beat.sample_id-start)/span*pw,y=top+(hi-point[1])/(hi-lo)*ph,isSelected=beatKey(beat)===selected;
      const color=palette[beat.label] || palette.selection;
      if(isSelected) {
        c.strokeStyle=palette.selection;c.lineWidth=1;c.setLineDash([3,3]);c.beginPath();c.moveTo(x,top);c.lineTo(x,top+ph);c.stroke();c.setLineDash([]);
      }
      c.beginPath();c.arc(x,y,isSelected?5:3,0,Math.PI*2);c.fillStyle=color;c.fill();
      c.strokeStyle=isSelected?palette.selection:palette.edge;c.lineWidth=isSelected?2:1;c.stroke();
      if(isSelected || x-lastLabelX>32) {
        c.fillStyle=color;c.textAlign='center';c.font='bold 10px "Segoe UI",sans-serif';
        c.fillText(beat.label,x,Math.max(top+10,y-10));lastLabelX=x;
      }
    }
  }
  c.restore();
}
$('refresh').onclick=refresh;
$('detail-retry').onclick=async()=>{
  const epoch=state.epoch, sid=state.selected;
  $('detail-retry').disabled=true; detailFeedback('正在重新读取测量结果…');
  try {await Promise.all([loadWave(),loadAnalysis()]);}
  finally {if(epoch===state.epoch && sid===state.selected)$('detail-retry').disabled=false;}
};
$('analyze').onclick=async()=>{
  const sid=state.selected, epoch=state.epoch;if(!sid || state.analyzing)return;
  state.analyzing=sid;state.analysisGeneration++;
  $('analyze').disabled=true;text('analyze','正在复算…');text('model-status','分析中');
  try {
    await api('/api/sessions/'+encodeURIComponent(sid)+'/analysis-jobs?force=true',{method:'POST'});
  } catch(error) {if(epoch===state.epoch && sid===state.selected)text('model-message','分析请求未完成：'+error.message);}
  finally {if(epoch===state.epoch) {state.analyzing=null;await loadAnalysis();}}
};
$('window').onchange=loadWave;
$('show-markers').onchange=draw;
$('beats-prev').onclick=()=>{view().page=Math.max(0,view().page-1);renderBeats();};
$('beats-next').onclick=()=>{view().page++;renderBeats();};
$('follow').onclick=()=>{state.follow=!state.follow;loadWave();};
let sliderTimer;
$('position').oninput=()=>{state.follow=false;clearTimeout(sliderTimer);sliderTimer=setTimeout(loadWave,80);};
$('settings').onclick=()=>{$('token').value=state.token;$('credentials').showModal();};
$('save-token').onclick=()=>{state.token=$('token').value.trim();sessionStorage.setItem('ecg-token',state.token);refresh();};
$('download').onclick=async()=>{
  const sid=state.selected,epoch=state.epoch;if(!sid)return;
  if(document.documentElement?.dataset?.nativeApp==='android') {
    location.href='ecg-export://download/'+encodeURIComponent(sid)+'?user='+encodeURIComponent(state.user?.id || '');
    return;
  }
  $('download').disabled=true;
  try {
    const response=await api('/api/sessions/'+encodeURIComponent(sid)+'/export');
    const blob=await response.blob();if(epoch!==state.epoch)return;
    const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=sid+'.csv';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error) {notice('下载失败：'+error.message);} finally {$('download').disabled=false;}
};
new ResizeObserver(draw).observe($('chart'));
fetch('/health',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(health=>{
  state.cloud=health?.deployment==='cloud';
  text('deployment-label',state.cloud?'云端演示':'电脑联调');
  text('service-location',state.cloud?'课程演示 · 云端服务':'课程演示 · 本地服务');
  if(state.wave)renderProvenance(state.wave.session);
}).catch(()=>{});
