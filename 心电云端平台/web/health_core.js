'use strict';
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ECGHealth=api;})(globalThis,()=>{
  const defaults={textSize:'standard',contrast:'standard',refreshSeconds:30,duration:180};
  function preferences(value={}){return {
    textSize:value.textSize==='large'?'large':'standard',contrast:value.contrast==='high'?'high':'standard',
    refreshSeconds:[15,30,60].includes(Number(value.refreshSeconds))?Number(value.refreshSeconds):30,
    duration:[60,180,300].includes(Number(value.duration))?Number(value.duration):180};}
  function day(date=new Date()){return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');}
  function series(buckets,metric){return buckets.map(b=>metric==='hr'?b.hr_mean:metric==='duration'?b.duration_s/60:b.records);}
  function points(values,width=620,height=190){const finite=values.filter(v=>Number.isFinite(v));const max=Math.max(1,...finite);return values.map((v,i)=>Number.isFinite(v)?{x:34+(i+.5)*(width-50)/values.length,y:height-25-v/max*(height-45),value:v}:null);}
  return {defaults,preferences,day,series,points};
});
