// NCC Sentinel: network-first; never cache authenticated pages, API responses, or sensitive records.
const CACHE="ncc-public-static-v1";
const ALLOWED=new Set(["/static/style.css","/static/app.js","/static/ncc-icon.svg"]);
self.addEventListener("install",event=>{self.skipWaiting();});
self.addEventListener("activate",event=>{event.waitUntil((async()=>{for(const name of await caches.keys())if(name!==CACHE)await caches.delete(name);await self.clients.claim();})());});
self.addEventListener("fetch",event=>{
 const req=event.request;
 if(req.method!=="GET"||new URL(req.url).origin!==self.location.origin)return;
 const path=new URL(req.url).pathname;
 if(!ALLOWED.has(path))return;
 event.respondWith(fetch(req).then(async response=>{if(response.ok){const cache=await caches.open(CACHE);cache.put(req,response.clone());}return response;}).catch(async()=> (await caches.match(req))||Response.error()));
});
