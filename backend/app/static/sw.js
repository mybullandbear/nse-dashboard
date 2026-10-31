const CACHE_NAME = 'mybullandbear-shell-v7';
const SHELL_URLS = ['/static/offline.html','/static/css/modern-terminal.css','/static/icons/icon-192.png','/static/icons/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_URLS)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('mybullandbear-') && key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/static/offline.html')));
    return;
  }
  // Only public, explicitly listed assets are stored. Never cache private responses.
  if (SHELL_URLS.includes(url.pathname)) event.respondWith(fetch(request).catch(() => caches.match(request)));
});
