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
  function readiness(device){
    if(!device.active)return {ready:false,label:'已停用',hint:'请联系管理员启用设备。'};
    if(device.connection!=='online')return {ready:false,label:device.connection==='unknown'?'尚未连接':'离线',hint:'请检查终端电源和网络，等待设备上线。'};
    if(device.state!=='standby')return {ready:false,label:'忙碌中',hint:'设备正在处理任务，请等待结束后刷新。'};
    if(!device.remote_ready)return {ready:false,label:'尚未准备好',hint:'请在终端选择真实采集串口；旧版终端需先更新。'};
    return {ready:true,label:'可测量',hint:'请确认电极贴好并选择测量时长。'};
  }
  return {defaults,preferences,day,series,points,readiness};
});
