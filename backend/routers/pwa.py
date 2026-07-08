import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from backend.templating import templates

# Brand values duplicated from base.html's theme-color meta tag and
# app.css's --bg variable — the manifest format has no way to reference a
# stylesheet, so these two sources have to be kept in sync by hand.
THEME_COLOR = "#e8532c"
BACKGROUND_COLOR = "#f3f4f6"

router = APIRouter()

# Bump this whenever a precached file's content changes — the service
# worker deletes any cache keyed under an older version on activation, so
# this string is the whole update mechanism for already-installed clients.
CACHE_VERSION = "griptrack-v1"

# Everything the service worker precaches on install: the static shell plus
# the offline fallback page itself, so it's servable with no network at
# all. Deliberately excludes every authenticated per-user page.
PRECACHE_URLS = [
    "/static/app.css",
    "/static/htmx.min.js",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/icons/icon-512-maskable.png",
    "/static/icons/apple-touch-icon.png",
    "/offline",
]

SERVICE_WORKER_JS = """\
const CACHE_VERSION = %(cache_version)s;
const PRECACHE_URLS = %(precache_urls)s;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_VERSION)
            .map((key) => caches.delete(key))
        )
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Navigations: always prefer the live, per-user server response. Only
  // fall back to the cached offline page when the network is unreachable
  // — an authenticated page is never itself served from cache.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/offline"))
    );
    return;
  }

  // Static shell assets: cache-first for instant repeat loads.
  const path = new URL(request.url).pathname;
  if (PRECACHE_URLS.includes(path)) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request))
    );
  }
});
""" % {
    "cache_version": json.dumps(CACHE_VERSION),
    "precache_urls": json.dumps(PRECACHE_URLS),
}


@router.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    return JSONResponse(
        {
            "name": "GripTrack",
            "short_name": "GripTrack",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "theme_color": THEME_COLOR,
            "background_color": BACKGROUND_COLOR,
            "icons": [
                {
                    "src": "/static/icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/icons/icon-512-maskable.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/sw.js")
def service_worker() -> Response:
    # Served from the app root, not /static — a service worker's scope is
    # limited to the path it's served from, so root-serving is required
    # for it to control navigations across the whole app.
    return Response(SERVICE_WORKER_JS, media_type="text/javascript")


@router.get("/offline")
def offline_fallback(request: Request):
    return templates.TemplateResponse(request, "offline.html", {"user": None})
