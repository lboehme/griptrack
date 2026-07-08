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


def test_new_routes_carry_the_unchanged_csp(client):
    # No CSP change was needed for this slice: /sw.js and /offline are
    # same-origin, and self-registration needs no extra directive beyond
    # what's already granted.
    for path in ("/sw.js", "/offline"):
        response = client.get(path)
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
