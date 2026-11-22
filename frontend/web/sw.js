const cacheName = "phrase-room-shell-v9";
const assets = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./library.json",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
];
self.addEventListener("install", (event) =>
  event.waitUntil(
    caches
      .open(cacheName)
      .then((cache) => cache.addAll(assets))
      .then(() => self.skipWaiting()),
  ),
);
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key.startsWith("phrase-room-shell-") && key !== cacheName,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  ),
);
self.addEventListener("fetch", (event) => {
  const req = event.request,
    u = new URL(req.url);
  if (
    req.method !== "GET" ||
    u.origin !== location.origin ||
    u.pathname.startsWith("/api/")
  )
    return;
  const known = assets.some(
    (path) => new URL(path, self.registration.scope).pathname === u.pathname,
  );
  if (!known) return;
  event.respondWith(
    caches
      .open(cacheName)
      .then(
        async (cache) =>
          (await cache.match(req, { ignoreSearch: true })) || fetch(req),
      ),
  );
});
