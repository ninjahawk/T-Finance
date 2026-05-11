const CACHE = 'tf-v1';
const SHELL = ['/T-Finance/', '/T-Finance/index.html', '/T-Finance/manifest.json', '/T-Finance/App Icon.jpeg'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // data.json: network first, fall back to cache
  if (url.pathname.includes('data.json')) {
    e.respondWith(
      fetch(e.request)
        .then(r => { const c = r.clone(); caches.open(CACHE).then(ca => ca.put(e.request, c)); return r; })
        .catch(() => caches.match('data.json'))
    );
    return;
  }

  // Shell: cache first
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
