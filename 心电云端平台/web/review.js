'use strict';
var RecordReview=(()=>{
 let current=null,version=0,dirty=false,saving=false;
 const labels={pending:'待复核',viewed:'已查看',suspected_interference:'疑似干扰'};
 function editing(disabled){for(const id of ['review-refresh','review-note','review-status'])$(id).disabled=disabled;}
 function clear(){version++;current=null;dirty=false;saving=false;editing(false);$('review-form').reset();$('review-panel').hidden=true;text('review-feedback','');$('review-save').disabled=true;}
 function matches(){return ECGWorkflow.reviewMatches(current,state.selected,state.analysis,state.physiology);}
 async function load(){
  if(saving)return;
  if(!state.auth||!state.user||!state.selected)return;
  const generation=++version,epoch=state.epoch,sid=state.selected;
  $('review-panel').hidden=false;
  try{
   const response=await api('/api/sessions/'+encodeURIComponent(sid)+'/review');const data=await response.json();
   if(epoch!==state.epoch||generation!==version||sid!==state.selected)return;
   current=data;
   if(!dirty){$('review-status').value=data.status;$('review-note').value=data.note;}
   $('review-save').disabled=false;
   text('review-feedback',data.stale?'分析结果或版本已变化，请重新查看后保存复核。':data.updated?'上次复核：'+date(data.updated*1000)+' · '+labels[data.status]:'尚未人工复核。复核标记不会修改算法输出。');
  }catch(error){if(epoch===state.epoch&&generation===version){current=null;$('review-save').disabled=true;text('review-feedback',error.message);}}
 }
 function changed(){clear();if(state.ready&&state.auth&&state.selected)load();}
 function reportRows(){
  if(!state.auth)return [];
  if(!matches())return [['人工复核','复核与当前显示结果未同步，请刷新结果与复核后重新生成报告']];
  return [['人工复核',labels[current.status]+(current.stale?'（已过期，需重新复核）':'')],['复核备注',current.note||'无'],['复核保存时间',current.updated?date(current.updated*1000):'尚未保存']];
 }
 $('review-form').oninput=()=>{dirty=true;};$('review-refresh').onclick=()=>{dirty=false;load();};
 $('review-form').onsubmit=async event=>{
  event.preventDefault();if(saving||!current)return;
  if(!matches()){text('review-feedback','请先刷新波形和两项分析结果，再点击“刷新复核”；显示内容不一致时不能确认复核。');return;}
  saving=true;editing(true);$('review-save').disabled=true;const epoch=state.epoch,sid=state.selected,generation=version;
  try{
   const response=await api('/api/sessions/'+encodeURIComponent(sid)+'/review',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:$('review-status').value,note:$('review-note').value,revision:current.revision,context:current.context})});
   const result=await response.json();if(epoch!==state.epoch||generation!==version||sid!==state.selected)return;
   current=result;dirty=false;experience('clearReport');text('review-feedback','复核已保存 · '+labels[result.status]+'。原始数据和分类标签保持独立。');
  }catch(error){if(epoch===state.epoch&&generation===version)text('review-feedback',error.message);}
  finally{if(epoch===state.epoch&&generation===version){saving=false;editing(false);$('review-save').disabled=!current;}}
 };
 return {clear,changed,load,reportRows};
})();
