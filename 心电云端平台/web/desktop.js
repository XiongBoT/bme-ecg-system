'use strict';
function resetDesktop(){
  document.body.classList.remove('wave-focus','device-expanded');
  $('wave-focus').setAttribute('aria-pressed','false');text('wave-focus','专注波形');
  $('beat-filter').value='all';$('amplitude').value='1';
}
$('wave-focus').onclick=()=>{
  const focused=document.body.classList.toggle('wave-focus');
  $('wave-focus').setAttribute('aria-pressed',String(focused));text('wave-focus',focused?'退出专注':'专注波形');
  draw();
};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('wave-focus')){$('wave-focus').click();}});
$('amplitude').onchange=()=>{state.amplitude=Number($('amplitude').value);draw();};
$('beat-filter').onchange=()=>{state.beatFilter=$('beat-filter').value;view().page=0;renderBeats();draw();};
function shiftWindow(direction){
  const s=state.wave?.session;if(!s||s.session_id!==state.selected)return;
  const width=Number($('window').value)*360;
  $('position').value=ECGDesktop.windowEnd(Number($('position').value),direction*width,s.first_sample_id??0,s.last_sample_id??0,width);
  state.follow=false;loadWave();
}
$('wave-previous').onclick=()=>shiftWindow(-1);$('wave-next').onclick=()=>shiftWindow(1);
function stepBeat(direction){
  const beats=ECGDesktop.filteredBeats(currentBeats(),state.beatFilter);if(!beats.length)return;
  const current=beats.findIndex(b=>beatKey(b)===view().selected);
  const index=current<0?(direction>0?0:beats.length-1):Math.max(0,Math.min(beats.length-1,current+direction));
  view().page=Math.floor(index/PAGE_SIZE);selectBeat(beats[index]);
}
$('beat-previous').onclick=()=>stepBeat(-1);$('beat-next').onclick=()=>stepBeat(1);
$('filters-toggle').onclick=()=>{
  $('filter-panel').open=!$('filter-panel').open;
};
$('filter-panel').addEventListener('toggle',()=>$('filters-toggle').setAttribute('aria-expanded',String($('filter-panel').open)));
for(const id of ['download-desktop','nav-download','login-download'])$(id).onclick=()=>$('desktop-download').showModal();
$('desktop-download-close').onclick=()=>$('desktop-download').close();
let reconnecting=false;
$('connection-retry').onclick=async()=>{
  if(reconnecting)return;reconnecting=true;$('connection-retry').disabled=true;
  try{if(state.ready)await refresh();else await initialize();}
  finally{reconnecting=false;$('connection-retry').disabled=false;}
};
window.addEventListener('offline',()=>connectionStatus(connectionProblem(new TypeError('offline'))));
window.addEventListener('online',()=>{$('connection-retry').click();});
