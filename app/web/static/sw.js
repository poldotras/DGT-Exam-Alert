/* DGT Panel service worker.
 *
 * Served from "/sw.js" (root scope) so it can control the whole panel. It precaches the
 * static shell and shows an offline page when a navigation can't reach the network. It
 * deliberately never caches authenticated HTML, so panel data is always fresh and never
 * leaked from the cache. */
const CACHE = "dgt-panel-v1";
const PRECACHE = [
  "/static/style.css",
  "/static/offline.html",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Page navigations: go to the network (fresh, authenticated data); if offline, show the
  // cached offline page instead of the browser's error.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/static/offline.html")));
    return;
  }

  // Static assets: serve from cache first, then fall back to the network and cache it.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req).then(
        (cached) =>
          cached ||
          fetch(req).then((resp) => {
            const copy = resp.clone();
            caches.open(CACHE).then((cache) => cache.put(req, copy));
            return resp;
          })
      )
    );
  }
});
