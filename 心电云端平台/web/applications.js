'use strict';
var AccountApplications=(()=>{
  let generation=0,reviewGeneration=0,busy=false,reviewBusy=false;
  function clearReview(){reviewGeneration++;reviewBusy=false;$('application-list').replaceChildren();$('application-review-feedback').textContent='';}
  function clear(){generation++;busy=false;clearReview();$('application-form').reset();$('application-dialog').close();$('application-feedback').textContent='';$('application-submit').disabled=false;}
  $('apply-account').onclick=()=>{clear();$('application-dialog').showModal();};
  $('application-close').onclick=()=>$('application-dialog').close();
  $('application-dialog').addEventListener('close',()=>{generation++;$('application-password').value='';$('application-confirm').value='';busy=false;$('application-submit').disabled=false;});
  $('application-form').onsubmit=async event=>{
    event.preventDefault();if(busy)return;
    const ticket=generation,epoch=state.epoch,username=$('application-username').value.trim().toLowerCase(),password=$('application-password').value;
    if(!/^[a-z0-9][a-z0-9_-]{2,31}$/.test(username)){$('application-feedback').textContent='账号格式不正确。';return;}
    if(Array.from(password).length<5||Array.from(password).length>128){$('application-feedback').textContent='密码须为5–128个字符。';return;}
    if(password!==$('application-confirm').value){$('application-feedback').textContent='两次密码不一致。';return;}
    busy=true;$('application-submit').disabled=true;$('application-feedback').textContent='正在提交申请…';
    try{
      const response=await fetch('/api/account-applications',{method:'POST',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000),headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,password_confirm:$('application-confirm').value,note:$('application-note').value.trim()})});
      const result=await response.json();if(ticket!==generation||epoch!==state.epoch)return;
      if(!response.ok)throw new Error([401,404].includes(response.status)?'服务器尚未开放账号申请，请联系项目管理员':typeof result.detail==='string'?result.detail:'请检查账号和密码后重试');
      $('application-form').reset();$('username').value=username;$('application-feedback').textContent=result.message;
    }catch(e){if(ticket===generation&&epoch===state.epoch)$('application-feedback').textContent='申请未确认：'+e.message;}
    finally{if(ticket===generation&&epoch===state.epoch){busy=false;$('application-submit').disabled=false;}}
  };
  const current=(epoch,ticket)=>epoch===state.epoch&&ticket===reviewGeneration&&state.user?.is_admin&&$('admin-dialog').open;
  async function load(){
    if(!state.user?.is_admin||!$('admin-dialog').open||reviewBusy)return;
    const epoch=state.epoch,ticket=++reviewGeneration;$('application-review-feedback').textContent='正在读取申请…';
    try{
      const result=await(await api('/api/admin/account-applications')).json();if(!current(epoch,ticket))return;
      const parent=$('application-list');parent.replaceChildren();$('application-review-feedback').textContent=result.applications.length?'待审核 '+result.applications.length+' 项。通过后请按需要配置设备授权。':'暂无待审核申请。';
      for(const item of result.applications){
        const card=document.createElement('article');card.className='measurement-task';const title=document.createElement('h3'),note=document.createElement('p'),stamp=document.createElement('p');
        title.textContent=item.username;note.textContent=item.note||'未填写申请说明';stamp.textContent=new Date(item.created_at*1000).toLocaleString();card.append(title,note,stamp);
        for(const [action,label]of [['approve','通过申请'],['reject','拒绝申请']]){
          const button=document.createElement('button');button.type='button';button.className='button '+(action==='approve'?'primary':'secondary');button.textContent=label;
          button.onclick=async()=>{
            if(reviewBusy||!current(epoch,ticket)||!confirm(label+'：'+item.username+'？'))return;
            reviewBusy=true;for(const b of parent.querySelectorAll('button'))b.disabled=true;
            try{await jsonRequest('/api/admin/account-applications/'+encodeURIComponent(item.id)+'/'+action,'POST',{});if(!current(epoch,ticket))return;reviewBusy=false;await load();await loadAdmin();}
            catch(e){if(current(epoch,ticket))$('application-review-feedback').textContent='处理未完成：'+e.message;}
            finally{if(epoch===state.epoch){reviewBusy=false;for(const b of parent.querySelectorAll('button'))b.disabled=false;}}
          };card.append(button);
        }parent.append(card);
      }
    }catch(e){if(current(epoch,ticket)){$('application-list').replaceChildren();$('application-review-feedback').textContent='申请列表暂不可用：'+e.message;}}
  }
  $('refresh-applications').onclick=load;$('application-review').addEventListener('toggle',()=>{if($('application-review').open)load();});
  $('admin-dialog').addEventListener('close',clearReview);
  return {clear,load};
})();
