(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;else root.ECGWorkflow=value;})(globalThis,function(){
 'use strict';
 const names={not_run:'尚未开始',queued:'等待处理',running:'正在分析',complete:'分析完成',ineligible:'条件不足，未得到有效结果',failed:'分析未完成',not_configured:'服务未就绪',stale:'结果需更新',pending:'等待自动提交',blocked:'需要处理',cancelled:'自动提交已取消'};
 function client(fetcher,onClear){
  let epoch=0,user=null,csrf='';
  function clear(message='登录状态已改变'){epoch++;user=null;csrf='';onClear(message);}
  return {get epoch(){return epoch;},get user(){return user;},clear,set(value,token){epoch++;user=value;csrf=token;},
   async request(path,method='GET',payload){
    const generation=epoch;
    const response=await fetcher(path,{method,credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
    if(generation!==epoch)throw new Error('登录状态已改变');
    const who=response.headers.get('X-ECG-User');
    if(user&&who&&who!==user.id){clear('其他页面已切换账号，请返回工作台重新登录。');throw new Error('账号已改变');}
    const body=await response.json();
    if(generation!==epoch)throw new Error('登录状态已改变');
    if(response.status===401||response.status===403){clear('登录或权限已失效，请返回工作台重新登录。');throw new Error('登录或权限已失效');}
    if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'请求未完成（'+response.status+'）');
    return body;
   }};
 }
 function reviewMatches(review,sid,classification,physiology){
  if(!review||review.session_id!==sid)return false;
  return [['model',classification],['physiology',physiology]].every(([kind,value])=>{
   const expected=review.basis?.analyses?.[kind];if(!expected||!value||value.session_id!==sid)return false;
   return value.source_digest===expected.digest && (value.analyzed_at||null)===(expected.analyzed_at||null)
    && (value.task?.job_id||null)===(expected.job?.job_id||null)
    && (value.task?.status||null)===(expected.job?.status||null)
    && value.analysis_status===(expected.job&&['queued','running','failed'].includes(expected.job.status)?expected.job.status:expected.status);
  });
 }
 return {client,reviewMatches,status:value=>names[value]||'状态待确认'};
});
