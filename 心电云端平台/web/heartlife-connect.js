'use strict';
(()=>{
  const $=id=>document.getElementById(id);
  let current={phase:'loading'}, timer=null;
  const date=value=>value?new Date(value*1000).toLocaleString():'—';
  const controller=ECGHeartLife.createController((...args)=>fetch(...args),state=>{
    current=state;const busy=state.phase==='busy'||state.phase==='loading';
    $('bridge-feedback').textContent=state.message||(state.phase==='loading'?'正在确认连接状态…':state.phase==='login'?'请先登录心电账号。':'');
    $('bridge-login').hidden=!!state.user||!['login','busy'].includes(state.phase);
    $('bridge-account').hidden=!state.user;
    $('bridge-account-name').textContent=state.user?.username||'';
    $('bridge-linked').hidden=!state.linked;$('bridge-link-expiry').textContent=date(state.expires_at);
    $('bridge-code-form').hidden=state.linked||state.phase==='disabled';
    $('bridge-code-panel').hidden=!state.code;$('bridge-code').value=state.code;
    $('bridge-code-expiry').textContent=date(state.code_expires_at);
    $('bridge-open').hidden=!state.url;if(state.url)$('bridge-open').href=state.url;else $('bridge-open').removeAttribute('href');
    $('bridge-revoke').hidden=!state.linked&&!state.code;
    for(const id of ['bridge-login-submit','bridge-generate','bridge-revoke','bridge-refresh'])$(id).disabled=busy;
    if(!state.user)$('bridge-consent').checked=false;
  });
  $('bridge-login').onsubmit=async event=>{event.preventDefault();const password=$('bridge-password').value;$('bridge-password').value='';await controller.login($('bridge-username').value.trim(),password);};
  $('bridge-code-form').onsubmit=event=>{event.preventDefault();return controller.generate($('bridge-consent').checked);};
  $('bridge-revoke').onclick=()=>{if(confirm('撤销后，心伴将无法继续读取本人的心电摘要。确定撤销？'))return controller.revoke();};
  $('bridge-logout').onclick=()=>{ $('bridge-password').value='';return controller.logout();};
  $('bridge-refresh').onclick=()=>controller.load();
  $('bridge-copy').onclick=async()=>{
    const code=current.code;if(!code)return;
    try{if(!navigator.clipboard?.writeText)throw new Error('unavailable');await navigator.clipboard.writeText(code);if(current.code===code)$('bridge-feedback').textContent='已复制，请前往心伴粘贴。';}
    catch(_){if(current.code===code){$('bridge-code').focus();$('bridge-code').select();$('bridge-feedback').textContent='请长按或使用系统复制，将选中的绑定码复制。';}}
  };
  window.addEventListener('pagehide',()=>{clearInterval(timer);timer=null;controller.clear();$('bridge-password').value='';});
  window.addEventListener('pageshow',event=>{if(event.persisted){controller.load();timer=setInterval(()=>controller.expire(),1000);}});
  controller.load();timer=setInterval(()=>controller.expire(),1000);
})();
