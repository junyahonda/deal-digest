const scope = self.registration.scope;
const cachePrefix = `deal-digest:${scope}:`;
const cacheName = `${cachePrefix}v2`;
const shell = ["./", "./styles.css", "./app.js", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png"].map((path) => new URL(path, scope).href);
const shellPage = shell[0];
const indexPage = new URL("./index.html", scope).href;
const data = new URL("./data/deals.json", scope).href;

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(cacheName);
    await Promise.all([
      cache.addAll(shell.map((url) => new Request(url, { cache: "reload" }))),
      cache.add(new Request(data, { cache: "reload" })).catch(() => {}),
    ]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith(cachePrefix) && key !== cacheName)
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

async function networkFirst(request, key) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) {
      await cache.put(key, response.clone()).catch(() => {});
      return response;
    }
    return await cache.match(key) || response;
  } catch {
    return await cache.match(key) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const key = request.url === indexPage ? shellPage : request.url;
  if (key === data || shell.includes(key)) {
    event.respondWith(networkFirst(request, key));
  }
});
