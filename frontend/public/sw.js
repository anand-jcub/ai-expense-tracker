/* Cache the /app shell only. Never cache /api/ financial JSON. */
const SHELL = 'expense-app-shell-v12'

self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(
    caches.open(SHELL).then((cache) => cache.addAll(['/app/', '/app/index.html'])),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (url.pathname.startsWith('/api/')) return
  if (event.request.method !== 'GET') return
  if (!url.pathname.startsWith('/app/')) return

  // Network-first for the shell HTML so updates are immediate
  if (url.pathname === '/app/' || url.pathname === '/app/index.html') {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone()
            caches.open(SHELL).then((cache) => cache.put(event.request, copy))
          }
          return res
        })
        .catch(() => caches.match(event.request).then((hit) => hit || caches.match('/app/'))),
    )
    return
  }

  // Network-first with cache fallback for assets
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone()
          caches.open(SHELL).then((cache) => cache.put(event.request, copy))
        }
        return res
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match('/app/'))),
  )
})

/* Push Notification & Click handling */
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = { title: 'Review Required', body: event.data ? event.data.text() : 'Statement transactions need review.' }
  }

  const title = data.title || 'Review Required'
  const options = {
    body: data.body || 'New transactions need your review.',
    icon: data.icon || '/app/icon-192.png',
    badge: data.badge || '/app/icon-192.png',
    tag: data.tag || 'statement-review',
    renotify: true,
    data: data.data || { url: data.url || '/app/?screen=ask&review=1' },
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data && event.notification.data.url) || '/app/?screen=ask&review=1'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes('/app') && 'focus' in client) {
          if ('navigate' in client) {
            client.navigate(targetUrl)
          }
          return client.focus()
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl)
      }
    })
  )
})

