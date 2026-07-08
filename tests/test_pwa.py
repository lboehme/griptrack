def test_manifest_has_required_fields_with_sane_values(client):
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert "manifest+json" in response.headers["content-type"]

    manifest = response.json()
    assert manifest["name"]
    assert manifest["short_name"]
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#e8532c"
    assert manifest["background_color"] == "#f3f4f6"
    assert len(manifest["icons"]) >= 3
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])


def test_every_manifest_icon_is_served(client):
    manifest = client.get("/manifest.webmanifest").json()

    for icon in manifest["icons"]:
        response = client.get(icon["src"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"


def test_apple_touch_icon_is_served(client):
    response = client.get("/static/icons/apple-touch-icon.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_base_template_wires_manifest_and_ios_tags(client):
    response = client.get("/health")

    assert '<link rel="manifest" href="/manifest.webmanifest">' in response.text
    assert (
        '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">'
        in response.text
    )
    assert 'name="apple-mobile-web-app-capable" content="yes"' in response.text


def test_manifest_route_unaffected_by_existing_csp(client):
    response = client.get("/manifest.webmanifest")

    # default-src 'self' already covers manifest-src and img-src 'self'
    # already covers the icons — no CSP change was needed for this slice,
    # confirmed by the header still being present and unmodified here.
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
