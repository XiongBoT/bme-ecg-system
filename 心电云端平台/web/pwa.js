'use strict';
(()=>{
  const el=id=>document.getElementById(id);
  const display=window.matchMedia('(display-mode: standalone)');
  const installed=()=>display.matches||navigator.standalone===true;
  const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(/Macintosh/.test(navigator.userAgent)&&navigator.maxTouchPoints>1);
  const embedded=/MicroMessenger|\bQQ\//.test(navigator.userAgent);
  let promptEvent=null,registration=null,reloadRequested=false;
  const feedback=value=>{el('pwa-feedback').textContent=value;};
  function installState(){
    el('pwa-install').hidden=installed();
    el('pwa-context').textContent=installed()?'桌面应用 · 联网查看记录':'把心电健康助手放到手机桌面';
  }
  function help(){
    feedback('');
    el('pwa-confirm').hidden=!promptEvent;
    el('pwa-instructions').textContent=promptEvent?'点击下方“安装应用”，然后按手机提示确认。安装完成后可从桌面打开。':
      embedded?'请先通过右上角菜单选择在系统浏览器打开，再添加到手机桌面。iPhone 建议使用 Safari。':
      ios?'请在 Safari 中打开本站，点击“分享”，选择“添加到主屏幕”；如有“作为网页 App 打开”选项，请保持开启，再点“添加”。':
      '请在浏览器菜单中选择“安装应用”或“添加到主屏幕”。如果没有该选项，可换用支持安装的浏览器，或继续使用此网页。不同手机的入口名称可能不同。';
    el('pwa-help').showModal();
  }
  el('pwa-install').onclick=help;
  el('pwa-help-close').onclick=()=>el('pwa-help').close();
  el('pwa-confirm').onclick=async()=>{
    if(!promptEvent){help();return;}
    const pending=promptEvent;promptEvent=null;el('pwa-confirm').disabled=true;
    try {
      await pending.prompt();const choice=await pending.userChoice;
      feedback(choice?.outcome==='accepted'?'已提交安装，请按系统提示完成后从桌面打开。':'已取消安装，仍可正常使用网页。');
    } catch(_) {feedback('浏览器暂未允许安装，可通过浏览器菜单添加到主屏幕。');}
    finally {el('pwa-confirm').disabled=false;el('pwa-confirm').hidden=true;}
  };
  window.addEventListener('beforeinstallprompt',event=>{
    event.preventDefault();promptEvent=event;installState();
    if(el('pwa-help').open){el('pwa-confirm').hidden=false;el('pwa-instructions').textContent='浏览器已准备好安装，点击“安装应用”继续。';}
  });
  window.addEventListener('appinstalled',()=>{promptEvent=null;el('pwa-install').hidden=true;el('pwa-help').close();el('pwa-context').textContent='已安装，可从手机桌面打开';});
  if(display.addEventListener)display.addEventListener('change',installState);
  installState();
  const offline=()=>{el('pwa-network').hidden=false;el('pwa-network').textContent='网络已断开，页面中的记录与结果为此前加载内容。联网后请刷新确认。';};
  window.addEventListener('offline',offline);
  window.addEventListener('online',()=>{el('pwa-network').hidden=false;el('pwa-network').textContent='手机网络已恢复，请刷新页面以重新确认登录和最新记录。';});
  if(navigator.onLine===false)offline();
  el('pwa-update').hidden=true;
  el('pwa-update-button').onclick=()=>{
    if(!registration?.waiting){location.reload();return;}
    reloadRequested=true;el('pwa-update-button').disabled=true;
    registration.waiting.postMessage({type:'ECG_ACTIVATE_UPDATE'});
  };
  if(navigator.serviceWorker&&window.isSecureContext){
    navigator.serviceWorker.addEventListener('controllerchange',()=>{if(reloadRequested)location.reload();});
    navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'}).then(value=>{
      registration=value;
      const ready=()=>{if(value.waiting&&navigator.serviceWorker.controller)el('pwa-update').hidden=false;};
      ready();
      value.addEventListener('updatefound',()=>{
        const incoming=value.installing;if(incoming)incoming.addEventListener('statechange',ready);
      });
      value.update().catch(()=>{});
    }).catch(()=>{el('pwa-context').textContent='可继续使用网页；安装功能暂不可用';});
  }
})();
