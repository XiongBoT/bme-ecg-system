'use strict';
var RecordAnnotations=(()=>{
 let version=0,loaded='',current=null,creating='',busy=false,offset=0,total=0;
 const labels={note:'观察备注',suspected_interference:'疑似干扰',attention:'需要关注'};
 const key=()=>state.user?.id+':'+state.selected;
 const message=value=>text('annotation-feedback',value);
 function controls(disabled){for(const id of ['annotation-save','annotation-window','annotation-new','annotation-refresh','annotation-start','annotation-end','annotation-kind','annotation-note','annotation-deleted','annotation-prev','annotation-next'])$(id).disabled=disabled;}
 function resetForm(){current=null;creating='';$('annotation-form').reset();text('annotation-editing','新建片段标注');}
 function clear(){version++;loaded='';busy=false;offset=total=0;resetForm();controls(false);$('annotation-panel').hidden=true;$('annotation-list').replaceChildren();message('');}
 function changed(){clear();}
 function available(){const s=state.wave?.session;return state.auth&&state.user&&s?.session_id===state.selected&&s.upload_status==='complete'&&!s.trashed_at;}
 function useWindow(){
  if(!available()||busy)return;
  const w=state.wave,s=w.session;
  $('annotation-start').value=(Math.max(s.first_sample_id,w.start_sample)/360).toFixed(3);
  $('annotation-end').value=(Math.min(s.last_sample_id,w.end_sample)/360).toFixed(3);
 }
 function edit(row){if(busy)return;current=row;creating='';$('annotation-start').value=(row.start_sample/360).toFixed(3);$('annotation-end').value=(row.end_sample/360).toFixed(3);$('annotation-kind').value=row.kind;$('annotation-note').value=row.note;text('annotation-editing','编辑标注 · 第 '+row.revision+' 版');$('annotation-start').focus();}
 function view(row){
  if(busy||!available())return;
  state.follow=false;$('window').value=String(row.end_sample-row.start_sample<5*360?5:row.end_sample-row.start_sample<10*360?10:row.end_sample-row.start_sample<30*360?30:60);
  $('position').value=row.end_sample;loadWave();$('wave-panel').scrollIntoView({block:'start',behavior:'smooth'});
  message('定位范围 '+(row.start_sample/360).toFixed(3)+'–'+(row.end_sample/360).toFixed(3)+' 秒；缺样和无效点仍按原记录显示。');
 }
 function button(caption,action){const b=document.createElement('button');b.type='button';b.className='button secondary';b.textContent=caption;b.onclick=action;return b;}
 function render(rows){
  $('annotation-list').replaceChildren();
  for(const row of rows){const box=document.createElement('article'),title=document.createElement('strong'),note=document.createElement('p'),actions=document.createElement('div');box.className='annotation-item';title.textContent=(row.start_sample/360).toFixed(3)+'–'+(row.end_sample/360).toFixed(3)+' 秒 · '+labels[row.kind]+(row.deleted?' · 已撤下':'');note.textContent=row.note||'未填写备注';actions.className='annotation-actions';actions.append(button('查看片段',()=>view(row)));if(!row.deleted)actions.append(button('编辑',()=>edit(row)));actions.append(button(row.deleted?'恢复':'撤下',()=>write({...row,deleted:!row.deleted},row.id)));box.append(title,note,actions);$('annotation-list').append(box);}
  if(!rows.length){const p=document.createElement('p');p.className='muted';p.textContent='当前没有片段标注。';$('annotation-list').append(p);}
  text('annotation-page',(Math.floor(offset/25)+1)+' / '+Math.max(1,Math.ceil(total/25))+' · '+total+' 条');$('annotation-prev').disabled=offset===0;$('annotation-next').disabled=offset+25>=total;
 }
 async function load(){
  if(busy||!available())return;
  const stamp=++version,epoch=state.epoch,sid=state.selected;$('annotation-panel').hidden=false;
  try{const p=new URLSearchParams({limit:'25',offset:String(offset),include_deleted:String($('annotation-deleted').checked)});const body=await(await api('/api/sessions/'+encodeURIComponent(sid)+'/annotations?'+p)).json();if(stamp!==version||epoch!==state.epoch||sid!==state.selected)return;loaded=key();total=body.total;render(body.annotations);}
  catch(error){if(stamp===version&&epoch===state.epoch)message(error.message+'，可点击刷新重试。');}
 }
 function updated(){if(!available()){if(loaded)clear();return;}if(loaded!==key()&&!busy)load();}
 async function write(values,aid){
  if(busy||!available())return;
  busy=true;controls(true);const stamp=version,epoch=state.epoch,sid=state.selected;
  const payload={start_sample:values.start_sample,end_sample:values.end_sample,kind:values.kind,note:values.note,revision:values.revision,deleted:values.deleted};
  try{
   const result=await(await api('/api/sessions/'+encodeURIComponent(sid)+'/annotations/'+aid,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
   if(stamp!==version||epoch!==state.epoch||sid!==state.selected)return;
   resetForm();message(result.deleted?'标注已撤下，勾选“显示已撤下”可恢复。':'标注已保存。原始波形和分类结果保持独立。');
  }catch(error){if(stamp===version&&epoch===state.epoch)message(error.message+'；如已在其他页面修改，请刷新后重新选择。');}
  finally{if(stamp===version&&epoch===state.epoch){busy=false;controls(false);await load();}}
 }
 $('annotation-form').onsubmit=event=>{event.preventDefault();if(busy||!available())return;const start=Number($('annotation-start').value),end=Number($('annotation-end').value);if($('annotation-start').value===''||$('annotation-end').value===''||!Number.isFinite(start)||!Number.isFinite(end)||end<start){message('请填写正确的起止时间。');return;}if(!current&&!creating)creating=crypto.randomUUID().replaceAll('-','');write({start_sample:Math.round(start*360),end_sample:Math.round(end*360),kind:$('annotation-kind').value,note:$('annotation-note').value,revision:current?.revision||0,deleted:false},current?.id||creating);};
 $('annotation-window').onclick=useWindow;$('annotation-new').onclick=()=>{if(busy)return;resetForm();useWindow();};$('annotation-refresh').onclick=load;
 $('annotation-deleted').onchange=()=>{offset=0;load();};$('annotation-prev').onclick=()=>{offset=Math.max(0,offset-25);load();};$('annotation-next').onclick=()=>{offset+=25;load();};
 return {clear,changed,updated,load,useWindow};
})();
