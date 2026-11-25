'use strict';
// Only anonymous, explicitly listed assets may enter Cache Storage.
// Auth, ECG records, HTML workspace, downloads and analysis stay network-only.
const CACHE='ecg-app-public-v2';
const PUBLIC_ASSETS=['/assets/offline.html','/assets/icons/icon-192.png',
  '/assets/icons/icon-512.png','/assets/icons/icon-maskable.png','/assets/icons/apple-touch-icon.png'];
self.addEventListener('install',event=>{
  event.waitUntil((async()=>{
    const cache=await caches.open(CACHE);
    await Promise.all(PUBLIC_ASSETS.map(async path=>{
      const response=await fetch(new Request(new URL(path,self.location.origin),{credentials:'omit',cache:'reload'}));
      if(!response.ok || response.redirected)throw new Error('Public offline resource unavailable');
      await cache.put(path,response);
    }));
  })());
});
self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    const names=await caches.keys();
    await Promise.all(names.filter(name=>name.startsWith('ecg-app-')&&name!==CACHE).map(name=>caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener('message',event=>{
  if(event.data?.type==='ECG_ACTIVATE_UPDATE')event.waitUntil(self.skipWaiting());
});
self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url);
  if(request.method!=='GET'||url.origin!==self.location.origin||request.mode!=='navigate'||!['/','/devices','/admin','/admin/accounts','/database'].includes(url.pathname))return;
  event.respondWith((async()=>{
    try {
      const response=await fetch(request);
      if(response.status<500)return response;
    } catch(_) { /* No private response is cached or replayed. */ }
    const fallback=await (await caches.open(CACHE)).match('/assets/offline.html');
    return fallback||new Response('暂时无法连接，请联网后重新打开心电健康助手。',{
      status:503,headers:{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'}});
  })());
});
