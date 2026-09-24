"""S0 Look (issue #144) acceptance check: the app makes no requests outside
127.0.0.1/localhost while rendering its main pages. Fonts, the topo map and
uPlot are all vendored under /static; a stray Google Fonts or CDN reference
would silently work in a browser with real network access but break (or
leak) on the on-device Android WebView, which has no such access."""

from urllib.parse import urlparse

from playwright.sync_api import expect


def _seed_session_and_worksets(page, live_server):
    """Mirrors tests/e2e/test_ui_viewport_360.py's fixture: logs a max test
    for both hands, then starts a session and lands on /session/worksets
    (with the grip/edge/date query string a bare route can't guess)."""
    for hand in ("left", "right"):
        page.goto(f"{live_server}/max-tests")
        form = page.locator('form[action="/max-tests"]')
        form.locator(f'input[name="hand"][value="{hand}"]').check()
        form.locator("select.grip-select").select_option(label=["Half crimp", "half crimp"])
        form.locator('input[name="edge_mm"]').fill("20")
        form.locator('input[name="weight"]').fill("40")
        form.locator('button[type="submit"]').click()

    page.goto(f"{live_server}/session/new")
    page.locator(".grip-select").select_option(label=["Half crimp", "half crimp"])
    page.locator('input[name="edge_mm"]').fill("20")
    page.get_by_role("button", name="Start warmup").click()
    warmup_url = page.url
    page.get_by_role("link", name="Continue to work sets").click()
    expect(page.locator(".focus-pill")).to_be_visible()
    return warmup_url, page.url


def test_main_pages_make_no_requests_outside_localhost(live_server, authenticated_page):
    page = authenticated_page
    warmup_url, worksets_url = _seed_session_and_worksets(page, live_server)

    external_requests = []

    def on_request(request):
        host = urlparse(request.url).hostname
        if host not in ("127.0.0.1", "localhost"):
            external_requests.append(request.url)

    page.on("request", on_request)

    routes = [
        f"{live_server}/",
        warmup_url,
        worksets_url,
        f"{live_server}/dashboard",
        f"{live_server}/climbs",
        f"{live_server}/history",
        f"{live_server}/max-tests",
        f"{live_server}/profile",
        f"{live_server}/plates",
    ]
    for url in routes:
        page.goto(url)
        page.wait_for_load_state("networkidle")

    assert external_requests == [], f"Requests left 127.0.0.1/localhost: {external_requests}"
