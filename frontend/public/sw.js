/* Curio service worker.
 *
 * Three jobs: keep the app shell available offline, cache API reads so a
 * previously visited card opens instantly and works on a train, and receive
 * push notifications.
 *
 * Strategy per resource type:
 *   navigation  -> network first, fall back to the cached page, then /offline
 *   /api/ GET   -> stale-while-revalidate (show something now, refresh behind)
 *   static      -> cache first (build assets are content-hashed)
 *
 * Nothing here caches a POST, and nothing caches a reader-specific endpoint
 * beyond the current session's use — /api/v1/me/* is deliberately excluded so
 * one person's saves cannot be served to another on a shared device.
 */

const VERSION = "curio-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const API_CACHE = `${VERSION}-api`;
const ASSET_CACHE = `${VERSION}-assets`;

const SHELL_URLS = ["/", "/offline", "/manifest.webmanifest"];

const API_CACHE_DENYLIST = [/\/api\/v1\/me\//, /\/api\/v1\/admin\//];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // addAll rejects wholesale if any single URL fails, which would leave
      // the worker uninstalled; add individually and tolerate misses.
      .then((cache) =>
        Promise.allSettled(SHELL_URLS.map((url) => cache.add(url))),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !key.startsWith(VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(request));
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    if (API_CACHE_DENYLIST.some((pattern) => pattern.test(url.pathname))) return;
    event.respondWith(staleWhileRevalidate(request, API_CACHE));
    return;
  }

  if (url.pathname.startsWith("/_next/static/") || /\.(woff2?|png|svg|ico)$/.test(url.pathname)) {
    event.respondWith(cacheFirst(request, ASSET_CACHE));
  }
});

async function handleNavigation(request) {
  try {
    const response = await fetch(request);
    const cache = await caches.open(SHELL_CACHE);
    cache.put(request, response.clone());
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return (await caches.match("/offline")) ?? Response.error();
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const network = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);

  // Return whatever we have immediately; the refresh lands for next time.
  if (cached) return cached;
  const response = await network;
  return response ?? new Response(JSON.stringify({ detail: "offline" }), {
    status: 503,
    headers: { "content-type": "application/json" },
  });
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(cacheName);
    cache.put(request, response.clone());
  }
  return response;
}

// --- Push -------------------------------------------------------------------

self.addEventListener("push", (event) => {
  let payload = {
    title: "Curio",
    body: "Something new to be curious about.",
    url: "/",
  };

  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch {
    if (event.data) payload.body = event.data.text();
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/badge-72.png",
      tag: payload.tag || "curio",
      // Replace rather than stack: the platform sends at most one a day, and
      // a pile of them in the tray is exactly the pattern we are avoiding.
      renotify: false,
      data: { url: payload.url },
      requireInteraction: false,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        // Reuse an open tab if there is one — opening a fifth Curio window is
        // never what the reader wanted.
        for (const client of clientList) {
          if ("focus" in client) {
            client.navigate(target);
            return client.focus();
          }
        }
        return self.clients.openWindow(target);
      }),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});
