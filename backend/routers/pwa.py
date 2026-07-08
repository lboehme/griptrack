from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Brand values duplicated from base.html's theme-color meta tag and
# app.css's --bg variable — the manifest format has no way to reference a
# stylesheet, so these two sources have to be kept in sync by hand.
THEME_COLOR = "#e8532c"
BACKGROUND_COLOR = "#f3f4f6"

router = APIRouter()


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
