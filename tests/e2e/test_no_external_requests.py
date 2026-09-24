"""S0 Look (issue #144) acceptance check: the app makes no requests outside
127.0.0.1/localhost while rendering its main pages. Fonts, the topo map and
uPlot are all vendored under /static; a stray Google Fonts or CDN reference
would silently work in a browser with real network access but break (or
leak) on the on-device Android WebView, which has no such access."""

from urllib.parse import urlparse

from tests.e2e.conftest import advance_to_worksets, start_session_play


def test_main_pages_make_no_requests_outside_localhost(live_server, authenticated_page):
    page = authenticated_page
    start_session_play(page, live_server)
    warmup_url = page.url
    advance_to_worksets(page)
    worksets_url = page.url

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
        f"{live_server}/progress",
        f"{live_server}/progress/volume",
        f"{live_server}/climbs",
        f"{live_server}/progress/timeline",
        f"{live_server}/progress/maxes",
        f"{live_server}/profile",
        f"{live_server}/plates",
    ]
    for url in routes:
        page.goto(url)
        page.wait_for_load_state("networkidle")

    assert external_requests == [], f"Requests left 127.0.0.1/localhost: {external_requests}"
