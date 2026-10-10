/* Service worker tối giản để cài PeerBridge như app.
 * - Trang và tài nguyên tĩnh: lấy mạng trước, mất mạng thì dùng bản đã lưu.
 * - Không bao giờ lưu cache dữ liệu API (dữ liệu học tập luôn lấy mới từ server). */
const CACHE = "peerbridge-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return; // API ở domain khác: không đụng tới
  event.respondWith(
    fetch(req).then((res) => {
      if (res.ok && (req.mode === "navigate" || url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/"))) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
  );
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window" }).then((list) => (list[0] ? list[0].focus() : self.clients.openWindow("/"))));
});
