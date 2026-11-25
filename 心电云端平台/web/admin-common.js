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
  const links=[];
  const iconPaths={
   records:'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2ZM9 8h6M9 12h6M9 16h4',
   tasks:'m4 6 2 2 4-4M13 6h7M4 13h3M13 13h7M4 20h3M13 20h7',
   overview:'M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z',
   operations:'M3 12h4l3-7 4 14 3-7h4',
   accounts:'M16 8a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2',
   devices:'M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2ZM7 21h10M12 17v4M6 11h3l2-4 3 7 2-3h2',
   maintenance:'M14.7 6.3a5 5 0 0 0-6.4 6.4l-4.7 4.7a2.1 2.1 0 0 0 3 3l4.7-4.7a5 5 0 0 0 6.4-6.4l-3 3-3-3 3-3Z',
   activity:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2'
  };
  const groups=[['日常工作',[
   ['personal','我的记录','/','records'],['tasks','任务中心','/tasks','tasks']
  ]],['管理工具',[
   ['overview','管理概览','/admin','overview'],['operations','运行总览','/operations','operations'],['accounts','账号管理','/admin/accounts','accounts'],['devices','采集设备','/devices','devices'],['records','记录管理','/database','records'],['maintenance','检查与备份','/database#db-maintenance-section','maintenance'],['activity','操作记录','/database#db-activity-section','activity']
  ]]];
  for(const [title,items] of groups){
   const group=node('div','','admin-nav-group'),destinations=node('div','','admin-nav-links');
   group.append(node('p',title,'admin-nav-label'));
   for(const [id,label,href,icon] of items){
    const a=node('a',''),symbol=document.createElementNS('http://www.w3.org/2000/svg','svg'),shape=document.createElementNS('http://www.w3.org/2000/svg','path');
    symbol.setAttribute('viewBox','0 0 24 24');symbol.setAttribute('class','admin-nav-icon');symbol.setAttribute('aria-hidden','true');symbol.setAttribute('focusable','false');shape.setAttribute('d',iconPaths[icon]);symbol.append(shape);
    // Stay in this document so section links retain filters and unsaved forms.
    a.append(symbol,node('span',label));a.href=document.body.dataset.adminSection==='records'&&href.startsWith('/database')?(href.slice('/database'.length)||'#db-records-section'):href;links.push([id,a]);destinations.append(a);
   }
   group.append(destinations);nav.append(group);
  }
  const mark=()=>{let active=document.body.dataset.adminSection;if(active==='records')active=({'#db-maintenance-section':'maintenance','#db-activity-section':'activity'})[window.location.hash]||active;for(const [id,a] of links){if(active===id)a.setAttribute('aria-current',['maintenance','activity'].includes(id)?'location':'page');else a.removeAttribute('aria-current');}};
  mark();window.addEventListener('hashchange',mark);
  const note=node('p','按账号隔离记录 · 管理运行信息','admin-nav-note');nav.append(note);
 }
 navigation();return {el,text,node,date,link,bytes,Session};
})();
