const CACHE = "raven-v2";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/manifest.json",
  "/offline.html",
];
const API_CACHE = "raven-api-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE && k !== API_CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== "GET") return;

  // API requests: network first, fallback to cache
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirstWithApiCache(request));
    return;
  }

  // WebSocket: don't cache
  if (url.pathname.startsWith("/ws")) return;

  // Static assets: cache first
  event.respondWith(cacheFirstWithOffline(request));
});

async function cacheFirstWithOffline(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const offline = await caches.match("/offline.html");
    if (offline) return offline;
    return new Response(
      "<html><body style='background:#0f1117;color:#e0e0e0;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif'><div><h1>Offline</h1><p>Connect to the internet to use Raven AI.</p></div></body></html>",
      { status: 503, headers: { "Content-Type": "text/html;charset=UTF-8" } }
    );
  }
}

async function networkFirstWithApiCache(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(API_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

// ── Push Notifications ──────────────────────────────────────────

self.addEventListener("push", (event) => {
  let data = { title: "Raven AI", body: "New notification", url: "/" };
  if (event.data) {
    try {
      data = Object.assign(data, event.data.json());
    } catch {
      data.body = event.data.text();
    }
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icons/icon-192.svg",
      badge: "/icons/icon-192.svg",
      vibrate: [200, 100, 200],
      tag: "raven-notification",
      renotify: true,
      requireInteraction: true,
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if (client.url.startsWith(self.location.origin) && "focus" in client) {
            client.focus();
            client.navigate(url);
            return;
          }
        }
        if ("openWindow" in self.clients) {
          self.clients.openWindow(url);
        }
      })
  );
});
