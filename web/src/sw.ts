import {encryptedPush,hasEncryptedDevices} from './crypto/push';
// ServiceWorker globals are supplied by the browser, outside the DOM window.
declare const self:any;
// No conversation or authenticated API data is cached on the device.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event:any) => event.waitUntil(self.clients.claim()));
self.addEventListener('push', (event:any) => {
  let data:any = {};
  try { data = event.data.json(); } catch {}
  event.waitUntil((async()=>{
  if(data.envelope)data=await encryptedPush(data.envelope);
  else if(await hasEncryptedDevices())data={title:'Codex Workspace',body:'Новое зашифрованное сообщение',url:'/'};
  const url = typeof data.url === 'string' && /^\/#(?:thread=[a-zA-Z0-9-]+)$/.test(data.url) ? data.url : '/';
  const title = typeof data.title === 'string' && data.title.trim() ? Array.from(data.title).slice(0,120).join('') : 'Codex Workspace';
  await self.registration.showNotification(title, {
    body: typeof data.body === 'string' && data.body.trim() ? Array.from(data.body).slice(0,520).join('') : 'Готов новый ответ',
    icon: '/icon-192.png', badge: '/icon-192.png', tag: String(data.tag || 'workspace'), data: {url}
  });
  })());
});
self.addEventListener('notificationclick', (event:any) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({type:'window', includeUncontrolled:true});
    for (const client of windows) {
      if (new URL(client.url).origin === target.origin) {
        await client.navigate(target.href); return client.focus();
      }
    }
    return self.clients.openWindow(target.href);
  })());
});
