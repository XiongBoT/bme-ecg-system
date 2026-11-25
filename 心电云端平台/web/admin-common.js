'use strict';
window.AdminUI=(()=>{
 const el=id=>document.getElementById(id);
 const text=(id,value)=>{const target=el(id);if(target)target.textContent=value;};
 const node=(tag,caption,className='')=>{const n=document.createElement(tag);n.textContent=caption;n.className=className;return n;};
 const date=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString():'未记录';
 const link=(path,values={})=>{const query=new URLSearchParams();for(const [key,value] of Object.entries(values))if(value!==null&&value!==undefined&&value!=='')query.set(key,String(value));return path+(query.size?'?'+query:'');};
 const bytes=value=>{if(!Number.isFinite(value))return '未知';const units=['B','KiB','MiB','GiB','TiB'];let i=0;while(value>=1024&&i<4){value/=1024;i++;}return value.toFixed(i?1:0)+' '+units[i];};
 class Session{
  constructor(onClear){this.epoch=0;this.user=null;this.csrf='';this.onClear=onClear;this.checking=false;}
  clear(message){this.epoch++;this.user=null;this.csrf='';this.onClear(message);}
  async request(path,method='GET',payload){
   const epoch=this.epoch;
   const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json','X-CSRF-Token':this.csrf},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
   if(epoch!==this.epoch)throw new Error('登录状态已改变');
   const uid=response.headers.get('X-ECG-User');
   if(this.user&&uid&&uid!==this.user.id){this.clear('其他页面已切换账号，请返回工作台重新进入。');throw new Error('账号已改变');}
   if(response.status===401||response.status===403){this.clear('管理权限或登录已失效，请返回工作台登录管理员账号。');throw new Error('需要管理员登录');}
   const body=await response.json();if(epoch!==this.epoch)throw new Error('登录状态已改变');
   if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'请求未完成（'+response.status+'）');
   return body;
  }
  async identify(){
   const epoch=this.epoch,result=await this.request('/api/auth/me');
   if(epoch!==this.epoch)throw new Error('登录状态已改变');
   if(!result.user?.is_admin){this.clear('此页面需要管理员账号，请返回工作台。');throw new Error('需要管理员账号');}
   this.user=result.user;this.csrf=result.csrf_token;return result.user;
  }
  watch(){
   const check=async()=>{if(document.hidden||!this.user||this.checking)return;this.checking=true;try{await this.identify();}catch(error){if(this.user)this.clear('无法确认当前登录状态，请刷新后重试。');}finally{this.checking=false;}};
   setInterval(check,5000);window.addEventListener('focus',check);
   window.addEventListener('pagehide',()=>this.clear('已离开页面，请刷新后继续。'));
  }
 }
 function navigation(){
  const nav=el('admin-navigation');if(!nav)return;
  nav.append(node('p','ADMIN WORKSPACE','admin-nav-label'));
  const links=[];
  for(const [id,label,href] of [['overview','运行总览','/admin'],['accounts','账号管理','/admin/accounts'],['devices','采集设备','/devices'],['records','记录管理','/database'],['maintenance','检查与备份','/database#db-maintenance-section'],['activity','操作记录','/database#db-activity-section']]){
   const a=node('a',label);a.href=href;links.push([id,a]);nav.append(a);
  }
  const mark=()=>{let active=document.body.dataset.adminSection;if(active==='records')active=({'#db-maintenance-section':'maintenance','#db-activity-section':'activity'})[window.location.hash]||active;for(const [id,a] of links){if(active===id)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}};
  mark();window.addEventListener('hashchange',mark);
  const note=node('p','按账号隔离记录 · 管理运行信息','admin-nav-note');nav.append(note);
 }
 navigation();return {el,text,node,date,link,bytes,Session};
})();
