const CACHE = "personal-favorite-static-v3";

const STATIC_FILES = [
    "/manifest.json",
    "/static/style.css",
    "/static/css/style.css",
    "/static/icon.svg"
];

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE).then(cache => cache.addAll(STATIC_FILES))
    );

    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys
                    .filter(key => key !== CACHE)
                    .map(key => caches.delete(key))
            )
        )
    );

    self.clients.claim();
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET") {
        return;
    }

    const url = new URL(event.request.url);

    // لا نخزن صفحات الحسابات أو الصفحات الديناميكية
    // لأنها تحتوي على بيانات المستخدم الحالي.
    const isStatic =
        url.pathname.startsWith("/static/") ||
        url.pathname === "/manifest.json";

    if (!isStatic) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then(response => {
                if (response.ok) {
                    const copy = response.clone();

                    caches.open(CACHE).then(cache => {
                        cache.put(event.request, copy);
                    });
                }

                return response;
            })
            .catch(() => caches.match(event.request))
    );
});
