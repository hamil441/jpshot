// JPShot service worker: offline app shell + data, runtime cache for the OCR engine, Android share target.
const VERSION = "jpshot-v1";
const SHELL = ["./", "index.html", "css/app.css", "manifest.webmanifest", "icons/icon-192.png",
  "js/app.js", "js/ui.js", "js/nlp.js", "js/data.js", "js/grammar.js", "js/pitch.js", "js/difficulty.js",
  "js/kanji.js", "js/conjugate.js", "js/services.js", "js/store.js", "js/anki.js", "js/ocr.js",
  "vendor/kuromoji/kuromoji.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k !== VERSION && k !== "jpshot-share" && k !== "jpshot-runtime").map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function handleShare(request) {
  const form = await request.formData();
  const cache = await caches.open("jpshot-share");
  const file = form.get("image");
  if (file && typeof file !== "string") await cache.put("shared-image", new Response(file, { headers: { "content-type": file.type } }));
  const text = [form.get("text"), form.get("url"), form.get("title")].find((x) => x && String(x).trim());
  if (text) await cache.put("shared-text", new Response(String(text)));
  return Response.redirect(new URL("./?share=1", self.registration.scope).href, 303);
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method === "POST" && url.pathname.endsWith("/share-target")) { e.respondWith(handleShare(req)); return; }
  if (req.method !== "GET") return;
  const same = url.origin === location.origin;
  // big, rarely-changing files: cache first
  const heavy = same && /\/(vendor|data)\//.test(url.pathname);
  const cdn = /(^|\.)jsdelivr\.net$/.test(url.hostname) || /tessdata|tesseract/.test(url.href);
  if (heavy || cdn) {
    e.respondWith(caches.open(heavy ? VERSION : "jpshot-runtime").then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok || res.type === "opaque") c.put(req, res.clone());
      return res;
    }));
    return;
  }
  if (!same) return;
  // app shell: network first so updates arrive, cache when offline
  e.respondWith(fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req).then((r) => r || caches.match("index.html"))));
});
