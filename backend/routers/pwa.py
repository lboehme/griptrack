import hashlib
import json
from pathlib import Path
from string import Template

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from backend.templating import templates

# Brand values duplicated from base.html's theme-color meta tag and
# app.css's --bg variable — the manifest format has no way to reference a
# stylesheet, so these two sources have to be kept in sync by hand.
THEME_COLOR = "#e8532c"
BACKGROUND_COLOR = "#f3f4f6"

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

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

# Everything whose content feeds CACHE_VERSION — one source file per
# precached URL. The /static URLs map directly to files under STATIC_DIR
# (see backend/main.py's StaticFiles mount); "/offline" is server-rendered
# from offline.html wrapped by base.html, so hashing those two template
# sources stands in for the rendered page (any change to what /offline
# serves goes through one of them).
_HASHED_SOURCE_FILES = [
    STATIC_DIR / url.removeprefix("/static/") for url in PRECACHE_URLS if url.startswith("/static/")
] + [
    TEMPLATES_DIR / "offline.html",
    TEMPLATES_DIR / "base.html",
]


def _compute_cache_version() -> str:
    """Derive CACHE_VERSION from the content of every precached asset's source.

    Replaces a manual "bump CACHE_VERSION whenever a precached file
    changes" rule — a maintenance landmine: forget it once and installed
    clients keep serving stale assets. Hashing content directly means the
    version changes automatically, and only when it actually needs to.
    Computed once at import/startup from the files on disk at that moment.
    """
    digest = hashlib.sha256()
    for path in sorted(_HASHED_SOURCE_FILES):
        # A missing listed file raising FileNotFoundError here is
        # intentional: fail loud at boot rather than silently serve a
        # version that no longer tracks the full precache set.
        digest.update(path.read_bytes())
    return f"griptrack-{digest.hexdigest()[:16]}"


CACHE_VERSION = _compute_cache_version()

SERVICE_WORKER_JS_TEMPLATE = Template("""\
const CACHE_VERSION = $cache_version;
const PRECACHE_URLS = $precache_urls;

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
""")

SERVICE_WORKER_JS = SERVICE_WORKER_JS_TEMPLATE.substitute(
    cache_version=json.dumps(CACHE_VERSION),
    precache_urls=json.dumps(PRECACHE_URLS),
)


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
