def test_service_worker_is_served_from_app_root_as_javascript(client):
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_service_worker_carries_a_version_and_precaches_the_static_shell(client):
    response = client.get("/sw.js")

    body = response.text
    assert "CACHE_VERSION" in body
    for asset in (
        "/static/app.css",
        "/static/htmx.min.js",
        "/static/icons/icon-192.png",
        "/static/icons/icon-512.png",
        "/static/icons/icon-512-maskable.png",
        "/static/icons/apple-touch-icon.png",
        "/offline",
    ):
        assert asset in body


def test_offline_fallback_page_renders_standalone(client):
    response = client.get("/offline")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "offline" in response.text.lower()


def test_base_template_registers_the_service_worker(client):
    response = client.get("/health")

    assert '<script src="/static/register-sw.js"' in response.text

    registration_script = client.get("/static/register-sw.js")
    assert registration_script.status_code == 200
    assert "javascript" in registration_script.headers["content-type"]
    assert "serviceWorker" in registration_script.text


def test_webview_build_flag_skips_service_worker_registration_and_manifest(
    monkeypatch, client_factory
):
    # GRIPTRACK_WEBVIEW_BUILD=1 is the Android/Chaquopy WebView build (#93,
    # #95): WebView SW support is unreliable and redundant once the server
    # is already on-device, so this mode must serve the app fully without
    # registering the SW or relying on the PWA manifest.
    monkeypatch.setenv("GRIPTRACK_WEBVIEW_BUILD", "1")
    client = client_factory()

    response = client.get("/health")

    assert '<script src="/static/register-sw.js"' not in response.text
    assert '<link rel="manifest"' not in response.text


def test_default_build_still_registers_the_service_worker_and_manifest(client_factory):
    # No GRIPTRACK_WEBVIEW_BUILD set — the existing web/PWA build's behavior
    # must be unchanged by the new flag.
    client = client_factory()

    response = client.get("/health")

    assert '<script src="/static/register-sw.js"' in response.text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in response.text


def test_new_routes_carry_the_unchanged_csp(client):
    # No CSP change was needed for this slice: /sw.js and /offline are
    # same-origin, and self-registration needs no extra directive beyond
    # what's already granted.
    for path in ("/sw.js", "/offline"):
        response = client.get(path)
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def _cache_version_with_tweaked_file(pwa_module, monkeypatch, tmp_path, filename: str) -> str:
    """CACHE_VERSION recomputed from the *real* hashed source list, with
    exactly one named file's content altered (via tmp copies — the real
    files on disk are never touched)."""
    copies = []
    for index, source in enumerate(pwa_module._HASHED_SOURCE_FILES):
        copy = tmp_path / f"{index}-{source.name}"
        content = source.read_bytes()
        if source.name == filename:
            content += b"\n<!-- cache-version test tweak -->\n"
        copy.write_bytes(content)
        copies.append(copy)
    monkeypatch.setattr(pwa_module, "_HASHED_SOURCE_FILES", copies)
    return pwa_module._compute_cache_version()


def test_cache_version_changes_when_a_precached_static_asset_changes(tmp_path, monkeypatch):
    # CACHE_VERSION is a content hash with no manual-bump step: editing a
    # real precached asset's bytes must change the version.
    import backend.routers.pwa as pwa_module

    baseline = pwa_module._compute_cache_version()
    tweaked = _cache_version_with_tweaked_file(pwa_module, monkeypatch, tmp_path, "app.css")

    assert tweaked != baseline

    # And CACHE_VERSION, as actually computed at import time, is exactly
    # what's baked into the served service worker JS.
    assert pwa_module.CACHE_VERSION in pwa_module.SERVICE_WORKER_JS


def test_cache_version_changes_when_the_offline_page_source_changes(tmp_path, monkeypatch):
    # "/offline" is precached too — its page is server-rendered from
    # offline.html (wrapped by base.html), so both templates' source must
    # be part of the digest or installed clients would keep a stale
    # offline page forever.
    import backend.routers.pwa as pwa_module

    baseline = pwa_module._compute_cache_version()

    for template in ("offline.html", "base.html"):
        tweaked = _cache_version_with_tweaked_file(pwa_module, monkeypatch, tmp_path, template)
        assert tweaked != baseline, f"{template} content is not reflected in CACHE_VERSION"
