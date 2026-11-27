'use strict';
(function(root,factory){
  const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ECGHeartLife=api;
})(typeof globalThis!=='undefined'?globalThis:this,()=>{
  function safeUrl(value){
    try{const url=new URL(value);return url.protocol==='https:'&&url.hostname&&!url.username&&!url.password&&!url.search&&!url.hash?url.href:null;}
    catch(_){return null;}
  }
  function createController(fetcher,changed){
    let revision=0,csrf='',user=null;
    let state={phase:'loading',enabled:false,user:null,url:null,linked:false,measurement_allowed:false,expires_at:null,code:'',code_expires_at:null,code_measurement_allowed:false,message:''};
    const emit=()=>changed({...state});
    const current=ticket=>ticket===revision;
    const errorMessage=error=>error.name==='AbortError'?'连接超时，请刷新后重试':error.status?error.message:'暂时无法连接，请检查网络后刷新。';
    function reset(phase='loading'){
      revision++;csrf='';user=null;
      state={phase,enabled:false,user:null,url:null,linked:false,measurement_allowed:false,expires_at:null,code:'',code_expires_at:null,code_measurement_allowed:false,message:''};emit();return revision;
    }
    async function request(path,{method='GET',body,expected=user?.id,token=csrf}={}){
      const headers={'Accept':'application/json'};
      if(method!=='GET'){headers['X-CSRF-Token']=token;if(body!==undefined)headers['Content-Type']='application/json';}
      const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
      try{
        const response=await fetcher(path,{method,headers,credentials:'same-origin',cache:'no-store',redirect:'error',signal:abort.signal,
          ...(body===undefined?{}:{body:JSON.stringify(body)})});
        const value=await response.json();
        if(!response.ok){const error=new Error(typeof value.detail==='string'?value.detail:'请求未完成，请刷新后重试');error.status=response.status;throw error;}
        if(expected&&response.headers.get('X-ECG-User')!==expected){const error=new Error('登录账号已改变，请重新确认');error.status=401;throw error;}
        return value;
      }finally{clearTimeout(timer);}
    }
    function failure(error,ticket){
      if(!current(ticket))return;
      if(error.status===401){reset('login');state.message='登录已失效或账号已改变，请重新登录';}
      else {state.phase=user?(state.enabled?'ready':'disabled'):'error';state.code='';state.code_expires_at=null;state.code_measurement_allowed=false;state.message=errorMessage(error);}
      emit();
    }
    async function load(){
      const ticket=reset();
      try{
        const config=await request('/api/auth/config',{expected:null});if(!current(ticket))return;
        state.url=safeUrl(config.heartlife_url);
        if(!config.enabled){state.phase='disabled';state.message='心伴连接需要个人账号模式，请联系项目管理员。';emit();return;}
        const account=await request('/api/auth/me',{expected:null});if(!current(ticket))return;
        user=account.user;csrf=account.csrf_token;state.user={id:user.id,username:user.username};
        const link=await request('/api/heartlife/link');if(!current(ticket))return;
        state.url=safeUrl(link.heartlife_url)||state.url;state.enabled=!!link.enabled;state.linked=!!link.linked;state.expires_at=link.expires_at;
        state.measurement_allowed=state.linked&&link.measurement_allowed===true;
        state.phase=link.enabled?'ready':'disabled';state.message=link.enabled?'':'心伴连接当前未启用。';emit();
      }catch(error){failure(error,ticket);}
    }
    async function login(username,password){
      if(state.phase==='busy')return;
      const ticket=revision;state.phase='busy';state.message='';emit();
      try{await request('/api/auth/login',{method:'POST',body:{username,password},expected:null});if(current(ticket))await load();}
      catch(error){if(current(ticket)){state.phase='login';state.message=errorMessage(error);emit();}}
    }
    async function generate(consent,measurementAllowed=false){
      if(!user||!state.enabled||state.phase!=='ready'||state.linked)return;
      if(!consent){state.message='请先确认仅关联本人账号，并允许读取摘要。';emit();return;}
      const ticket=++revision;state.phase='busy';state.message='';state.code='';state.code_expires_at=null;state.code_measurement_allowed=false;emit();
      try{
        const code=await request('/api/heartlife/link-code',{method:'POST',body:{measurement_allowed:measurementAllowed===true}});if(!current(ticket))return;
        state.phase='ready';state.code=code.code;state.code_expires_at=code.expires_at;
        state.code_measurement_allowed=code.measurement_allowed===true;
        state.message='将此一次性码粘贴到心伴的“心电记录”页面。';emit();
      }catch(error){failure(error,ticket);}
    }
    async function revoke(){
      if(!user||state.phase==='busy')return;
      const ticket=++revision;state.phase='busy';state.message='';state.code='';state.code_expires_at=null;state.code_measurement_allowed=false;emit();
      try{await request('/api/heartlife/link',{method:'DELETE'});if(!current(ticket))return;
        state.linked=false;state.measurement_allowed=false;state.expires_at=null;state.phase=state.enabled?'ready':'disabled';state.message='已撤销心伴关联及未使用的绑定码。已下发的测量不会因此取消。';emit();
      }catch(error){failure(error,ticket);}
    }
    async function logout(){
      if(!user)return;
      const oldUser=user.id,oldCsrf=csrf,ticket=reset('loading');
      try{await request('/api/auth/logout',{method:'POST',expected:oldUser,token:oldCsrf});if(current(ticket))await load();}
      catch(error){failure(error,ticket);}
    }
    function expire(now=Date.now()/1000){
      if(state.code&&state.code_expires_at<=now){state.code='';state.code_expires_at=null;state.code_measurement_allowed=false;state.message='绑定码已过期，请重新生成。';emit();}
    }
    return {load,login,generate,revoke,logout,expire,clear:()=>reset('loading')};
  }
  return {safeUrl,createController};
});
