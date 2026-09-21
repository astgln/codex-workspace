// No conversation or authenticated API data is cached on the device.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data.json(); } catch {}
  const url = typeof data.url === 'string' && /^\/#(?:thread=[a-zA-Z0-9-]+)$/.test(data.url) ? data.url : '/';
  const title = typeof data.title === 'string' && data.title.trim() ? Array.from(data.title).slice(0,120).join('') : 'Codex Workspace';
  event.waitUntil(self.registration.showNotification(title, {
    body: typeof data.body === 'string' && data.body.trim() ? Array.from(data.body).slice(0,520).join('') : 'Готов новый ответ',
    icon: '/icon-192.png', badge: '/icon-192.png', tag: String(data.tag || 'workspace'), data: {url}
  }));
});
self.addEventListener('notificationclick', event => {
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
