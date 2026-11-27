'use strict';
(()=>{
  const $=id=>document.getElementById(id);
  let current={phase:'loading'}, timer=null;
  const date=value=>value?new Date(value*1000).toLocaleString():'—';
  const scope=allowed=>allowed===true?'摘要、私人周报与发起测量':'只读摘要与私人周报';
  const controller=ECGHeartLife.createController((...args)=>fetch(...args),state=>{
    current=state;const busy=state.phase==='busy'||state.phase==='loading';
    $('bridge-feedback').textContent=state.message||(state.phase==='loading'?'正在确认连接状态…':state.phase==='login'?'请先登录心电账号。':'');
    $('bridge-login').hidden=!!state.user||!['login','busy'].includes(state.phase);
    $('bridge-account').hidden=!state.user;
    $('bridge-account-name').textContent=state.user?.username||'';
    $('bridge-linked').hidden=!state.linked;$('bridge-link-expiry').textContent=date(state.expires_at);
    $('bridge-link-scope').textContent=scope(state.measurement_allowed);
    $('bridge-code-form').hidden=state.linked||state.phase==='disabled';
    $('bridge-code-panel').hidden=!state.code;$('bridge-code').value=state.code;
    $('bridge-code-expiry').textContent=date(state.code_expires_at);
    $('bridge-code-scope').textContent=scope(state.code_measurement_allowed);
    $('bridge-generate').textContent=state.code?'重新生成绑定码':'生成一次性绑定码';
    $('bridge-open').hidden=!state.url;if(state.url)$('bridge-open').href=state.url;else $('bridge-open').removeAttribute('href');
    $('bridge-revoke').hidden=!state.linked&&!state.code;
    for(const id of ['bridge-login-submit','bridge-generate','bridge-revoke','bridge-refresh'])$(id).disabled=busy;
    if(!state.user){$('bridge-consent').checked=false;$('bridge-measurement-consent').checked=false;}
  });
  $('bridge-login').onsubmit=async event=>{event.preventDefault();const password=$('bridge-password').value;$('bridge-password').value='';await controller.login($('bridge-username').value.trim(),password);};
  $('bridge-code-form').onsubmit=event=>{event.preventDefault();return controller.generate($('bridge-consent').checked,$('bridge-measurement-consent').checked);};
  $('bridge-revoke').onclick=()=>{
    if(confirm('撤销后，心伴将无法继续读取心电摘要或发起新测量。已下发的测量不会因此取消。确定撤销？')){
      $('bridge-consent').checked=false;$('bridge-measurement-consent').checked=false;return controller.revoke();
    }
  };
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
