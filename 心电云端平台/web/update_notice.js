'use strict';
(()=>{
  function start(){
    const build=document.querySelector('meta[name="ecg-web-build"]')?.content;
    if(!/^[a-f0-9]{64}$/.test(build||'')||document.documentElement.dataset.nativeApp)return;
    const MAX_BYTES=16384,POLL_MS=300000,MIN_GAP_MS=60000;
    let pending=null,lastCheck=-Infinity,timer=null,stopped=false;
    function notify(){
      // The existing PWA handler activates its waiting worker only on this click.
      const pwa=document.getElementById('pwa-update');
      if(pwa){pwa.hidden=false;return;}
      if(document.getElementById('web-update-notice'))return;
      const box=document.createElement('div'),message=document.createElement('span'),button=document.createElement('button');
      box.id='web-update-notice';box.className='web-update-notice';box.setAttribute('role','status');
      message.textContent='网页已更新。请保存尚未提交的输入，再刷新使用新版；已保存记录不受影响。';
      button.id='web-update-refresh';button.type='button';button.textContent='刷新更新';
      button.onclick=()=>location.reload();
      box.append(message,button);document.body.prepend(box);
    }
    async function readMetadata(response){
      if(!response.ok||response.redirected||!/^application\/json(?:;|$)/i.test(response.headers.get('content-type')||''))throw Error('Unavailable');
      if(Number(response.headers.get('content-length'))>MAX_BYTES)throw Error('Too large');
      const reader=response.body?.getReader();
      if(!reader)throw Error('Unreadable response');
      const decoder=new TextDecoder('utf-8',{fatal:true});let size=0,text='';
      try {
        while(true){
          const {done,value}=await reader.read();if(done)break;
          size+=value.byteLength;
          if(size>MAX_BYTES){await reader.cancel();throw Error('Too large');}
          text+=decoder.decode(value,{stream:true});
        }
        text+=decoder.decode();
      } finally {reader.releaseLock();}
      return JSON.parse(text);
    }
    async function check(){
      const now=Date.now(),elapsed=now-lastCheck;
      if(stopped||pending||document.hidden||navigator.onLine===false||(elapsed>=0&&elapsed<MIN_GAP_MS))return;
      lastCheck=now;
      const request=new AbortController();pending=request;
      const timeout=setTimeout(()=>request.abort(),6000);
      try {
        const response=await fetch('/api/updates',{credentials:'omit',cache:'no-store',redirect:'error',signal:request.signal});
        const data=await readMetadata(response);
        if(!stopped&&pending===request&&!request.signal.aborted&&data?.schema===1&&/^[a-f0-9]{64}$/.test(data.web?.build_id||'')&&data.web.build_id!==build)notify();
      } catch(_) { /* A failed check leaves the current page and user inputs intact. */ }
      finally {clearTimeout(timeout);if(pending===request)pending=null;}
    }
    function resume(){stopped=false;if(timer===null)timer=setInterval(check,POLL_MS);check();}
    document.addEventListener('visibilitychange',check);
    window.addEventListener('online',check);
    window.addEventListener('pagehide',()=>{stopped=true;if(timer!==null)clearInterval(timer);timer=null;if(pending)pending.abort();pending=null;});
    window.addEventListener('pageshow',resume);
    resume();
  }
  // Wait until other deferred scripts have installed the existing PWA handlers.
  if(document.readyState==='complete')start();else document.addEventListener('DOMContentLoaded',start,{once:true});
})();
