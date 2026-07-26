const SHELL="signal-index-shell-v1";
const JSON_CACHE="signal-index-json-v1";
const SHELL_ROUTES=["/","/dashboard","/inbox","/sessions","/manifest.webmanifest","/icon.svg"];
self.addEventListener("install",event=>event.waitUntil(caches.open(SHELL).then(cache=>cache.addAll(SHELL_ROUTES))));
self.addEventListener("activate",event=>event.waitUntil(self.clients.claim()));
self.addEventListener("fetch",event=>{
  const request=event.request;
  if(request.method!=="GET")return;
  const url=new URL(request.url);
  if(request.headers.get("range")||/audio|recordings\/.*\/media/.test(url.pathname))return;
  if(request.mode==="navigate"){
    event.respondWith(fetch(request).catch(()=>caches.match(request).then(hit=>hit||caches.match("/dashboard"))));
  }else if(request.headers.get("accept")?.includes("application/json")){
    event.respondWith(fetch(request).then(response=>{const copy=response.clone();caches.open(JSON_CACHE).then(cache=>cache.put(request,copy));return response;}).catch(()=>caches.match(request)));
  }
});
self.addEventListener("sync",event=>{if(event.tag==="signal-index-sync")event.waitUntil(self.clients.matchAll().then(clients=>clients.forEach(client=>client.postMessage({type:"SYNC_REQUIRED"}))));});

